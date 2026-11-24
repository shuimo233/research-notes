"""Check which 2025 tasks can safely use a fixed-marginal query strategy."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys
from time import process_time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from frontier_plan import bits
from mixture_budget_bound import certified_plan, independent_policy_certificate
from mixture_query import MixturePlan
from mixture_station_run import SIDE, cohort_ids, conditional_laws, training
from station_query import EDGES, label, load_snapshot


def build_context(key, ids, bases, fit, trained, edges):
    group, month, lows = key
    domains, mix, conditional, marginals, _ = conditional_laws(
        group,
        month,
        dict(zip("HABCD", lows, strict=True)),
        ids[group],
        bases,
        fit,
        trained,
    )
    return MixturePlan(
        RelationInquiry(domains, edges, label, marginals), mix, conditional
    )


def rows(ledger):
    with gzip.open(ledger, "rt", encoding="ascii") as f:
        for line in f:
            row = json.loads(line)
            key = row["region"], int(row["date"][5:7]), tuple(row["lows"])
            yield key, row


def run(snapshot, ledger):
    fit, dates, bases = load_snapshot(snapshot)
    trained = training(snapshot, bases)
    ids = cohort_ids()
    report = Counter()

    @lru_cache(None)
    def evaluate(key, edges):
        p = build_context(key, ids, bases, fit, trained, edges)
        return p, independent_policy_certificate(p)

    contexts = set()
    for key, row in rows(ledger):
        contexts.add(key)
        main, side = evaluate(key, EDGES), evaluate(key, SIDE)
        solver, (policy, a, b) = main
        opt = Q(row["expected"]["mixture"])
        assert a <= opt <= b == Q(row["expected"]["matched"])
        report["tasks"] += 1
        report["main_exact_without_correlated_search"] += a == b
        report["main_within_0.01_query"] += b - a <= Q(1, 100)
        report["main_within_0.05_query"] += b - a <= Q(1, 20)
        truth = {u: dates[row["date"]][v] for u, v in ids[row["region"]].items()}
        if a == b:
            path, result, _ = solver.service.execute(truth.__getitem__, planner=policy)
            assert not solver.optimum.cache_info().currsize
        else:
            assert solver.optimum(*solver.initial())[0] == opt
            path, result = solver.execute(truth.__getitem__)
        assert [result[e] for e in EDGES] == row["labels"]
        report["dispatch_reads"] += len(path)
        _, (_, s, t) = side
        assert s <= Q(row["expected"]["cheap_probe"]) <= t
        report["side_exact_without_correlated_search"] += s == t
        report["side_can_rule_out_unit_probe_first"] += t - s < 1
        report["side_can_rule_out_discount_probe_first"] += t - s < Q(1, 10)
    report["contexts"] = len(contexts)
    return report


def benchmark(snapshot, ledger):
    fit, _, bases = load_snapshot(snapshot)
    trained = training(snapshot, bases)
    ids = cohort_ids()
    contexts = {}
    occurrences = Counter()
    for key, row in rows(ledger):
        contexts[key] = Q(row["expected"]["mixture"])
        occurrences[key] += 1
    results = []
    for strategy in ("posterior", "screened", "screened", "posterior"):
        started = process_time()
        counter = Counter()
        for key, expected in contexts.items():
            solver = build_context(key, ids, bases, fit, trained, EDGES)
            initial = solver.initial()
            if strategy == "screened":
                policy, lo, hi = certified_plan(solver)
                assert lo == hi == expected
                live, forced, _ = initial
                unforced = live & ~solver._required(live, forced)
                if policy is not None and any(
                    solver.neighbors[i] & unforced for i in bits(unforced)
                ):
                    counter["branching_tasks_using_certificate"] += occurrences[key]
            else:
                assert solver.optimum(*initial)[0] == expected
            counter["cached_posterior_states"] += solver.optimum.cache_info().currsize
            solver.clear()
        results.append(
            dict(
                strategy=strategy,
                cpu_seconds=round(process_time() - started, 3),
                **counter,
            )
        )
    return dict(unique_contexts=len(contexts), runs=results)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("ledger", type=Path)
    p.add_argument("--benchmark", action="store_true")
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    operation = benchmark if a.benchmark else run
    print(json.dumps(operation(a.snapshot, a.ledger), indent=2))
