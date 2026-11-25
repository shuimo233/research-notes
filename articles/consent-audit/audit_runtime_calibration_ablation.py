"""Matched two-factor comparison using a frozen calibration table."""

import argparse
from collections import Counter
from fractions import Fraction as F
import gzip
from hashlib import sha256
from heapq import heappop, heappush
from itertools import product
import json
from math import ceil
from pathlib import Path
from random import Random
from time import perf_counter_ns

from audit_runtime_calibration import CalibratedPlanner, optimal_tasks
from audit_runtime_calibration_check import calibration
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
from audit_runtime_parallel_oracle import exact_peak
from audit_runtime_strata_check import verify_plan

CASES = (14, 16, 20, 25, 43, 49)
ARMS = ("squared_greedy", "squared_exact", "calibrated_greedy", "calibrated_exact")
PAIRS = {
    "weight_at_greedy": ("calibrated_greedy", "squared_greedy"),
    "exact_at_calibrated": ("calibrated_exact", "calibrated_greedy"),
    "exact_at_squared": ("squared_exact", "squared_greedy"),
    "combined": ("calibrated_exact", "squared_greedy"),
}
DIGEST = "870faea836d6b6c6c6c127cf2d011faa759894206d3f46cdc51b8823776a9502"
TRACE = "audit-runtime-calibration-ablation-trace.json.gz"
RESULTS = "audit-runtime-calibration-ablation-results.json"


def data(ledger, policies, profile):
    rows, _ = load_records(ledger, policies)
    groups = {
        r["case"]: r["new"]["blocks"]
        for r in json.loads(gzip.decompress(locked(policies, PARTITIONS)))
        if r["case"] in CASES and r["threshold"] == "0"
    }
    assert set(groups) == set(CASES)
    contents = profile.read_bytes()
    assert sha256(contents).hexdigest() == DIGEST
    return rows, groups, calibration(rows, json.loads(contents))


def greedy(weights, k):
    tasks = [[] for _ in range(k)]
    live = [(0, i) for i in range(k)]
    for neg, i in sorted((-w, j) for j, w in enumerate(weights)):
        load, lane = heappop(live)
        tasks[lane].append(i)
        heappush(live, (load - neg, lane))
    return [sorted(b) for b in tasks]


def linear_lookup(profile, w):
    if w in profile:
        return profile[w]
    a = max((k for k in profile if k < w), default=None)
    b = min((k for k in profile if k > w), default=None)
    if a is None:
        return profile[b]
    if b is None:
        return profile[a]
    return ceil(F((b - w) * profile[a] + (w - a) * profile[b], b - a))


def summarize(ledger, policies, table, trace):
    rows, groups, profile = data(ledger, policies, table)
    assert len(trace) == 576
    missed = Counter()
    execution = []
    for (rep, c, w), chunk in zip(
        product(range(2), CASES, range(3)),
        (trace[i : i + 16] for i in range(0, len(trace), 16)),
        strict=True,
    ):
        choices = []
        for step, r in enumerate(chunk):
            assert r["key"] == [rep, c, w, step]
            z = r["route"]
            assert len(z) == 8 and all(type(m) is int and 0 <= m < 8 for m in z)
            choices.append(z)
            if step >= 8:
                reference = [0] * 8
                for j, b in enumerate(groups[c]):
                    for i in b:
                        reference[i] = j
                verify_plan({"common": reference, "stratified": z}, groups[c])
            widths = [
                max(int(row["length"]), MODES[i])
                for row, i in zip(rows[c, w], z, strict=True)
            ]
            k = min(4, len(set(widths)))
            missed.update(v for v in widths if v not in profile)
            assert set(r["details"]) == set(ARMS)
            shift = (rep + c + w + step) % 4
            assert r["order"] == list(ARMS[shift:] + ARMS[:shift])
            frozen = sha256(expected(rows[c, w], z)).hexdigest()
            for a, rec in r["details"].items():
                jobs = rec["jobs"]
                assert (
                    rec["sha256"] == frozen and type(rec["ns"]) is int and rec["ns"] > 0
                )
                assert 1 <= len(jobs) <= k and all(jobs)
                assert sorted(i for j in jobs for i in j) == list(range(8))
                weights = [
                    linear_lookup(profile, v) if a.startswith("calibrated") else v * v
                    for v in widths
                ]
                maximum = max(sum(weights[i] for i in j) for j in jobs)
                if a.endswith("exact"):
                    assert maximum == exact_peak(
                        tuple(sorted(weights, reverse=True)), k
                    )
                else:
                    assert jobs == greedy(weights, k)
        assert all(
            Counter(v) == {i: 2 for i in range(8)} for v in zip(*choices, strict=True)
        )

    for rep in range(2):
        rows = [b["details"] for b in trace if b["key"][0] == rep]
        views = {}
        for name, (a, b) in PAIRS.items():
            speed = comparison([r[a]["ns"] for r in rows], [r[b]["ns"] for r in rows])
            same = sum(sorted(r[a]["jobs"]) == sorted(r[b]["jobs"]) for r in rows)
            views[name] = {**speed, "identical_layouts": same}
        execution.append(
            {
                "comparison": views,
                "p95_ns": {a: p95([r[a]["ns"] for r in rows]) for a in ARMS},
            }
        )
    return {
        "rounds": execution,
        "interpolated_widths": {str(w): n for w, n in sorted(missed.items())},
        "measurements": 2304,
        "bitwise_scores": 55296,
        "passes": {
            k: all(F(x["comparison"][k]["p95_ratio"]) <= F(19, 20) for x in execution)
            for k in PAIRS
        },
    }


