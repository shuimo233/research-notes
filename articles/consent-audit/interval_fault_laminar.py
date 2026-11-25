"""Optimal fixed source purchases under nested or disjoint corruption budgets."""

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from math import inf

from interval_fault_joint_source import minimum_pair_cover
from interval_fault_world_tree import answer_tree, discriminate, minimal_supports


@dataclass(frozen=True)
class Quota:
    mask: int
    budget: int


@dataclass(frozen=True)
class QuotaPlan:
    cost: int | None
    selected: tuple
    requirements: int
    calls: int
    matching_calls: int
    witness: tuple | None = None


def normalize(quotas, size):
    groups = {}
    for q in quotas:
        if not 0 < q.mask < (1 << size) or q.budget < 0:
            raise ValueError(
                "nonempty in-range source groups and nonnegative quotas required"
            )
        groups[q.mask] = min(groups.get(q.mask, q.budget), q.budget)
    for a, b in combinations(groups, 2):
        if a & b not in (0, a, b):
            raise ValueError("source groups must be nested or disjoint")
    return tuple(Quota(mask, groups[mask]) for mask in sorted(groups))


def permitted(mask, quotas):
    return all((mask & q.mask).bit_count() <= q.budget for q in quotas)


def separated(disagreement, quotas):
    return any((disagreement & q.mask).bit_count() > 2 * q.budget for q in quotas)


def _bits(mask):
    while mask:
        single = mask & -mask
        yield single.bit_length() - 1
        mask ^= single


def _selection_mask(selected, size):
    if any(i not in range(size) for i in selected) or len(set(selected)) != len(
        selected
    ):
        raise ValueError("select each in-range source ID at most once")
    return sum(1 << i for i in selected)


def _order(size, quotas):
    top = (1 << size) - 1
    groups = {q.mask for q in quotas} | {top}
    children = defaultdict(list)
    for group in groups - {top}:
        parent = min(
            (h for h in groups if h != group and h & group == group), key=int.bit_count
        )
        children[parent].append(group)
    stack = [top]
    while stack:
        group = stack.pop()
        if group.bit_count() == 1:
            yield group.bit_length() - 1
            continue
        descendants = sorted(children[group])
        others = group ^ sum(descendants)
        stack.extend(reversed([*descendants, *(1 << i for i in _bits(others))]))


def common_reply(offers, a, b, selected, quotas):
    difference = discriminate(offers, a, b)
    used = _selection_mask(selected, len(offers))
    difference &= used
    if separated(difference, quotas):
        raise ValueError("there is no shared transcript under these quotas")
    ordered = [i for i in _order(len(offers), quotas) if difference & (1 << i)]
    left = sum(1 << i for i in ordered[::2])
    right = difference ^ left
    assert permitted(left, quotas) and permitted(right, quotas)
    record = tuple(offers[i].values[b if left & (1 << i) else a] for i in selected)
    return a, b, record, left, right


def label_options(labels, offers, selected, replies, quotas):
    _selection_mask(selected, len(offers))
    return {
        label
        for i, label in enumerate(labels)
        if permitted(
            sum(
                (offers[j].values[i] != observed) << j
                for j, observed in zip(selected, replies, strict=True)
            ),
            quotas,
        )
    }


def _stronger(a, b):
    return a[0] & b[0] == a[0] and a[1] >= b[1]


def _intersection(rows):
    unique = set(rows)
    return tuple(
        sorted(b for b in unique if not any(a != b and _stronger(a, b) for a in unique))
    )


def _union(rows):
    unique = set(rows)
    return tuple(
        sorted(a for a in unique if not any(a != b and _stronger(a, b) for b in unique))
    )


def _satisfied(mask, row):
    return (mask & row[0]).bit_count() >= row[1]


def _fixed(prices, active):
    forced = 0
    for mask, needed in active:
        if mask.bit_count() < needed:
            return inf, 0, False
        if mask.bit_count() == needed:
            forced |= mask
    deficits = tuple(
        (mask & ~forced, required - (forced & mask).bit_count())
        for mask, required in active
        if (forced & mask).bit_count() < required
    )
    start = sum(prices[i] for i in _bits(forced))
    if not deficits:
        return start, forced, False
    used = [i for i in range(len(prices)) if any(row[0] & (1 << i) for row in deficits)]
    demands = tuple(d for _, d in deficits)
    hits = [tuple(j for j, (m, _) in enumerate(deficits) if m & (1 << i)) for i in used]
    if all(len(r) <= 2 for r in hits):
        offsets = minimum_pair_cover([prices[i] for i in used], hits, demands)
        assert offsets is not None
        selected = [used[i] for i in offsets]
        return (
            start + sum(prices[i] for i in selected),
            forced | sum(1 << i for i in selected),
            True,
        )
    states = {(0,) * len(demands): (0, 0)}
    for i, sites in zip(used, hits, strict=True):
        expanded = states.copy()
        for earned, (charge, selected) in states.items():
            after = list(earned)
            for j in sites:
                after[j] = min(demands[j], after[j] + 1)
            key = tuple(after)
            value = charge + prices[i], selected | (1 << i)
            if value < expanded.get(key, (inf, 0)):
                expanded[key] = value
        states = expanded
    cost, selected = states[demands]
    return start + cost, forced | selected, False


