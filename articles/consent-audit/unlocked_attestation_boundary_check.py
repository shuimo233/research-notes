"""Finite checks for safe menu compression, signed search, and hardness reductions."""

from collections import Counter
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import ShorterWorlds, impose, new_exact
from conclusion_replay import closure
from public_optimality import PublicAudit
from public_optimality_check import distances, model
from transit_optimality_check import known_can_certify
from unlocked_attestation import AnchorPath, menu, signed_minimum, solve
from unlocked_attestation_check import DirectOracle


def fact_edges(facts):
    return [(v, u, -c) for u, v, c in facts]


def check_geometry(rng):
    tallies = Counter()
    for _ in range(125):
        n = rng.randint(2, 5)
        lows = [rng.randrange(-2, 2) for _ in range(n)]
        bands = [(lo, lo + rng.randrange(1, 7)) for lo in lows]
        actual = (0, *(rng.randint(a, b) for a, b in bands))
        rows = [
            (
                i,
                j,
                actual[j] - actual[i] - rng.randrange(3),
                actual[j] - actual[i] + rng.randrange(3),
            )
            for i, j in combinations(range(n + 1), 2)
            if rng.random() < 0.5
        ]
        public = closure(bands, rows)
        raw = [
            edge
            for i, (a, b) in enumerate(bands, 1)
            for edge in ((0, i, b), (i, 0, -a))
        ]
        raw.extend(edge for i, j, a, b in rows for edge in ((i, j, b), (j, i, -a)))
        grid = rng.randrange(1, 4)
        facts = menu(public, actual, grid)
        graph = AnchorPath(public, actual, facts)
        for _ in range(10):
            subset = [i for i in range(1, len(facts) + 1) if rng.random() < 0.32]
            chosen = [facts[i - 1] for i in subset]
            tested = distances(n + 1, [*raw, *fact_edges(chosen)])
            result = new_exact(public, tested)
            witness = graph.conflict(subset)
            assert bool(witness) == bool(result)
            if witness:
                assert set(witness) <= set(subset)
                example = distances(
                    n + 1, [*raw, *fact_edges([facts[i - 1] for i in witness])]
                )
                assert new_exact(public, example)
            tallies["anchor_path_cases"] += 1
        for span in (1, 2, 3):
            raw_menu = [
                (i, j, cut)
                for i, j in product(range(n + 1), repeat=2)
                if i != j
                for cut in range(-public[j][i] + 1, actual[j] - actual[i] + 1)
                if cut % grid == 0 and rng.random() < 0.18
            ]
            strongest = [
                (
                    i,
                    j,
                    cut
                    if actual[j] - actual[i] - cut < span
                    else grid * ((actual[j] - actual[i] - span) // grid),
                )
                for i, j, cut in raw_menu
            ]
            original = distances(n + 1, [*raw, *fact_edges(raw_menu)])
            replaced = distances(n + 1, [*raw, *fact_edges(strongest)])
            assert all(
                (original[i][0] + original[0][i] < span)
                == (replaced[i][0] + replaced[0][i] < span)
                for i in range(1, n + 1)
            )
            tallies["width_representatives"] += 1
    return tallies


def check_signed(rng):
    for _ in range(350):
        n = rng.randint(1, 7)
        roots = [
            sum((rng.randrange(2) << i) for i in range(1, n + 1)) for _ in range(12)
        ]
        required, rejected = set(roots[:6]), set(roots[6:])
        feasible = [
            k
            for k in range(0, 1 << (n + 1), 2)
            if all(k & r for r in required) and all(k & r != r for r in rejected)
        ]
        choose, _ = signed_minimum(n, required, rejected)
        if not feasible:
            assert choose is None
        else:
            assert sum(1 << i for i in choose) in feasible
            assert len(choose) == min(k.bit_count() for k in feasible)
    return 350


def api(bands, constraints, targets, observed, labels):
    packet = dict(
        archive=dict(bands=bands, bounds=constraints, targets=targets),
        certificate=dict(labels=labels, disclosed=observed),
    )
    return PublicAudit(
        closure(bands, constraints), targets, packet["certificate"]
    ), packet


def strict_example():
    n = 120
    targets = [(0, i, (1,)) for i in (2, 3)]
    facts = [(1, i, -n, 0) for i in (2, 3)]
    state, _ = api([(0, n), (0, 1), (0, 1)], facts, targets, [(2, 0), (3, 0)], [0, 0])
    actual = (0, n, 0, 0)
    oracle = ShorterWorlds(state, [])
    pure = solve(oracle, actual, 60, preserve_strict=False)
    assert pure["status"] == "protection_impossible"
    proper = solve(oracle, actual, 60)
    assert proper["status"] == "proved" and len(proper["attested"]) == 1
    assert not new_exact(state.fibre, impose(state.fibre, proper["attested"]))


def hypergraph_case(n, edges):
    m = len(edges)
    # All h, H and L have domain {-1,0,1}. Two S and T pairs are Boolean.
    bounds = [(-1, 1)] * (n + 2 * m) + [(0, 1)] * 4
    s1, t1, s2, t2 = range(n + 2 * m + 1, n + 2 * m + 5)
    rules = []
    for i, row in enumerate(edges):
        hi, lo = n + 2 * i + 1, n + 2 * i + 2
        for v in row:
            rules.extend(((hi, v, 0, 2), (v, lo, 0, 2)))
        for s, t in ((s1, t1), (s2, t2)):
            rules.extend(((lo, s, -1, 1), (hi, t, 0, 2)))
    return api(
        bounds, rules, [(t1, s1, (1,)), (t2, s2, (1,))], [(s1, 0), (s2, 0)], [0, 0]
    )


def check_hypergraphs(rng):
    graphs = [(5, tuple(combinations(range(1, 6), 3)))]
    for _ in range(23):
        n = rng.randint(3, 5)
        graphs.append(
            (
                n,
                tuple(
                    e for e in combinations(range(1, n + 1), 3) if rng.random() < 0.45
                ),
            )
        )
    legal, tested, impossible = 0, 0, 0
    for n, edges in graphs:
        if not edges:
            continue
        _, packet = hypergraph_case(n, edges)
        dims, _, _, _, _, _, alt = model(packet)
        assert not known_can_certify(dims, (0,) * dims, alt, 1)
        oracle = DirectOracle(packet, [])
        expected = False
        for shade in product((-1, 0, 1), repeat=n):
            chosen = [
                (0, i, 0) if v == 1 else (i, 0, 0) for i, v in enumerate(shade, 1) if v
            ]
            covers = all({shade[i - 1] for i in row} >= {-1, 1} for row in edges)
            assert oracle.query(chosen) != covers
            assert not oracle.locks(chosen)
            expected |= covers
            tested += 1
        assert not oracle.query(
            [(a, b, 0) for i in range(1, n + 1) for a, b in ((0, i), (i, 0))]
        )
        legal += 1
        impossible += not expected
    assert impossible >= 1
    return dict(
        hypergraphs=legal,
        colourings_and_partial_colourings=tested,
        uncolourable=impossible,
    )


def check_cardinality():
    systems = [
        [{0, 1}, {1, 2}, {0, 2}],
        [{0}, {1}, {2}],
        [{0, 1, 2}, {1}, {2}],
        [{0, 1}, {0}, {1}],
    ]
    tests = 0
    for sets in systems:
        m = len(set().union(*sets))
        n = len(sets)
        t = [m + n + 1, m + n + 2]
        facts = [(1 + i, j, -1, 1) for i in range(m) for j in t]
        facts.extend(
            (1 + m + j, 1 + i, 0, 2) for j, region in enumerate(sets) for i in region
        )
        _, packet = api(
            [(-1, 1)] * (m + n) + [(0, 1)] * 2,
            facts,
            [(0, i, (1,)) for i in t],
            [(i, 0) for i in t],
            [0, 0],
        )
        dims, _, _, _, _, _, alt = model(packet)
        assert not known_can_certify(dims, (0, *([1] * (m + n)), 0, 0), alt, 1)
        oracle = DirectOracle(packet, [])
        for k in range(n + 1):
            for s in combinations(range(n), k):
                candidates = [(0, 1 + m + j, 0) for j in s]
                truth = set().union(*(sets[j] for j in s)) >= set(range(m))
                assert oracle.query(candidates) != truth
                assert not oracle.locks(candidates)
                tests += 1
    return tests


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    random = Random(982358)
    strict_example()
    result = dict(
        **check_geometry(random),
        signed_instances=check_signed(random),
        **check_hypergraphs(random),
        set_cover_choices=check_cardinality(),
        strongest_only_loses_solution=True,
    )
    print(json.dumps(result))
