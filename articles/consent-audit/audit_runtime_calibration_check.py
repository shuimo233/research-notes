"""Check calibration, exact task placement, and held-out clock comparisons."""

import argparse
from collections import Counter
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import product
import json
from math import ceil
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_runtime_latency_check import (
    GRAPH,
    MODES,
    PARTITIONS,
    comparison,
    expected,
    load_records,
    locked,
    p95,
)
from audit_runtime_parallel_check import task_layout
from audit_runtime_parallel_oracle import exact_peak
from audit_runtime_strata_check import verify_plan

CALIBRATION = (3, 6, 10)
PRIOR = (0, 1, 12, 22, 34, 58)
NEW = (4, 11, 26, 32, 44, 56)
CASES = tuple(sorted((*PRIOR, *NEW)))
ORDERS = (("default", "squared", "calibrated"), ("calibrated", "squared", "default"))
ARMS = ORDERS[0]
MODEL = "audit-runtime-calibration-profile.json"
TRACE = "audit-runtime-calibration-trace.json.gz"
RESULTS = "audit-runtime-calibration-results.json"


def records(ledger, plans):
    rows, _ = load_records(ledger, plans)
    groups = {
        v["case"]: v["new"]["blocks"]
        for v in json.loads(gzip.decompress(locked(plans, PARTITIONS)))
        if v["threshold"] == "0" and v["case"] in CASES
    }
    assert set(groups) == set(CASES)
    return rows, groups


def sources(rows):
    anchors = []
    for c in CALIBRATION:
        _, w, s = min(
            (int(r["length"]), w, s) for w in range(3) for s, r in enumerate(rows[c, w])
        )
        anchors.append([c, w, s])
    widths = sorted(
        {
            max(v, int(r["length"]))
            for c, w in product(CASES, range(3))
            for r in rows[c, w]
            for v in MODES
        }
    )
    return anchors, widths


def calibration(rows, data):
    anchors, widths = sources(rows)
    assert data["anchors"] == anchors and data["graph"] == GRAPH
    assert list(map(int, data["widths"])) == widths
    lookup = {}
    for width, values in data["widths"].items():
        assert len(values["pairs"]) == 12
        samples = []
        for (a, r), record in zip(
            product(range(3), range(4)), values["pairs"], strict=True
        ):
            assert record[:2] == [a, r]
            _, _, first, two, four = record
            assert first == (2 if (a + r + int(width)) % 2 == 0 else 4)
            assert type(two) is int and type(four) is int and min(two, four) > 0
            samples.append(F(four - two, 2))
        lookup[int(width)] = max(1, ceil(median(samples)))
        assert lookup[int(width)] == values["marginal_ns"]
    return lookup


def describe(chunks):
    elapsed = {a: [q[a]["ns"] for q in chunks] for a in ARMS}
    calls = {a: sum(len(q[a]["jobs"]) for q in chunks) for a in ARMS}
    views = {}
    for name, a, b in (
        ("calibrated_default", "calibrated", "default"),
        ("squared_default", "squared", "default"),
        ("calibrated_squared", "calibrated", "squared"),
    ):
        v = comparison(elapsed[a], elapsed[b])
        v["call_ratio"] = str(F(calls[a], calls[b]))
        views[name] = v
    return {
        "pairs": len(chunks),
        "arms": {
            a: {
                "p95_ns": p95(elapsed[a]),
                "median_ns": str(median(map(F, elapsed[a]))),
                "mean_calls": str(F(calls[a], len(chunks))),
            }
            for a in ARMS
        },
        "comparison": views,
    }


