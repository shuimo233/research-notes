"""Small exhaustive checks of membership, compact LP equivalence, and hardness."""

from collections import Counter
from fractions import Fraction as F
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle
from conclusion_replay import closure
from lag_protection import exact_lags
from selection_odds import choose_weighted, load_certificate, members, patterns, verify
from selection_odds_run import solve
from selection_protection import comparison


def raw_worlds(bands, facts):
    return [
        w
        for w in ((0, *s) for s in product(*(range(lo, hi + 1) for lo, hi in bands)))
        if all(a <= w[v] - w[u] <= b for u, v, a, b in facts)
    ]


def bitpattern(world, labels):
    return sum(1 << i for i, (u, v, t) in enumerate(labels) if world[v] - world[u] >= t)


def test_patterns(rng):
    sizes = Counter()
    for _ in range(100):
        n = rng.randint(1, 4)
        bands = [
            (lo, lo + rng.randint(1, 3))
            for lo in (rng.randint(-2, 2) for _ in range(n))
        ]
        x = (0, *(rng.randint(lo, hi) for lo, hi in bands))
        facts = [
            (u, v, x[v] - x[u] - rng.randrange(3), x[v] - x[u] + rng.randrange(3))
            for u, v in combinations(range(n + 1), 2)
            if rng.random() < 0.45
        ]
        q = []
        for _ in range(6):
            u, v = rng.sample(range(n + 1), 2)
            q.append((u, v, x[v] - x[u] + rng.randrange(-2, 3)))
        masks, reject, _ = patterns(closure(bands, facts), q)
        expected = {bitpattern(s, q) for s in raw_worlds(bands, facts)}
        assert set(masks) | ({0} if reject else set()) == expected
        sizes["symbolic_regions"] += len(expected)
        sizes["networks"] += 1
    return sizes


def direct_channel_feasible(n, regions, ratio):
    """Numerical sanity check with one probability variable per pattern and label."""
    from scipy.optimize import linprog

    variables = [(m, i) for m in regions for i in members(m)]
    fixed, limits = [], []
    for m in regions:
        fixed.append([int(q == m) for q, _ in variables])
    for ix, (_, i) in enumerate(variables):
        for jx, (_, j) in enumerate(variables):
            if i == j and ix != jx:
                row = [0] * len(variables)
                row[ix], row[jx] = 1, -float(ratio)
                limits.append(row)
    res = linprog(
        [0] * len(variables),
        A_ub=limits or None,
        b_ub=[0] * len(limits) or None,
        A_eq=fixed,
        b_eq=[1] * len(fixed),
        bounds=[(1 / (2 * n), 1)] * len(variables),
        method="highs",
    )
    return res.success


def test_lotteries(rng):
    n = 2
    nested = solve(n, [1, 3])
    assert nested["weighted_ratio"] == "4/3" and nested["uniform_ratio"] == "2"
    w, t, f, s, lo, hi = load_certificate(nested)
    try:
        verify(w, t + F(1, 20), f, s, lo, hi)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted an inflated minimum weight sum")
    for _ in range(50):
        n = rng.randint(2, 5)
        domains = {rng.randint(1, (1 << n) - 1) for _ in range(rng.randint(2, 12))}
        for j in range(n):
            if not any(m & 1 << j for m in domains):
                domains.add(1 << j)
        regions = sorted(domains)
        cert = solve(n, regions)
        ratio = F(cert["weighted_ratio"])
        assert direct_channel_feasible(n, regions, ratio)
        if ratio > 1:
            assert not direct_channel_feasible(n, regions, (ratio + 1) / 2)
    choices = []
    for digit in range(4):
        with patch("selection_odds.randbelow", return_value=digit) as source:
            choices.append(choose_weighted([0, 1], [F(3, 4), F(1, 4)]))
            source.assert_called_once_with(4)
    assert choices == [0, 0, 0, 1]
    return dict(direct_channel_instances=50, nested_optimum="4/3", exact_sampler=True)


def directed(edges):
    return [(i, j, 2) for u, v in edges for i, j in ((u, v), (v, u))]


def maxcut(n, edges):
    return max(
        sum(t[u - 1] != t[v - 1] for u, v in edges) for t in product((0, 1), repeat=n)
    )


def test_cut(rng):
    total = 0
    for n in range(2, 6):
        for _ in range(6):
            edges = [e for e in combinations(range(1, n + 1), 2) if rng.random() < 0.55]
            if not edges:
                continue
            q = directed(edges)
            d = closure([(0, 3)] * n)
            masks, _, _ = patterns(d, q)
            assert {1 << i for i in range(len(q))} <= set(masks)
            for fact in q:
                assert not exact_lags(d, comparison(d, fact))
            delta = maxcut(n, edges)
            cert = solve(len(q), masks)
            assert F(cert["weighted_ratio"]) == delta
            assert max(m.bit_count() for m in masks) == delta
            total += 1

    # The same reductions fit an old archive with an original minimum of three.
    n, edges = 3, [(1, 2), (2, 3), (1, 3)]
    bounds = [(0, 1)] * 9 + [(0, 3)] * (n + 2)
    facts = [(g, i, -1, 0) for g in range(1, 4) for i in (2 * g + 2, 2 * g + 3)]
    facts.extend((10 + i % 2, i, -3, 0) for i in range(4, 10))
    facts.extend((10, t, -3, 0) for t in range(12, 12 + n))
    packet = dict(
        archive=dict(
            bands=bounds, bounds=facts, targets=[(0, i, (1,)) for i in range(4, 10)]
        ),
        certificate=dict(labels=[0] * 6, disclosed=[(i, 0) for i in (1, 2, 3)]),
    )
    authority = DirectOracle(packet, [])
    q = [(u + 11, v + 11, d) for u, v, d in directed(edges)]
    assert authority.query([])
    assert not authority.query([(0, 10, 1)]) and not authority.query([(0, 11, 1)])
    assert all(not authority.query([t]) for t in q)
    f = tuple(map(tuple, authority.f))
    assert all(not exact_lags(f, comparison(f, t)) for t in q)
    regions, _, _ = patterns(f, q)
    assert F(solve(len(q), regions)["weighted_ratio"]) == maxcut(n, edges)
    return dict(cut_instances=total, reduction_in_original_contract=True)


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    rng = Random(727162)
    print(
        json.dumps(dict(**test_patterns(rng), **test_lotteries(rng), **test_cut(rng)))
    )
