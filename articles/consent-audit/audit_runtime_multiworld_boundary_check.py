"""Check multiworld optimality by small exact graph and probability enumeration."""

import argparse
from fractions import Fraction as F
from itertools import combinations, product
import json
from pathlib import Path
from random import Random

from audit_runtime_multiworld import compile_partition, conservative_partition
from audit_runtime_multiworld_check import exact_groups, is_compatible, safe_baseline
from audit_runtime_partition import matching_partition
from audit_runtime_partition_boundary_check import atom_law, set_partitions


def edges(rates):
    return {
        pair
        for pair in combinations(range(len(rates[0])), 2)
        if not is_compatible(rates, *pair)
    }


def clique_number(n, e):
    return max(
        s
        for s in range(1, n + 1)
        if any(set(combinations(group, 2)) <= e for group in combinations(range(n), s))
    )


def direct_probability_audit(rates, blocks):
    n, m = len(rates[0]), len(rates[0][0])
    weights = tuple(F(2 * (i + 1), m * (m + 1)) for i in range(m))
    if m > 1:
        assert len(set(weights)) == m
    full = []
    for table in rates:
        ind = atom_law(table, weights, [(i,) for i in range(n)])
        shared = atom_law(table, weights, blocks)
        full.append((ind, {x: (p + shared[x]) / 2 for x, p in ind.items()}))
    audited = 0
    for depth in range(1, n + 1):
        for window in combinations(range(n), depth):
            values = []
            for a, b in full:
                p, q = (
                    sum(v for k, v in table.items() if all(k[i] for i in window))
                    for table in (a, b)
                )
                values.append(q / p)
            assert len(set(values)) == 1
            if depth == 1:
                assert values[0] == 1
            audited += 1
    return audited


def encode_graph(e, n, baseline=True):
    low = (F(1, 4), F(3, 4))
    still = (F(1, 2), F(1, 2))
    result = tuple(
        tuple(low if i in edge else still for i in range(n)) for edge in sorted(e)
    )
    return (*result, (still,) * n) if baseline else result


def verify(rates):
    n = len(rates[0])
    conflict = edges(rates)
    evidence = compile_partition(rates)
    baseline = conservative_partition(rates)
    exact_groups(rates, evidence)
    safe_baseline(rates, baseline)
    optimum = min(
        len(p)
        for p in set_partitions(n)
        if all((i, j) not in conflict for b in p for i, j in combinations(b, 2))
    )
    assert optimum == len(evidence["blocks"]) <= len(baseline["blocks"])
    if len(rates) == 2:
        assert len(matching_partition(rates)["blocks"]) == optimum
    if len(rates) <= 4:
        assert clique_number(n, conflict) == optimum
    return evidence, direct_probability_audit(rates, evidence["blocks"])


def checks(example):
    cycle = {(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)}
    rates = tuple(
        tuple(tuple(map(F, v)) for v in row)
        for row in json.loads(example.read_bytes())["rates"]
    )
    assert set(rates) == set(encode_graph(cycle, 5, False)) and edges(rates) == cycle
    evidence, prob = verify(rates)
    assert len(evidence["blocks"]) == 3 and clique_number(5, cycle) == 2
    assert evidence["partial_core"]["kind"] == "matching"
    assert (
        len(evidence["partial_core"]["pairs"]) == 2
        and evidence["partial_core"]["barrier"] == []
    )
    rng = Random(20261125)
    count = 1
    reductions = 0
    varied = (F(1, 5), F(1, 2))
    still = (F(1, 3), F(1, 3))
    six = tuple(
        tuple(varied if w // 2 == i // 2 else still for i in range(6)) for w in range(6)
    )
    dp, extra = verify(six)
    assert dp["partial_core"]["kind"] == "counts" and len(dp["blocks"]) == 2
    prob += extra
    count += 1
    scores = tuple(map(F, ("1/5", "2/5", "3/5", "4/5")))
    for w, n in product(range(2, 8), range(2, 8)):
        for j in range(4):
            matrix = []
            for world in range(w):
                row = []
                for i in range(n):
                    if world and (world + i + j) % 5 == 0:
                        row.append(matrix[0][i])
                    elif rng.randrange(3) > 0:
                        row.append((rng.choice(scores),) * 3)
                    else:
                        row.append(tuple(rng.choice(scores) for _ in range(3)))
                matrix.append(tuple(row))
            _, a = verify(tuple(matrix))
            count += 1
            prob += a
    for n in range(2, 8):
        for trial in range(4):
            e = {a for a in combinations(range(n), 2) if rng.randrange(2)}
            if not e:
                e = {(0, 1)}
            model = encode_graph(e, n)
            assert edges(model) == e
            _, a = verify(model)
            count += 1
            prob += a
            reductions += 1
    return {
        "enumerated": count,
        "probability_windows": prob,
        "graph_reductions": reductions,
        "five_world_cycle": {"clique": 2, "optimum": 3},
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("example", type=Path)
    a = cli.parse_args()
    print(json.dumps(checks(a.example)))
