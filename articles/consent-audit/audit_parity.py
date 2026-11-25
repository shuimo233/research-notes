"""Exact bilateral low-window certificates, with a sharp last-window formula."""

from collections import defaultdict
from fractions import Fraction as F
from math import comb, prod


def equality_lp(A, b, c):
    """Maximize c*x at A*x=b, x>=0, returning exact primal and dual."""
    if min(b) < 0:
        raise ValueError(
            "the artificial starting basis requires nonnegative right sides"
        )
    n, m = len(c), len(b)
    table = [
        [*map(F, row), *(F(i == j) for j in range(m)), F(b[i])]
        for i, row in enumerate(A)
    ]
    basic = [n + i for i in range(m)]

    def pivot(row, col):
        divisor = table[row][col]
        table[row] = [v / divisor for v in table[row]]
        for i, line in enumerate(table):
            factor = line[col]
            if i != row and factor:
                table[i] = [
                    v - factor * p for v, p in zip(line, table[row], strict=True)
                ]
        basic[row] = col

    def maximize(cost, columns):
        while True:
            current = [cost[j] for j in basic]
            col = next(
                (
                    j
                    for j in range(columns)
                    if j not in basic
                    and cost[j]
                    > sum(z * line[j] for z, line in zip(current, table, strict=True))
                ),
                None,
            )
            if col is None:
                return sum(z * line[-1] for z, line in zip(current, table, strict=True))
            candidates = [
                (line[-1] / line[col], basic[i], i)
                for i, line in enumerate(table)
                if line[col] > 0
            ]
            if not candidates:
                raise ArithmeticError("the equality LP is unbounded")
            pivot(min(candidates)[2], col)

    if maximize([0] * n + [-1] * m, n + m) != 0:
        raise ValueError("infeasible equality LP")
    i = 0
    while i < len(basic):
        if basic[i] >= n:
            col = next((j for j in range(n) if table[i][j] and j not in basic), None)
            if col is None:
                if table[i][-1]:
                    raise ArithmeticError(
                        "could not remove a nonzero artificial variable"
                    )
                del basic[i]
                del table[i]
                continue
            pivot(i, col)
        i += 1
    value = maximize([*c, *([0] * m)], n)
    x = [F(0)] * n
    for col, line in zip(basic, table, strict=True):
        x[col] = line[-1]
    dual = [
        sum(c[col] * line[n + i] for col, line in zip(basic, table, strict=True))
        for i in range(m)
    ]
    if min(x) < 0 or [
        sum(v * p for v, p in zip(row, x, strict=True)) for row in A
    ] != list(b):
        raise ArithmeticError("invalid primal certificate")
    if any(
        sum(z * row[j] for z, row in zip(dual, A, strict=True)) < c[j] for j in range(n)
    ):
        raise ArithmeticError("invalid dual certificate")
    if sum(y * v for y, v in zip(dual, b, strict=True)) != value:
        raise ArithmeticError("duality gap")
    return value, x, dual


def count_problem(w, k, p, gamma):
    """Integral equality layout except the common marginal and floor."""
    n = w + 1
    mean = w * p
    base = gamma * (1 - p) ** w / (1 - gamma)
    centered = [j - mean for j in range(n)]
    rows = [
        [*([1] * n), *([-1] * n)],
        [*centered, *([0] * n)],
        [*([0] * n), *centered],
    ]
    for u in range(2, k + 1):
        moments = [comb(w - j, u) for j in range(n)]
        rows.append([*moments, *(-a for a in moments)])
    rows.append([*([0] * n), base + 1, *([base] * w)])
    return rows, [0] * (len(rows) - 1) + [1], [1, *([0] * w), -1, *([0] * w)]


def worst_equal(w, k, p, gamma):
    p, gamma = F(p), F(gamma)
    if type(w) is not int or type(k) is not int or w < 2 or not 1 <= k <= w:
        raise ValueError("expected at least two requests and a valid audited depth")
    if not 0 < p < 1 or not 0 < gamma < 1:
        raise ValueError("probabilities must be strictly between zero and one")
    A, b, c = count_problem(w, k, p, gamma)
    gap, x, dual = equality_lp(A, b, c)
    t = sum(x[w + 1 :])
    return (
        1 + gap,
        [
            [a / t for a in x[: w + 1]],
            [a / t for a in x[w + 1 :]],
        ],
        dual,
    )


def interval_union(probabilities):
    """Couple Bernoulli bits to minimize the all-zero probability."""
    left = F(0)
    arcs = []
    breaks = {F(0), F(1)}
    for p in probabilities:
        if not 0 <= p <= 1:
            raise ValueError("invalid edge probability")
        arcs.append((left, p))
        if 0 < p < 1:
            breaks.update((left, (left + p) % 1))
        left = (left + p) % 1
    row = defaultdict(F)
    edges = sorted(breaks)
    for a, b in zip(edges, edges[1:]):
        x = (a + b) / 2
        mask = sum(1 << i for i, (start, p) in enumerate(arcs) if (x - start) % 1 < p)
        row[mask] += b - a
    return dict(sorted(row.items()))


