"""Independent optimizer certificate and matched replay audit."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha256
from itertools import combinations_with_replacement, product
import json
from math import comb, prod
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
    process_cost,
)
from audit_runtime_strata_check import CASES as PREVIOUS, refined_groups, verify_plan

NEW = (2, 9, 27, 39, 46, 57)
CASES = tuple(sorted((*PREVIOUS, *NEW)))
ARMS = ("independent", "strata", "histogram")
TRACE = "audit-runtime-histogram-trace.json.gz"
RESULTS = "audit-runtime-histogram-results.json"
PLANS = "audit-runtime-histogram-plans.json"


def source_records(ledger, policies):
    rows, _ = load_records(ledger, policies)
    groups = {
        v["case"]: v["new"]["blocks"]
        for v in json.loads(gzip.decompress(locked(policies, PARTITIONS)))
        if v["threshold"] == "0" and v["case"] in CASES
    }
    assert set(groups) == set(CASES)
    return rows, groups


def lengths_from(rows, case):
    return tuple(tuple(int(r["length"]) for r in rows[case, w]) for w in range(3))


def reference_budget(lengths, p):
    total = {0: 1}
    for n in lengths:
        result = defaultdict(int)
        for x, c in total.items():
            for w in MODES:
                result[x + max(n, w) ** p] += c
        total = result
    cumulative = 0
    for t, k in sorted(total.items()):
        cumulative += k
        if 10 * cumulative >= 9 * 8 ** len(lengths):
            return t
    raise ArithmeticError("incomplete independent runtime law")


@cache
def menu(n):
    if n < 4:
        base = ((i,) for i in range(8)) if n == 1 else ((i, 7 - i) for i in range(4))
        return (tuple(tuple(t.count(i) for i in range(8)) for t in base),)
    results = []
    for raw in combinations_with_replacement(range(8), n):
        v = tuple(raw.count(i) for i in range(8))
        if max(v) > n // 4:
            continue
        u = tuple(n // 4 - x for x in v)
        if v <= u:
            results.append((v, u))
    return results


def avoided(base, floors, t):
    """Count no-hit assignments by choosing slots for equal floors first."""
    n = len(base)
    equal = floors.count(t)
    long = sum(x > t for x in base)
    flat = base.count(t)
    high = sum(x > t for x in floors)
    if long < equal or high < flat:
        return F(0)
    return F(
        comb(long, equal) * comb(high, flat), comb(n, equal) * comb(n - equal, flat)
    )


@cache
def evaluate(base, hists, targets):
    lists = [
        tuple(m for m, k in zip(MODES, h, strict=True) for _ in range(k)) for h in hists
    ]
    stats = [
        tuple(
            sum(
                max(a, b) ** p
                for a, b in zip(sorted(base, reverse=True), ls, strict=True)
            )
            for p in (1, 2)
        )
        for ls in lists
    ]
    return tuple(map(max, zip(*stats, strict=True))), tuple(
        sum(avoided(base, ls, t) for ls in lists) / len(lists) for t in targets
    )


def proof(lengths, declared, plan):
    groups = refined_groups(declared)
    bounds = tuple(reference_budget(v, p) for v in lengths for p in (1, 2))
    assert list(bounds) == plan["caps"]
    targets = [sorted(set(v) | set(MODES)) for v in lengths]
    options = []
    for b in groups:
        values = []
        for h in menu(len(b)):
            p = [
                evaluate(tuple(v[i] for i in b), h, tuple(t))
                for v, t in zip(lengths, targets, strict=True)
            ]
            values.append(
                (h, tuple(x for val, _ in p for x in val), tuple(m for _, m in p))
            )
        options.append(values)
    best = None
    for c in product(*options):
        max_load = tuple(map(sum, zip(*(o[1] for o in c), strict=True)))
        if any(a > b for a, b in zip(max_load, bounds, strict=True)):
            continue
        width = 0
        for outcomes in zip(*(o[2] for o in c), strict=True):
            width += sum(1 - prod(x) for x in zip(*outcomes, strict=True))
        key = width / 3, tuple(o[0] for o in c), max_load
        best = key if best is None else min(key, best)
    if best is None:
        assert (
            not plan["blocks"]
            and plan["maxima"] is None
            and plan["residual_mean_widths"] is None
        )
    else:
        chosen = tuple(tuple(tuple(h) for h in b["histograms"]) for b in plan["blocks"])
        assert [b["items"] for b in plan["blocks"]] == groups
        assert best == (F(plan["residual_mean_widths"]), chosen, tuple(plan["maxima"]))
        for b in plan["blocks"]:
            n = len(b["items"])
            table = b["histograms"]
            assert all(len(h) == 8 and min(h) >= 0 and sum(h) == n for h in table)
            assert all(
                F(sum(col), len(table)) == F(n, 8) for col in zip(*table, strict=True)
            )


def summarize_views(all_batches):
    views = {}
    for arm in ARMS:
        t = [b["timing"][arm] for b in all_batches]
        views[arm] = {
            "median_ns": str(median(map(F, t))),
            "p95_ns": p95(t),
            "mean_widths": str(
                F(sum(x["work"][arm]["widths"] for x in all_batches), len(t))
            ),
            "work_p95": p95([x["work"][arm]["tokens"] for x in all_batches]),
            "squares_p95": p95([x["work"][arm]["squares"] for x in all_batches]),
        }
    pairs = {}
    for arm in ("strata", "histogram"):
        v = comparison(
            [b["timing"][arm] for b in all_batches],
            [b["timing"]["independent"] for b in all_batches],
        )
        v["width_ratio"] = str(
            F(views[arm]["mean_widths"]) / F(views["independent"]["mean_widths"])
        )
        pairs[arm] = v
    return {"arms": views, "comparison": pairs}


def summarize(ledger, policies, plans, data, verify=True):
    rows, groups = source_records(ledger, policies)
    assert set(plans) == {str(k) for k in CASES}
    assert data["graph"] == GRAPH
    if verify:
        for c in CASES:
            proof(lengths_from(rows, c), groups[c], plans[str(c)])
    batches = data["batches"]
    assert len(batches) == 1728
    for (rep, c, w), chunk in zip(
        product(range(2), CASES, range(3)),
        (batches[i : i + 16] for i in range(0, len(batches), 16)),
        strict=True,
    ):
        hist = {a: [Counter() for _ in range(8)] for a in ARMS}
        marks = plans[str(c)]["blocks"]
        observed = [Counter() for _ in marks]
        for step, b in enumerate(chunk):
            assert b["key"] == [rep, c, w, step]
            u = (rep + c + w + step) % 3
            assert b["order"] == list(ARMS[u:] + ARMS[:u])
            assert set(b["route"]) == set(b["timing"]) == set(ARMS)
            assert all(type(x) is int and x > 0 for x in b["timing"].values())
            if step < 8:
                assert (
                    b["route"]["independent"]
                    == b["route"]["strata"]
                    == b["route"]["histogram"]
                )
            else:
                common = [0] * 8
                for k, block in enumerate(groups[c]):
                    for i in block:
                        common[i] = k
                verify_plan(
                    {"common": common, "stratified": b["route"]["strata"]}, groups[c]
                )
                for signature, blk in zip(observed, marks, strict=True):
                    chosen = [b["route"]["histogram"][i] for i in blk["items"]]
                    signature[tuple(chosen.count(j) for j in range(8))] += 1
                if marks:
                    compiled = plans[str(c)]["caps"][2 * w : 2 * w + 2]
                    assert b["work"]["histogram"]["tokens"] <= compiled[0]
                    assert b["work"]["histogram"]["squares"] <= compiled[1]
            for arm, z in b["route"].items():
                assert len(z) == 8 and all(type(x) is int and 0 <= x < 8 for x in z)
                for i, j in enumerate(z):
                    hist[arm][i][j] += 1
                assert process_cost(rows[c, w], z) == b["work"][arm]
                assert sha256(expected(rows[c, w], z)).hexdigest() == b["sha256"][arm]
        assert all(a == {i: 2 for i in range(8)} for q in hist.values() for a in q)
        for signature, blk in zip(observed, marks, strict=True):
            table = blk["histograms"]
            expected_hist = Counter(tuple(q) for q in table)
            assert signature == {
                k: v * 8 // len(table) for k, v in expected_hist.items()
            }

    rounds = []
    for r in range(2):
        subset = [b for b in batches if b["key"][0] == r]
        rounds.append(
            {
                "whole": summarize_views(subset),
                "new": summarize_views([b for b in subset if b["key"][1] in NEW]),
                "previous": summarize_views(
                    [b for b in subset if b["key"][1] in PREVIOUS]
                ),
                "changed_half": summarize_views(
                    [b for b in subset if b["key"][-1] >= 8]
                ),
            }
        )
    gate = True
    transfer = True
    for r in rounds:
        a = r["whole"]["comparison"]["histogram"]
        gate &= (
            F(a["p95_ratio"]) <= F(19, 20)
            and F(a["paired_median_ratio"]) <= F(21, 20)
            and F(a["width_ratio"]) <= F(19, 20)
        )
        transfer &= F(r["new"]["comparison"]["histogram"]["p95_ratio"]) <= F(21, 20)
    return {
        "batches": len(batches),
        "measurements": 3 * len(batches),
        "bitwise_scores": 72 * len(batches),
        "graph": GRAPH,
        "environment": data["environment"],
        "rounds": rounds,
        "primary_gate": gate,
        "transfer_gate": transfer,
        "fallbacks": [int(k) for k, v in plans.items() if not v["blocks"]],
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for p in ("ledger", "policies", "folder"):
        cli.add_argument(p, type=Path)
    arg = cli.parse_args()
    plan = json.loads((arg.folder / PLANS).read_bytes())
    trace = json.loads(gzip.decompress((arg.folder / TRACE).read_bytes()))
    statistics = summarize(arg.ledger, arg.policies, plan, trace)
    assert statistics == json.loads((arg.folder / RESULTS).read_bytes())
    print(
        json.dumps(
            {
                k: statistics[k]
                for k in (
                    "measurements",
                    "bitwise_scores",
                    "fallbacks",
                    "primary_gate",
                    "transfer_gate",
                )
            }
            | {"verified": True}
        )
    )
