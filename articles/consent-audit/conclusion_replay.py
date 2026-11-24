"""Certify changed threshold reports after hiding exact integer observations."""

from bisect import bisect_right
from itertools import combinations


def closure(bands, bounds=()):
    """Distances d[u][v] bound x[v] - x[u]; vertex zero is the reference."""
    size = len(bands) + 1
    inf = float("inf")
    d = [[0 if u == v else inf for v in range(size)] for u in range(size)]
    for u, (lo, hi) in enumerate(bands, 1):
        d[0][u], d[u][0] = hi, -lo
    for u, v, lo, hi in bounds:
        d[u][v] = min(d[u][v], hi)
        d[v][u] = min(d[v][u], -lo)
    for k in range(size):
        for u in range(size):
            row = d[u]
            prefix = row[k]
            for v in range(size):
                row[v] = min(row[v], prefix + d[k][v])
    if any(d[u][u] < 0 for u in range(size)):
        raise ValueError("archived constraints are inconsistent")
    return tuple(map(tuple, d))


def interval(d, u, v):
    return -d[v][u], d[u][v]


def pin(d, i, value):
    lo, hi = interval(d, 0, i)
    if not lo <= value <= hi:
        raise ValueError("recorded observation is outside the archive support")
    return tuple(
        tuple(
            min(d[u][v], d[u][i] - value + d[0][v], d[u][0] + value + d[i][v])
            for v in range(len(d))
        )
        for u in range(len(d))
    )


def components(d):
    return tuple(
        next(v for v in range(u + 1) if d[u][v] + d[v][u] == 0) for u in range(len(d))
    )


def possibilities(d, target):
    u, v, cuts = target
    lo, hi = interval(d, u, v)
    return bisect_right(cuts, lo), bisect_right(cuts, hi)


def necessary(d, targets):
    """Unique required rigid components; return their first coordinates."""
    classes = components(d)
    required = set()
    for target in targets:
        lo, hi = possibilities(d, target)
        if lo != hi:
            u, v, _ = target
            required.update((classes[u], classes[v]))
    return tuple(sorted(required - {0}))


def labels(d, targets):
    answer = []
    for target in targets:
        lo, hi = possibilities(d, target)
        if lo != hi:
            raise ValueError("undetermined audit label")
        answer.append(lo)
    return answer


def first_probe(d, targets, static):
    """Consider one extra observation with a guaranteed fixed continuation."""
    first, budget = None, len(static)
    for i in sorted(set(components(d)) - {0}):
        lo, hi = interval(d, 0, i)
        remaining = 0
        for value in range(lo, hi + 1):
            remaining = max(remaining, len(necessary(pin(d, i, value), targets)))
            if remaining + 1 >= budget:
                break
        if remaining + 1 < budget:
            first, budget = i, remaining + 1
    return first, budget


def replay(d, targets, plan, ask):
    for i in plan:
        d = pin(d, i, ask(i))
    return labels(d, targets)


def shortest(d, targets, truth):
    """Retrospective reference given all exact values; exponential in sites."""
    active = sorted(set(components(d)) - {0})
    for width in range(len(active) + 1):
        for subset in combinations(active, width):
            after = d
            for i in subset:
                after = pin(after, i, truth[i])
            if not necessary(after, targets):
                return subset
    raise ArithmeticError("the full record did not determine the report")
