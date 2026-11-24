"""Verify posterior query costs by enumerating literal histories and independently auditing field records."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from mixture_budget_bound import certified_plan, independent_policy_certificate
from mixture_query import MixturePlan
from station_query import EDGES, STATIONS
from station_query_check import category, certified, data
from mixture_station_run import SIDE


def raw_minimum(names, domains, tables, weights, conditional, costs, disabled=()):
    """Decision tree on exact readings with no forced-head, belief quotient or graph shortcut."""

    @lru_cache(None)
    def done(history):
        known = dict(history)
        for (u, v), table in tables.items():
            left = [known[u]] if u in known else domains[u]
            right = [known[v]] if v in known else domains[v]
            if len({table[a, b] for a, b in product(left, right)}) != 1:
                return False
        return True

    @lru_cache(None)
    def solve(history):
        if done(history):
            return Q(0)
        known = dict(history)
        post = tuple(
            w * prod(conditional[u][z][x] for u, x in history)
            for z, w in enumerate(weights)
        )
        denominator = sum(post)
        return min(
            costs[u]
            + sum(
                sum(w * conditional[u][z][x] for z, w in enumerate(post))
                / denominator
                * solve(tuple(sorted((*history, (u, x)))))
                for x in domains[u]
            )
            for u in names
            if u not in known and u not in disabled
        )

    answer = solve(())
    solve.cache_clear()
    done.cache_clear()
    return answer


def build(domains, grids, weights, conditional, costs, disabled=()):
    tagged = {u: [(u, x) for x in xs] for u, xs in domains.items()}
    param = {
        u: [{(u, x): p for x, p in row.items()} for row in rows]
        for u, rows in conditional.items()
    }
    marginal = {
        u: {x: sum(w * row[x] for w, row in zip(weights, param[u])) for x in xs}
        for u, xs in tagged.items()
    }

    def answer(a, b):
        u, x = a
        v, y = b
        return grids[u, v][x, y]

    inquiry = RelationInquiry(tagged, grids, answer, marginal)
    return MixturePlan(inquiry, weights, param, costs, disabled)


def exact_check(domains, grids, weights, conditional, costs, disabled=()):
    p = build(domains, grids, weights, conditional, costs, disabled)
    actual = p.optimum(*p.initial())[0]
    expected = raw_minimum(
        sorted(domains), domains, grids, weights, conditional, costs, disabled
    )
    assert actual == expected
    _, lower, upper = independent_policy_certificate(p)
    assert lower <= expected <= upper
    policy, a, b = certified_plan(p)
    assert a == b == expected and (policy is not None) == (lower == upper)
    policy, a, b = certified_plan(p, tolerance=upper - lower)
    assert policy is not None and (a, b) == (lower, upper)
    p.clear()
    return actual


def signal_case(k, cost, error, two_signals):
    signals = ("S", "T") if two_signals else ("S",)
    names = [(f"A{i}", f"B{i}") for i in range(k)]
    domains = {u: (0, 1) for pair in names for u in pair}
    bits = tuple(product((0, 1), repeat=k))
    domains.update({u: bits for u in signals})
    modes = list(product(bits, bits)) if two_signals else [(z, None) for z in bits]
    prior = [Q(1, len(modes))] * len(modes)
    laws = {u: [] for u in domains}
    for z, r in modes:
        for i, (a, b) in enumerate(names):
            for u, correct in ((a, z[i]), (b, 1 - z[i])):
                laws[u].append(
                    {x: 1 - error if x == correct else error for x in domains[u]}
                )
        for signal in signals:
            clean = (
                tuple(a ^ b for a, b in zip(z, r))
                if signal == "T"
                else r
                if two_signals
                else z
            )
            laws[signal].append(
                {
                    v: prod((1 - error if a == b else error) for a, b in zip(v, clean))
                    for v in bits
                }
            )
    grids = {e: {(a, b): a & b for a, b in product((0, 1), repeat=2)} for e in names}
    prices = {u: cost if u in signals else Q(1) for u in domains}
    actual = exact_check(domains, grids, prior, laws, prices)
    e = (1 - (1 - 2 * error) ** (len(signals) + 1)) / 2
    assert actual == min(Q(3 * k, 2), len(signals) * cost + k * (1 + e))
    no = exact_check(domains, grids, prior, laws, prices, signals)
    assert no == Q(3 * k, 2)
    if two_signals:
        for signal in signals:
            alone = exact_check(domains, grids, prior, laws, prices, (signal,))
            assert alone == no
    return str(actual), str(no)


def synthetic():
    error = Q(1, 20)
    results = dict(
        unit_probe=signal_case(3, Q(1), error, False),
        complementary_probes=signal_case(2, Q(1, 10), error, True),
    )
    results["unit_complementary_upper_bound"] = str(
        2 + 5 * (1 + (1 - (1 - 2 * Q(1, 100)) ** 3) / 2)
    )
    assert Q(results["unit_complementary_upper_bound"]) < Q(15, 2)
    rng = Random(20261124)
    for count in range(80):
        names = list("ABCDE"[: 3 + count % 3])
        domains = {u: tuple(range(2 + (count + ord(u)) % 2)) for u in names}
        conditional = {}
        for u, xs in domains.items():
            conditional[u] = []
            for z in range(2 + count % 2):
                ws = [rng.randint(1, 5) for x in xs]
                conditional[u].append({x: Q(w, sum(ws)) for x, w in zip(xs, ws)})
        grids = {
            e: {(a, b): rng.randrange(3) for a, b in product(*(domains[u] for u in e))}
            for e in combinations(names, 2)
            if rng.random() < 0.45
        }
        weights = [Q(1, 2 + count % 2)] * (2 + count % 2)
        exact_check(
            domains,
            grids,
            weights,
            conditional,
            {u: Q(1 + rng.randrange(4), 2) for u in names},
        )
    results["raw_history_matches"] = 80
    return results


def verify_fields(snapshot, manifest, results, raw):
    readings = data(snapshot, manifest, raw, last_year=2025)
    seen = Counter()
    totals = Counter()
    expected_days = set()
    ids = {}
    for region, codes in STATIONS.items():
        ids[region] = {u: "USW000" + s for u, s in codes.items()}
        expected_days.update(
            (region, d)
            for d in set.intersection(*(set(readings[s]) for s in ids[region].values()))
            if d.startswith("2025-")
        )
    with gzip.open(
        results / "mixture-station-ledger.jsonl.gz", "rt", encoding="ascii"
    ) as f:
        for line in f:
            row = json.loads(line)
            group, day = row["region"], row["date"]
            expected_days.remove((group, day))
            truth = {u: readings[s][day] for u, s in ids[group].items()}
            bands = {u: (t, t + 19) for u, t in zip("HABCD", row["lows"], strict=True)}
            assert all(a <= truth[u] <= b for u, (a, b) in bands.items())
            labels = [category(truth[a] - truth[b]) for a, b in EDGES]
            assert row["labels"] == labels
            seen[group] += 1
            for edges, paths in ((EDGES, row["paths"]), (SIDE, row["side_paths"])):
                for name, path in paths.items():
                    known = {u: truth[u] for u in path}
                    assert len(known) == len(path)
                    assert certified(edges, bands, known) == [
                        category(truth[a] - truth[b]) for a, b in edges
                    ]
                    totals[name] += len(path) - Q(9, 10) * (
                        name == "cheap_probe" and "H" in known
                    )
                    if name == "no_probe":
                        assert "H" not in known
                    if name in ("unit_probe", "cheap_probe"):
                        totals[name + "_H_reads"] += "H" in known
    assert not expected_days
    report = json.loads((results / "mixture-station-results.json").read_bytes())
    totals.update(tasks=sum(seen.values()))
    assert {k: Q(v) for k, v in report["by_region"]["total"].items()} == totals
    return dict(
        replay_tasks=sum(seen.values()), certificate_paths=6 * sum(seen.values())
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("snapshot", "manifest", "results"):
        p.add_argument(n, nargs="?", type=Path)
    p.add_argument("--raw-directory", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    if any((a.snapshot, a.manifest, a.results)) and not all(
        (a.snapshot, a.manifest, a.results)
    ):
        p.error("provide snapshot, manifest and results together")
    report = synthetic()
    if a.snapshot:
        report.update(verify_fields(a.snapshot, a.manifest, a.results, a.raw_directory))
    print(json.dumps(report, indent=2))
