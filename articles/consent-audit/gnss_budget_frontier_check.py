"""Check S4 acquisition, interval certificates, and replay without the planner."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
from math import comb, isclose
from pathlib import Path

import numpy as np

from gnss_quality_verification_check import (
    audit_raw,
    intersect,
    interval_witness,
    unpack,
    wgs84_xyz,
    winner_upper,
)

LABELS = ("south", "north")
BUDGETS = ("4", "5", "6")


def check_scope(cases, plan):
    lats = [Decimal(str(r["reference"]["lla"][0])) for r in cases]
    mid = (max(lats) + min(lats)) / 2
    assert Decimal(plan["boundary_deg"]) == mid
    origin = cases[0]["reference"]["utc_ms"]
    possible = defaultdict(list)
    excluded = 0
    for i, r in enumerate(cases):
        t = r["reference"]["utc_ms"] - origin
        d = abs(lats[i] - mid) * 111111
        if d <= 15:
            excluded += 1
        else:
            possible[t // 5000].append((abs(t % 5000 - 2500), t, i, d))
    assert plan["guard_excluded"] == excluded
    catalog = plan["catalog"]
    assert len(catalog) == len(possible)
    assert plan["thinned"] == len(cases) - excluded - len(catalog)
    for slot, r in zip(sorted(possible), catalog, strict=True):
        _, t, i, d = min(possible[slot])
        assert r["fixture_row"] == i and r["near"] == (d <= 60)
        assert r["label"] == ("north" if lats[i] > mid else "south")
        assert r["block"] == t // 30000
        assert r["split"] == ("heldout" if r["block"] % 2 else "calibration")
        xyz = wgs84_xyz(cases[i]["reference"]["lla"])
        assert all(
            isclose(a, b, abs_tol=1e-7, rel_tol=0)
            for a, b in zip(xyz, r["ecef_m"], strict=True)
        )
    assert sorted(
        [p["world"] for p in plan["plan"]] + plan["unavailable_worlds"]
    ) == list(range(len(catalog)))


def score_check(residual, weights, labels, world, record):
    for y in LABELS:
        bound = Fraction(*record["labels_needed2"][y])
        rows = 2 * residual[labels == y]
        assert intersect(rows, weights, bound, 1).any()
        assert not intersect(rows, weights, bound, 1, strict=True).any()
    value = Fraction(*record["true_needed2"])
    actual = 2 * residual[world : world + 1]
    assert intersect(actual, weights, value, 1).item()
    assert not intersect(actual, weights, value, 1, strict=True).item()
    # Sum of all squared pair differences equals n times centered SSE.
    sets = combinations(range(residual.shape[1]), residual.shape[1] - 1)
    terms = [
        sum((residual[:, a] - residual[:, b]) ** 2 for a, b in combinations(keep, 2))
        for keep in sets
    ]
    best = np.minimum.reduce(terms)
    assert record["lts"] == {
        y: int(best[labels == y].min() - best.min()) for y in LABELS
    }


def rank(values):
    ordered = sorted(x for x in values if x is not None)
    index = (9 * len(values) + 18) // 10 - 1
    return ordered[index] if index < len(ordered) else None


def packed(q):
    return None if q is None else [q.numerator, q.denominator]


def verify_replay(rows, plan, summary):
    train, test = rows["calibration"], rows["heldout"]
    truth_scores = {
        k: [Fraction(*r["budgets"][k]["true_needed2"]) for r in train] for k in BUDGETS
    }
    per_k = {k: rank(x) for k, x in truth_scores.items()}
    joint = rank([max(v) for v in zip(*truth_scores.values(), strict=True)])
    lts = {
        k: rank([r["budgets"][k]["lts"][r["truth"]] for r in train]) for k in BUDGETS
    }
    r6 = [Fraction(*r["budgets"]["6"]["radius2"]) for r in train]
    ratio6 = rank(
        [n / d if d else None for n, d in zip(truth_scores["6"], r6, strict=True)]
    )
    assert summary["cutoffs"] == {
        "fixed": {k: packed(q) for k, q in per_k.items()},
        "joint": packed(joint),
        "lts": lts,
        "ratio6": packed(ratio6),
    }
    methods = defaultdict(Counter)
    near = defaultdict(Counter)
    indexed = {case["world"]: case for case in plan["plan"]}
    for row in test:
        configured = indexed[row["world"]]
        truth = row["truth"]
        decisions = {}

        def assign(method, accepted):
            decisions[method] = "abstain"
            if len(accepted) == 1:
                decisions[method] = "correct" if truth in accepted else "wrong"

        for k in BUDGETS:
            b = row["budgets"][k]
            d = Fraction(*b["radius2"])
            demand = {y: Fraction(*q) for y, q in b["labels_needed2"].items()}
            assign("limit" + k, [y for y in LABELS if demand[y] < d])
            assign(
                "absolute" + k,
                [
                    y
                    for y in LABELS
                    if per_k[k] is not None and demand[y] <= per_k[k] < d
                ],
            )
            assign(
                "lts" + k,
                [y for y in LABELS if lts[k] is not None and b["lts"][y] <= lts[k]],
            )
            if k == "6":
                assign(
                    "ratio6",
                    [
                        y
                        for y in LABELS
                        if ratio6 is not None
                        and ratio6 < 1
                        and demand[y] <= ratio6 * d < d
                    ],
                )
        admitted = [
            k
            for k in BUDGETS
            if joint is not None and joint < Fraction(*row["budgets"][k]["radius2"])
        ]
        best = min(admitted, default=None)
        assert row["picked"] == best
        if best is None:
            assert row["reads"] == []
            assign("minimum_reads", [])
            assign("variable_lts", [])
            status = "no_roster"
        else:
            chosen = configured["rosters"][best]
            assert row["reads"] == [
                configured["satellites"][i] for i in chosen["indices"]
            ]
            b = row["budgets"][best]
            assign(
                "minimum_reads",
                [y for y in LABELS if Fraction(*b["labels_needed2"][y]) <= joint],
            )
            decisions["variable_lts"] = decisions["lts" + best]
            status = decisions["minimum_reads"]
            if status == "abstain":
                status = "incompatible"
        assert row["decisions"] == decisions and row["status"] == status
        for method, value in decisions.items():
            assert summary["by_method"][method][truth].get(value, 0) > 0
            methods[method, truth][value] += 1
            if row["near"]:
                near[method, truth][value] += 1
    for method, observed in summary["by_method"].items():
        for y in LABELS:
            assert observed[y] == methods[method, y]
            assert summary["near_boundary"][method][y] == near[method, y]
    assert summary["read_count_distribution"] == Counter(
        str(len(r["reads"])) for r in test
    )
    assert summary["primary_status"] == Counter(r["status"] for r in test)
    counts = Counter(r["truth"] for r in test)
    assert counts == summary["heldout"]
    assert Counter(r["truth"] for r in train) == summary["calibration"]
    for k in BUDGETS:
        paired = [
            r
            for r in test
            if all(r["decisions"][m] == "correct" for m in ("minimum_reads", "lts" + k))
        ]
        assert summary["common_correct"][k] == {
            "count": len(paired),
            "primary_reads": sum(len(r["reads"]) for r in paired),
            "baseline_reads": int(k) * len(paired),
        }
    cheapest = next(
        (
            k
            for k in ("4", "5")
            if all(
                methods["lts" + k, y]["correct"] >= methods["lts6", y]["correct"]
                and not methods["lts" + k, y]["wrong"]
                for y in LABELS
            )
        ),
        None,
    )
    assert summary["cheapest_matching_lts"] == cheapest
    six = summary["common_correct"]["6"]
    low = summary["common_correct"].get(cheapest)
    gate = {
        "each_class_count": min(counts[y] for y in LABELS) >= 8,
        "each_class_80_correct": all(
            counts[y] > 0 and methods["minimum_reads", y]["correct"] / counts[y] >= 0.8
            for y in LABELS
        ),
        "zero_wrong": not any(methods["minimum_reads", y]["wrong"] for y in LABELS),
        "matches_lts6_by_class": all(
            methods["minimum_reads", y]["correct"] >= methods["lts6", y]["correct"]
            for y in LABELS
        ),
        "matches_variable_lts_by_class": all(
            methods["minimum_reads", y]["correct"]
            >= methods["variable_lts", y]["correct"]
            for y in LABELS
        ),
        "saves_one_per_common_correct_lts6": six["count"] > 0
        and six["primary_reads"] <= 5 * six["count"],
        "saves_against_cheapest_matching_lts": low is None
        or low["primary_reads"] < low["baseline_reads"],
    }
    assert summary["gate_inputs"] == gate
    assert summary["gate"] == all(gate.values())


def audit(log, reference, nav, fixture_path, plan_path, rows_path, result_path):
    fixture, plan, rows = map(unpack, (fixture_path, plan_path, rows_path))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert plan["fixture_sha256"] == sha256(fixture_path.read_bytes()).hexdigest()
    assert result["design_sha256"] == sha256(plan_path.read_bytes()).hexdigest()
    source_ranges = audit_raw(log, reference, nav, fixture)
    cases = fixture["cases"]
    check_scope(cases, plan)
    catalog = plan["catalog"]
    labels = np.array([w["label"] for w in catalog])
    lo, hi = map(
        np.asarray,
        zip(
            *(
                (i, j)
                for i in np.flatnonzero(labels == "south")
                for j in np.flatnonzero(labels == "north")
            ),
            strict=True,
        ),
    )
    by_world = {}
    for split, group in rows.items():
        for row in group:
            i = row["world"]
            assert i not in by_world and catalog[i]["split"] == split
            assert all(row[k] == catalog[i][k] for k in ("near", "block"))
            assert row["truth"] == catalog[i]["label"]
            by_world[i] = row
    assert set(by_world) == {m["world"] for m in plan["plan"]}
    comparisons, collisions = 0, 0
    for m in plan["plan"]:
        world = m["world"]
        svs = m["satellites"]
        raw = {
            s["sat"]: s for s in cases[catalog[world]["fixture_row"]]["epoch"]["items"]
        }
        assert sorted(set(svs)) == svs
        reads = np.array([round(1000 * raw[s]["pseudorange"]) for s in svs])
        weights = np.asarray(m["weights"], dtype=np.int64)
        expected = [
            round(1024 * 10 ** ((40 - sorted([15, raw[s]["cn0"], 50])[1]) / 20))
            for s in svs
        ]
        assert weights.tolist() == expected
        table = np.asarray(m["nominal_mm"], dtype=np.int64)
        diffs = table[hi] - table[lo]
        previous = Fraction(0)
        for k in BUDGETS:
            roster = m["rosters"][k]
            take = roster["indices"]
            assert len(take) == int(k) and sorted(set(take)) == take
            pair, bound = interval_witness(
                table, weights, diffs, roster, lo, hi, labels
            )
            assert bound >= previous
            previous = bound
            checks = winner_upper(diffs, weights, tuple(take), pair, bound)
            assert checks == roster["search"]["options"] == comb(len(svs), int(k))
            comparisons += checks
            collisions += 1
            metrics = by_world[world]["budgets"][k]
            assert metrics["radius2"] == roster["radius2"]
            score_check((reads - table)[:, take], weights[take], labels, world, metrics)
    verify_replay(rows, plan, result)
    return {
        "raw_selected_pseudoranges": source_ranges,
        "verified_roster_optimizations": collisions,
        "verified_roster_combinations": comparisons,
        "verified_closed_collision_replies": collisions,
        "verified_calibration_epochs": len(rows["calibration"]),
        "verified_heldout_epochs": len(rows["heldout"]),
        "passed_primary_gate": result["gate"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("log", "reference", "nav", "fixture", "plan", "rows", "result"):
        parser.add_argument(name, type=Path)
    print(json.dumps(audit(*vars(parser.parse_args()).values()), indent=2))