def run(selected, ledger, policies, table, model, graph, out):
    from audit_runtime_latency import balanced, encoded_rows, scores_as_bytes
    from audit_runtime_parallel import CpuExecutor
    from audit_runtime_strata import balanced_strata
    from go_model_fetch import verify

    verify(graph, GRAPH)
    rows, groups, profile = data(ledger, policies, table)
    tokens = encoded_rows(selected, model, rows)
    fitted = CalibratedPlanner(profile)
    rows_done = []
    rng = Random(7765387)
    with CpuExecutor(graph) as service:
        service.execute(tokens[CASES[0], 0], list(MODES), "balanced")
        for rep, c, w in product(range(2), CASES, range(3)):
            routes = balanced([[i] for i in range(8)], rng) + balanced_strata(
                groups[c], rng
            )
            for step, z in enumerate(routes):
                floor = [MODES[i] for i in z]
                rotation = (rep + c + w + step) % 4
                order = ARMS[rotation:] + ARMS[:rotation]
                out_row = {}
                for a in order:

                    def planner(widths, workers):
                        m = min(workers, len(set(widths)))
                        weights = [
                            fitted.cost(x) if a.startswith("calibrated") else x * x
                            for x in widths
                        ]
                        fn = optimal_tasks if a.endswith("exact") else greedy
                        return fn(weights, m)

                    start = perf_counter_ns()
                    score, jobs = service.execute(
                        tokens[c, w], floor, "balanced", planner=planner
                    )
                    elapsed = perf_counter_ns() - start
                    actual = scores_as_bytes(score)
                    assert actual == expected(rows[c, w], z)
                    out_row[a] = {
                        "ns": elapsed,
                        "jobs": jobs,
                        "sha256": sha256(actual).hexdigest(),
                    }
                rows_done.append(
                    {
                        "key": [rep, c, w, step],
                        "order": list(order),
                        "route": z,
                        "details": out_row,
                    }
                )
            if w == 2:
                print(
                    json.dumps(
                        {
                            "round": rep + 1,
                            "case": c,
                            "measurements": len(rows_done) * 4,
                        }
                    ),
                    flush=True,
                )
    report = summarize(ledger, policies, table, rows_done)
    out.mkdir(parents=True, exist_ok=True)
    (out / TRACE).write_bytes(
        gzip.compress(json.dumps(rows_done, separators=(",", ":")).encode(), mtime=0)
    )
    (out / RESULTS).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps({k: report[k] for k in ("measurements", "bitwise_scores", "passes")})
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for k in ("selected", "ledger", "policies", "table", "model", "graph", "out"):
        cli.add_argument(k, type=Path)
    cli.add_argument("--check", action="store_true")
    a = cli.parse_args()
    if a.check:
        r = summarize(
            a.ledger,
            a.policies,
            a.table,
            json.loads(gzip.decompress((a.out / TRACE).read_bytes())),
        )
        assert r == json.loads((a.out / RESULTS).read_bytes())
        print(
            json.dumps(
                {
                    "verified": True,
                    "measurements": r["measurements"],
                    "passes": r["passes"],
                }
            )
        )
    else:
        run(a.selected, a.ledger, a.policies, a.table, a.model, a.graph, a.out)
