"""Audit matched routes, task placement, score digests, and all timing gates."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha256
from heapq import heappop, heappush
from itertools import product
import json
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
from audit_runtime_strata_check import verify_plan

PRIOR = (0, 12, 24, 34, 48, 59)
NEW = (1, 7, 13, 22, 42, 58)
CASES = tuple(sorted((*PRIOR, *NEW)))
ROUTES = ("independent", "stratified")
ENGINES = ("operator", "bucket", "balanced")
ARMS = tuple(f"{route}_{engine}" for route, engine in product(ROUTES, ENGINES))
TRACE = "audit-runtime-parallel-trace.json.gz"
RESULTS = "audit-runtime-parallel-results.json"


def records(ledger, plans):
    rows, _ = load_records(ledger, plans)
    groups = {
        r["case"]: r["new"]["blocks"]
        for r in json.loads(gzip.decompress(locked(plans, PARTITIONS)))
        if r["case"] in CASES and r["threshold"] == "0"
    }
    assert set(groups) == set(CASES)
    return rows, groups


def task_layout(widths):
    seen = defaultdict(list)
    for i, e in enumerate(widths):
        seen[e].append(i)
    buckets = list(seen.values())
    pending = [(0, j) for j in range(min(4, len(buckets)))]
    slots = [[] for _ in pending]
    for w, i in sorted((-e, i) for i, e in enumerate(widths)):
        cost, j = heappop(pending)
        slots[j].append(i)
        heappush(pending, (cost + w * w, j))
    return buckets, [sorted(s) for s in slots]


def describe(rows):
    arms = {}
    for arm in ARMS:
        clock = [r["elapsed"][arm] for r in rows]
        arms[arm] = {
            "median_ns": str(median(map(F, clock))),
            "p95_ns": p95(clock),
            "mean_calls": str(F(sum(len(r["jobs"][arm]) for r in rows), len(clock))),
            "cpu_ns": sum(r["cpu"][arm] for r in rows),
            "mean_peak_square_work": str(
                F(sum(r["peak_work"][arm] for r in rows), len(clock))
            ),
        }
    labels = {
        "combined": ("stratified_balanced", "independent_operator"),
        **{
            f"{s}_{e}": (f"{s}_{e}", f"{s}_operator")
            for s in ROUTES
            for e in ("bucket", "balanced")
        },
        **{f"{s}_balance_vs_bucket": (f"{s}_balanced", f"{s}_bucket") for s in ROUTES},
    }
    relative = {}
    for name, (a, b) in labels.items():
        values = comparison(
            [r["elapsed"][a] for r in rows], [r["elapsed"][b] for r in rows]
        )
        values["call_ratio"] = str(F(arms[a]["mean_calls"]) / F(arms[b]["mean_calls"]))
        cpu = arms[b]["cpu_ns"]
        values["cpu_ratio"] = str(F(arms[a]["cpu_ns"], cpu)) if cpu else None
        relative[name] = values
    return {"count": len(rows), "arms": arms, "comparison": relative}


def summarize(ledger, plans, data):
    rows, blocks = records(ledger, plans)
    assert data["graph"] == GRAPH
    batches = data["batches"]
    assert len(batches) == 1152
    for (rep, c, w), chunk in zip(
        product(range(2), CASES, range(3)),
        (batches[k : k + 16] for k in range(0, len(batches), 16)),
        strict=True,
    ):
        hist = {route: [Counter() for _ in range(8)] for route in ROUTES}
        for i, row in enumerate(chunk):
            assert row["key"] == [rep, c, w, i]
            mode = row["route"]
            assert set(mode) == set(ROUTES)
            shift = (rep + c + w + i) % 6
            assert row["order"] == list(ARMS[shift:] + ARMS[:shift])
            for key in ("elapsed", "cpu", "jobs", "sha256", "peak_work"):
                assert set(row[key]) == set(ARMS)
            if i < 8:
                assert mode["independent"] == mode["stratified"]
            else:
                common = [0] * 8
                for k, b in enumerate(blocks[c]):
                    for j in b:
                        common[j] = k
                verify_plan(
                    {"common": common, "stratified": mode["stratified"]}, blocks[c]
                )
            for route, z in mode.items():
                assert len(z) == 8 and all(type(x) is int and 0 <= x < 8 for x in z)
                for k, m in enumerate(z):
                    hist[route][k][m] += 1
                widths = [
                    max(int(item["length"]), MODES[j])
                    for item, j in zip(rows[c, w], z, strict=True)
                ]
                buckets, balanced = task_layout(widths)
                code = sha256(expected(rows[c, w], z)).hexdigest()
                for engine in ENGINES:
                    a = f"{route}_{engine}"
                    jobs = balanced if engine == "balanced" else buckets
                    assert jobs == row["jobs"][a]
                    assert row["sha256"][a] == code
                    assert type(row["elapsed"][a]) is int and row["elapsed"][a] > 0
                    assert type(row["cpu"][a]) is int and row["cpu"][a] >= 0
                    want = (
                        sum(v * v for v in widths)
                        if engine == "operator"
                        else max(sum(widths[t] ** 2 for t in job) for job in jobs)
                    )
                    assert row["peak_work"][a] == want
        assert all(a == {i: 2 for i in range(8)} for q in hist.values() for a in q)
    rounds = []
    for r in range(2):
        run = [x for x in batches if x["key"][0] == r]
        rounds.append(
            {
                "whole": describe(run),
                "new": describe([x for x in run if x["key"][1] in NEW]),
                "reused": describe([x for x in run if x["key"][1] in PRIOR]),
            }
        )
    gate = True
    transfer = True
    for r in rounds:
        v = r["whole"]["comparison"]["combined"]
        gate &= (
            F(v["p95_ratio"]) <= F(19, 20)
            and F(v["paired_median_ratio"]) <= F(21, 20)
            and F(v["call_ratio"]) <= F(19, 20)
        )
        transfer &= F(r["new"]["comparison"]["combined"]["p95_ratio"]) <= F(21, 20)
    return {
        "graph": GRAPH,
        "environment": data["environment"],
        "batches": len(batches),
        "measurements": len(batches) * len(ARMS),
        "bitwise_scores": len(batches) * len(ARMS) * 24,
        "rounds": rounds,
        "primary_gate": gate,
        "transfer_gate": transfer,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for k in ("ledger", "plans", "directory"):
        cli.add_argument(k, type=Path)
    a = cli.parse_args()
    report = summarize(
        a.ledger,
        a.plans,
        json.loads(gzip.decompress((a.directory / TRACE).read_bytes())),
    )
    assert report == json.loads((a.directory / RESULTS).read_bytes())
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "measurements",
                    "bitwise_scores",
                    "primary_gate",
                    "transfer_gate",
                )
            }
            | {"verified": True}
        )
    )
