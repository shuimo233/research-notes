"""Finite checks for rational witnesses, affine invariants, and full lag hardness."""

from collections import Counter
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle
from conclusion_replay import closure, components
from lag_protection import LagCycles, decode, rational_table, verify_rational
from lag_protection_check import newly_fixed
from public_optimality_check import distances
from unlocked_attestation import menu
from unlocked_attestation_boundary_check import hypergraph_case


def facts_edges(bounds, rows):
    edges = [p for i, (a, b) in enumerate(bounds, 1) for p in ((0, i, b), (i, 0, -a))]
    edges.extend(p for u, v, a, b in rows for p in ((u, v, b), (v, u, -a)))
    return edges


def frozen_pairs(a, b):
    return [
        (i, j)
        for i, j in combinations(range(len(a)), 2)
        if a[i][j] + a[j][i] > 0 and b[i][j] + b[j][i] == 0
    ]


def test_graphs(rng):
    count = Counter()
    for _ in range(140):
        n = rng.randint(2, 6)
        bounds = [
            (lo, lo + rng.randint(1, 6))
            for lo in [rng.randint(-3, 2) for _ in range(n - 1)]
        ]
        actual = (0, *(rng.randint(a, b) for a, b in bounds))
        constraints = []
        for i, j in combinations(range(n), 2):
            if rng.random() < 0.4:
                t = actual[j] - actual[i]
                constraints.append((i, j, t - rng.randrange(3), t + rng.randrange(3)))
        edges = facts_edges(bounds, constraints)
        before = distances(n, edges)
        groups = components(before)
        candidates = menu(before, actual, rng.choice((1, 2, 3)))
        test = LagCycles(before, actual, candidates)
        for _ in range(8):
            indices = [i for i in range(1, len(candidates) + 1) if rng.random() < 0.25]
            facts = [candidates[i - 1] for i in indices]
            after = distances(n, [*edges, *((v, u, -b) for u, v, b in facts)])
            lost = frozen_pairs(before, after)
            cycle = test.conflict(indices)
            assert bool(cycle) == bool(lost)
            count["subsets"] += 1
            if cycle:
                chosen = [candidates[i - 1] for i in cycle]
                assert frozen_pairs(
                    before, distances(n, [*edges, *((v, u, -b) for u, v, b in chosen)])
                )
                count["cycles"] += 1
                continue
            r = rational_table(before, after)
            k = verify_rational(n, edges, facts, r)
            samples = decode(r)
            assert len(samples) == k == len(set(groups))
            for w in samples:
                assert w[0] == 0
                assert all(w[v] - w[u] <= b for u, v, b in edges)
                assert all(w[v] - w[u] >= b for u, v, b in facts)
            for i, j in combinations(range(n), 2):
                assert (groups[i] != groups[j]) == (
                    len({s[j] - s[i] for s in samples}) > 1
                )
            for _ in range(4):
                a = [rng.randint(-2, 2) for _ in range(n)]
                stable = all(
                    sum(a[i] for i in range(n) if groups[i] == k) == 0
                    for k in set(groups) - {0}
                )
                scores = {
                    sum(k * x for k, x in zip(a, w, strict=True)) for w in samples
                }
                assert stable == (len(scores) == 1)
                count["linear_statistics"] += 1
            count["rational_proofs"] += 1
    return count


def test_bounds():
    # Individual timepoints stay unknown after a relative difference becomes rigid.
    bounds = [(0, 1), (0, 1)]
    d = closure(bounds)
    equal = closure(bounds, [(1, 2, 0, 0)])
    assert frozen_pairs(d, equal) == [(1, 2)]
    assert all(equal[0][i] == d[0][i] and equal[i][0] == d[i][0] for i in (1, 2))
    edges = facts_edges(bounds, [])
    try:
        verify_rational(
            3, edges, [(2, 1, 0)], dict(denominator=3, numerators=[0, 1, 1])
        )
    except ValueError:
        pass
    else:
        raise AssertionError("an equal-residue certificate was accepted")

    ordered = closure(bounds, [(1, 2, 0, 1)])
    p = rational_table(d, ordered)
    assert verify_rational(3, edges, [(1, 2, 0)], p) == 3
    worlds = decode(p)
    assert len(worlds) == 3 and {w[1] * (1 - w[2]) for w in worlds} == {0}
    assert {x * (1 - y) for x, y in product((0, 1), repeat=2)} == {0, 1}
    # Two individually admissible signs can form a new zero cycle.
    assert not frozen_pairs(d, ordered)
    individually = closure(bounds, [(2, 1, 0, 1)])
    assert not frozen_pairs(d, individually)
    assert frozen_pairs(d, equal)

    for n in (2, 4, 6):
        bands = [(0, 1)] * n
        chain_facts = [(i, i + 1, 0, 1) for i in range(1, n)]
        chain = closure(bands, chain_facts)
        witness = rational_table(chain, chain)
        assert witness["denominator"] == n + 1
        all_tables = decode(witness)
        for omitted in range(len(all_tables)):
            reduced = [t for i, t in enumerate(all_tables) if i != omitted]
            assert any(
                len({w[j] - w[i] for w in reduced}) == 1
                for i, j in combinations(range(n + 1), 2)
            )
    signatures = [v for v in product((0, 1), repeat=3) if 0 in v and 1 in v]
    independent = [(0, *(v[i] for v in signatures)) for i in range(3)]
    assert all(
        len({x[j] - x[i] for x in independent}) > 1
        for i, j in combinations(range(7), 2)
    )
    return dict(
        chain_tight=True,
        independent_binary_six_in_three=True,
        nonlinear_counterexample=True,
    )


def test_reduction(rng):
    graphs = [(5, list(combinations(range(1, 6), 3)))]
    for _ in range(15):
        n = rng.randint(3, 5)
        graph = [e for e in combinations(range(1, n + 1), 3) if rng.random() < 0.55]
        if graph:
            graphs.append((n, graph))
    count = 0
    unsat = 0
    for n, graph in graphs:
        _, packet = hypergraph_case(n, graph)
        oracle = DirectOracle(packet, [])
        feasible = False
        for assignment in product((-1, 0, 1), repeat=n):
            q = [
                (0, i, 0) if c > 0 else (i, 0, 0)
                for i, c in enumerate(assignment, 1)
                if c
            ]
            assert not newly_fixed(oracle, q)
            is_coloured = all({assignment[i - 1] for i in e} >= {-1, 1} for e in graph)
            assert oracle.query(q) != is_coloured
            feasible |= is_coloured
            count += 1
        quotient_collapse = [
            (u, v, 0) for i in range(1, n + 1) for u, v in ((0, i), (i, 0))
        ]
        assert newly_fixed(oracle, quotient_collapse) and not oracle.query(
            quotient_collapse
        )
        unsat += not feasible
    assert unsat >= 1
    return dict(hypergraphs=len(graphs), partial_colourings=count, uncolourable=unsat)


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    rng = Random(285135)
    print(json.dumps(dict(**test_graphs(rng), **test_bounds(), **test_reduction(rng))))
