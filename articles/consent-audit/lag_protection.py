"""Protect all previously variable lags and certify them with one rational table."""

from collections import deque
from functools import lru_cache
from itertools import combinations

from conclusion_replay import components
from slack_certificate import sites, visible


def exact_lags(before, after):
    return [
        (i, j)
        for i, j in combinations(range(len(before)), 2)
        if before[i][j] + before[j][i] > 0 and after[i][j] + after[j][i] == 0
    ]


def tight_arcs(zone, record, classes):
    return {
        (classes[i], classes[j])
        for i, row in enumerate(zone)
        for j, limit in enumerate(row)
        if classes[i] != classes[j] and limit == record[j] - record[i]
    }


def ordinal(classes, arcs):
    graph = {c: [] for c in sorted(set(classes))}
    indegree = dict.fromkeys(graph, 0)
    for u, v in sorted(arcs):
        graph[u].append(v)
        indegree[v] += 1
    frontier = deque(k for k, count in indegree.items() if count == 0)
    order = {}
    while frontier:
        i = frontier.popleft()
        order[i] = len(order)
        for j in graph[i]:
            indegree[j] -= 1
            if indegree[j] == 0:
                frontier.append(j)
    if len(order) != len(graph):
        raise ValueError("the published comparisons fix a previously variable lag")
    return order


def rational_table(original, augmented):
    classes = components(original)
    record = augmented[0]
    rank = ordinal(classes, tight_arcs(augmented, record, classes))
    denom = len(rank)
    numbers = [denom * x + rank[0] - rank[classes[i]] for i, x in enumerate(record)]
    return dict(denominator=denom, numerators=numbers)


def decode(proof):
    divisor = proof["denominator"]
    return [
        [(value + phase) // divisor for value in proof["numerators"]]
        for phase in range(divisor)
    ]


def old_components(n, edges, record):
    """Find rigid classes by a linear-time SCC pass over raw tight arcs."""
    graph = [[] for _ in range(n)]
    dual = [[] for _ in range(n)]
    for u, v, limit in edges:
        if record[v] - record[u] == limit:
            graph[u].append(v)
            dual[v].append(u)
    seen = set()
    finished = []
    for root in range(n):
        agenda = [root]
        while agenda:
            u = agenda.pop()
            if u < 0:
                finished.append(~u)
            elif u not in seen:
                seen.add(u)
                agenda.append(~u)
                agenda.extend(graph[u])
    representative = [None] * n
    for root in reversed(finished):
        if representative[root] is not None:
            continue
        block = []
        agenda = [root]
        while agenda:
            u = agenda.pop()
            if representative[u] is None:
                representative[u] = root
                block.append(u)
                agenda.extend(dual[u])
        first = min(block)
        for i in block:
            representative[i] = first
    return representative


def verify_rational(n, original, comparisons, proof):
    denom = proof["denominator"]
    num = proof["numerators"]
    if (
        type(denom) is not int
        or denom <= 0
        or len(num) != n
        or any(type(t) is not int for t in num)
        or num[0] != 0
    ):
        raise ValueError("invalid reference, denominator, or numerator")
    for u, v, cap in original:
        if num[v] - num[u] > denom * cap:
            raise ValueError("hypothetical table violates an original bound")
    for u, v, cut in comparisons:
        if num[v] - num[u] < denom * cut:
            raise ValueError("hypothetical table violates an attestation")
    rigid = old_components(n, original, [x // denom for x in num])
    by_class = {}
    for r, z in zip(rigid, num, strict=True):
        residue = z % denom
        if by_class.setdefault(r, residue) != residue:
            raise ValueError(
                "members of one original rigid class have different residues"
            )
    if len(by_class) != denom or len(set(by_class.values())) != denom:
        raise ValueError("residues do not distinguish all originally variable lags")
    return denom


class LagCycles:
    def __init__(self, public, actual, facts):
        self.classes = components(public)
        self.base = [[] for _ in public]
        for u, v in sorted(tight_arcs(public, actual, self.classes)):
            self.base[u].append((v, 0))
        self.tight = {
            i: (self.classes[v], self.classes[u])
            for i, (u, v, cut) in enumerate(facts, 1)
            if actual[v] - actual[u] == cut and self.classes[v] != self.classes[u]
        }
        self.tight_mask = visible(self.tight)

    def conflict(self, chosen):
        return self._path(visible(chosen) & self.tight_mask)

    @lru_cache(maxsize=8192)
    def _path(self, selected):
        graph = [row.copy() for row in self.base]
        for i in sites(selected):
            u, v = self.tight[i]
            tree = {v: None}
            queue = deque([v])
            while queue:
                a = queue.popleft()
                if a == u:
                    cycle = [i]
                    while a != v:
                        a, prior = tree[a]
                        if prior:
                            cycle.append(prior)
                    return tuple(sorted(cycle))
                for b, mark in graph[a]:
                    if b not in tree:
                        tree[b] = (a, mark)
                        queue.append(b)
            graph[u].append((v, i))
        return ()

    @staticmethod
    def witness(before, after):
        return dict(rational=rational_table(before, after))
