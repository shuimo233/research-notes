"""Audit GPS roster optimality, threshold witnesses, and independent labelled replay."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import hypot, radians, sin, sqrt, tan
from pathlib import Path

import numpy as np

from gnss_clock_audit import predict
from gnss_clock_audit_check import wgs84_xyz

LABELS = ("south", "north")
MODES = ("margin_six", "elevation_six", "all")


def unpack(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def min_span_with_omissions(values, faults):
    numbers = list(map(int, values))
    return min(
        max(keep) - min(keep) for keep in combinations(numbers, len(numbers) - faults)
    )


def colliding_rows(data, width, faults):
    # Count how many kept intervals can share each prospective lower endpoint.
    mask = np.zeros(data.shape[:-1], dtype=bool)
    for i in range(data.shape[-1]):
        start = data[..., i, None]
        mask |= (
            np.count_nonzero((data >= start) & (data <= start + width), axis=-1)
            >= data.shape[-1] - faults
        )
        if np.all(mask):
            break
    return mask


def scope(fixture, design):
    rows = fixture["cases"]
    latitudes = [Decimal(str(c["reference"]["lla"][0])) for c in rows]
    cut = (max(latitudes) + min(latitudes)) / 2
    assert design["route_boundary_deg"] == str(cut) and design["guard_m"] == 15
    expected = [i for i, x in enumerate(latitudes) if abs(x - cut) * 111111 > 15]
    assert design["excluded_within_guard"] + len(expected) == len(rows)
    assert expected == [r["fixture_row"] for r in design["catalog"]]
    labels, partitions = [], []
    anchor = rows[0]["reference"]["utc_ms"]
    for i, item in zip(expected, design["catalog"], strict=True):
        row = rows[i]["reference"]
        label = LABELS[latitudes[i] > cut]
        partition = (
            "heldout" if ((row["utc_ms"] - anchor) // 30000) % 2 else "calibration"
        )
        assert item["label"] == label and item["split"] == partition
        assert (
            max(
                abs(x - y)
                for x, y in zip(item["ecef_m"], wgs84_xyz(row["lla"]), strict=True)
            )
            < 1e-7
        )
        labels.append(label)
        partitions.append(partition)
    assert sorted(
        [r["world"] for r in design["plan"]] + design["unavailable_worlds"]
    ) == list(range(len(expected)))
    return cut, labels, partitions


def check_collision(plan, name, labels, predictions, gaps):
    record = plan["rosters"][name]
    indices = record["indices"]
    threshold = record["radius_4mm"]
    proof = record["collision"]
    a, b = proof["opposite_worlds"]
    assert len(indices) == len(set(indices)) and sorted(indices) == indices
    assert set(indices) <= set(range(predictions.shape[-1]))
    matrix = gaps[:, indices]
    if threshold:
        assert not np.any(colliding_rows(matrix, threshold - 1, 2))
    assert labels[a] != labels[b] and threshold >= 0
    assert len(proof["clock_4mm"]) == 2 and len(proof["fault_indices"]) == 2
    for world, offset, errors in zip(
        (a, b), proof["clock_4mm"], proof["fault_indices"], strict=True
    ):
        found = [
            j
            for j, (i, answer) in enumerate(
                zip(indices, proof["reply_4mm"], strict=True)
            )
            if abs(int(predictions[world, i]) * 4 + offset - answer) > threshold
        ]
        assert found == errors and len(errors) <= 1, (plan["world"], name)
    return threshold


def check_all_routes(plan, labels, pair_left, pair_right):
    predicted = np.array(plan["nominal_mm"], dtype=np.int64)
    assert predicted.shape == (len(labels), len(plan["satellites"]))
    prns = plan["satellites"]
    assert prns == sorted(set(prns))
    assert (
        len(prns) == len(plan["center_elevation_deg"])
        and min(plan["center_elevation_deg"]) >= 5
    )
    differences = predicted[pair_right] - predicted[pair_left]
    assert plan["rosters"]["all"]["indices"] == list(range(len(prns)))
    high = sorted(
        sorted(
            range(len(prns)), key=lambda i: (-plan["center_elevation_deg"][i], prns[i])
        )[:6]
    )
    assert plan["rosters"]["elevation_six"]["indices"] == high
    radius = check_collision(plan, "margin_six", labels, predicted, differences)
    winner = tuple(plan["rosters"]["margin_six"]["indices"])
    for name in MODES[1:]:
        check_collision(plan, name, labels, predicted, differences)
    assert len(winner) == 6
    # The winning pair and a few independent pairs provide cheap upper bounds;
    # all remaining competitors are checked against the full pair table.
    proof = plan["rosters"]["margin_six"]["collision"]
    a, b = proof["opposite_worlds"]
    prime = int(np.flatnonzero((pair_left == a) & (pair_right == b))[0])
    top = [prime, *range(min(7, len(differences)))]
    roster_index = list(combinations(range(len(prns)), 6))
    rivals = np.array(roster_index)
    limit = np.array([radius - (candidate < winner) for candidate in roster_index])
    # Check one bound per proposal. limit is lowered by a quarter mm for
    # lexicographically earlier rosters, which cannot tie a chosen optimum.
    witnesses = []
    for i, bound in enumerate(limit):
        if bound == radius:
            break
    else:
        i = len(limit)
    if i:
        witnesses.extend(
            np.any(
                colliding_rows(differences[top][:, rivals[:i]], radius - 1, 2), axis=0
            )
        )
    if i < len(limit):
        witnesses.extend(
            np.any(colliding_rows(differences[top][:, rivals[i:]], radius, 2), axis=0)
        )
    for j, observed in enumerate(witnesses):
        if not observed:
            assert np.any(colliding_rows(differences[:, rivals[j]], int(limit[j]), 2))
    assert len(witnesses) == plan["pruning"]["options"]
    assert plan["pruning"]["evaluated"] + plan["pruning"]["bounded"] == len(witnesses)
    return predicted, len(witnesses)


def route_latitude_from_z(p, lat):
    angle = radians(float(lat))
    e2 = 0.0066943799901413165
    a = 6378137
    return p * tan(angle) - a * e2 * sin(angle) / sqrt(1 - e2 * sin(angle) ** 2)


def pnt_test(point, cutoff, truth):
    if "position_ecef" not in point:
        return "abstain"
    x, y, z = point["position_ecef"]
    dist = hypot(x, y)
    margin = Decimal(15) / 111111
    if (
        route_latitude_from_z(dist, cutoff - margin)
        <= z
        <= route_latitude_from_z(dist, cutoff + margin)
    ):
        return "abstain"
    label = LABELS[z > route_latitude_from_z(dist, cutoff)]
    return "correct" if truth == label else "wrong"


def rank(values):
    target = -(-(len(values) + 1) * 9 // 10)
    picked = sorted([x for x in values if x is not None])
    return picked[target - 1] if len(picked) >= target else None


def decide(metric, threshold, truth):
    compatible = {
        l for l, x in metric.items() if threshold is not None and x <= threshold
    }
    return (
        "correct"
        if compatible == {truth}
        else "wrong"
        if len(compatible) == 1
        else "abstain"
    )


def check_orbits(fixture, design, exe, nav):
    center = [
        sum(w["ecef_m"][i] for w in design["catalog"]) / len(design["catalog"])
        for i in range(3)
    ]
    tasks, expected = [], []
    for j, row in enumerate(design["plan"]):
        if j % 20:
            continue
        meta = fixture["cases"][design["catalog"][row["world"]]["fixture_row"]]["epoch"]
        visible = [p["sat"] for p in meta["items"]]
        assert set(row["satellites"]) <= set(visible)
        for p in (0, len(design["catalog"]) // 2, len(design["catalog"]) - 1):
            xyz = design["catalog"][p]["ecef_m"]
            for column, sv in enumerate(row["satellites"]):
                tasks.append((meta["week"], meta["tow"], sv, xyz))
                expected.append(("nominal", row["nominal_mm"][p][column]))
        for column, sv in enumerate(row["satellites"]):
            tasks.append((meta["week"], meta["tow"], sv, center))
            expected.append(("elevation", row["center_elevation_deg"][column]))
    for got, (field, registered) in zip(
        predict(exe, nav, tasks), expected, strict=True
    ):
        assert got is not None
        if field == "nominal":
            assert round(got[field] * 1000) == registered
        else:
            assert abs(got[field] - registered) < 1e-6
    return len(tasks)


def audit(fixture, design, replay, report, exe, nav):
    cut, labels, partitions = scope(fixture, design)
    left = np.array([i for i, label in enumerate(labels) if label == "south"])
    right = np.array([i for i, label in enumerate(labels) if label == "north"])
    pairs = np.repeat(left, len(right)), np.tile(right, len(left))
    checks = 0
    for plan, row in zip(design["plan"], replay, strict=True):
        world = plan["world"]
        assert (
            row["world"] == world
            and row["truth"] == labels[world]
            and row["split"] == partitions[world]
        )
        matrix, robes = check_all_routes(plan, labels, *pairs)
        checks += robes
        example = fixture["cases"][design["catalog"][world]["fixture_row"]]["epoch"]
        received = {r["sat"]: round(1000 * r["pseudorange"]) for r in example["items"]}
        actual = np.array([received[s] for s in plan["satellites"]], dtype=np.int64)
        all_residuals = actual - matrix
        for name in MODES:
            record = plan["rosters"][name]
            measured = all_residuals[:, record["indices"]]
            raw_needed = [2 * min_span_with_omissions(z, 1) for z in measured]
            thresholds = {
                y: min(x for x, l in zip(raw_needed, labels, strict=True) if l == y)
                for y in LABELS
            }
            info = row["empirical"][name]
            assert (
                info["needed_4mm"] == raw_needed[world]
                and info["label_needed_4mm"] == thresholds
            )
            assert info["radius_4mm"] == record["radius_4mm"] and info["reads"] == len(
                record["indices"]
            )
            if name == "margin_six":
                scores = {y: [] for y in LABELS}
                for x, y in zip(measured, labels, strict=True):
                    loss = min(
                        5 * sum(v * v for v in kept) - sum(kept) ** 2
                        for kept in combinations(map(int, x), 5)
                    )
                    scores[y].append(loss)
                base = min(min(v) for v in scores.values())
                assert row["lts_scores_x5"] == {
                    l: min(v) - base for l, v in scores.items()
                }
    train = [r for r in replay if r["split"] == "calibration"]
    test = [r for r in replay if r["split"] == "heldout"]
    scales = {}
    for name in MODES:
        t = [r["empirical"][name] for r in train]
        q = rank(
            [
                Fraction(x["needed_4mm"], x["radius_4mm"]) if x["radius_4mm"] else None
                for x in t
            ]
        )
        scales[name] = q
        assert report["calibration_ratios"][name] == (
            [q.numerator, q.denominator] if q is not None else None
        )
    threshold = rank([r["lts_scores_x5"][r["truth"]] for r in train])
    assert report["lts_cutoff_x5"] == threshold
    verdict = {
        name: {label: Counter() for label in LABELS}
        for name in report["heldout_by_method"]
    }
    for row in test:
        truth = row["truth"]
        d = {}
        for name in MODES:
            sample = row["empirical"][name]
            gate = sample["radius_4mm"]
            q = scales[name]
            t = gate * q if gate and q is not None and q < 1 else None
            d[name] = decide(sample["label_needed_4mm"], t, truth)
            d[name + "_limit"] = decide(sample["label_needed_4mm"], gate - 1, truth)
            d[name + "_rtklib"] = pnt_test(row["rtklib"][name], cut, truth)
        d["lts"] = decide(row["lts_scores_x5"], threshold, truth)
        assert d == row["decisions"]
        for m, outcome in d.items():
            verdict[m][truth][outcome] += 1
    assert verdict == report["heldout_by_method"]
    total = Counter(r["truth"] for r in test)
    direct = verdict["margin_six"]
    assert total == report["heldout_labels"]
    q = scales["margin_six"]
    factors = {
        "threshold_below_collision": q is not None and q < 1,
        "six_cheaper_at_every_test": min(r["empirical"]["all"]["reads"] for r in test)
        > 6,
        "north_test_count": total["north"] >= 8,
        "eighty_percent_correct_each": all(
            Fraction(direct[l]["correct"], total[l]) >= Fraction(4, 5) for l in LABELS
        ),
        "zero_wrong": sum(direct[l]["wrong"] for l in LABELS) == 0,
        "matches_lts_each": all(
            direct[l]["correct"] >= verdict["lts"][l]["correct"] for l in LABELS
        ),
    }
    assert report["gate_inputs"] == factors and report["gate"] == all(factors.values())
    return {
        "verified_rosters": checks,
        "tested_collision_witnesses": 3 * len(replay),
        "verified_calibration": len(train),
        "verified_heldout": len(test),
        "reread_nominal_cells": check_orbits(fixture, design, exe, nav),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("fixture", "design", "replay", "report", "executable", "navigation"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    d = unpack(a.design)
    r = json.loads(a.report.read_bytes())
    assert d["fixture_sha256"] == sha256(a.fixture.read_bytes()).hexdigest()
    assert r["design_sha256"] == sha256(a.design.read_bytes()).hexdigest()
    print(
        json.dumps(
            audit(unpack(a.fixture), d, unpack(a.replay), r, a.executable, a.navigation)
        )
    )
