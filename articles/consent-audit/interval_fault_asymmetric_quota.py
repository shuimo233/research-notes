"""Exact source verification when candidate worlds have different capacity profiles."""

from dataclasses import dataclass
from functools import cache
from itertools import combinations

from interval_fault_laminar import Quota, _union, normalize, quota_cover
from interval_fault_world_tree import discriminate


@dataclass(frozen=True)
class Hierarchy:
    size: int
    masks: tuple
    children: tuple

    def capacities(self, limits):
        if any(group not in self.masks or cap < 0 for group, cap in limits.items()):
            raise ValueError(
                "the world must use the declared hierarchy and nonnegative bounds"
            )
        return tuple(
            min(group.bit_count(), limits.get(group, group.bit_count()))
            for group in self.masks
        )


@dataclass(frozen=True)
class Plan:
    cost: int | None
    selected: tuple
    cuts: tuple
    witness: tuple | None = None


def hierarchy(size, masks):
    if size < 1:
        raise ValueError("at least one source is required")
    groups = {q.mask for q in normalize(tuple(Quota(m, 0) for m in masks), size)}
    groups.update(1 << i for i in range(size))
    groups.add((1 << size) - 1)
    order = tuple(sorted(groups, key=lambda m: (m.bit_count(), m)))
    children = [[] for _ in order]
    for i, mask in enumerate(order[:-1]):
        parent = next(j for j in range(i + 1, len(order)) if order[j] & mask == mask)
        children[parent].append(i)
    return Hierarchy(size, order, tuple(tuple(row) for row in children))


def _bounds(tree, difference, a, b):
    if (
        difference < 0
        or difference.bit_length() > tree.size
        or len(a) != len(tree.masks)
        or len(b) != len(tree.masks)
    ):
        raise ValueError(
            "in-range disagreements and aligned capacity profiles required"
        )
    counts = [(g & difference).bit_count() for g in tree.masks]
    upper, capacity_b = [], []
    for i, children in enumerate(tree.children):
        raw_a = sum(upper[j] for j in children) if children else counts[i]
        raw_b = sum(capacity_b[j] for j in children) if children else counts[i]
        upper.append(min(a[i], raw_a))
        capacity_b.append(min(b[i], raw_b))
    return counts, upper, capacity_b


def split(tree, difference, a, b):
    """Return two disjoint allowed mismatch sets, or None when incompatible."""
    counts, ua, ub = _bounds(tree, difference, a, b)
    low = [c - v for c, v in zip(counts, ub, strict=True)]
    if any(x > y for x, y in zip(low, ua, strict=True)):
        return None
    root = len(counts) - 1
    pending = [(root, low[root])]
    mask_a = 0
    for node, assigned in pending:
        children = tree.children[node]
        if not children:
            if assigned:
                mask_a |= tree.masks[node]
            continue
        extra = assigned - sum(low[j] for j in children)
        for j in children:
            added = min(extra, ua[j] - low[j])
            pending.append((j, low[j] + added))
            extra -= added
        assert not extra
    return mask_a, difference ^ mask_a


def obstruction(tree, difference, a, b):
    """Return a group and two separate antichain covers of its disagreements."""
    counts, ua, ub = _bounds(tree, difference, a, b)
    bad = next((i for i, c in enumerate(counts) if c > ua[i] + ub[i]), None)
    if bad is None:
        return None

    def cover(world, upper):
        pending = [bad]
        saved = []
        for i in pending:
            if not counts[i]:
                continue
            if upper[i] == world[i] or not tree.children[i]:
                saved.append(i)
            else:
                pending.extend(tree.children[i])
        return tuple(saved)

    return bad, cover(a, ua), cover(b, ub)


def compatible_labels(labels, offers, chosen, seen, tree, capacities):
    if len(chosen) != len(set(chosen)) or any(
        i not in range(tree.size) for i in chosen
    ):
        raise ValueError("purchase each in-range source at most once")
    possible = set()
    for (w, label), row in zip(enumerate(labels), capacities, strict=True):
        mismatches = sum(
            (offers[i].values[w] != reply) << i
            for i, reply in zip(chosen, seen, strict=True)
        )
        if all(
            (mismatches & group).bit_count() <= cap
            for group, cap in zip(tree.masks, row, strict=True)
        ):
            possible.add(label)
    return possible


def _bits(mask):
    return tuple(i for i in range(mask.bit_length()) if mask & (1 << i))