def fair_two_unchecked_depths(w, gamma):
    """Sharp fairness formula when only depths w-1 and w were omitted."""
    gamma = F(gamma)
    if type(w) is not int or w < 3 or not 0 < gamma < 1:
        raise ValueError("expected at least three requests and an interior floor")
    middle = comb(w - 1, (w - 1) // 2)
    difference = [
        (-1) ** j * comb(w, j) * (1 - F(2 * j, w)) / middle for j in range(w + 1)
    ]
    residual = [[max(F(0), sign * x) for x in difference] for sign in (1, -1)]
    return 1 + (1 - gamma) / gamma * F(2**w, middle), residual


def fair_from_or_contrast(w, k, gamma):
    """Lift the known free-marginal OR contrast to a fair w-request pair."""
    gamma = F(gamma)
    if type(w) is not int or type(k) is not int or not 1 <= k < w or not 0 < gamma < 1:
        raise ValueError("expected 1 <= audited < requests and an interior floor")
    n = w - 1
    A = [[*([1] * w), *([0] * w)], [*([0] * w), *([1] * w)]]
    for u in range(1, k):
        row = [comb(n - j, u) for j in range(w)]
        A.append([*row, *(-z for z in row)])
    v, x, _ = equality_lp(A, [1, 1] + [0] * (k - 1), [1, *([0] * n), -1, *([0] * n)])
    original = [x[:w], x[w:]]
    lifted = [[F(0)] * (w + 1) for _ in original]
    for i, row in enumerate(original):
        reverse = original[i if k % 2 else 1 - i]
        for j, (a, b) in enumerate(zip(row, reverse, strict=True)):
            lifted[i][j] += a / 2
            lifted[i][w - j] += b / 2
    return 1 + (1 - gamma) / gamma * 2 ** (w - 1) * v, lifted


def heterogeneous_from_or_contrast(probabilities, k, gamma):
    """Lift a fair contrast when the smallest and largest rates sum to at least one."""
    rates = list(map(F, probabilities))
    gamma = F(gamma)
    if len(rates) < 2 or any(not 0 < p < 1 for p in rates) or not 0 < gamma < 1:
        raise ValueError("expected interior probabilities and at least two requests")
    high = max(rates)
    if min(rates) + high < 1:
        raise ValueError("the smallest and largest rates must sum to at least one")
    _, fair = fair_from_or_contrast(len(rates), k, F(1, 2))
    weight = 2 * (1 - high)
    common = (
        {
            m: (1 - weight) * p
            for m, p in interval_union(
                [(r - weight / 2) / (1 - weight) for r in rates]
            ).items()
        }
        if weight < 1
        else {}
    )
    r = 1 + (1 - gamma) * weight * fair[0][0] / (gamma * prod(1 - p for p in rates))
    return r, weight, fair, common


def last_window(probabilities, gamma):
    """Exact heterogeneous result when all proper windows must match.

    The witness is a shared sparse residual, plus uniform even parity in
    the numerator and uniform odd parity in the denominator.
    """
    p = list(map(F, probabilities))
    gamma = F(gamma)
    w = len(p)
    if w < 2 or any(not 0 < a < 1 for a in p) or not 0 < gamma < 1:
        raise ValueError(
            "expected two or more interior marginals and an interior floor"
        )
    mean = sum(p)
    base = gamma * prod(1 - a for a in p) / (1 - gamma)
    limit = 2 * min(min(a, 1 - a) for a in p)
    slope = F(w, 2) - 1
    candidates = [F(0), limit]
    if slope:
        elbow = (mean - 1) / slope
        if 0 < elbow < limit:
            candidates.append(elbow)

    def ratio(alpha):
        shared_zero = max(0, 1 - mean + alpha * slope)
        return 1 + alpha / (2 ** (w - 1) * (base + shared_zero))

    alpha = max(candidates, key=ratio)
    common = (
        {
            m: (1 - alpha) * q
            for m, q in interval_union(
                [(a - alpha / 2) / (1 - alpha) for a in p]
            ).items()
        }
        if alpha < 1
        else {}
    )
    return ratio(alpha), alpha, common


def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="model", required=True)
    homogeneous = sub.add_parser("equal-rate")
    homogeneous.add_argument("width", type=int)
    homogeneous.add_argument("audited", type=int)
    homogeneous.add_argument("rate", type=F)
    homogeneous.add_argument("floor", type=F)
    heterogeneous = sub.add_parser("last-window")
    heterogeneous.add_argument("floor", type=F)
    heterogeneous.add_argument("rates", type=F, nargs="+")
    a = parser.parse_args()
    try:
        if a.model == "equal-rate":
            r, laws, dual = worst_equal(a.width, a.audited, a.rate, a.floor)
            info = dict(
                ratio=str(r),
                residual_counts=[list(map(str, q)) for q in laws],
                dual=list(map(str, dual)),
            )
        else:
            r, alpha, sparse = last_window(a.rates, a.floor)
            info = dict(
                ratio=str(r),
                parity_weight=str(alpha),
                shared_residual={m: str(p) for m, p in sparse.items()},
            )
    except (ArithmeticError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
