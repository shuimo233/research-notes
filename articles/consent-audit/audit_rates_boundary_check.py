"""Compare grouped and plateau results to uncompressed models and direct transformations."""

from fractions import Fraction as F
from itertools import product
import json
from math import comb, prod
from pathlib import Path
import subprocess
import sys

from audit_parity import fair_from_or_contrast, heterogeneous_from_or_contrast
from audit_parity_boundary_check import atom_lp
from audit_rates import (
    plateau_threshold,
    rate_groups,
    rounding_loss,
    serialize,
    solve_rates,
)
from audit_rates_check import check_proof


def grouped():
    caps = 0
    for rates, gamma in product(
        (
            [F(1, 5)] * 4,
            [F(1, 10), F(1, 5), F(1, 5), F(2, 5)],
            [F(1, 20), F(1, 10), F(1, 4), F(3, 10), F(2, 5)],
            [F(1, 20), F(1, 20), F(1, 4), F(1, 4), F(7, 20), F(2, 5)],
            [F(1, 5), F(4, 5), F(4, 5), F(4, 5)],
        ),
        (F(1, 4), F(1, 2), F(3, 4)),
    ):
        for k in sorted({1, 2, 3, len(rates) - 1, len(rates)}):
            saved = serialize(rates, k, gamma)
            r = check_proof(rates, k, gamma, saved)
            atom_lp(rates, gamma, k, r)
            if k == len(rates):
                assert r == 1
            elif min(rates) + max(rates) >= 1:
                assert r == heterogeneous_from_or_contrast(rates, k, gamma)[0]
            caps += 1
    rates = [F(1, 5), F(4, 5), F(4, 5), F(4, 5)]
    actual = solve_rates(rates, 2, F(1, 2))[0]
    averaged = solve_rates([sum(rates) / 4] * 4, 2, F(1, 2))[0]
    assert actual == F(131, 6) > averaged
    return caps


def dense_plateau(others, k, expected):
    from scipy import __version__
    from scipy.optimize import linprog

    assert __version__ == "1.16.3"
    n = 1 << len(others)
    columns = range(n)
    _, fair = fair_from_or_contrast(len(others) + 1, k, F(1, 2))
    D = 2 * fair[0][0]
    flat = [0] * n
    one = [1] * n
    neg = [-1] * n
    zero = [1, *flat[1:]]
    A = [
        [*one, *flat, *flat, *flat],
        [*flat, *flat, *one, *flat],
        [*flat, *one, *flat, *neg],
        [*zero, *flat, *flat, *flat],
        [*flat, *flat, *zero, *flat],
    ]
    b = [1, 1, 0, float(D), 0]
    for j, p in enumerate(others):
        values = [float(int(bool(mask >> j & 1)) - p) for mask in columns]
        A.extend(([*values, *values, *flat, *flat], [*flat, *flat, *values, *values]))
        b.extend((0, 0))
    for V in range(1, n):
        items = [int(not mask & V) for mask in columns]
        lost = [-x for x in items]
        if V.bit_count() <= k:
            A.append([*items, *items, *lost, *lost])
            b.append(0)
        if V.bit_count() < k:
            A.append([*items, *flat, *lost, *flat])
            b.append(0)
    result = linprog([*flat, *one, *flat, *flat], A_eq=A, b_eq=b, method="highs")
    assert result.success and abs(result.fun - float(expected / (1 - expected))) < 1e-8


