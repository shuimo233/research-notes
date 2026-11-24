"""Likelihood bounds for truthful release with a distinct but uninformative refusal message."""

from fractions import Fraction
from math import lcm
from secrets import randbelow

from selection_odds import members, total


def distribution(weights, mask, service):
    if not mask:
        return {-1: Fraction(1)}
    mass = total(weights, mask)
    answered = max(service, mass)
    return {
        -1: 1 - answered,
        **{i: answered * weights[i] / mass for i in members(mask)},
    }


def ratio_of(table):
    observed = {}
    for row in table:
        for label, probability in row.items():
            if probability <= 0:
                raise ValueError(
                    "probabilities must be positive on the whole allowed support"
                )
            observed.setdefault(label, []).append(probability)
    return max(max(xs) / min(xs) for xs in observed.values())


def verify(weights, reciprocal, floor, service, masks, cap, lower, upper):
    n = len(weights)
    if not 0 < service < 1 or not 0 < reciprocal <= 1 - service:
        raise ValueError("invalid service requirement or reciprocal odds bound")
    if floor <= 0 or any(a < floor for a in weights):
        raise ValueError("weight below the real-label probability floor")
    if (
        not masks
        or len(set(masks)) != len(masks)
        or any(m <= 0 or m >= 1 << n for m in masks)
    ):
        raise ValueError("invalid membership patterns")
    if any(
        not service * reciprocal <= total(weights, m) <= 1 - reciprocal for m in masks
    ):
        raise ValueError("primal feasibility failed for a nonempty pattern")
    if cap < 0 or any(
        m not in masks or z <= 0 for m, z in (*lower.items(), *upper.items())
    ):
        raise ValueError("invalid certificate multiplier")
    if cap + sum(upper.values()) + service * sum(lower.values()) != 1:
        raise ValueError("dual coefficient of the objective does not equal one")
    for j in range(n):
        in_over = sum(value for m, value in upper.items() if m & (1 << j))
        in_under = sum(value for m, value in lower.items() if m & (1 << j))
        if in_over < in_under:
            raise ValueError("dual constraint on a label has the wrong sign")
    bound = cap * (1 - service) + sum(
        price * (1 - floor * m.bit_count()) for m, price in upper.items()
    )
    bound += sum(price * floor * m.bit_count() for m, price in lower.items())
    if bound != reciprocal:
        raise ValueError("primal and dual optima differ")
    table = [distribution(weights, m, service) for m in [0, *masks]]
    if any(sum(row.values()) != 1 for row in table):
        raise ValueError("inconsistent probabilities")
    if any(
        row[-1] > 1 - service or any(p < floor for j, p in row.items() if j >= 0)
        for row in table[1:]
    ):
        raise ValueError(
            "the implemented lottery does not meet service and probability floors"
        )
    ratio = ratio_of(table)
    if ratio * reciprocal != 1:
        raise ArithmeticError("implemented worst odds differ from the exact optimum")
    return ratio


def unpack(data):
    def prices(name):
        out = {m: Fraction(x) for m, x in data[name]}
        if len(out) != len(data[name]):
            raise ValueError("duplicate multiplier")
        return out

    return (
        [Fraction(w) for w in data["weights"]],
        Fraction(data["reciprocal"]),
        Fraction(data["floor"]),
        Fraction(data["service"]),
        Fraction(data["cap_dual"]),
        prices("lower_dual"),
        prices("upper_dual"),
    )


def choose(row):
    denom = lcm(*(f.denominator for f in row.values()))
    boundaries = [(k, int(p * denom)) for k, p in row.items()]
    cursor = randbelow(sum(v for _, v in boundaries))
    for i, v in boundaries:
        if cursor < v:
            return i
        cursor -= v
    raise ArithmeticError("sampling fell outside the exact distribution")
