"""Check the one-cut derivation and reconstruct plans from only intervals and edge rates."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from itertools import combinations, product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from end_cut_query import compile_end_cuts, trigger_shape, triggered
from frontier_theory_check import plan_for, raw_optimum
from station_query import EDGES, STATIONS, load_snapshot
from station_query_check import category


def geometric_cases():
    count = 0
    for length, other, offset, tol in product(
        range(1, 10), range(1, 10), range(-12, 13), range(1, 5)
    ):
        if other < 2 * tol or other + 2 * tol - 2 < length - 1:
            continue
        a, b = 0, length - 1
        c, d = offset, offset + other - 1
        shape = trigger_shape((a, b), (c, d), tol)
        for x in range(a, b + 1):
            possible = {(x - y >= tol) - (x - y <= -tol) for y in range(c, d + 1)}
            prediction = triggered(shape, x)
            assert prediction == (len(possible) > 1)
        count += 1
    return count


def equal_width_cases():
    positive, negative = 0, 0
    edges = list(combinations(range(3), 2))
    for length in range(2, 12):
        for tol in range(1, length + 2):
            if length + 2 <= 2 * tol and tol < length:
                domains = [range(length), range(length), range(1, length + 1)]
                grids = {
                    (i, j): [
                        [(x - y >= tol) - (x - y <= -tol) for y in domains[j]]
                        for x in domains[i]
                    ]
                    for i, j in edges
                }
                costs = [Q(1, 100 * length * length), 1, 1]
                rates, values = [], []
                for shift in (-1, 1):
                    law = [Q(1, length)] * length
                    for x, sign in [
                        (0, 1),
                        (length - tol, -1),
                        (length - tol + 1, 1),
                        (tol, -1),
                    ]:
                        law[x] += Q(shift * sign, 2 * length)
                    weights = [law, [Q(1, length)] * length, [Q(1, length)] * length]
                    plan = plan_for(weights, grids, costs)
                    value = raw_optimum(weights, grids, costs)
                    assert plan.root_value() == value
                    assert plan.names[plan.optimum(plan.counts, 0)[1]] == "0"
                    rates.append(plan.rates)
                    values.append(value)
                assert rates[0] == rates[1] and values[0] != values[1]
                negative += 1
                if (length, tol) == (4, 3):
                    weights = [
                        [Q(q, 10) for q in mass]
                        for mass in ((4, 1, 4, 1), (1, 4, 1, 4))
                    ]
                    values = [
                        raw_optimum([law, [Q(1, 4)] * 4, [Q(1, 4)] * 4], grids, [1] * 3)
                        for law in weights
                    ]
                    assert values == [Q(21, 8), Q(51, 20)]
                continue
            for b, c in product((-length, -1, 0, 1, length), repeat=2):
                domains = {
                    str(i): range(a, a + length) for i, a in enumerate((0, b, c))
                }
                bands = {u: (d.start, d.stop - 1) for u, d in domains.items()}
                laws = {}
                rates = {}
                edges_text = [(str(i), str(j)) for i, j in edges]
                for u in domains:
                    law = Counter()
                    for x in domains[u]:
                        flags = tuple(
                            v
                            for v in sorted(domains)
                            if u != v
                            and len(
                                {(x - y >= tol) - (x - y <= -tol) for y in domains[v]}
                            )
                            > 1
                        )
                        law[flags] += Q(
                            2 * (x - domains[u].start + 1), length * (length + 1)
                        )
                    laws[u] = law
                    rates[u] = {
                        v: p
                        for v in domains
                        if u != v
                        and (p := sum(p for mask, p in law.items() if v in mask))
                    }
                compiled = compile_end_cuts(bands, edges_text, rates, tol)
                for i, u in enumerate(compiled.names):
                    masses = {
                        tuple(
                            v for j, v in enumerate(compiled.names) if mask >> j & 1
                        ): p
                        for mask, p in compiled.groups[i]
                    }
                    assert masses == laws[u]
                positive += 1
    return positive, negative


def check(snapshot, ledger):
    fit, dates, _ = load_snapshot(snapshot)
    counts = Counter()

    @lru_cache(None)
    def check_key(region, month, lows, expected):
        bands = {u: (v, v + 19) for u, v in zip("HABCD", lows, strict=True)}
        neighbors = {u: [] for u in bands}
        for a, b in EDGES:
            if category(bands[a][0] - bands[b][1]) != category(
                bands[a][1] - bands[b][0]
            ):
                neighbors[a].append(b)
                neighbors[b].append(a)
        grouped = {}
        rates = {}
        masks = {}
        for u, (a, b) in bands.items():
            data = fit["USW000" + STATIONS[region][u], month]
            denominator = sum(data[x] + 1 for x in range(a, b + 1))
            law = Counter()
            actual = {}
            probs = {v: Q(0) for v in neighbors[u]}
            for x in range(a, b + 1):
                m = tuple(
                    sorted(
                        v
                        for v in neighbors[u]
                        if category(x - bands[v][1]) != category(x - bands[v][0])
                    )
                )
                p = Q(data[x] + 1, denominator)
                law[m] += p
                actual[x] = m
                for v in m:
                    probs[v] += p
            grouped[u] = law
            rates[u] = probs
            masks[u] = actual
        p = compile_end_cuts(bands, EDGES, rates, 10)
        for i, u in enumerate(p.names):
            expanded = {
                tuple(v for j, v in enumerate(p.names) if mask >> j & 1): prob
                for mask, prob in p.groups[i]
            }
            assert expanded == grouped[u]
            counts["local_laws_verified"] += 1
            if len(expanded) > 1:
                counts["variable_local_laws"] += 1
        assert p.root_value() == Q(expected)
        return p, masks

    with gzip.open(ledger, "rt", encoding="ascii") as f:
        for line in f:
            r = json.loads(line)
            region, day = r["region"], r["date"]
            p, masks = check_key(region, int(day[5:7]), tuple(r["lows"]), r["expected"])
            live = list(p.counts)
            forced = 0
            path = []
            while True:
                i, _ = p.action(tuple(live), forced)
                if i is None:
                    break
                u = p.names[i]
                x = dates[day]["USW000" + STATIONS[region][u]]
                forced |= sum(1 << p.indices[v] for v in masks[u][x])
                live[i] = 0
                path.append(u)
            assert path == r["paths"]["full"]
            counts["replays_verified"] += 1
            counts["reads"] = counts["reads"] + len(path)
    counts["planning_keys_verified"] = check_key.cache_info().currsize
    counts["exhaustive_interval_pairs"] = geometric_cases()
    (
        counts["equal_width_supported_cases"],
        counts["equal_width_cost_counterexamples"],
    ) = equal_width_cases()
    return counts


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("ledger", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.snapshot, a.ledger), indent=2))