def plateaus():
    checked = 0
    for rates in (
        [F(1, 5)] * 2,
        [F(1, 5)] * 3,
        [F(7, 20)] * 4,
        [F(2, 5)] * 5,
        [F(1, 10), F(1, 4), F(7, 20), F(2, 5)],
    ):
        for k in sorted({1, 2, min(3, len(rates)), len(rates)}):
            u, witness, _ = plateau_threshold(rates, k)
            assert max(rates) <= u <= max(max(rates), 1 - min(rates))
            assert sum(witness[0].values()) == sum(witness[2].values()) == 1
            assert sum(witness[1].values()) == sum(witness[3].values()) == u / (1 - u)
            if k == 1:
                assert u == max(max(rates), 1 - sum(rates))
            if k == len(rates):
                assert u == max(max(rates), 1 - min(rates))
            if k == 2 and len(set(rates)) == 1:
                n = len(rates)
                r = rates[0]
                q = min(
                    (n * (n - 1 - 2 * m) * r + m * (m + 1))
                    / (2 * (n - 1) + m * (m - 1))
                    for m in range(n)
                )
                assert 1 - u == q
            dense_plateau(rates, k, u)
            gamma = F(1, 2)
            _, fair = fair_from_or_contrast(len(rates) + 1, k, gamma)
            upper = 1 + 2 * fair[0][0] / prod(1 - p for p in rates)
            r, _, _ = solve_rates([*rates, u], k, gamma)
            assert r == upper
            assert solve_rates([*rates, u - F(1, 1000)], k, gamma)[0] < upper
            assert solve_rates([*rates, (1 + u) / 2], k, gamma)[0] == upper
            checked += 1
    assert plateau_threshold([F(7, 20)] * 4, 2)[0] == F(13, 30)
    return checked


def transport():
    p = [F(1, 10), F(1, 5), F(1, 5), F(2, 5)]
    q = [a + F(1, 100) for a in p]
    gamma = F(1, 2)
    order = sorted(p)
    r, (x, y), _ = solve_rates(order, 2, gamma)
    highs = [a + F(1, 100) for a in order]
    assert r <= solve_rates(highs, 2, gamma)[0]
    actual_excess = (solve_rates(highs, 2, gamma)[0] - 1) / (r - 1)
    assert 1 <= actual_excess <= rounding_loss(order, highs, gamma)
    assert rounding_loss(order, order, gamma) == 1
    groups = rate_groups(order)
    positions = [i for i, (_, n) in enumerate(groups) for _ in range(n)]
    table = []
    for block in (x, y):
        row = {}
        for s in range(1 << len(order)):
            coords = tuple(
                sum(bool(s >> i & 1) for i, j in enumerate(positions) if j == g)
                for g in range(len(groups))
            )
            count = prod(comb(n, c) for (_, n), c in zip(groups, coords, strict=True))
            base = prod(p if s >> i & 1 else 1 - p for i, p in enumerate(order))
            row[s] = gamma * base + (1 - gamma) * block.get(coords, 0) / count
        table.append(row)
    flipped = []
    fill = [(b - a) / (1 - a) for a, b in zip(order, highs, strict=True)]
    for row in table:
        out = {}
        for t in row:
            out[t] = sum(
                v
                * prod(
                    fill[i] if t >> i & 1 else 1 - fill[i]
                    for i in range(len(p))
                    if not s >> i & 1
                )
                for s, v in row.items()
                if s & t == s
            )
        assert sum(out.values()) == 1
        assert all(
            sum(v for t, v in out.items() if t >> i & 1) == b
            for i, b in enumerate(highs)
        )
        assert all(
            v >= gamma * prod(b if t >> i & 1 else 1 - b for i, b in enumerate(highs))
            for t, v in out.items()
        )
        flipped.append(out)
    for w in range(1 << len(p)):
        a, b, c, d = [
            sum(v for s, v in row.items() if not s & w) for row in (*table, *flipped)
        ]
        assert a / b == c / d
    q = highs
    script = str(Path(__file__).with_name("audit_rates.py"))
    r = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-B",
                script,
                "2",
                "1/2",
                *(f"{a}:{b}" for a, b in zip(order, q, strict=True)),
            ]
        )
    )
    assert F(r["lower"]["ratio"]) == solve_rates(order, 2, gamma)[0]
    assert F(r["upper"]["ratio"]) == solve_rates(q, 2, gamma)[0]
    return True


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(
                raw_group_pairs=grouped(),
                raw_plateaus=plateaus(),
                activation=transport(),
            )
        )
    )
