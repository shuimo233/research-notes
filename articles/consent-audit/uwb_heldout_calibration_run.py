"""Fit measurement contracts on calibration positions and score the held-out positions."""

import argparse
from collections import Counter
from decimal import Decimal
import gzip
from hashlib import sha256
import json
from pathlib import Path
from statistics import median

from interval_fault_noisy import Offer
from interval_fault_shared_calibration import (
    certificate_sources,
    compatible_labels,
    plan,
)

STEM = "uwb-heldout-calibration"
E_MM = 300
FAULTS = 1


def mm(value):
    return round(1000 * value)


def distance(anchor, position):
    return mm(
        sum(
            (Decimal(a) - Decimal(x)) ** 2
            for a, x in zip(anchor, position, strict=True)
        ).sqrt()
    )


def envelope(residuals):
    """Return the minimum twice-radius and twice-center, both as integers."""
    ordered = sorted(residuals)
    knots = zip(ordered, ordered[len(ordered) - FAULTS - 1 :])
    width, _, center = min((hi - lo, abs(hi + lo), hi + lo) for lo, hi in knots)
    return width, center


def band(calibration_residuals):
    centers = [envelope(row)[1] for row in calibration_residuals]
    return min(centers) - 100, max(centers) + 100


def fits(residuals, allowed):
    """Check the frozen offset band and at most one arbitrary bad source."""
    ordered = sorted(residuals)
    for lo, hi in zip(ordered, ordered[len(ordered) - FAULTS - 1 :]):
        if (
            hi - lo <= 2 * E_MM
            and 2 * (hi - E_MM) <= allowed[1]
            and 2 * (lo + E_MM) >= allowed[0]
        ):
            return True
    return False


def measure(site, all_anchors, anchors):
    sources = site["anchors"]
    if any(a not in sources or not sources[a]["range_m"] for a in anchors):
        return None
    reference = {a: distance(p, site["position_m"]) for a, p in all_anchors.items()}
    ranges = {
        a: mm(median(map(Decimal, row["range_m"])))
        for a, row in sources.items()
        if row["range_m"]
    }
    correction = sum(
        any(
            tuple(map(Decimal, xyz)) != tuple(map(Decimal, site["position_m"]))
            for xyz in sources[a]["raw_tag_m"]
        )
        for a in anchors
    )
    anchor_correction = sum(
        any(
            tuple(map(Decimal, xyz)) != tuple(map(Decimal, all_anchors[a]))
            for xyz in sources[a]["raw_anchor_m"]
        )
        for a in anchors
    )
    return {
        "reference": reference,
        "ranges": ranges,
        "residuals": {a: value - reference[a] for a, value in ranges.items()},
        "los": all(sources[a]["los"] == ["LOS"] for a in anchors),
        "raw_tag_disagreements": correction,
        "raw_anchor_disagreements": anchor_correction,
    }


def _witness(residuals, names, bounds):
    intervals = [(2 * (x - E_MM), 2 * (x + E_MM)) for x in residuals]
    which = certificate_sources(intervals, tuple(range(len(names))), FAULTS, bounds)
    return {names[i]: list(intervals[i]) for i in which}


def _decoder_marginal(labels, offers, selected, observed, bounds):
    possible = set()
    for w, label in enumerate(labels):
        misses = sum(
            not bounds[0] - 2 * E_MM
            <= reading - offers[i].values[w][0]
            <= bounds[1] + 2 * E_MM
            for i, reading in zip(selected, observed, strict=True)
        )
        if misses <= FAULTS:
            possible.add(label)
    return possible


def procurement(sites, measured, anchors, corrections, bounds, accepted):
    split_x2 = round(2 * median([mm(Decimal(site["position_m"][0])) for site in sites]))
    candidates = [
        site
        for site in sites
        if abs(2 * mm(Decimal(site["position_m"][0])) - split_x2) > 1000
    ]
    labels = [2 * mm(Decimal(s["position_m"][0])) > split_x2 for s in candidates]
    if len(set(labels)) < 2:
        return {"skipped": "both checkpoint labels required", "threshold_2mm": split_x2}
    offers = [
        Offer(
            1,
            tuple(
                (2 * (measured[s["folder"]]["reference"][a] + corrections[a]),)
                for s in candidates
            ),
        )
        for a in anchors
    ]
    n = len(anchors)
    full = (1 << n) - 1
    groups = (1, full ^ 1)
    limits = [{full: FAULTS, 1: 1, full ^ 1: n - 1}] * len(labels)
    intervals = [bounds] * len(labels)
    errors = [2 * E_MM] * n
    rows = {}
    for mode in ("shared", "marginal"):
        outcome = plan(labels, offers, groups, limits, intervals, errors, mode)
        if outcome.cost is None:
            rows[mode] = {"queries": None, "proof": outcome.proof}
            continue
        tests, counts = {}, Counter()
        for candidate, label in zip(candidates, labels, strict=True):
            if candidate["split"] != "heldout":
                continue
            key = candidate["folder"]
            observation = [
                2 * measured[key]["ranges"][anchors[i]] for i in outcome.selected
            ]
            if mode == "shared":
                possible = compatible_labels(
                    labels,
                    offers,
                    outcome.selected,
                    [(x,) for x in observation],
                    limits,
                    intervals,
                    errors,
                )
            else:
                possible = _decoder_marginal(
                    labels, offers, outcome.selected, observation, bounds
                )
            said = (
                "correct"
                if possible == {label}
                else "wrong"
                if len(possible) == 1
                else "abstain"
            )
            tests[key] = {"labels": sorted(possible), "state": said}
            counts[said] += 1
        rows[mode] = {
            "queries": outcome.cost,
            "anchors": [anchors[i] for i in outcome.selected],
            "replay": dict(counts),
            "tests": tests,
        }
    shared, marginal = rows["shared"], rows["marginal"]
    gate = (
        accepted
        and shared["queries"] is not None
        and marginal["queries"] is not None
        and shared["queries"] < marginal["queries"]
        and shared["replay"].get("wrong", 0) == 0
        and shared["replay"].get("correct", 0) >= 12
    )
    return {
        "threshold_2mm": split_x2,
        "candidates": len(candidates),
        **rows,
        "gate": gate,
    }


