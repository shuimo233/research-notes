"""Independently check weighted rosters with interval intersections."""

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import isclose
from pathlib import Path

import numpy as np

from gnss_clock_audit_check import state_epochs, wgs84_xyz

LABELS = ("south", "north")
MODES = ("weighted", "geometry", "elevation", "strength", "all")


def unpack(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def exact_fraction(record):
    return None if record is None else Fraction(*record)


def intersect(centers, widths, radius, failures, strict=False):
    a, b = radius.numerator, radius.denominator
    origins = centers * b
    extents = widths * a
    low, high = origins - extents, origins + extents
    shape = centers.shape[:-1]
    possible = np.zeros(shape, dtype=bool)
    needed = centers.shape[-1] - failures
    for i in range(centers.shape[-1]):
        p = low[..., i, None]
        good = (low <= p) & ((p < high) if strict else (p <= high))
        possible |= np.count_nonzero(good, axis=-1) >= needed
        if np.all(possible):
            break
    return possible


def winner_upper(diffs, weights, expected, pair, bound):
    n = len(weights)
    pool = list(combinations(range(n), 6))
    rival = np.array(pool, dtype=np.int64)
    first = [pair, *range(min(8, len(diffs)))]
    start = pool.index(expected)
    fast = []
    for a, b, strict in ((0, start, True), (start, len(pool), False)):
        if a < b:
            fast.extend(
                np.any(
                    intersect(
                        diffs[first][:, rival[a:b]],
                        weights[rival[a:b]],
                        bound,
                        2,
                        strict,
                    ),
                    axis=0,
                )
            )
    for j, exists in enumerate(fast):
        if not exists:
            assert np.any(
                intersect(diffs[:, rival[j]], weights[rival[j]], bound, 2, j < start)
            )
    assert len(fast) == len(pool)
    return len(pool)


def interval_witness(table, weights, diffs, portfolio, lo, hi, labels):
    indices = portfolio["indices"]
    bound = exact_fraction(portfolio["radius2"])
    assert not intersect(diffs[:, indices], weights[indices], bound, 2, True).any()
    a, b = portfolio["pair"]
    assert labels[a] == "south" and labels[b] == "north"
    lim = np.flatnonzero((lo == a) & (hi == b))
    assert len(lim) == 1
    sample = portfolio["witness"]
    reply = [Fraction(*v) for v in sample["reply_mm"]]
    clocks = [Fraction(*v) for v in sample["clocks_mm"]]
    assert len(clocks) == 2 and len(sample["faults"]) == 2
    for i, world in enumerate((a, b)):
        failed = [
            j
            for j, (p, r) in enumerate(zip(indices, reply, strict=True))
            if abs(r - int(table[world, p]) - clocks[i]) > bound * int(weights[p]) / 2
        ]
        assert failed == sample["faults"][i] and len(failed) <= 1
    return int(lim[0]), bound


def choice(metric, cap, truth, strict=False):
    labels = {
        y
        for y in LABELS
        if cap is not None and (metric[y] < cap if strict else metric[y] <= cap)
    }
    return (
        "correct" if labels == {truth} else "wrong" if len(labels) == 1 else "abstain"
    )


def population_rank(values):
    rank = -(-(len(values) + 1) * 9 // 10)
    known = sorted(v for v in values if v is not None)
    return known[rank - 1] if rank <= len(known) else None


def scope(fixture, plan, old):
    if old:
        assert plan["catalog"] == old["catalog"] and plan["temporal_thinning"] == 0
        assert plan["guard_excluded"] == old["excluded_within_guard"]
        assert plan["unavailable_worlds"] == old["unavailable_worlds"]
        assert [r["world"] for r in plan["plan"]] == [r["world"] for r in old["plan"]]
        return
    cases = fixture["cases"]
    lat = [Decimal(str(r["reference"]["lla"][0])) for r in cases]
    mid = (max(lat) + min(lat)) / 2
    assert plan["boundary_deg"] == str(mid)
    after = [i for i, x in enumerate(lat) if abs(x - mid) * 111111 > 15]
    assert plan["guard_excluded"] == len(cases) - len(after)
    t0 = cases[0]["reference"]["utc_ms"]
    groups = {}
    for i in after:
        t = cases[i]["reference"]["utc_ms"] - t0
        groups.setdefault(t // 30000, []).append(i)
    selected = sorted(
        (
            min(
                rows,
                key=lambda i: (
                    abs(cases[i]["reference"]["utc_ms"] - t0 - 30000 * slot - 15000),
                    i,
                ),
            ),
            slot,
        )
        for slot, rows in groups.items()
    )
    assert plan["temporal_thinning"] == len(after) - len(selected) and len(
        selected
    ) == len(plan["catalog"])
    for row, (i, slot) in zip(plan["catalog"], selected, strict=True):
        assert row["fixture_row"] == i and row["label"] == LABELS[lat[i] > mid]
        assert row["split"] == ("heldout" if (slot // 2) % 2 else "calibration")
        assert (
            max(
                abs(x - y)
                for x, y in zip(
                    row["ecef_m"], wgs84_xyz(cases[i]["reference"]["lla"]), strict=True
                )
            )
            < 1e-7
        )
    assert sorted(
        [x["world"] for x in plan["plan"]] + plan["unavailable_worlds"]
    ) == list(range(len(selected)))


def audit_case(fixture, design, replay, old, left, right, labels):
    expected_world = design["world"]
    assert (
        replay["world"] == expected_world and replay["truth"] == labels[expected_world]
    )
    src = old if old is not None else design
    sats = src["satellites"]
    assert sats == sorted(set(sats)) and len(sats) >= 6
    raw = {x["sat"]: x for x in fixture["epoch"]["items"]}
    weights = np.array(
        [
            max(1, round(1024 * 10 ** ((40 - max(15, min(50, raw[i]["cn0"]))) / 20)))
            for i in sats
        ],
        dtype=np.int64,
    )
    assert weights.tolist() == design["weights"]
    table = np.array(src["nominal_mm"], dtype=np.int64)
    assert table.shape == (len(labels), len(sats))
    diffs = table[right] - table[left]
    benchmarks = {
        "all": list(range(len(sats))),
        "elevation": sorted(
            sorted(
                range(len(sats)),
                key=lambda i: (-src["center_elevation_deg"][i], sats[i]),
            )[:6]
        ),
        "strength": sorted(
            sorted(range(len(sats)), key=lambda i: (-raw[sats[i]]["cn0"], sats[i]))[:6]
        ),
    }
    if old:
        benchmarks["geometry"] = old["rosters"]["margin_six"]["indices"]
    for mode, m in benchmarks.items():
        assert design["rosters"][mode]["indices"] == m
    readings = np.array(
        [round(raw[k]["pseudorange"] * 1000) for k in sats], dtype=np.int64
    )
    residual = readings - table
    cases = 0
    for mode in MODES:
        row = design["rosters"][mode]
        take = row["indices"]
        assert take == sorted(set(take)) and len(take) == (
            len(sats) if mode == "all" else 6
        )
        assert set(take) <= set(range(len(sats)))
        pair, bound = interval_witness(table, weights, diffs, row, left, right, labels)
        if mode == "weighted":
            cases = winner_upper(diffs, weights, tuple(take), pair, bound)
        if mode == "geometry" and old is None:
            # Use independent minimum-span ranking for the unweighted roster.
            plain = diffs[:, take]
            earliest = min(
                (
                    (max(z) - min(z))
                    for row in plain
                    for z in combinations(map(int, row), 4)
                )
            )
            witness_pair = next(
                j
                for j, z in enumerate(plain)
                if intersect(
                    z[None, :], np.ones(6, dtype=np.int64), Fraction(earliest, 2), 2
                )[0]
            )
            winner_upper(
                diffs,
                np.ones(len(sats), dtype=np.int64),
                tuple(take),
                witness_pair,
                Fraction(earliest, 2),
            )
        report = replay["rosters"][mode]
        assert report["radius2"] == row["radius2"] and report["reads"] == len(take)
        observed = residual[:, take]
        adjusted = 2 * observed
        for y in (*LABELS, "actual"):
            rows = (
                adjusted[labels == y]
                if y != "actual"
                else adjusted[expected_world : expected_world + 1]
            )
            got = exact_fraction(
                report["true_needed2"] if y == "actual" else report["labels_needed2"][y]
            )
            assert intersect(rows, weights[take], got, 1).any()
            assert not intersect(rows, weights[take], got, 1, True).any()
        if mode == "weighted":
            scores = {y: [] for y in LABELS}
            for world, v in enumerate(observed):
                loss = min(
                    5 * sum(x * x for x in surviving) - sum(surviving) ** 2
                    for surviving in combinations(map(int, v), 5)
                )
                scores[labels[world]].append(loss)
            baseline = min(min(values) for values in scores.values())
            assert replay["lts_x5"] == {y: min(z) - baseline for y, z in scores.items()}
    assert cases == design["optimization"]["options"]
    return cases


def check_summary(replay, report, external):
    t = [r for r in replay if r["split"] == "calibration"]
    v = [r for r in replay if r["split"] == "heldout"]
    assert report["calibration_counts"] == Counter(x["truth"] for x in t)
    assert report["heldout_counts"] == Counter(x["truth"] for x in v)
    ratios = {}
    for m in MODES:
        scores = []
        for row in t:
            z = row["rosters"][m]
            needed, rad = (exact_fraction(z[k]) for k in ("true_needed2", "radius2"))
            scores.append(needed / rad if rad else None)
        q = population_rank(scores)
        assert q == exact_fraction(report["ratios"][m])
        assert report["calibration_inside"][m] == sum(
            x is not None and x < 1 for x in scores
        )
        ratios[m] = q
    ls = population_rank([x["lts_x5"][x["truth"]] for x in t])
    assert ls == report["lts_cutoff_x5"]
    modes = (*MODES, *(m + "_limit" for m in MODES), "lts")
    verdict = {m: {y: Counter() for y in LABELS} for m in modes}
    for row in v:
        y = row["truth"]
        decisions = {}
        for m in MODES:
            z = row["rosters"][m]
            beta = ratios[m]
            rad = Fraction(*z["radius2"])
            scores = {k: Fraction(*score) for k, score in z["labels_needed2"].items()}
            decisions[m] = choice(
                scores, beta * rad if rad and beta is not None and beta < 1 else None, y
            )
            decisions[m + "_limit"] = choice(scores, rad, y, True)
        decisions["lts"] = choice(row["lts_x5"], ls, y)
        assert decisions == row["decision"]
        for m, status in decisions.items():
            verdict[m][y][status] += 1
    assert verdict == report["by_method"]
    counts = Counter(x["truth"] for x in v)
    primary = verdict["weighted"]
    comparisons = ("geometry", "elevation", "strength", "lts")
    factors = {
        "external_dataset": external,
        "each_class_count": all(counts[y] >= 8 for y in LABELS),
        "saves_one_everywhere": bool(v)
        and all(x["rosters"]["all"]["reads"] > 6 for x in v),
        "below_collision": ratios["weighted"] is not None and ratios["weighted"] < 1,
        "each_class_80_correct": all(
            counts[y] > 0 and primary[y]["correct"] / counts[y] >= 0.8 for y in LABELS
        ),
        "zero_wrong": sum(primary[y]["wrong"] for y in LABELS) == 0,
        "beats_or_matches_each_baseline": all(
            primary[y]["correct"] >= verdict[m][y]["correct"]
            for m in comparisons
            for y in LABELS
        ),
        "strictly_beats_geometry_total": sum(primary[y]["correct"] for y in LABELS)
        > sum(verdict["geometry"][y]["correct"] for y in LABELS),
    }
    assert factors == report["gate_inputs"] and report["gate"] == all(factors.values())
    return len(t), len(v)


def audit_raw(log, ref, nav, fixture):
    values, c = state_epochs(log)
    data = fixture["inputs"]
    assert data["source_sha256"] == {
        p.name: sha256(p.read_bytes()).hexdigest() for p in (log, ref, nav)
    }
    assert data["raw_epochs"] == len(values) and data["raw_counts"] == c
    grid = []
    for line in ref.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("%"):
            continue
        day, t, lat, lon, h, q, *_ = line.split()
        stamp = datetime.strptime(day + " " + t, "%Y/%m/%d %H:%M:%S.%f").replace(
            tzinfo=timezone.utc
        )
        utc = round((stamp - timedelta(seconds=18)).timestamp() * 1000)
        grid.append((utc, tuple(map(Decimal, (lat, lon, h))), int(q)))
    times = [x[0] for x in grid]
    assert data["reference_quality"] == Counter(str(x[2]) for x in grid)
    known = {}
    skips = Counter()
    for key, items in values.items():
        tow = sorted(o[3] for o in items.values())
        m = len(tow) // 2
        middle = tow[m] if len(tow) % 2 else (tow[m - 1] + tow[m]) / 2
        week = next(iter(items.values()))[2]
        instant = 315964800000 + week * 604800000 + round(middle * 1000) - 18000
        j = bisect_left(times, instant)
        if j < len(times) and times[j] == instant:
            endpoints = [grid[j]]
        elif 0 < j < len(times) and times[j] - times[j - 1] <= 1000:
            endpoints = grid[j - 1 : j + 1]
        else:
            skips["missing_adjacent_reference"] += 1
            continue
        if any(x[2] != 1 for x in endpoints):
            skips["reference_not_fixed"] += 1
            continue
        known[key] = instant, endpoints
    assert data["excluded"] == skips
    assert len(known) == len(fixture["cases"]) == data["aligned_fixed_interpolated"]
    assert [r["reference"]["utc_ms"] for r in fixture["cases"]] == sorted(
        v[0] for v in known.values()
    )
    total = 0
    for row in fixture["cases"]:
        key = tuple(row["epoch"]["clock_key"])
        t, ends = known.pop(key)
        expected = row["reference"]
        assert expected["utc_ms"] == t == row["epoch"]["measurement_utc_ms"]
        lead, follow = ends[0], ends[-1]
        equal = (
            Decimal(t - lead[0]) / (follow[0] - lead[0]) if follow[0] != lead[0] else 0
        )
        truth = [a + equal * (b - a) for a, b in zip(lead[1], follow[1], strict=True)]
        assert all(
            isclose(float(x), y, abs_tol=1e-9, rel_tol=0)
            for x, y in zip(truth, expected["lla"], strict=True)
        )
        assert expected["fixed_bracket"] == [
            {"utc_ms": u, "lla": list(map(float, p)), "quality": q} for u, p, q in ends
        ]
        assert {x["sat"] for x in row["epoch"]["items"]} == set(values[key])
        for item in row["epoch"]["items"]:
            meters, _, _, _, strength = values[key][item["sat"]]
            assert (
                abs(float(meters) - item["pseudorange"]) < 1e-7
                and float(strength) == item["cn0"]
            )
            total += 1
    return total


def verify(fixture, design, replay, summary, old):
    scope(fixture, design, old)
    labels = np.array([s["label"] for s in design["catalog"]])
    south, north = np.flatnonzero(labels == "south"), np.flatnonzero(labels == "north")
    left, right = np.repeat(south, len(north)), np.tile(north, len(south))
    source = {r["world"]: r for r in old["plan"]} if old else {}
    tested = 0
    for record, result in zip(design["plan"], replay, strict=True):
        scene = design["catalog"][record["world"]]
        assert result["split"] == scene["split"]
        tested += audit_case(
            fixture["cases"][scene["fixture_row"]],
            record,
            result,
            source.get(record["world"]),
            left,
            right,
            labels,
        )
    fit, check = check_summary(replay, summary, old is None)
    return {
        "verified_six_star_combinations": tested,
        "verified_collision_replies": 5 * len(replay),
        "verified_calibration": fit,
        "verified_heldout": check,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("fixture", "design", "replay", "result"):
        p.add_argument(k, type=Path)
    p.add_argument("--geometry", type=Path)
    p.add_argument("--s3-inputs", type=Path, nargs=3)
    a = p.parse_args()
    fixture, design, replay = [unpack(x) for x in (a.fixture, a.design, a.replay)]
    old = unpack(a.geometry) if a.geometry else None
    summary = json.loads(a.result.read_bytes())
    assert design["fixture_sha256"] == sha256(a.fixture.read_bytes()).hexdigest()
    assert summary["design_sha256"] == sha256(a.design.read_bytes()).hexdigest()
    assert design["geometry_sha256"] == (
        sha256(a.geometry.read_bytes()).hexdigest() if a.geometry else None
    )
    checked = verify(fixture, design, replay, summary, old)
    if a.s3_inputs:
        checked["verified_raw_s3_pseudoranges"] = audit_raw(*a.s3_inputs, fixture)
    print(json.dumps(checked))
