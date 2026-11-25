"""Recompute all comparisons and check the balanced width assignments."""

import argparse
from collections import Counter
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_runtime_latency_check import (
    GRAPH,
    PARTITIONS,
    comparison,
    expected,
    load_records,
    locked,
    p95,
    process_cost,
)

REUSED = (0, 12, 24, 34, 48, 59)
NEW = (5, 17, 23, 37, 45, 53)
CASES = tuple(sorted((*REUSED, *NEW)))
ARMS = ("independent", "common", "stratified")
TRACE = "audit-runtime-strata-trace.json.gz"
RESULTS = "audit-runtime-strata-results.json"


def records(ledger, stored):
    source, _ = load_records(ledger, stored)
    blocks = {}
    for row in json.loads(gzip.decompress(locked(stored, PARTITIONS))):
        if row["case"] in CASES and row["threshold"] == "0":
            blocks[row["case"]] = row["new"]["blocks"]
    assert set(blocks) == set(CASES)
    return source, blocks


def refined_groups(blocks):
    result = []
    for block in blocks:
        positions = sorted(block)
        for size in (8, 4, 2, 1):
            if len(positions) >= size:
                result.append(positions[:size])
                positions = positions[size:]
        assert not positions
    return result


def verify_plan(routing, blocks):
    assert all(len({routing["common"][i] for i in b}) == 1 for b in blocks)
    for b in refined_groups(blocks):
        s = min(4, len(b))
        hist = Counter(routing["stratified"][i] for i in b)
        strata = Counter()
        for mode, copies in hist.items():
            assert copies == len(b) // s
            strata[mode // (8 // s)] += copies
        assert strata == {j: len(b) // s for j in range(s)}


def describe(batches):
    output = {}
    for arm in ARMS:
        timing = [r["timing"][arm] for r in batches]
        output[arm] = {
            "p95_ns": p95(timing),
            "median_ns": str(median(map(F, timing))),
            "widths": str(
                F(sum(x["work"][arm]["widths"] for x in batches), len(timing))
            ),
            "width_sum": str(
                F(sum(x["work"][arm]["tokens"] for x in batches), len(timing))
            ),
            "width_p95": p95([x["work"][arm]["tokens"] for x in batches]),
            "width_square_p95": p95([x["work"][arm]["squares"] for x in batches]),
        }
    comparisons = {}
    for arm in ("common", "stratified"):
        t1 = [r["timing"][arm] for r in batches]
        t0 = [r["timing"]["independent"] for r in batches]
        comparisons[arm] = {
            **comparison(t1, t0),
            "width_ratio": str(
                F(output[arm]["widths"]) / F(output["independent"]["widths"])
            ),
        }
    return {"count": len(batches), "arms": output, "comparisons": comparisons}


def summarize(ledger, plans, data):
    source, groups = records(ledger, plans)
    assert data["graph"] == GRAPH
    batches = data["batches"]
    assert len(batches) == 1152
    checksum_count = 0
    for (rep, c, w), chunk in zip(
        product(range(2), CASES, range(3)),
        (batches[i : i + 16] for i in range(0, len(batches), 16)),
        strict=True,
    ):
        counts = {arm: [Counter() for _ in range(8)] for arm in ARMS}
        for trial, r in enumerate(chunk):
            assert r["key"] == [rep, c, w, trial]
            routes = r["route"]
            assert set(routes) == set(ARMS)
            shift = (rep + c + w + trial) % 3
            assert r["order"] == list(ARMS[shift:] + ARMS[:shift])
            assert set(r["timing"]) == set(ARMS) and all(
                type(t) is int and t > 0 for t in r["timing"].values()
            )
            if trial < 8:
                assert routes["independent"] == routes["common"] == routes["stratified"]
            else:
                verify_plan(routes, groups[c])
            for arm, route in routes.items():
                assert len(route) == 8 and all(
                    type(x) is int and 0 <= x < 8 for x in route
                )
                for i, x in enumerate(route):
                    counts[arm][i][x] += 1
                assert r["work"][arm] == process_cost(source[c, w], route)
                assert (
                    r["sha256"][arm]
                    == sha256(expected(source[c, w], route)).hexdigest()
                )
                checksum_count += 24
        assert all(v == {x: 2 for x in range(8)} for h in counts.values() for v in h)
        for key in ("tokens", "squares"):
            assert len({sum(r["work"][a][key] for r in chunk) for a in ARMS}) == 1

    reports = []
    for r in range(2):
        run = [x for x in batches if x["key"][0] == r]
        reports.append(
            {
                "whole": describe(run),
                "new": describe([x for x in run if x["key"][1] in NEW]),
                "reused": describe([x for x in run if x["key"][1] in REUSED]),
                "same_input_half": describe([x for x in run if x["key"][-1] < 8]),
                "changed_half": describe([x for x in run if x["key"][-1] >= 8]),
            }
        )
    gate = True
    transfer = True
    for r in reports:
        o = r["whole"]["comparisons"]["stratified"]
        gate &= (
            F(o["p95_ratio"]) <= F(19, 20)
            and F(o["paired_median_ratio"]) <= F(21, 20)
            and F(o["width_ratio"]) <= F(19, 20)
        )
        transfer &= F(r["new"]["comparisons"]["stratified"]["p95_ratio"]) <= F(21, 20)
    return {
        "graph": data["graph"],
        "environment": data["environment"],
        "batches": len(batches),
        "measurements": len(batches) * 3,
        "bitwise_scores": checksum_count,
        "rounds": reports,
        "primary_gate": gate,
        "transfer_gate": transfer,
    }


def verify(ledger, plans, directory):
    data = json.loads(gzip.decompress((directory / TRACE).read_bytes()))
    calculated = summarize(ledger, plans, data)
    assert calculated == json.loads((directory / RESULTS).read_bytes())
    print(
        json.dumps(
            {
                k: calculated[k]
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


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("ledger", "plans", "directory"):
        cli.add_argument(n, type=Path)
    opts = cli.parse_args()
    verify(opts.ledger, opts.plans, opts.directory)
