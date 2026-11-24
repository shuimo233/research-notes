"""Exact membership patterns and likelihood-ratio certificates for public catalogues."""

from fractions import Fraction
from math import lcm
from secrets import randbelow

from attested_optimality import Exhausted
from selection_protection import comparison


def members(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def patterns(zone, labels, limit=100_000):
    """Each Boolean pattern on an integer DBM has a single feasible-zone test."""
    stack = [(0, 0, zone)]
    out = set()
    visited = 0
    while stack:
        i, mask, cell = stack.pop()
        visited += 1
        if visited > limit:
            raise Exhausted("membership pattern search exceeded the budget")
        if i == len(labels):
            out.add(mask)
            continue
        no = comparison(cell, labels[i], False)
        if no is not None:
            stack.append((i + 1, mask, no))
        yes = comparison(cell, labels[i])
        if yes is not None:
            stack.append((i + 1, mask | 1 << i, yes))
    return sorted(out - {0}), 0 in out, visited


def antichains(patterns):
    distinct = sorted(set(patterns))
    lower = [s for s in distinct if not any(r != s and r & s == r for r in distinct)]
    upper = [s for s in distinct if not any(r != s and r & s == s for r in distinct)]
    return lower, upper


def total(weights, mask):
    return sum((weights[i] for i in members(mask)), Fraction(0))


def likelihood(weights, patterns):
    """Exact conditional-choice likelihood ratio, across contexts permitting the same message."""
    local = [[] for _ in weights]
    for mask in patterns:
        z = total(weights, mask)
        for i in members(mask):
            local[i].append(weights[i] / z)
    if not all(local):
        raise ValueError("a catalogue label has no feasible context")
    return max(max(values) / min(values) for values in local)


def verify(weights, value, floor, patterns, lower, upper):
    """Check primal feasibility, the shifted-variable dual, and equal objectives."""
    n = len(weights)
    if len(set(patterns)) != len(patterns) or any(
        s <= 0 or s >= 1 << n for s in patterns
    ):
        raise ValueError("invalid membership masks")
    if not patterns or not all(weights[i] >= floor for i in range(n)) or floor <= 0:
        raise ValueError("invalid positive floor or weight")
    if not 0 < value <= 1 or any(
        not value <= total(weights, mask) <= 1 for mask in patterns
    ):
        raise ValueError("primal weight sums violate the certified objective")
    if any(
        mask not in patterns or price <= 0
        for mask, price in (*lower.items(), *upper.items())
    ):
        raise ValueError("invalid nonzero dual entry")
    if sum(lower.values()) != 1:
        raise ValueError("dual prices must sum to one on lower rows")
    for i in range(n):
        bit = 1 << i
        if sum(v for m, v in upper.items() if m & bit) < sum(
            v for m, v in lower.items() if m & bit
        ):
            raise ValueError("dual coefficient has the wrong sign")
    cap = sum(floor * m.bit_count() * v for m, v in lower.items())
    cap += sum((1 - floor * m.bit_count()) * v for m, v in upper.items())
    if cap != value:
        raise ValueError("primal and dual rational objectives differ")
    ratio = likelihood(weights, patterns)
    if ratio * value != 1:
        raise ArithmeticError(
            "optimal rate does not match the certified likelihood ratio"
        )
    return ratio


def choose_weighted(enabled, weights):
    divisor = lcm(*(weights[i].denominator for i in enabled))
    masses = [int(divisor * weights[i]) for i in enabled]
    cursor = randbelow(sum(masses))
    for label, mass in zip(enabled, masses, strict=True):
        if cursor < mass:
            return label
        cursor -= mass
    raise ArithmeticError("the exact sampler exceeded its total mass")


def load_certificate(data):
    def prices(key):
        values = {m: Fraction(v) for m, v in data[key]}
        if len(values) != len(data[key]):
            raise ValueError("duplicate dual row")
        return values

    return (
        [Fraction(t) for t in data["weights"]],
        Fraction(data["lambda"]),
        Fraction(data["floor"]),
        data["patterns"],
        prices("lower_dual"),
        prices("upper_dual"),
    )
