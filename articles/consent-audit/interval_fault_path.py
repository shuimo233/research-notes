"""Compile all one-report repairs of a connected inconsistent difference graph."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RepairPath:
    base: tuple
    position: tuple
    residual: int
    # Index 0 denotes discarding the selected chord instead of a tree edge.
    kept_positions: tuple
    repair_edges: tuple
    rank: tuple

    def partition(self, source, target):
        """Two values, plus the half-open rank interval of the second value."""
        left, right = self.position[source], self.position[target]
        base = self.base[target] - self.base[source]
        if left == right:
            return base, base, 0, 0
        shifted = base + (self.residual if left < right else -self.residual)
        a, b = sorted((left, right))
        return base, shifted, self.rank[a + 1], self.rank[b + 1]

    def values(self, u, v):
        base, shifted, first, end = self.partition(u, v)
        result = set()
        if end > first:
            result.add(shifted)
        if end - first < len(self.kept_positions):
            result.add(base)
        return result

    def outcomes(self, u, v, threshold):
        return {value >= threshold for value in self.values(u, v)}

    def can_settle(self, source, target, threshold, u, v):
        base, shifted, a, b = self.partition(source, target)
        n = len(self.kept_positions)
        if b - a in (0, n) or (base >= threshold) == (shifted >= threshold):
            return False
        qbase, qshifted, c, d = self.partition(u, v)
        if d - c in (0, n) or qbase == qshifted:
            return False
        return (a, b) == (c, d) or (b - a + d - c == n and (b <= c or d <= a))

    def after_probe(self, source, target, threshold, u, v, answer):
        """Possible target labels after a trusted value, empty on contradiction."""
        base, shifted, a, b = self.partition(source, target)
        qbase, qshifted, c, d = self.partition(u, v)
        overlap = max(0, min(b, d) - max(a, c))
        if answer == qbase:
            remaining = len(self.kept_positions) - (d - c)
            shifted_count = b - a - overlap
        elif answer == qshifted:
            remaining = d - c
            shifted_count = overlap
        else:
            return set()
        labels = set()
        if remaining > shifted_count:
            labels.add(base >= threshold)
        if shifted_count:
            labels.add(shifted >= threshold)
        return labels

    def value_at(self, source, target, edge):
        i = self.kept_positions[self.repair_edges.index(edge)]
        shift = (self.position[target] >= i) - (self.position[source] >= i)
        return self.base[target] - self.base[source] + self.residual * shift


def _tree(size, reports, skip):
    graph = [[] for _ in range(size)]
    for i, (u, v, delta) in enumerate(reports):
        if i != skip:
            graph[u].append((v, i, delta))
            graph[v].append((u, i, -delta))
    forest = [[] for _ in range(size)]
    base = [None] * size
    base[0] = 0
    tree_edges = [False] * len(reports)
    queue = [0]
    for u in queue:
        for v, i, delta in graph[u]:
            if base[v] is None:
                base[v] = base[u] + delta
                forest[u].append((v, i))
                forest[v].append((u, i))
                tree_edges[i] = True
                queue.append(v)
    if len(queue) != size:
        raise ValueError("a connected report graph is needed")
    return base, forest, tree_edges


def _route(tree, source, target):
    seen = [None] * len(tree)
    seen[source] = (source, -1)
    queue = [source]
    for u in queue:
        if u == target:
            break
        for v, i in tree[u]:
            if seen[v] is None:
                seen[v] = (u, i)
                queue.append(v)
    vertices, edges = [target], []
    while target != source:
        target, edge = seen[target]
        vertices.append(target)
        edges.append(edge)
    return vertices[::-1], edges[::-1]


def _positions(tree, path):
    position = [None] * len(tree)
    for i, u in enumerate(path):
        position[u] = i
    queue = list(path)
    for u in queue:
        for v, _ in tree[u]:
            if position[v] is None:
                position[v] = position[u]
                queue.append(v)
    return position


def _gauges(base, position, bands, length):
    bound = [(-float("inf"), float("inf")) for _ in range(length)]

    def intersect(a, b):
        return (max(a[0], b[0]), min(a[1], b[1]))

    for i, (lo, hi) in enumerate(bands):
        j = position[i]
        bound[j] = intersect(bound[j], (lo - base[i], hi - base[i]))
    prefix, suffix = bound[:], bound[:]
    for j in range(1, length):
        prefix[j] = intersect(prefix[j - 1], bound[j])
    for j in range(length - 2, -1, -1):
        suffix[j] = intersect(suffix[j + 1], bound[j])
    return prefix, suffix


def compile_path(intervals, reports, *, reference_edge=None):
    """Compile positions and rank table in linear time in vertices plus reports.

    The original graph must be connected and inconsistent. The optional
    reference edge must restore consistency of all exact differences.
    Empty feasible repair sets are represented directly.
    """
    base, tree, tree_edges = _tree(len(intervals), reports, reference_edge)
    chords = [
        (i, reports[i][2] - (base[reports[i][1]] - base[reports[i][0]]))
        for i in range(len(reports))
        if not tree_edges[i]
    ]
    nonzero = [(i, d) for i, d in chords if d]
    if not nonzero:
        raise ValueError("a contradictory cycle is needed")
    chosen, residual = nonzero[0]
    if reference_edge is not None and nonzero != [(reference_edge, residual)]:
        raise ValueError("the reference edge does not restore consistency")
    origin, end, _ = reports[chosen]
    path, edges = _route(tree, origin, end)
    position = _positions(tree, path)
    k = len(edges)
    forbidden = [0] * (k + 2)
    lower, upper = 1, k
    for i, delta in chords:
        if i == chosen:
            continue
        u, v, _ = reports[i]
        a, b = position[u], position[v]
        lo, hi = sorted((a, b))
        if not delta:
            forbidden[lo + 1] += 1
            forbidden[hi + 1] -= 1
        elif a != b and delta == (residual if a < b else -residual):
            lower, upper = max(lower, lo + 1), min(upper, hi)
        else:
            lower, upper = 1, 0
            break

    prefix, suffix = _gauges(base, position, intervals, len(path))
    kept_positions, repair_edges = [], []
    if len(nonzero) == 1 and prefix[-1][0] <= prefix[-1][1]:
        kept_positions.append(0)
        repair_edges.append(chosen)
    active = 0
    for j, edge in enumerate(edges, 1):
        active += forbidden[j]
        if active or not lower <= j <= upper:
            continue
        lo, hi = prefix[j - 1]
        a, b = suffix[j]
        if max(lo, a - residual) <= min(hi, b - residual):
            kept_positions.append(j)
            repair_edges.append(edge)

    rank = [0] * (k + 2)
    for j in kept_positions:
        rank[j + 1] = 1
    for j in range(1, len(rank)):
        rank[j] += rank[j - 1]
    return RepairPath(
        tuple(base),
        tuple(position),
        residual,
        tuple(kept_positions),
        tuple(repair_edges),
        tuple(rank),
    )