def _hitting_set(prices, cuts):
    retained = []
    for mask in sorted(set(cuts), key=lambda x: (x.bit_count(), x)):
        if not any(mask & sub == sub for sub in retained):
            retained.append(mask)
    hits = [
        sum(bool((1 << i) & row) << r for r, row in enumerate(retained))
        for i in range(len(prices))
    ]

    @cache
    def solve(uncovered):
        if not uncovered:
            return 0, 0
        mandatory = retained[(uncovered & -uncovered).bit_length() - 1]
        choices = []
        for i in _bits(mandatory):
            cost, mask = solve(uncovered & ~hits[i])
            choices.append((cost + prices[i], mask | (1 << i)))
        return min(choices)

    return solve((1 << len(retained)) - 1)


def plan_asymmetric(labels, offers, tree, budgets):
    """Find the exact cheapest portfolio, with auditable necessary hit cuts."""
    if len(offers) != tree.size or not labels or len(budgets) != len(labels):
        raise ValueError("aligned sources and worlds required")
    if any(len(q.values) != len(labels) or q.cost <= 0 for q in offers):
        raise ValueError("complete value table and positive prices required")
    if any(len(row) != len(tree.masks) or any(k < 0 for k in row) for row in budgets):
        raise ValueError("one nonnegative capacity per hierarchy node is required")
    raw = []
    for a, b in combinations(range(len(labels)), 2):
        if labels[a] != labels[b]:
            raw.append((a, b, discriminate(offers, a, b)))

    @cache
    def allocation(a, b, used):
        return split(tree, used, budgets[a], budgets[b])

    cuts, proof = [], []
    while True:
        cost, selected = _hitting_set([q.cost for q in offers], cuts)
        for a, b, original in raw:
            same = selected & original
            if allocation(a, b, same) is None:
                continue
            # Extend the shared-reply coordinates while they can still be split.
            for i in _bits(original & ~same):
                bigger = same | (1 << i)
                if allocation(a, b, bigger) is not None:
                    same = bigger
            left, right = allocation(a, b, same)
            remaining = original & ~same
            if not remaining:
                seen = tuple(
                    q.values[b if left & (1 << i) else a] for i, q in enumerate(offers)
                )
                return Plan(None, (), tuple(proof), (a, b, seen, left, right))
            cuts.append(remaining)
            proof.append((a, b, left, right, remaining))
            break
        else:
            return Plan(cost, _bits(selected), tuple(proof))


def two_level_conditions(difference, root_a, root_b, groups):
    """Compile the OR of positive separation conditions for a pair of worlds."""
    options = [(difference, root_a + root_b + 1)]
    for group, cap_a, cap_b in groups:
        options.append((difference & group, cap_a + cap_b + 1))
    for count in range(1, len(groups) + 1):
        for subset in combinations(groups, count):
            mask = difference & sum(g for g, _, _ in subset)
            options.extend(
                (
                    (mask, root_a + sum(b for _, _, b in subset) + 1),
                    (mask, root_b + sum(a for _, a, _ in subset) + 1),
                )
            )
    return _union((mask, k) for mask, k in options if mask.bit_count() >= k)


def two_level_plan(labels, offers, group_masks, limits):
    """Optimize from a disjunction per opposite pair, using the existing solver."""
    root = (1 << len(offers)) - 1
    groups = tuple(group_masks)
    if (
        len(groups) < 2
        or any(g <= 0 or g & ~root for g in groups)
        or any(g & h for g, h in combinations(groups, 2))
        or sum(groups) != root
    ):
        raise ValueError("at least two nonempty disjoint groups must cover the sources")
    if (
        not labels
        or len(limits) != len(labels)
        or any(q.cost <= 0 or len(q.values) != len(labels) for q in offers)
        or any(set(row) != {root, *groups} or min(row.values()) < 0 for row in limits)
    ):
        raise ValueError("aligned complete worlds with nonnegative capacities required")
    clauses = set()
    for a, b in combinations(range(len(labels)), 2):
        if labels[a] == labels[b]:
            continue
        options = two_level_conditions(
            discriminate(offers, a, b),
            limits[a][root],
            limits[b][root],
            tuple((g, limits[a][g], limits[b][g]) for g in groups),
        )
        if not options:
            return None, (), 0, 0
        clauses.add(options)
    cost, selected, calls, _ = quota_cover([q.cost for q in offers], sorted(clauses))
    return cost, selected, sum(map(len, clauses)), calls
