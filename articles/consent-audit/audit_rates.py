"""Exact grouped certificates and robust bounds for service-rate intervals."""

from collections import Counter
from fractions import Fraction as F
from itertools import product
from math import comb, prod

from audit_parity import equality_lp, fair_from_or_contrast


def rate_groups(rates):
    return tuple(sorted(Counter(map(F, rates)).items()))


def tables(groups, k):
    cells = list(product(*(range(n + 1) for _, n in groups)))
    keys = [
        a
        for a in product(*(range(min(n, k) + 1) for _, n in groups))
        if 2 <= sum(a) <= k
    ]
    exposure = [
        [
            prod(comb(n - j, t) for (_, n), j, t in zip(groups, c, a, strict=True))
            for c in cells
        ]
        for a in keys
    ]
    means = [[j[i] - p * n for j in cells] for i, (p, n) in enumerate(groups)]
    return cells, exposure, means


def solve_rates(rates, k, gamma):
    gamma = F(gamma)
    groups = rate_groups(rates)
    w = sum(n for _, n in groups)
    if type(k) is not int or not 1 <= k <= w or w < 2 or not 0 < gamma < 1:
        raise ValueError(
            "expected at least two requests, valid depth, and an interior floor"
        )
    if any(not 0 < p < 1 for p, _ in groups):
        raise ValueError("every service rate must lie strictly between zero and one")
    cells, moments, means = tables(groups, k)
    n = len(cells)
    flat = [0] * n
    base = gamma / (1 - gamma) * prod((1 - p) ** v for p, v in groups)
    A = [
        [*([1] * n), *([-1] * n)],
        *[[*a, *flat] for a in means],
        *[[*flat, *a] for a in means],
        *[[*a, *(-z for z in a)] for a in moments],
        [*flat, base + 1, *([base] * (n - 1))],
    ]
    c = [1, *flat[1:], -1, *flat[1:]]
    v, x, dual = equality_lp(A, [0] * (len(A) - 1) + [1], c)
    scale = sum(x[n:])
    tables_out = [
        {c: v / scale for c, v in zip(cells, block, strict=True) if v}
        for block in (x[:n], x[n:])
    ]
    return 1 + v, tables_out, dual


def plateau_threshold(other_rates, k):
    """Return the rate at which the distinguished request hits the OR bound."""
    groups = rate_groups(other_rates)
    w = 1 + sum(n for _, n in groups)
    if (
        type(k) is not int
        or not 1 <= k < w
        or w < 2
        or any(not 0 < p < 1 for p, _ in groups)
    ):
        raise ValueError("expected 1 <= audited < requests and interior rates")
    _, lift = fair_from_or_contrast(w, k, F(1, 2))
    D = 2 * lift[0][0]
    cells, moments, means = tables(groups, k)
    n = len(cells)
    flat = [0] * n
    ones = [1] * n
    zero = [1, *flat[1:]]
    A = [
        [*ones, *flat, *flat, *flat],
        [*flat, *flat, *ones, *flat],
        [*flat, *ones, *flat, *([-1] * n)],
        [*zero, *flat, *flat, *flat],
        [*flat, *flat, *zero, *flat],
    ]
    for v in means:
        a = [-x for x in v]
        A.extend(([*v, *v, *flat, *flat], [*flat, *flat, *v, *v]))
        if k >= 2:
            A.append([*v, *flat, *a, *flat])
    for row in moments:
        opposite = [-x for x in row]
        A.append([*row, *row, *opposite, *opposite])
    _, inside, _ = tables(groups, k - 1)
    for row in inside:
        A.append([*row, *flat, *(-x for x in row), *flat])
    c = [*flat, *([-1] * n), *flat, *flat]
    b = [1, 1, 0, D, 0] + [0] * (len(A) - 5)
    v, x, dual = equality_lp(A, b, c)
    rate = 1 - 1 / (1 - v)
    witness = [
        {key: q for key, q in zip(cells, x[i : i + n], strict=True) if q}
        for i in range(0, 4 * n, n)
    ]
    return rate, witness, dual


def rounding_loss(low, high, gamma):
    """Bound the factor by which rounding up can increase odds in excess of one."""
    p, q = list(map(F, low)), list(map(F, high))
    gamma = F(gamma)
    if (
        not 0 < gamma < 1
        or not p
        or any(not 0 < a <= b < 1 for a, b in zip(p, q, strict=True))
    ):
        raise ValueError(
            "expected matching ordered interior rates and an interior floor"
        )
    cap = min(a / b for a, b in zip(p, q, strict=True))
    b0 = gamma / (1 - gamma) * prod(1 - a for a in p)
    b1 = gamma / (1 - gamma) * prod(1 - b for b in q)
    offset, slope = 1 - sum(p), sum(q) - 1
    candidates = [cap]
    if slope and 0 < (cut := -offset / slope) < cap:
        candidates.append(cut)
    return min((b0 + max(0, offset + slope * t)) / (t * b1) for t in candidates)


def serialize(rates, k, gamma):
    rates = tuple(rates)
    r, witness, dual = solve_rates(rates, k, gamma)
    groups = rate_groups(rates)
    return dict(
        ratio=str(r),
        groups=[[str(p), n] for p, n in groups],
        residual=[[[list(c), str(v)] for c, v in row.items()] for row in witness],
        dual=list(map(str, dual)),
        cells=prod(n + 1 for _, n in groups),
    )


def main():
    import argparse
    import json

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audited", type=int)
    p.add_argument("floor", type=F)
    p.add_argument("rates", nargs="+", metavar="RATE_OR_LO:HI")
    arg = p.parse_args()
    try:
        bounds = [tuple(map(F, text.split(":"))) for text in arg.rates]
        if any(len(x) not in (1, 2) or x[0] > x[-1] for x in bounds):
            raise ValueError("use a rate or an increasing lower:upper interval")
        low = [x[0] for x in bounds]
        high = [x[-1] for x in bounds]
        low_report = serialize(low, arg.audited, arg.floor)
        high_report = (
            low_report if low == high else serialize(high, arg.audited, arg.floor)
        )
    except (ValueError, ArithmeticError) as error:
        p.exit(2, f"{error}\n")
    print(json.dumps(dict(lower=low_report, upper=high_report), indent=2))


if __name__ == "__main__":
    main()