def quota_cover(prices, clauses):
    """Each clause is an OR of (source mask, minimum count) alternatives."""
    agenda = [()]
    best, winner = sum(prices) + 1, 0
    seen = set()
    calls = matching = 0
    while agenda:
        active = agenda.pop()
        if active in seen:
            continue
        seen.add(active)
        caution, candidate, matched = _fixed(prices, active)
        calls += 1
        matching += matched
        if caution >= best:
            continue
        unsatisfied = [
            clause
            for clause in clauses
            if not any(_satisfied(candidate, p) for p in clause)
        ]
        if not unsatisfied:
            best, winner = caution, candidate
        else:
            menu = min(unsatisfied, key=len)
            agenda.extend(_intersection((*active, condition)) for condition in menu)
    assert best <= sum(prices)
    return best, tuple(_bits(winner)), calls, matching


def quota_plan(labels, offers, quotas):
    if not labels or any(q.cost <= 0 or len(q.values) != len(labels) for q in offers):
        raise ValueError("aligned finite worlds and positive source prices required")
    quotas = normalize(quotas, len(offers))
    tree = answer_tree(offers, len(labels))
    edges = tree.edges if tree.convex else combinations(range(len(labels)), 2)
    supports = minimal_supports(
        ((a, b) for a, b in edges if labels[a] != labels[b]), offers
    )
    clauses = []
    for mask, (a, b) in supports:
        menu = _union(
            (mask & q.mask, 2 * q.budget + 1)
            for q in quotas
            if (mask & q.mask).bit_count() > 2 * q.budget
        )
        if not menu:
            evidence = common_reply(offers, a, b, tuple(range(len(offers))), quotas)
            return QuotaPlan(None, (), len(supports), 0, 0, evidence)
        clauses.append(menu)
    cost, selected, calls, matching = quota_cover([q.cost for q in offers], clauses)
    return QuotaPlan(cost, selected, len(clauses), calls, matching)


def tight_two_domains(size, prices, supports, domains, demand=3):
    """Use a minimum cut when every feasible row/domain forces all its offers."""
    import networkx as nx

    if (
        len(prices) != len(supports)
        or any(p <= 0 for p in prices)
        or demand < 1
        or size < 1
    ):
        raise ValueError(
            "aligned positive prices, nonempty rows and positive demand required"
        )
    columns = [[[], []] for _ in range(size)]
    pair_weights = defaultdict(lambda: [0, 0])
    for i, (rows, color) in enumerate(zip(supports, domains, strict=True)):
        if (
            color not in (0, 1)
            or len(rows) > 2
            or len(set(rows)) != len(rows)
            or any(v not in range(size) for v in rows)
        ):
            raise ValueError("two domains and at most two rows per offer required")
        for v in rows:
            columns[v][color].append(i)
        if len(rows) == 2:
            pair_weights[tuple(sorted(rows))][color] += prices[i]
    if any(len(part) > demand for pair in columns for part in pair):
        raise ValueError(
            "some row can meet its demand without buying every offer in a domain"
        )
    if any(max(map(len, pair)) < demand for pair in columns):
        return None
    penalty = 4 * sum(prices) + 2
    unary = [
        [
            2 * sum(prices[i] for i in part) + penalty * (len(part) < demand)
            for part in pair
        ]
        for pair in columns
    ]
    graph = nx.DiGraph()
    left, right = size, size + 1
    graph.add_nodes_from(range(size + 2))
    for (a, b), (w0, w1) in pair_weights.items():
        unary[a][1] += w0 - w1
        unary[b][1] += w0 - w1
        graph.add_edge(a, b, capacity=w0 + w1)
        graph.add_edge(b, a, capacity=w0 + w1)
    for i, row in enumerate(unary):
        z = min(row)
        graph.add_edge(left, i, capacity=row[1] - z)
        graph.add_edge(i, right, capacity=row[0] - z)
    _, (zero, _) = nx.minimum_cut(graph, left, right)
    chosen = set()
    for i, row in enumerate(columns):
        block = row[int(i not in zero)]
        assert len(block) == demand
        chosen.update(block)
    return sum(prices[i] for i in chosen), tuple(sorted(chosen))
