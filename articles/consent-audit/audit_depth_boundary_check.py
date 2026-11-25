"""Cross-check the depth formula and exact search against full atom-level linear programs."""

from fractions import Fraction as F
from itertools import product
from math import comb
import json
from pathlib import Path
import subprocess
import sys

from audit_depth import avoidance, worst_full_ratio
from audit_depth_check import certify_upper


def direct(width, depth, rate, gamma, target):
    from scipy.optimize import linprog

    n = 1 << width
    cells = range(n)
    equations = [
        [1] * n + [0] * n,
        [0] * n + [1] * n,
    ]
    values = [1, 1]
    for bit in range(width):
        indices = [int(bool(s & (1 << bit))) for s in cells]
        equations += [indices + [0] * n, [0] * n + indices]
        values += [float(rate)] * 2
    orders = []
    for v in range(1, n):
        if v.bit_count() <= depth:
            keep = [int(not s & v) for s in cells]
            orders.append([*keep, *(-a for a in keep)])
    floor = [
        float(gamma * rate ** s.bit_count() * (1 - rate) ** (width - s.bit_count()))
        for s in cells
    ]
    objective = [-1, *([0] * (n - 1)), float(target), *([0] * (n - 1))]
    result = linprog(
        objective,
        A_ub=orders,
        b_ub=[0] * len(orders),
        A_eq=equations,
        b_eq=values,
        bounds=[(p, 1) for p in floor] * 2,
        method="highs",
    )
    assert result.success and abs(result.fun) <= 1e-7
    return True


def cases():
    from scipy import __version__

    if __version__ != "1.16.3":
        raise RuntimeError("recorded numerical cross-check uses SciPy 1.16.3")
    exercise = [
        (F("1/20"), F(1, 2)),
        (F(1, 5), F(1, 3)),
        (F(7, 20), F(1, 1000)),
        (F(7, 20), F(999, 1000)),
        (F(1, 2), F(1, 2)),
        (F(7, 10), F(3, 4)),
        (F(4, 5), F(1, 2)),
    ]
    tests = 0
    for width in (2, 3, 4, 6):
        for k, (rate, gamma) in product(range(1, width + 1), exercise):
            ratio, rows = worst_full_ratio(width, k, rate, gamma)
            p, q = rows
            assert ratio == p[0] / q[0]
            assert all(avoidance(p, i) <= avoidance(q, i) for i in range(1, k + 1))
            certify_upper(width, k, rate, gamma, ratio)
            assert direct(width, k, rate, gamma, ratio)
            for law in rows:
                assert (
                    sum(law) == 1
                    and sum(i * x for i, x in enumerate(law)) == width * rate
                )
                assert all(
                    x >= gamma * comb(width, i) * rate**i * (1 - rate) ** (width - i)
                    for i, x in enumerate(law)
                )
            if rate == F(1, 2):
                expected = 1 + (1 - gamma) / gamma * F(
                    2 ** (width - 1) * (width - k), width - 1
                )
                assert ratio == expected
                assert p[0] - q[0] == (1 - gamma) * F(width - k, 2 * (width - 1))
            tests += 1
    ratio, (p, q) = worst_full_ratio(3, 2, F(1, 20), F(1, 2))
    assert q[0] > (1 - F(1, 20)) ** 3 / 2 + F(17, 40)
    assert ratio > 1
    return tests


def audit_regression():
    # Equal first and third moments of all-refusal need not bound the second.
    p = [F(0), F(3, 4), F(0), F(1, 4)]
    q = [F(0), F(1, 2), F(1, 2), F(0)]
    assert avoidance(p, 1) == avoidance(q, 1) and avoidance(p, 3) == avoidance(q, 3)
    assert avoidance(p, 2) == F(1, 4) > F(1, 6) == avoidance(q, 2)
    here = str(Path(__file__).with_name("audit_depth.py"))
    command = [sys.executable, "-B", here, "10", "2", "1/2", "1/2"]
    tool = json.loads(subprocess.check_output([*command, "--target", "10"]))
    assert tool["ratio"] == "4105/9" and tool["gap_at_ratio_optimum"] == "2/9"
    assert tool["minimum_depth_at_target"] == 10
    at_boundary = json.loads(subprocess.check_output([*command, "--target", "521/9"]))
    assert at_boundary["minimum_depth_at_target"] == 9
    return True


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(full_lp_cases=cases(), middle_depth_counterexample=audit_regression())
        )
    )
