"""Compare exact grouped certificates with independently built raw atom LPs."""

from fractions import Fraction as F
from itertools import combinations, product
import json
from math import prod

import numpy as np
from scipy.optimize import linprog

from audit_asymmetric import bounds, fixed
from audit_asymmetric_check import EXAMPLE, PEAK, PEAK_ODDS, box_value, proof_value


def direct(first, second, floor, caps):
    """Use raw probabilities and an explicit denominator scale, without grouping."""
    w = len(first)
    states = list(product((0, 1), repeat=w))
    n = len(states)
    pos = list(range(w))
    a_eq, b_eq, a_ub = [], [], []
    for j, rates in enumerate((first, second)):
        block = 0 if j == 0 else n

        def row(weights, scale=0):
            return [0] * block + weights + [0] * (n - block) + [scale]

        a_eq.append(row([1] * n, -1))
        b_eq.append(0)
        for i, rate in enumerate(rates):
            a_eq.append(row([x[i] for x in states], -rate))
            b_eq.append(0)
        for i, state in enumerate(states):
            point_floor = floor * prod(
                r if bit else 1 - r for r, bit in zip(rates, state, strict=True)
            )
            a_ub.append(row([-int(k == i) for k in range(n)], point_floor))
    a_eq.append([0] * (2 * n - 1) + [1, 0])
    b_eq.append(1)
    for depth, cap in enumerate(caps, start=2):
        for s in combinations(pos, depth):
            event = [prod(x[i] for i in s) for x in states]
            first_mass = prod(first[i] for i in s)
            second_mass = prod(second[i] for i in s)
            a_ub.extend(
                (
                    [x * second_mass for x in event]
                    + [-cap * x * first_mass for x in event]
                    + [0],
                    [-cap * x * second_mass for x in event]
                    + [x * first_mass for x in event]
                    + [0],
                )
            )
    c = [0] * (2 * n + 1)
    c[n - 1] = -1
    optimum = linprog(
        c,
        A_eq=np.asarray(a_eq, dtype=float),
        b_eq=b_eq,
        A_ub=np.asarray(a_ub, dtype=float),
        b_ub=[0] * len(a_ub),
        method="highs",
    )
    assert optimum.success, optimum.message
    return -optimum.fun


def verify_peak():
    _, _, q, floor, caps = EXAMPLE
    rows = [
        [F(z, 5750) for z in (60, 915, 90, 185, 1181, 144, 2119, 1056)],
        [F(z, 1250) for z in (6, 4, 154, 336, 9, 106, 581, 54)],
    ]
    atoms = list(product((0, 1), repeat=3))
    for rates, law in zip((PEAK, q), rows, strict=True):
        assert sum(law) == 1
        for a, mass in zip(atoms, law, strict=True):
            assert mass >= floor * prod(
                p if b else 1 - p for p, b in zip(rates, a, strict=True)
            )
        for i, p in enumerate(rates):
            assert sum(m for a, m in zip(atoms, law, strict=True) if a[i]) == p
    for i, j in combinations(range(3), 2):
        lift = [
            sum(m for a, m in zip(atoms, law, strict=True) if a[i] and a[j])
            / (rates[i] * rates[j])
            for rates, law in zip((PEAK, q), rows, strict=True)
        ]
        assert max(lift) <= caps[0] * min(lift)
    assert rows[0][-1] / rows[1][-1] == PEAK_ODDS == F(440, 81) * PEAK[0]
    assert (211 - 144 / PEAK[0]) / 625 == F(27, 625)
    x = F(9, 10)
    slope = F(25, 12) + F(1085, 12) * x * (211 * x - 288) / (211 * x - 144) ** 2
    assert slope == F(-13310, 7803)


def main():
    trials = [
        ((F(1, 5), F(3, 5)), (F(2, 5), F(4, 5))),
        ((F(3, 5), F(4, 5), F(3, 5)), (F(4, 5), F(1, 2), F(4, 5))),
        ((F(5, 8), F(3, 4), F(5, 8), F(3, 4)), (F(1, 2), F(3, 4), F(1, 2), F(4, 5))),
        (
            (F(9, 10), F(2, 5), F(2, 5), F(9, 10), F(2, 5)),
            (F(1, 5), F(3, 10), F(3, 10), F(1, 5), F(3, 10)),
        ),
    ]
    raw_count = 0
    for pair in trials:
        for p, q in (pair, pair[::-1]):
            for floor in (F(1, 4), F(2, 3)):
                for caps in ((), (F(1),), (F(11, 10),), (F(11, 10), F(21, 20))):
                    if len(caps) >= len(p):
                        continue
                    proof = fixed(p, q, floor, caps)
                    odds = proof_value(p, q, floor, caps, proof) * prod(p) / prod(q)
                    numeric = direct(p, q, floor, caps)
                    assert abs(float(odds) - numeric) <= 1e-8 * float(odds)
                    raw_count += 1
    lo, hi, q, floor, caps = EXAMPLE
    for p in (lo, PEAK, hi):
        proof = fixed(p, q, floor, caps)
        exact = proof_value(p, q, floor, caps, proof) * prod(p) / prod(q)
        assert abs(float(exact) - direct(p, q, floor, caps)) <= 1e-8 * float(exact)
        raw_count += 1
    p = tuple(map(F, ("7/10", "7/10", "2/5")))
    high = tuple(map(F, ("4/5", "4/5", "2/5")))
    denominator_hi = tuple(map(F, ("4/5", "19/20", "1/2")))
    report = bounds(p, high, q, floor, caps, F(21, 20), 32)
    _, _, lower, upper = box_value(p, high, q, floor, caps, report, 32)
    assert upper <= F(21, 20) * lower
    observed = []
    points = 0
    for i, j in product(range(5), repeat=2):
        x = (p[0] + (high[0] - p[0]) * i / 4, p[1] + (high[1] - p[1]) * j / 4, p[2])
        for y in (q, denominator_hi):
            value = direct(x, y, floor, caps)
            assert value <= float(upper) + 1e-8
            if y == q:
                observed.append(value)
            else:
                assert value <= observed[-1] + 1e-8
            points += 1
    verify_peak()
    print(
        json.dumps(
            {"raw_fixed": raw_count, "raw_box_grid": points, "analytic_witness": True}
        )
    )


if __name__ == "__main__":
    main()