def summarize(ledger, plans, measured, experiments):
    rows, groups = records(ledger, plans)
    cost = calibration(rows, measured)
    assert len(experiments) == 2
    outcomes = []
    for rep, batches in enumerate(experiments):
        assert [a["arm"] for a in batches] == list(ORDERS[rep])
        schedules = {a["arm"]: a["batches"] for a in batches}
        report = []
        by_case = {a: [] for a in CASES}
        wins = 0
        before, after = 0, 0
        planner = []
        sample_routes = []
        length = 576
        assert all(len(a) == length for a in schedules.values())
        for (c, w, step), chunk in zip(
            product(CASES, range(3), range(16)),
            zip(*(schedules[a] for a in ARMS), strict=True),
            strict=True,
        ):
            k = [rep, c, w, step]
            route = chunk[0]["route"]
            assert all(x["key"] == k and x["route"] == route for x in chunk)
            assert len(route) == 8 and all(type(x) is int and 0 <= x < 8 for x in route)
            sample_routes.append(route)
            if step >= 8:
                cover = [0] * 8
                for j, b in enumerate(groups[c]):
                    for i in b:
                        cover[i] = j
                verify_plan({"common": cover, "stratified": route}, groups[c])
            if step == 15:
                assert all(
                    Counter(z) == {a: 2 for a in range(8)}
                    for z in zip(*sample_routes, strict=True)
                )
                sample_routes = []
            width = [
                max(int(r["length"]), MODES[i])
                for r, i in zip(rows[c, w], route, strict=True)
            ]
            buckets, squared = task_layout(width)
            want = sha256(expected(rows[c, w], route)).hexdigest()
            b, z, a = chunk
            assert b["jobs"] == buckets and z["jobs"] == squared
            assert 1 <= len(a["jobs"]) <= min(4, len(buckets)) and all(a["jobs"])
            assert sorted(i for part in a["jobs"] for i in part) == list(range(8))
            costs = [cost[t] for t in width]
            objective = max(sum(costs[i] for i in q) for q in a["jobs"])
            old_peak = max(sum(costs[i] for i in q) for q in squared)
            assert objective == exact_peak(
                tuple(sorted(costs, reverse=True)), min(4, len(buckets))
            )
            assert old_peak >= objective
            wins += old_peak > objective
            before += old_peak
            after += objective
            planner.append(a["planner_ns"])
            for x in chunk:
                assert x["sha256"] == want and type(x["ns"]) is int and x["ns"] > 0
                assert type(x["planner_ns"]) is int and 0 <= x["planner_ns"] <= x["ns"]
            frame = dict(zip(ARMS, chunk, strict=True))
            report.append(frame)
            by_case[c].append(frame)
        outcomes.append(
            {
                "whole": describe(report),
                "new": describe([x for c in NEW for x in by_case[c]]),
                "reused": describe([x for c in PRIOR for x in by_case[c]]),
                "strictly_improved_proxy_batches": wins,
                "proxy_sum_ratio": str(F(after, before)),
                "planner_median_ns": str(median(map(F, planner))),
                "planner_p95_ns": p95(planner),
            }
        )
    gate = True
    transfer = True
    for r in outcomes:
        a = r["whole"]["comparison"]["calibrated_default"]
        gate &= (
            F(a["p95_ratio"]) <= F(19, 20)
            and F(a["call_ratio"]) <= F(19, 20)
            and F(a["paired_median_ratio"]) <= F(21, 20)
        )
        transfer &= F(r["new"]["comparison"]["calibrated_default"]["p95_ratio"]) <= F(
            21, 20
        )
    return {
        "rounds": outcomes,
        "calibrated_widths": len(cost),
        "calibration_pairs": len(cost) * 12,
        "measurements": 3456,
        "bitwise_scores": 82944,
        "primary_gate": gate,
        "transfer_gate": transfer,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("ledger", "plans", "folder"):
        cli.add_argument(name, type=Path)
    a = cli.parse_args()
    profile = json.loads((a.folder / MODEL).read_bytes())
    trace = json.loads(gzip.decompress((a.folder / TRACE).read_bytes()))
    report = summarize(a.ledger, a.plans, profile, trace)
    assert report == json.loads((a.folder / RESULTS).read_bytes())
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "calibrated_widths",
                    "measurements",
                    "bitwise_scores",
                    "primary_gate",
                    "transfer_gate",
                )
            }
            | {"verified": True}
        )
    )
