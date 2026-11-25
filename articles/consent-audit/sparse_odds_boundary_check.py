"""Cross-check rank sharpness, the single count law, and wide catalogue labels."""

from fractions import Fraction as F
from itertools import permutations
import json
from math import comb
from random import Random
from unittest.mock import patch

from sparse_odds import (
    anchor_lower,
    bounded_rank_counts,
    canonical_odds,
    catalogue_policy,
    sample_bounded,
    subsets,
    transform,
)
from sparse_odds_check import compare


def direct_lp(modes, n, r):
    from scipy.optimize import linprog

    keys = [(s, u) for s in modes for u in sorted(subsets(s))]
    nvar = len(keys)
    equalities, expected = [], []
    for s in modes:
        equalities.append([int(w == s) for w, _ in keys])
        expected.append(1)
        for k in range(n):
            if s >> k & 1:
                equalities.append([int(w == s and a >> k & 1) for w, a in keys])
                expected.append(0.5)
    constraints = []
    for w in range(1, 1 << n):
        for s, t in permutations(modes, 2):
            for message in subsets(w & s & t):
                constraints.append(
                    [
                        float(
                            (m == s and a & w == message)
                            - r * (m == t and a & w == message)
                        )
                        for m, a in keys
                    ]
                )
    f = linprog(
        [0] * nvar,
        A_eq=equalities,
        b_eq=expected,
        A_ub=constraints,
        b_ub=[0] * len(constraints),
        bounds=[(2 ** (-s.bit_count() - 1), 1) for s, _ in keys],
        method="highs",
    )
    assert f.success or f.status == 2
    return f.success


def downset(maxima):
    return sorted(set(a for m in maxima for a in subsets(m)))


def rank_boundaries():
    cases = [
        (1, [1], "2", F(2), F(199, 100)),
        (3, [3, 6], "3", F(3), F(299, 100)),
        (5, [7, 25], "32/7", F(32, 7), F(32, 7) - F(1, 1000)),
        (4, [7, 11], "2+sqrt(7)", F(93, 20), F(929, 200)),
        (4, [7, 11, 13, 14], "2+sqrt(7)", F(93, 20), F(929, 200)),
    ]
    for n, maxima, tag, upper, below in cases:
        modes = downset(maxima)
        cap, rows = catalogue_policy(modes)
        assert anchor_lower(modes)["lower"] == tag
        exhaustive, count = compare(rows, range(1, 1 << n))
        ratio, reduced, _ = canonical_odds(rows)
        assert exhaustive == ratio <= cap == upper and count >= reduced
        assert direct_lp(modes, n, upper) and not direct_lp(modes, n, below)
    empty = {0: {0: F(1)}}
    assert canonical_odds(empty) == (1, 0, None)
    huge = downset([(1 << 1024) | (1 << 83) | 1, (1 << 1024) | (1 << 83) | 2])
    assert canonical_odds(catalogue_policy(huge)[1])[0] == F(93, 20)
    return len(cases)


def finite_rank_lp(d, r):
    from scipy.optimize import linprog

    mat = [
        [float(comb(j, a) - r * (j == a)) if j >= a else 0 for j in range(d + 1)]
        for a in range(d + 1)
    ]
    f = linprog(
        [0] * (d + 1),
        A_eq=[[1] * (d + 1), list(range(d + 1))],
        b_eq=[1, d / 2],
        A_ub=mat,
        b_ub=[0] * (d + 1),
        bounds=[(comb(d, j) / 2 ** (d + 1), 1) for j in range(d + 1)],
        method="highs",
    )
    assert f.success or f.status == 2
    return f.success


def laws():
    assert not finite_rank_lp(3, F(929, 200))
    assert finite_rank_lp(3, F(93, 20))
    assert not finite_rank_lp(2, F(299, 100)) and finite_rank_lp(2, F(3))
    tested = []
    for d in (0, 1, 2, 3, 4, 8, 16, 32, 64, 128):
        r, w = bounded_rank_counts(d)
        assert sum(w) == 1 and sum(j * p for j, p in enumerate(w)) == F(d, 2)
        assert all(p >= F(comb(d, j), 2 ** (d + 1)) for j, p in enumerate(w))
        largest = max(a / b for a, b in zip(transform(w), w, strict=True))
        assert largest <= r
        if d:
            assert F(3, 2) ** d / 2 <= largest <= 24 * F(3, 2) ** d
        tested.append([d, float(largest)])
    with (
        patch("sparse_odds.choose", return_value=2),
        patch("sparse_odds.SystemRandom") as rng,
    ):
        rng.return_value.sample.return_value = [1, 3]
        assert sample_bounded(0b10101, [F(1, 5)] * 5) == 0b00100
        rng.return_value.sample.assert_called_once_with(range(4), 2)
    return tested


def arbitrary_channels():
    rng = Random(20261125)
    cases = 0
    for n in (2, 3, 4, 5):
        for _ in range(3):
            modes = sorted({0, *rng.sample(range(1, 1 << n), min(10, (1 << n) - 1))})
            rows = {}
            for s in modes:
                values = {u: rng.randint(1, 20) for u in subsets(s)}
                total = sum(values.values())
                rows[s] = {u: F(v, total) for u, v in values.items()}
            assert canonical_odds(rows)[0] == compare(rows, range(1, 1 << n))[0]
            cases += 1
    return cases


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(
                sharp_small_families=rank_boundaries(),
                rank_laws=laws(),
                arbitrary_channels=arbitrary_channels(),
            )
        )
    )
