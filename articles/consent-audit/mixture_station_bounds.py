"""Check which 2025 tasks can safely use a fixed-marginal query strategy."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from mixture_budget_bound import independent_policy_certificate
from mixture_query import MixturePlan
from mixture_station_run import SIDE, cohort_ids, conditional_laws, training
from station_query import EDGES, label, load_snapshot


def run(snapshot, ledger):
    fit, dates, bases = load_snapshot(snapshot)
    trained = training(snapshot, bases)
    ids = cohort_ids()
    report = Counter()

    @lru_cache(None)
    def evaluate(group, month, lows):
        domains, mix, conditional, marginals, _ = conditional_laws(
            group,
            month,
            dict(zip("HABCD", lows, strict=True)),
            ids[group],
            bases,
            fit,
            trained,
        )
        bounds = []
        for edges in (EDGES, SIDE):
            p = MixturePlan(
                RelationInquiry(domains, edges, label, marginals), mix, conditional
            )
            certificate = independent_policy_certificate(p)
            bounds.append((p, certificate))
        return bounds

    with gzip.open(ledger, "rt", encoding="ascii") as f:
        for line in f:
            row = json.loads(line)
            main, side = evaluate(
                row["region"], int(row["date"][5:7]), tuple(row["lows"])
            )
            solver, (policy, a, b) = main
            opt = Q(row["expected"]["mixture"])
            assert a <= opt <= b == Q(row["expected"]["matched"])
            report["tasks"] += 1
            report["main_exact_without_correlated_search"] += a == b
            report["main_within_0.01_query"] += b - a <= Q(1, 100)
            report["main_within_0.05_query"] += b - a <= Q(1, 20)
            truth = {u: dates[row["date"]][v] for u, v in ids[row["region"]].items()}
            if a == b:
                path, result, _ = solver.service.execute(
                    truth.__getitem__, planner=policy
                )
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
    report["contexts"] = evaluate.cache_info().currsize
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("ledger", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.snapshot, a.ledger), indent=2))
