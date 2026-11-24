"""Exact bounded transportation for two truth-compatible release channels."""

from collections import deque
from fractions import Fraction

from denial_odds import ratio_of


def focus(entries):
    incidence = {}
    for j, entry in enumerate(entries):
        for event in set(entry["comparison"][:2]) - {0}:
            incidence.setdefault(event, []).append(j)
    ranked = sorted(incidence, key=lambda v: (-len(incidence[v]), v))
    if not ranked:
        return []
    first = ranked[0]
    second = next((v for v in ranked[1:] if incidence[v] != incidence[first]), None)
    if second is None:
        return []
    return [(first, incidence[first]), (second, incidence[second])]


def project(mask, ids):
    return sum(1 << local for local, original in enumerate(ids) if mask >> original & 1)


def product(left, right):
    return {(i, j): left[i] * right[j] for i in left for j in right}


def simple(left, right, same):
    independent = product(left, right)
    l, r = left[-1], right[-1]
    both_refuse = min(l, r) if same else max(0, l + r - 1)
    block = {
        (True, True): both_refuse,
        (True, False): l - both_refuse,
        (False, True): r - both_refuse,
        (False, False): 1 - l - r + both_refuse,
    }
    return {
        (i, j): (
            p
            + p
            * block[i == -1, j == -1]
            / ((l if i == -1 else 1 - l) * (r if j == -1 else 1 - r))
        )
        / 2
        for (i, j), p in independent.items()
    }


def semantics(worlds):
    independent = [product(l, r) for l, r in worlds]
    minima = {}
    for row in independent:
        for cell, p in row.items():
            minima[cell] = min(minima.get(cell, p), p)
    floor = {cell: p / 2 for cell, p in sorted(minima.items())}
    margin = max(ratio_of([l for l, _ in worlds]), ratio_of([r for _, r in worlds]))
    return floor, margin, ratio_of(independent)


def one_cell_bounds(worlds, floor):
    """Compute attainable cell extrema without any cross-world ratio constraints."""
    greatest_lower = dict.fromkeys(floor, Fraction(0))
    least_upper = dict.fromkeys(floor, Fraction(1))
    for left, right in worlds:
        supply = {i: p - sum(floor[i, j] for j in right) for i, p in left.items()}
        demand = {j: p - sum(floor[i, j] for i in left) for j, p in right.items()}
        mass = sum(supply.values())
        for i, a in supply.items():
            for j, b in demand.items():
                cell = (i, j)
                least = floor[cell] + max(0, a + b - mass)
                most = floor[cell] + min(a, b)
                greatest_lower[cell] = max(greatest_lower[cell], least)
                least_upper[cell] = min(least_upper[cell], most)
    return greatest_lower, least_upper


def diagnose(worlds, floor, ratio):
    """Return the first cell or marginal cut violated by mandatory probability."""
    minimum, maximum = one_cell_bounds(worlds, floor)
    forced = {cell: max(floor[cell], v / ratio) for cell, v in minimum.items()}
    for (i, j), value in forced.items():
        if value > maximum[i, j]:
            return dict(
                kind="cell",
                cell=[i, j],
                required=str(value),
                available=str(maximum[i, j]),
            )
    for x, (left, right) in enumerate(worlds):
        for i, marginal in left.items():
            total = sum(forced[i, j] for j in right)
            if total > marginal:
                return dict(
                    kind="left",
                    world=x,
                    label=i,
                    required=str(total),
                    available=str(marginal),
                )
        for j, marginal in right.items():
            total = sum(forced[i, j] for i in left)
            if total > marginal:
                return dict(
                    kind="right",
                    world=x,
                    label=j,
                    required=str(total),
                    available=str(marginal),
                )
    return None


def cut(left, right, inside_left, inside_right, ratio):
    L, R = set(inside_left), set(inside_right)
    if not L <= left.keys() or not R <= right.keys():
        raise ValueError("cut names an unavailable output")
    coeff = {(i, j): ratio for i in L for j in right.keys() - R}
    coeff.update({(i, j): Fraction(-1) for i in left.keys() - L for j in R})
    demand = sum(left[i] for i in L) - sum(right[j] for j in R)
    return coeff, demand


def bounded_transport(left, right, lower, ratio):
    """Return either the exact flow or a separating (left set, right set)."""
    ls, rs = list(left), list(right)
    n, m = len(ls), len(rs)
    supply = {i: left[i] - sum(lower[i, j] for j in rs) for i in ls}
    demand = {j: right[j] - sum(lower[i, j] for i in ls) for j in rs}
    for i, p in supply.items():
        if p < 0:
            return None, (tuple(k for k in ls if k != i), tuple(rs))
    for j, p in demand.items():
        if p < 0:
            return None, ((), (j,))
    source, sink = n + m, n + m + 1
    network = [{} for _ in range(sink + 1)]

    def arc(u, v, capacity):
        network[u][v] = capacity
        network[v][u] = 0

    for a, i in enumerate(ls):
        arc(source, a, supply[i])
        for b, j in enumerate(rs, n):
            arc(a, b, (ratio - 1) * lower[i, j])
    for b, j in enumerate(rs, n):
        arc(b, sink, demand[j])

    while any(network[source].values()):
        parent = {source: None}
        queue = deque([source])
        while queue and sink not in parent:
            u = queue.popleft()
            for v, capacity in network[u].items():
                if capacity > 0 and v not in parent:
                    parent[v] = u
                    queue.append(v)
        if sink not in parent:
            return None, (
                tuple(i for a, i in enumerate(ls) if a in parent),
                tuple(j for b, j in enumerate(rs, n) if b in parent),
            )
        path = []
        v = sink
        while v != source:
            u = parent[v]
            path.append((u, v))
            v = u
        pushed = min(network[u][v] for u, v in path)
        for u, v in path:
            network[u][v] -= pushed
            network[v][u] += pushed
    return {
        (i, j): lower[i, j] + network[b][a]
        for a, i in enumerate(ls)
        for b, j in enumerate(rs, n)
    }, None


def check_negative(worlds, floor, ratio, rows):
    """Check nonnegative combination of necessary cuts at the fixed target."""
    remaining = dict.fromkeys(floor, 0)
    total = 0
    for world, left, right, price in rows:
        if type(world) is not int or not 0 <= world < len(worlds) or price <= 0:
            raise ValueError("invalid certificate multiplier")
        coeff, demand = cut(*worlds[world], left, right, ratio)
        total += price * (
            demand - sum(value * floor[cell] for cell, value in coeff.items())
        )
        for cell, value in coeff.items():
            remaining[cell] += price * value
    if total <= 0 or any(x > 0 for x in remaining.values()):
        raise ValueError("cut combination does not prove infeasibility")
    return total


def check_rows(worlds, floor, ratio, rows):
    for (left, right), row in zip(worlds, rows, strict=True):
        if row.keys() != product(left, right).keys():
            raise ValueError("incomplete or untruthful support")
        if any(p < floor[cell] for cell, p in row.items()):
            raise ValueError("output pair probability below its floor")
        for i, p in left.items():
            if sum(v for (x, _), v in row.items() if x == i) != p:
                raise ValueError("left release distribution changed")
        for j, p in right.items():
            if sum(v for (_, y), v in row.items() if y == j) != p:
                raise ValueError("right release distribution changed")
    if ratio_of(rows) > ratio:
        raise ValueError("joint ratio exceeds target")
