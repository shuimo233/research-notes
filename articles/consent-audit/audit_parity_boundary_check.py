"""Cross-check exact bilateral bounds and special cases with raw atomic probabilities."""

from fractions import Fraction as F
from itertools import product
import json
from math import comb, prod
from pathlib import Path
import subprocess
import sys

from audit_depth import avoidance, worst_full_ratio
from audit_parity import (
    fair_from_or_contrast,
    fair_two_unchecked_depths,
    heterogeneous_from_or_contrast,
    last_window,
    worst_equal,
)
from audit_parity_check import check_bilateral, check_heterogeneous


def atom_lp(rates, gamma, k, ratio):
    from scipy import __version__
    from scipy.optimize import linprog

    if __version__ != "1.16.3":
        raise RuntimeError("the numerical comparison pins SciPy 1.16.3")
    width = len(rates)
    n = 1 << width
    cells = range(n)
    equations = [
        [1] * n + [0] * n,
        [0] * n + [1] * n,
    ]
    values = [1, 1]
    for i, p in enumerate(rates):
        single = [int(bool(x & (1 << i))) for x in cells]
        equations.extend((single + [0] * n, [0] * n + single))
        values.extend((float(p), float(p)))
    for v in range(1, n):
        if 2 <= v.bit_count() <= k:
            row = [int(not x & v) for x in cells]
            equations.append([*row, *(-z for z in row)])
            values.append(0)
    floor = [
        float(gamma * prod(p if x >> i & 1 else 1 - p for i, p in enumerate(rates)))
        for x in cells
    ]
    result = linprog(
        [-1, *([0] * (n - 1)), float(ratio), *([0] * (n - 1))],
        A_eq=equations,
        b_eq=values,
        bounds=[(b, 1) for b in floor] * 2,
        method="highs",
    )
    assert result.success and abs(result.fun) < 1e-7


def homogeneous():
    total = 0
    for w in (3, 4, 5, 6):
        for k, p, gamma in product(
            range(2, w + 1), (F(1, 10), F(1, 5), F(1, 2), F(4, 5)), (F(1, 2),)
        ):
            r, table, dual = worst_equal(w, k, p, gamma)
            check_bilateral(w, k, p, gamma, r, table, dual)
            atom_lp([p] * w, gamma, k, r)
            if k == 2:
                assert r == worst_full_ratio(w, k, p, gamma)[0]
            if k == w:
                assert r == 1
            total += 1
    return total


def check_lift(w, k, gamma, ratio, rows):
    for law in rows:
        assert sum(law) == 1 and sum(j * p for j, p in enumerate(law)) == F(w, 2)
        assert min(law) >= 0
    assert all(avoidance(rows[0], u) == avoidance(rows[1], u) for u in range(1, k + 1))
    b = gamma * F(1, 2**w) / (1 - gamma)
    assert rows[1][0] == 0 and ratio == 1 + rows[0][0] / b


def fairness():
    checked = 0
    for w in range(2, 10):
        for k in range(1, w):
            r, rows = fair_from_or_contrast(w, k, F(1, 2))
            check_lift(w, k, F(1, 2), r, rows)
            assert r == worst_equal(w, k, F(1, 2), F(1, 2))[0]
            if k == w - 2:
                sharp, explicit = fair_two_unchecked_depths(w, F(1, 2))
                assert r == sharp
                check_lift(w, k, F(1, 2), sharp, explicit)
            checked += 1
    for w in (12, 20, 40, 128):
        gamma = F(3, 4)
        r, rows = fair_two_unchecked_depths(w, gamma)
        assert r == 1 + F(2**w, 3 * comb(w - 1, (w - 1) // 2))
        check_lift(w, w - 2, gamma, r, rows)
    return checked


def heterogeneous():
    mixed = (
        [F(1, 10), F(1, 5)],
        [F(1, 5), F(1, 4), F(1, 3)],
        [F(1, 5), F(2, 5), F(3, 5), F(4, 5)],
        [F(3, 10)] * 4,
        [F(1, 12), F(1, 6), F(1, 3), F(1, 2), F(3, 4)],
        [F(1, 5) + F(3 * i, 25) for i in range(6)],
        [F(1, 5), F(4, 5)] * 4,
    )
    for p, gamma in product(mixed, (F(1, 20), F(1, 2), F(4, 5))):
        r, alpha, shared = last_window(p, gamma)
        check_heterogeneous(p, gamma, r, alpha, list(shared.items()))
        atom_lp(p, gamma, len(p) - 1, r)
        if len(set(p)) == 1:
            assert r == worst_equal(len(p), len(p) - 1, p[0], gamma)[0]
    r, alpha, _ = last_window([F(3, 10)] * 4, F(1, 20))
    assert alpha == F(1, 5) and r > 1
    assert last_window([F(1, 5), F(4, 5)] * 4, F(1, 2))[0] == F(94509, 16384) > 3
    cli = str(Path(__file__).with_name("audit_parity.py"))
    output = subprocess.check_output(
        [
            sys.executable,
            "-B",
            cli,
            "last-window",
            "1/2",
            "1/5",
            "2/5",
            "3/5",
            "4/5",
        ]
    )
    assert json.loads(output)["ratio"] == "221/96"
    return len(mixed) * 3


def biased_lifts():
    groups = (
        [F(1, 5), F(2, 5), F(3, 5), F(4, 5)],
        [F(3, 10), F(3, 5), F(7, 10), F(9, 10)],
        [F(1, 5) + F(3 * i, 25) for i in range(6)],
        [F(4, 5)] * 6,
    )
    checked = 0
    for rates in groups:
        w = len(rates)
        for k in (2, 3, w - 1):
            gamma = F(1, 2)
            r, part, fair, common = heterogeneous_from_or_contrast(rates, k, gamma)
            complete = []
            for counts in fair:
                row = {}
                for a in range(1 << w):
                    n = a.bit_count()
                    base = prod(p if a >> i & 1 else 1 - p for i, p in enumerate(rates))
                    row[a] = gamma * base + (1 - gamma) * (
                        common.get(a, 0) + part * counts[n] / comb(w, n)
                    )
                assert sum(row.values()) == 1
                assert all(
                    sum(x for a, x in row.items() if a >> i & 1) == p
                    for i, p in enumerate(rates)
                )
                complete.append(row)
            x, y = complete
            assert x[0] / y[0] == r
            assert all(
                sum(p - y[a] for a, p in x.items() if not a & v) == 0
                for v in range(1, 1 << w)
                if v.bit_count() <= k
            )
            atom_lp(rates, gamma, k, r)
            checked += 1
    return checked


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(
                homogeneous_atomic=homogeneous(),
                contrast_lifts=fairness(),
                heterogeneous_atomic=heterogeneous(),
                biased_lifts=biased_lifts(),
            )
        )
    )
