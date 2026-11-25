"""Check roster choices, exact endpoint witnesses, and observed replay independently."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from uwb_heldout_calibration_check import fit, geometry, middle

CUTS = {"environment0": 4695, "environment2": 8295}
PILOT = "12.21_4.95_1.32"


def eligible(location, env):
    x = int(1000 * Decimal(location.split("_")[0]))
    return abs(x - CUTS[env]) > 500


def truth(folder, env):
    return int(1000 * Decimal(folder.split("_")[0])) > CUTS[env]


def source_predictions(env, record, biases):
    return {
        folder: [
            geometry(record["anchors_m"][a], folder.split("_")) + biases[a]
            for a in biases
        ]
        for folder in record["reference_path"]
        if eligible(folder, env)
    }


def data_points(data, anchors):
    result, missing = {}, []
    for row in data["sites"]:
        assert row["folder"] == data["reference_path"][row["rank"]]
        assert tuple(map(Decimal, row["position_m"])) == tuple(
            map(Decimal, row["folder"].split("_"))
        )
        supplied = row["anchors"]
        if any(a not in supplied or not supplied[a]["range_m"] for a in anchors):
            missing.append(row["folder"])
            continue
        result[row["folder"]] = (
            row["split"],
            {
                a: round(
                    middle([1000 * Fraction(raw) for raw in supplied[a]["range_m"]])
                )
                for a in anchors
            },
        )
    return result, missing


def min_radius4(values, band, faults, pair=False):
    count = max(0, len(values) - faults)
    if not count:
        return 0
    scores = []
    for kept in combinations(values, count):
        low, high = min(kept), max(kept)
        center = min(2 * band[1], max(2 * band[0], 2 * (low + high)))
        scores.append(max(4 * high - center, center - 4 * low))
    best = min(scores)
    if pair:
        assert best % 2 == 0
        return best // 2
    return best


def trimmed_squared(values, bounds):
    options = []
    for proposal in combinations(values, len(values) - 1):
        n = len(proposal)
        total = sum(proposal)
        squares = sum(x * x for x in proposal)
        offsets = [Fraction(v, 2) for v in bounds]
        mean = Fraction(total, n)
        if offsets[0] <= mean <= offsets[1]:
            options.append(squares - Fraction(total * total, n))
        for x in offsets:
            options.append(squares + n * x * x - 2 * x * total)
    return min(options)


def verified_rank(scores, num, den, extra=0):
    rank = -(-(len(scores) + extra) * num // den)
    return sorted(scores)[rank - 1] if 0 < rank <= len(scores) else None


def select_recompute(rows):
    contenders = []
    eligible = []
    for row in rows:
        budget = len(row["anchors"])
        gap = row["collision_4mm"] - row["demand_q80_4mm"]
        rank = (budget, -gap, row["anchors"])
        if gap > 0:
            eligible.append((rank, row))
        contenders.append(((-row["design_points_below_collision"], *rank), row))
    return min(eligible or contenders, key=lambda x: x[0])[1]


def verify_collision(env, row, witness, nominal, bounds, idx):
    names = witness["positions"]
    assert (
        row["pair"] == names
        and len(names) == 2
        and truth(names[0], env) != truth(names[1], env)
    )
    given = witness["reply_4mm"]
    assert len(given) == len(idx)
    assert len(witness["bias_4mm"]) == 2
    assert len(witness["fault_indices"]) == 2
    for key, offset, fault in zip(
        names, witness["bias_4mm"], witness["fault_indices"], strict=True
    ):
        assert 2 * bounds[0] <= offset <= 2 * bounds[1]
        mismatch = [
            j
            for j, i in enumerate(idx)
            if abs(given[j] - 4 * nominal[key][i] - offset) > row["collision_4mm"]
        ]
        assert mismatch == fault and len(mismatch) <= 1


def audit_design(env, fixture, declared):
    anchors = tuple(
        sorted(
            a for a in fixture["anchors_m"] if not (env == "environment2" and a == "A6")
        )
    )
    assert tuple(sorted(declared["biases_mm"])) == anchors
    # Only the originally designated calibration members are opened for scores.
    training = {
        **fixture,
        "sites": [s for s in fixture["sites"] if s["split"] == "calibration"],
    }
    measured, missing = data_points(training, anchors)
    assert not missing
    residual = {
        k: [
            reading[a] - geometry(fixture["anchors_m"][a], k.split("_"))
            for a in anchors
        ]
        for k, (_, reading) in measured.items()
    }
    bias = {
        a: round(middle([Fraction(r[i]) for r in residual.values()]))
        for i, a in enumerate(anchors)
    }
    assert bias == declared["biases_mm"]
    adjusted = {
        k: [x - bias[a] for a, x in zip(anchors, row, strict=True)]
        for k, row in residual.items()
    }
    centers = [fit(row)[1] for row in adjusted.values()]
    bounds = [min(centers) - 100, max(centers) + 100]
    assert bounds == declared["offset_2mm"]
    declared_targets = source_predictions(env, fixture, bias)
    assert len(declared_targets) == declared["candidates"]
    actual = sorted(set(adjusted) & declared_targets.keys())
    assert actual == declared["design_points"]
    delta = (bounds[0] - bounds[1], bounds[1] - bounds[0])
    different = [
        ((a, b), [v - u for u, v in zip(x, y, strict=True)])
        for (a, x), (b, y) in combinations(declared_targets.items(), 2)
        if truth(a, env) != truth(b, env)
    ]
    idx_of = {a: i for i, a in enumerate(anchors)}
    expected = {
        s for count in range(3, len(anchors) + 1) for s in combinations(anchors, count)
    }
    assert {tuple(row["anchors"]) for row in declared["subsets"]} == expected
    assert len(declared["subsets"]) == len(expected)
    pair_checks = 0
    witnesses = 0
    for row in declared["subsets"]:
        idx = tuple(idx_of[a] for a in row["anchors"])
        threshold, pair = min(
            (min_radius4([v[i] for i in idx], delta, 2, True), keys)
            for keys, v in different
        )
        assert row["collision_4mm"] == threshold and row["pair"] == list(pair)
        point = [min_radius4([adjusted[k][j] for j in idx], bounds, 1) for k in actual]
        assert row["demand_q80_4mm"] == verified_rank(point, 4, 5)
        assert row["design_points_below_collision"] == sum(v < threshold for v in point)
        pair_checks += len(different)
    assert declared["chosen"] == select_recompute(declared["subsets"])
    assert (
        declared["full"]["anchors"] == list(anchors)
        and declared["full"] in declared["subsets"]
    )
    for kind in ("chosen", "full"):
        row = declared[kind]
        verify_collision(
            env,
            row,
            declared[kind + "_collision"],
            declared_targets,
            bounds,
            [idx_of[a] for a in row["anchors"]],
        )
        witnesses += 1
    return anchors, declared_targets, bounds, pair_checks, witnesses


def decision(values, threshold, y, active):
    labels = [label for label, x in values.items() if active and x <= threshold]
    return "abstain" if len(labels) != 1 else "correct" if labels[0] == y else "wrong"


def audit_roster(env, report, row, anchors, nominal, bounds, points, compare_lts):
    selected = [anchors.index(a) for a in row["anchors"]]
    lts_calibration = {}
    expected_hold = {}
    expected_cal = {}
    for k, (split, reading) in points.items():
        given = [reading[anchors[i]] for i in selected]
        scores, sq = {}, {False: [], True: []}
        for world, expected in nominal.items():
            residuals = [v - expected[j] for j, v in zip(selected, given, strict=True)]
            scores[world] = min_radius4(residuals, bounds, 1)
            if compare_lts:
                sq[truth(world, env)].append(trimmed_squared(residuals, bounds))
        label_scores = {
            y: min(s for key, s in scores.items() if truth(key, env) == y) for y in sq
        }
        y = truth(k, env)
        if compare_lts:
            best = min(min(c) for c in sq.values())
            sq = {y: min(c) - best for y, c in sq.items()}
        if split == "calibration":
            expected_cal[k] = scores[k]
            if compare_lts:
                lts_calibration[k] = sq[y]
        else:
            expected_hold[k] = y, scores[k], label_scores, sq

    cutoff = verified_rank(list(expected_cal.values()), 9, 10, 1)
    limit = row["collision_4mm"]
    active = cutoff is not None and cutoff < limit
    assert report["eligible"] == active and report["calibrated_4mm"] == cutoff
    assert report["calibration"] == expected_cal and report[
        "calibration_below_collision"
    ] == sum(v < limit for v in expected_cal.values())
    assert report["certified_limit_4mm"] == (limit - 1 if limit else None)
    assert report["heldout"].keys() == expected_hold.keys()
    counts, capped, alternatives = Counter(), Counter(), Counter()
    if compare_lts:
        alternative_cutoff = verified_rank(list(lts_calibration.values()), 9, 10, 1)
        recorded = report["lts"]
        reported_cutoff = (
            Fraction(*recorded["threshold"])
            if recorded["threshold"] is not None
            else None
        )
        assert reported_cutoff == alternative_cutoff
        assert {
            k: Fraction(*v) for k, v in recorded["calibration"].items()
        } == lts_calibration
    for k, (y, needed, score, sq) in expected_hold.items():
        tested = report["heldout"][k]
        dec = decision(score, cutoff, y, active)
        cap = decision(score, limit - 1, y, True)
        assert tested["truth"] == y and tested["demand_radius_4mm"] == needed
        assert tested["label_radius_4mm"] == [score[False], score[True]]
        assert tested["decision"] == dec and tested["at_certified_limit"] == cap
        counts[dec] += 1
        capped[cap] += 1
        if compare_lts:
            comparison = (
                "abstain"
                if alternative_cutoff is None
                else decision(sq, alternative_cutoff, y, True)
            )
            assert tested["lts_decision"] == comparison
            assert [Fraction(*v) for v in tested["lts_scores"]] == [sq[False], sq[True]]
            alternatives[comparison] += 1
    assert report["counts"] == counts and report["at_certified_limit"] == capped
    if compare_lts:
        assert report["lts"]["counts"] == alternatives
    return len(expected_cal), len(expected_hold)


def audit(old, design, new, replay):
    results = {}
    for env, fixture in old["environments"].items():
        f = design["environments"][env]
        anchors, nominal, bounds, pairs, witnesses = audit_design(env, fixture, f)
        fresh = new["environments"][env]
        old_keys = {r["folder"] for r in fixture["sites"]}
        assert (
            fresh["reference_path"] == fixture["reference_path"]
            and fresh["anchors_m"] == fixture["anchors_m"]
        )
        if env == "environment2":
            old_keys.add(PILOT)
        assert {s["folder"] for s in fresh["sites"]} == set(
            fixture["reference_path"]
        ) - old_keys
        assert all(
            s["split"] == ("heldout" if s["rank"] // 5 % 2 else "calibration")
            for s in fresh["sites"]
        )
        boundary = sum(s["folder"] not in nominal for s in fresh["sites"])
        data, missing = data_points(
            {**fresh, "sites": [s for s in fresh["sites"] if s["folder"] in nominal]},
            anchors,
        )
        report = replay["environments"][env]
        assert (
            report["unavailable"] == missing
            and report["boundary_exclusions"] == boundary
        )
        counts = {
            kind: audit_roster(
                env,
                report[kind],
                f[kind],
                anchors,
                nominal,
                bounds,
                data,
                kind == "chosen",
            )
            for kind in ("chosen", "full")
        }
        chosen = report["chosen"]
        successes = chosen["counts"].get("correct", 0)
        assert report["gate"] == (
            len(f["chosen"]["anchors"]) < len(f["full"]["anchors"])
            and chosen["eligible"]
            and counts["chosen"][1] >= 12
            and 10 * successes >= 9 * counts["chosen"][1]
            and chosen["counts"].get("wrong", 0) == 0
            and successes >= chosen["lts"]["counts"].get("correct", 0)
        )
        results[env] = {
            "verified_subsets": len(f["subsets"]),
            "verified_pair_radii": pairs,
            "verified_limiting_replies": witnesses,
            "verified_calibration_scores": counts["chosen"][0],
            "verified_heldout_locations": counts["chosen"][1],
        }
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("old", "design", "new", "replay"):
        p.add_argument(arg, type=Path)
    args = p.parse_args()
    design, report = (
        json.loads(args.design.read_bytes()),
        json.loads(args.replay.read_bytes()),
    )
    old, new = [
        json.loads(gzip.decompress(path.read_bytes())) for path in (args.old, args.new)
    ]
    assert design["design_input_sha256"] == sha256(args.old.read_bytes()).hexdigest()
    assert (
        new["design_sha256"]
        == report["design_sha256"]
        == sha256(args.design.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    )
    assert report["observations_sha256"] == sha256(args.new.read_bytes()).hexdigest()
    print(json.dumps(audit(old, design, new, report)))