def evaluate(env, fixture):
    all_anchors = fixture["anchors_m"]
    anchors = tuple(
        a for a in sorted(all_anchors) if not (env == "environment2" and a == "A6")
    )
    measured = {
        site["folder"]: measure(site, all_anchors, anchors) for site in fixture["sites"]
    }
    sites = [s for s in fixture["sites"] if measured[s["folder"]] is not None]
    calibrating = [
        measured[s["folder"]]["residuals"] for s in sites if s["split"] == "calibration"
    ]
    corrections = {a: round(median([row[a] for row in calibrating])) for a in anchors}
    offsets = {
        "H": band(tuple(row[a] for a in anchors) for row in calibrating),
        "A": (0, 0),
        "AH": band(
            tuple(row[a] - corrections[a] for a in anchors) for row in calibrating
        ),
    }
    detail = {}
    for site in sites:
        name = site["folder"]
        data = measured[name]
        original = tuple(data["residuals"][a] for a in anchors)
        corrected = tuple(data["residuals"][a] - corrections[a] for a in anchors)
        metrics = {}
        for model, residuals in (("H", original), ("A", corrected), ("AH", corrected)):
            conforming = fits(residuals, offsets[model])
            metrics[model] = {
                "conforms": conforming,
                "unbounded_required_2mm": envelope(residuals)[0],
            }
            if not conforming:
                metrics[model]["witness_intervals_2mm"] = _witness(
                    residuals, anchors, offsets[model]
                )
        detail[name] = {
            "split": site["split"],
            "rank": site["rank"],
            "all_los": data["los"],
            "residual_mm": data["residuals"],
            "raw_tag_disagreements": data["raw_tag_disagreements"],
            "raw_anchor_disagreements": data["raw_anchor_disagreements"],
            "metrics": metrics,
        }
    counts = {}
    for partition in ("calibration", "heldout"):
        sample = [x for x in detail.values() if x["split"] == partition]
        counts[partition] = {
            "positions": len(sample),
            "all_los": sum(x["all_los"] for x in sample),
            "conforms": {
                model: sum(row["metrics"][model]["conforms"] for row in sample)
                for model in offsets
            },
            "unbounded_median_required_2mm": {
                model: median(
                    [row["metrics"][model]["unbounded_required_2mm"] for row in sample]
                )
                for model in ("H", "AH")
            },
        }
    gates = {m: counts["heldout"]["conforms"][m] >= 18 for m in offsets}
    actual_fault = [
        abs(row["residual_mm"]["A6"])
        for row in detail.values()
        if "A6" in row["residual_mm"]
    ]
    return {
        "raw_path_size": fixture["path_size"],
        "anchors": anchors,
        "data_excluded": len(fixture["sites"]) - len(sites),
        "calibrated_anchor_bias_mm": corrections,
        "offset_2mm": offsets,
        "counts": counts,
        "heldout_gates": gates,
        "recorded_environment2_A6_fault": {
            "positions_with_data": len(actual_fault),
            "absolute_median_mm": median(actual_fault),
            "above_300mm": sum(x > E_MM for x in actual_fault),
        }
        if env == "environment2" and actual_fault
        else None,
        "procurement": procurement(
            sites, measured, anchors, corrections, offsets["AH"], gates["AH"]
        ),
        "positions": detail,
    }


def run(observations, out):
    data = json.loads(gzip.decompress(observations.read_bytes()))
    result = {
        "source": data["source"],
        "observations_sha256": sha256(observations.read_bytes()).hexdigest(),
        "results": {
            e: evaluate(e, fixture) for e, fixture in data["environments"].items()
        },
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-results.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        env: {
            "counts": row["counts"],
            "gates": row["heldout_gates"],
            "purchase": {
                mode: {
                    key: val
                    for key, val in p.items()
                    if key in ("queries", "replay", "anchors")
                }
                for mode, p in row["procurement"].items()
                if mode in ("shared", "marginal")
            },
            "recorded_A6": row["recorded_environment2_A6_fault"],
        }
        for env, row in result["results"].items()
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("observations", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.observations, args.out)))
