"""Certify finite-world outputs through tree-convex or direct source constraints."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, product
from math import comb, inf

from interval_fault_joint_source import minimum_pair_cover
from interval_fault_noisy import ambiguous_record


@dataclass(frozen=True)
class AnswerTree:
    edges: tuple
    agreement: int
    possible: int

    @property
    def convex(self):
        return self.agreement == self.possible


@dataclass(frozen=True)
class WorldPlan:
    cost: int | None
    selected: tuple
    tree: AnswerTree
    opposite_pairs: int
    candidate_pairs: int
    constraints: tuple
    wide_sources: int
    wide_types: int
    matching_calls: int
    witness: tuple | None = None


def answer_tree(offers, size):
    """Recognize connected answer classes on a tree with no extra worlds."""
    complete = [
        (sum(q.values[u] == q.values[v] for q in offers), u, v)
        for u, v in combinations(range(size), 2)
    ]
    parent = list(range(size))

    def root(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    chosen = []
    agreement = 0
    for weight, u, v in sorted(complete, key=lambda item: (-item[0], item[1], item[2])):
        a, b = root(u), root(v)
        if a != b:
            parent[b] = a
            chosen.append((u, v))
            agreement += weight
            if len(chosen) == size - 1:
                break
    bound = sum(size - len(set(q.values)) for q in offers)
    return AnswerTree(tuple(chosen), agreement, bound)


def discriminate(offers, u, v):
    return sum((q.values[u] != q.values[v]) << i for i, q in enumerate(offers))


def minimal_supports(pairs, offers):
    """Keep one example pair for each undominated set of separating sources."""
    witnessed = {}
    for u, v in pairs:
        witnessed.setdefault(discriminate(offers, u, v), (u, v))
    retained = []
    for mask in sorted(witnessed, key=lambda x: (x.bit_count(), x)):
        if not any(mask & prior == prior for prior, _ in retained):
            retained.append((mask, witnessed[mask]))
    return tuple(retained)


def cover_groups(offers, retained, demand):
    types = defaultdict(list)
    for i, q in enumerate(offers):
        sites = tuple(k for k, (mask, _) in enumerate(retained) if mask & (1 << i))
        if sites:
            types[sites].append(i)
    compact, wide = [], []
    for sites, ids in types.items():
        ids.sort(key=lambda i: (offers[i].cost, i))
        active = tuple(ids[:demand])
        if len(sites) <= 2:
            compact.extend((i, sites) for i in active)
        else:
            wide.append((active, sites))
    return compact, wide


def optimize(offers, constraints, compact, wide, demand):
    """Enumerate purchases for wide types, then solve remaining pair cover."""
    calls, best, answer = 0, inf, ()
    prices = [offers[i].cost for i, _ in compact]
    coverage = [sites for _, sites in compact]
    options = (range(len(ids) + 1) for ids, _ in wide)
    for counts in product(*options):
        selected, residual = [], [demand] * constraints
        for n, (ids, sites) in zip(counts, wide, strict=True):
            selected.extend(ids[:n])
            for j in sites:
                residual[j] = max(0, residual[j] - n)
        base = sum(offers[i].cost for i in selected)
        if base >= best:
            continue
        rest = minimum_pair_cover(prices, coverage, residual)
        calls += 1
        if rest is not None:
            total = base + sum(prices[i] for i in rest)
            if total < best:
                best = total
                answer = tuple(sorted((*selected, *(compact[i][0] for i in rest))))
    assert best < inf
    return best, answer, calls


def world_plan(labels, offers, errors):
    """Select the cheapest fixed whole-source cover of all opposite worlds."""
    if (
        not labels
        or errors < 0
        or any(q.cost <= 0 or len(q.values) != len(labels) for q in offers)
    ):
        raise ValueError(
            "aligned nonempty worlds, positive prices and nonnegative error budget required"
        )
    size = len(labels)
    tree = answer_tree(offers, size)
    opposite = comb(size, 2) - sum(comb(n, 2) for n in Counter(labels).values())
    if not opposite:
        return WorldPlan(0, (), tree, 0, 0, (), 0, 0, 0)
    pairs = tree.edges if tree.convex else combinations(range(size), 2)
    material = tuple((a, b) for a, b in pairs if labels[a] != labels[b])
    retained = minimal_supports(material, offers)
    assert retained
    d = 2 * errors + 1
    compact, wide = cover_groups(offers, retained, d)
    wide_count = sum(len(ids) for ids, _ in wide)
    weakest, (a, b) = retained[0]
    if weakest.bit_count() < d:
        return WorldPlan(
            None,
            (),
            tree,
            opposite,
            len(material),
            retained,
            wide_count,
            len(wide),
            0,
            ambiguous_record(offers, a, b),
        )
    cost, chosen, calls = optimize(offers, len(retained), compact, wide, d)
    return WorldPlan(
        cost,
        chosen,
        tree,
        opposite,
        len(material),
        retained,
        wide_count,
        len(wide),
        calls,
    )
