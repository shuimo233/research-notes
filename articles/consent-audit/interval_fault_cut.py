"""Exact threshold and cross-check decisions under a bounded number of wrong differences."""

from itertools import combinations
from math import inf


def closure(size, intervals, reports, excluded=()):
    """Matrix entry i,j bounds x[j] - x[i] from above."""
    anchor = size
    d = [[inf] * (size + 1) for _ in range(size + 1)]
    for i in range(size + 1):
        d[i][i] = 0
    if intervals is not None:
        for i, (lower, upper) in enumerate(intervals):
            d[anchor][i] = upper
            d[i][anchor] = -lower
    for i, (u, v, value) in enumerate(reports):
        if i not in excluded:
            d[u][v] = min(d[u][v], value)
            d[v][u] = min(d[v][u], -value)
    for k in range(size + 1):
        for i, row in enumerate(d):
            if row[k] != inf:
                for j in range(size + 1):
                    row[j] = min(row[j], row[k] + d[k][j])
                if row[i] < 0:
                    return None
    return d


def branches(size, intervals, reports, budget):
    # A world violating fewer reports is also covered by a maximal deletion.
    for excluded in combinations(range(len(reports)), min(budget, len(reports))):
        d = closure(size, intervals, reports, excluded)
        if d is not None:
            yield d


def merge_ranges(ranges):
    merged = []
    for low, high in sorted(ranges):
        if merged and low <= merged[-1][1] + 1:
            merged[-1][1] = max(high, merged[-1][1])
        else:
            merged.append([low, high])
    return merged


def disjoint(left, right):
    i = j = 0
    while i < len(left) and j < len(right):
        a, b = left[i], right[j]
        if a[1] < b[0]:
            i += 1
        elif b[1] < a[0]:
            j += 1
        else:
            return False
    return True


def classify(dbms, source, target, threshold):
    return (
        any(-d[target][source] < threshold for d in dbms),
        any(d[source][target] >= threshold for d in dbms),
    )


def constrain(dbms, u, v, cost, probes):
    """Project the closure after adding x[v] - x[u] <= cost."""
    ranges = [[] for _ in probes]
    witness = None
    for d in dbms:
        if d[v][u] + cost < 0:
            continue

        def distance(i, j):
            return min(d[i][j], d[i][u] + cost + d[v][j])

        if witness is None:
            n = len(d) - 1
            witness = [distance(n, i) for i in range(n)]
        for collected, (a, b) in zip(ranges, probes, strict=True):
            collected.append((-distance(b, a), distance(a, b)))
    return witness, [merge_ranges(r) for r in ranges]


def inquire(dbms, source, target, threshold, probes):
    negative = constrain(dbms, source, target, threshold - 1, probes)
    positive = constrain(dbms, target, source, -threshold, probes)
    return negative, positive


def shift_scenarios(intervals, source, target, gap):
    """Yield one representative per distinct list configuration."""
    low = max(0, gap - intervals[target][1])
    high = min(gap, -intervals[source][0])
    if low > high:
        return
    changes = {low, 1, gap}
    for lo, hi in intervals:
        changes.update((1 - lo, gap - hi))
    for a in sorted(x for x in changes if low <= x <= high):
        labels = (-a, 0, gap - a)
        choices = [
            tuple(x for x in sorted(set(labels)) if lo <= x <= hi)
            for lo, hi in intervals
        ]
        choices[source] = (-a,)
        choices[target] = (gap - a,)
        yield choices


def cut_cost(edges, choices, source, target, incumbent):
    left, right = choices[source][0], choices[target][0]
    demands = [(source, target)]
    for i, allowed in enumerate(choices):
        if i not in (source, target):
            if left not in allowed:
                demands.append((source, i))
            if right not in allowed:
                demands.append((target, i))
    graph = [[] for _ in choices]
    for i, (u, v, _) in enumerate(edges):
        graph[u].append((v, i))
        graph[v].append((u, i))

    def first_path(removed):
        for start, end in demands:
            predecessor = {start: None}
            queue = [start]
            for u in queue:
                for v, i in graph[u]:
                    if v not in predecessor and i not in removed:
                        predecessor[v] = (u, i)
                        queue.append(v)
                if end in predecessor:
                    path = []
                    while end != start:
                        end, i = predecessor[end]
                        path.append(i)
                    return path
        return None

    seen = set()
    pending = [(0, frozenset())]
    while pending:
        total, removed = pending.pop()
        if total >= incumbent or removed in seen:
            continue
        seen.add(removed)
        path = first_path(removed)
        if path is None:
            incumbent = total
        else:
            pending.extend((total + edges[i][2], removed | {i}) for i in path)
    return incumbent


def clean_fault_count(reference, intervals, edges, source, target, threshold):
    """Minimum corrupt edge weight for x[target] - x[source] >= threshold.

    Each edge value must equal its difference in the feasible reference.
    The bundled exact cut solver branches on edges of unsplit demand paths.
    """
    gap = threshold - (reference[target] - reference[source])
    if gap <= 0:
        return 0
    shifts = [(a - x, b - x) for x, (a, b) in zip(reference, intervals, strict=True)]
    best = inf
    for lists in shift_scenarios(shifts, source, target, gap):
        best = cut_cost(edges, lists, source, target, best)
    return best
