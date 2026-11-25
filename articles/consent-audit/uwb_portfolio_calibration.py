"""Select and certify a UWB query roster before independent residual calibration."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from statistics import median

from uwb_heldout_calibration_run import band, distance, measure, mm

STEM = "uwb-portfolio-calibration"
CUT_MM = {"environment0": 4695, "environment2": 8295}


def read_frozen(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def dump(path, record):
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")


def design_digest(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def kth_item(values, numerator, denominator, extra=0):
    rank = (numerator * (len(values) + extra) + denominator - 1) // denominator
    return sorted(values)[rank - 1] if 0 < rank <= len(values) else None


def radius4(values, band2, faults, pair=False):
    """First feasible radius, in quarter millimeters, with closed intervals."""
    if len(values) <= faults:
        return 0
    values = sorted(values)
    shift = len(values) - faults - 1
    width = min(
        max(hi - lo, 2 * hi - band2[1], band2[0] - 2 * lo)
        for lo, hi in zip(values, values[shift:])
    )
    return width if pair else 2 * width


def label_at(folder, env):
    x = mm(Decimal(folder.split("_")[0]))
    return x > CUT_MM[env] if abs(x - CUT_MM[env]) > 500 else None


def catalog(env, fixture, biases):
    anchors = tuple(sorted(biases))
    return {
        folder: (
            label,
            tuple(
                distance(fixture["anchors_m"][a], folder.split("_")) + biases[a]
                for a in anchors
            ),
        )
        for folder in fixture["reference_path"]
        if (label := label_at(folder, env)) is not None
    }


def radius_candidates(answers, subset, band2):
    delta = band2[0] - band2[1], band2[1] - band2[0]
    opposite = []
    for (folder_a, (label_a, x)), (folder_b, (label_b, y)) in combinations(
        answers.items(), 2
    ):
        if label_a != label_b:
            radius = radius4([y[i] - x[i] for i in subset], delta, 2, pair=True)
            opposite.append((radius, folder_a, folder_b))
    return min(opposite)


def common_reply(answers, subset, band2, bottleneck):
    """Return a shared transcript at the exact radius and its fault allocation."""
    e, a, b = bottleneck
    x = [4 * answers[a][1][i] for i in subset]
    y = [4 * answers[b][1][i] for i in subset]
    shifts = [v - u for u, v in zip(x, y, strict=True)]
    extent = 2 * (band2[1] - band2[0])
    lower = max(-extent, min(shifts) - 2 * e)
    points = [lower, *(s - 2 * e for s in shifts if lower <= s - 2 * e <= extent)]
    difference = next(
        d for d in sorted(points) if sum(abs(s - d) > 2 * e for s in shifts) <= 2
    )
    bias_a = max(2 * band2[0], 2 * band2[0] + difference)
    bias_b = bias_a - difference
    conflicts = [i for i, s in enumerate(shifts) if abs(s - difference) > 2 * e]
    bad_a, bad_b = conflicts[:1], conflicts[1:]
    replies = [
        v + bias_b
        if i in bad_a
        else u + bias_a
        if i in bad_b
        else max(u + bias_a, v + bias_b) - e
        for i, (u, v) in enumerate(zip(x, y, strict=True))
    ]
    return {
        "positions": [a, b],
        "bias_4mm": [bias_a, bias_b],
        "reply_4mm": replies,
        "fault_indices": [bad_a, bad_b],
    }


def choose(record):
    scores = record["subsets"]
    passing = [x for x in scores if x["demand_q80_4mm"] < x["collision_4mm"]]
    feasible = bool(passing)
    return min(
        passing or scores,
        key=lambda x: (
            -x["design_points_below_collision"] if not feasible else 0,
            len(x["anchors"]),
            x["demand_q80_4mm"] - x["collision_4mm"],
            x["anchors"],
        ),
    )


def design(old_path, output):
    data = read_frozen(old_path)
    record = {
        "design_input_sha256": sha256(old_path.read_bytes()).hexdigest(),
        "environments": {},
    }
    for env, source in data["environments"].items():
        coordinates = source["anchors_m"]
        anchors = tuple(
            a for a in sorted(coordinates) if not (env == "environment2" and a == "A6")
        )
        training = {
            s["folder"]: measure(s, coordinates, anchors)
            for s in source["sites"]
            if s["split"] == "calibration"
        }
        biases = {
            a: round(median([item["residuals"][a] for item in training.values()]))
            for a in anchors
        }
        residuals = {
            k: tuple(x["residuals"][a] - biases[a] for a in anchors)
            for k, x in training.items()
        }
        offset = band(residuals.values())
        answers = catalog(env, source, biases)
        target = {
            "biases_mm": biases,
            "offset_2mm": offset,
            "candidates": len(answers),
            "design_points": sorted(set(residuals) & answers.keys()),
            "subsets": [],
        }
        for size in range(3, len(anchors) + 1):
            for subset in combinations(range(len(anchors)), size):
                radius, a, b = radius_candidates(answers, subset, offset)
                demand = [
                    radius4([residuals[k][i] for i in subset], offset, 1)
                    for k in target["design_points"]
                ]
                target["subsets"].append(
                    {
                        "anchors": [anchors[i] for i in subset],
                        "collision_4mm": radius,
                        "demand_q80_4mm": kth_item(demand, 4, 5),
                        "design_points_below_collision": sum(
                            x < radius for x in demand
                        ),
                        "pair": [a, b],
                    }
                )
        target["chosen"] = choose(target)
        target["full"] = target["subsets"][-1]
        for kind in ("chosen", "full"):
            row = target[kind]
            subset = [anchors.index(a) for a in row["anchors"]]
            target[kind + "_collision"] = common_reply(
                answers, subset, offset, (row["collision_4mm"], *row["pair"])
            )
        record["environments"][env] = target
    dump(output, record)
    return {
        k: {i: v[i] for i in ("chosen", "full", "candidates")}
        for k, v in record["environments"].items()
    }


def least_trimmed_squares(values, bounds):
    scores = []
    for leave in range(len(values)):
        retained = [x for i, x in enumerate(values) if i != leave]
        mu = min(
            Fraction(bounds[1], 2),
            max(Fraction(bounds[0], 2), Fraction(sum(retained), len(retained))),
        )
        scores.append(sum((r - mu) ** 2 for r in retained))
    return min(scores)


def point_scores(answers, selected, observed, bounds, compare_lts):
    by_label = {}
    squares = {}
    world = {}
    for key, (label, expected) in answers.items():
        residual = [v - expected[i] for i, v in zip(selected, observed, strict=True)]
        value = radius4(residual, bounds, 1)
        world[key] = value
        by_label[label] = min(by_label.get(label, value), value)
        if compare_lts:
            loss = least_trimmed_squares(residual, bounds)
            squares[label] = min(squares.get(label, loss), loss)
    if compare_lts:
        minimum = min(squares.values())
        squares = {label: x - minimum for label, x in squares.items()}
    return world, by_label, squares


def status(choices, truth):
    if choices == {truth}:
        return "correct"
    return "wrong" if len(choices) == 1 else "abstain"


def contract_report(answers, matrix, all_anchors, frozen, rosters, include_lts):
    subset = [all_anchors.index(a) for a in rosters["anchors"]]
    limit = rosters["collision_4mm"]
    parts = {"calibration": {}, "heldout": {}}
    for key, (split, measured) in matrix.items():
        given = [measured["ranges"][all_anchors[i]] for i in subset]
        all_points, labels, lts = point_scores(
            answers, subset, given, frozen, include_lts
        )
        parts[split][key] = (answers[key][0], all_points[key], labels, lts)
    calibration = parts["calibration"]
    heldout = parts["heldout"]
    calibrating = [r[1] for r in calibration.values()]
    q = kth_item(calibrating, 9, 10, 1)
    baseline = (
        kth_item([r[3][r[0]] for r in calibration.values()], 9, 10, 1)
        if include_lts
        else None
    )
    certified = q is not None and q < limit
    capped = limit - 1
    details, counts, capped_counts, lts_counts = {}, Counter(), Counter(), Counter()
    for k, (truth, demand, by_label, lts) in heldout.items():
        would = status({y for y, s in by_label.items() if s <= capped}, truth)
        decision = (
            status({y for y, s in by_label.items() if s <= q}, truth)
            if certified
            else "abstain"
        )
        details[k] = {
            "truth": truth,
            "demand_radius_4mm": demand,
            "label_radius_4mm": [by_label[y] for y in (False, True)],
            "decision": decision,
            "at_certified_limit": would,
        }
        counts[decision] += 1
        capped_counts[would] += 1
        if include_lts:
            lts_outcome = status(
                {y for y, s in lts.items() if baseline is None or s <= baseline}, truth
            )
            details[k]["lts_decision"] = lts_outcome
            details[k]["lts_scores"] = [
                [lts[y].numerator, lts[y].denominator] for y in (False, True)
            ]
            lts_counts[lts_outcome] += 1
    result = {
        "eligible": certified,
        "calibrated_4mm": q,
        "certified_limit_4mm": capped if limit else None,
        "calibration": {k: r[1] for k, r in calibration.items()},
        "calibration_below_collision": sum(x < limit for x in calibrating),
        "counts": dict(counts),
        "at_certified_limit": dict(capped_counts),
        "heldout": details,
    }
    if include_lts:
        result["lts"] = {
            "threshold": [baseline.numerator, baseline.denominator]
            if baseline is not None
            else None,
            "calibration": {
                k: [r[3][r[0]].numerator, r[3][r[0]].denominator]
                for k, r in calibration.items()
            },
            "counts": dict(lts_counts),
        }
    return result


def replay(design_path, new_path, output):
    raw, recorded = read_frozen(new_path), json.loads(design_path.read_bytes())
    design_sha = design_digest(design_path)
    assert raw["design_sha256"] == design_sha
    result = {
        "design_sha256": design_sha,
        "observations_sha256": sha256(new_path.read_bytes()).hexdigest(),
        "environments": {},
    }
    for env, reference in raw["environments"].items():
        frozen = recorded["environments"][env]
        anchor_data = reference["anchors_m"]
        anchors = tuple(sorted(frozen["biases_mm"]))
        answers = catalog(env, reference, frozen["biases_mm"])
        observed, unavailable = {}, []
        for s in reference["sites"]:
            if s["folder"] not in answers:
                continue
            data = measure(s, anchor_data, anchors)
            if data is None:
                unavailable.append(s["folder"])
            else:
                observed[s["folder"]] = (s["split"], data)
        chosen, full = [
            contract_report(
                answers,
                observed,
                anchors,
                frozen["offset_2mm"],
                frozen[which],
                which == "chosen",
            )
            for which in ("chosen", "full")
        ]
        n = len(chosen["heldout"])
        right = chosen["counts"].get("correct", 0)
        gate = (
            len(frozen["chosen"]["anchors"]) < len(frozen["full"]["anchors"])
            and chosen["eligible"]
            and n >= 12
            and 10 * right >= 9 * n
            and chosen["counts"].get("wrong", 0) == 0
            and right >= chosen["lts"]["counts"].get("correct", 0)
        )
        result["environments"][env] = {
            "chosen": chosen,
            "full": full,
            "unavailable": unavailable,
            "boundary_exclusions": len(reference["sites"])
            - len(observed)
            - len(unavailable),
            "gate": gate,
        }
    dump(output, result)
    return {
        env: {
            **{
                mode: {
                    k: r[mode][k]
                    for k in (
                        "calibrated_4mm",
                        "certified_limit_4mm",
                        "eligible",
                        "counts",
                        "at_certified_limit",
                        "calibration_below_collision",
                    )
                }
                for mode in ("chosen", "full")
            },
            "lts": r["chosen"]["lts"]["counts"],
            "gate": r["gate"],
        }
        for env, r in result["environments"].items()
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    a = sub.add_parser("design")
    a.add_argument("old", type=Path)
    a.add_argument("output", type=Path)
    b = sub.add_parser("replay")
    for key in ("design", "new", "output"):
        b.add_argument(key, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            design(args.old, args.output)
            if args.stage == "design"
            else replay(args.design, args.new, args.output)
        )
    )
