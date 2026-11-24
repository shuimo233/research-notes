"""Exact adaptive planning for finite pairwise outputs under independent categorical inputs."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from math import prod
from pathlib import Path
import json


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


class FrontierPlan:
    """Each type is an independent set of identical positions. Edges between adjacent types are complete."""

    def __init__(self, multiplicities, choices, edges, costs=None):
        self.names = tuple(sorted(multiplicities))
        if not self.names or set(choices) != set(self.names):
            raise ValueError("supply matching nonempty types and distributions")
        self.counts = tuple(multiplicities[u] for u in self.names)
        if any(type(n) is not int or n < 1 for n in self.counts):
            raise ValueError("positive multiplicities required")
        self.cost = tuple(Q(1 if costs is None else costs[u]) for u in self.names)
        if any(c <= 0 for c in self.cost):
            raise ValueError("positive costs required")
        self.indices = {u: i for i, u in enumerate(self.names)}
        self.neighbors = [0] * len(self.names)
        for u, v in edges:
            i, j = self.indices[u], self.indices[v]
            if i == j:
                raise ValueError("within-type edges require distinct types")
            self.neighbors[i] |= 1 << j
            self.neighbors[j] |= 1 << i
        self.groups = []
        self.rates = []
        self.certain = []
        for i, u in enumerate(self.names):
            grouped = Counter()
            for targets, p in choices[u]:
                mask = sum(1 << self.indices[v] for v in set(targets))
                if mask & ~self.neighbors[i] or Q(p) <= 0:
                    raise ValueError("invalid footprint or mass")
                grouped[mask] += Q(p)
            if sum(grouped.values()) != 1:
                raise ValueError("marginals must sum to one")
            self.groups.append(tuple(sorted(grouped.items())))
            rate = {
                j: sum(p for mask, p in grouped.items() if mask >> j & 1)
                for j in bits(self.neighbors[i])
            }
            self.rates.append(rate)
            self.certain.append(sum(1 << j for j, p in rate.items() if p == 1))
        # Bind caches to the instance; no sentence shares its fitted marginal law with another.
        self.parts = lru_cache(None)(self._parts)
        self.projections = lru_cache(None)(self._projections)
        self.optimum = lru_cache(None)(self._optimum)

    def _parts(self, counts):
        unseen = sum(1 << i for i, n in enumerate(counts) if n)
        components = []
        while unseen:
            front = unseen & -unseen
            block = 0
            while front:
                block |= front
                unseen &= ~front
                linked = 0
                for i in bits(front):
                    linked |= self.neighbors[i]
                front = linked & unseen
            components.append(
                (block, tuple(n if block >> i & 1 else 0 for i, n in enumerate(counts)))
            )
        return components

    def _projections(self, i, component):
        mass = Counter()
        for mask, p in self.groups[i]:
            mass[mask & component] += p
        return tuple(mass.items())

    def obligations(self, counts, forced):
        for i, n in enumerate(counts):
            if n:
                forced |= self.certain[i]
        return forced & sum(1 << i for i, n in enumerate(counts) if n)

    def greedy(self, counts, block):
        def key(i):
            resolved = sum(
                counts[j] * (1 - self.rates[i][j])
                for j in bits(self.neighbors[i] & block)
            )
            incident = sum(counts[j] for j in bits(self.neighbors[i] & block))
            return -resolved / self.cost[i], -incident, i

        return min(bits(block), key=key)

    def after_cost(self, i, counts, forced):
        remaining = list(counts)
        remaining[i] -= 1
        expected = self.cost[i]
        for block, local in self.parts(tuple(remaining)):
            for new, p in self.projections(i, block):
                expected += p * self.optimum(local, (forced | new) & block)[0]
        return expected

    def _optimum(self, counts, forced):
        parts = self.parts(counts)
        if not parts:
            return Q(0), None
        if len(parts) > 1:
            sub = [self.optimum(local, forced & block) for block, local in parts]
            return sum(v for v, _ in sub), next(
                (i for _, i in sub if i is not None), None
            )
        block, _ = parts[0]
        forced = self.obligations(counts, forced)
        if block.bit_count() == 1:
            i = next(bits(block))
            return (counts[i] * self.cost[i], i) if forced else (Q(0), None)
        if forced:
            i = next(bits(forced))
            return self.after_cost(i, counts, forced), i
        return min((self.after_cost(i, counts, 0), i) for i in bits(block))

    def action(self, counts, forced, mode="optimal", limit=None):
        """Return (type index, used greedy fallback for this decision)."""
        if mode not in ("optimal", "greedy"):
            raise ValueError("unknown policy")
        forced = self.obligations(counts, forced)
        if forced:
            return next(bits(forced)), False
        for block, local in self.parts(counts):
            if block.bit_count() < 2:
                continue
            if mode == "greedy":
                return self.greedy(local, block), False
            if limit is not None and prod(n + 1 for n in local) > limit:
                return self.greedy(local, block), True
            return self.optimum(local, 0)[1], False
        return None, False

    def root_value(self, limit=None):
        if limit is not None and any(
            block.bit_count() > 1 and prod(n + 1 for n in local) > limit
            for block, local in self.parts(self.counts)
        ):
            return None
        return self.optimum(self.counts, 0)[0]

    def fixed_cover(self, forced=0):
        """Maximum-weight independent set of omitted types, using the common product law."""
        m = self.counts
        weights = [
            m[j]
            * self.cost[j]
            * prod((1 - self.rates[i][j]) ** m[i] for i in bits(self.neighbors[j]))
            for j in range(len(m))
        ]

        @lru_cache(None)
        def best(mask):
            if not mask:
                return Q(0), 0, ()
            i = next(bits(mask))
            rest = mask ^ (1 << i)
            w, n, chosen = best(rest & ~self.neighbors[i])
            return min(
                (best(rest), (weights[i] + w, m[i] + n, (i,) + chosen)),
                key=lambda v: (-v[0], -v[1], v[2]),
            )

        saving, _, omitted = best(((1 << len(m)) - 1) & ~forced)
        return tuple(i for i in range(len(m)) if i not in omitted), sum(
            n * c for n, c in zip(m, self.cost)
        ) - saving


def star(center_cost, leaves):
    """leaves maps ID to (cost, probability leaf forces center, probability center forces leaf)."""
    center_cost = Q(center_cost)
    if center_cost <= 0:
        raise ValueError("positive center cost required")
    data = {u: tuple(map(Q, row)) for u, row in leaves.items()}
    if any(c <= 0 or not (0 <= a <= 1 and 0 <= b <= 1) for c, a, b in data.values()):
        raise ValueError("invalid leaf data")
    center_first = (
        center_cost + sum(c * b for c, a, b in data.values()) if data else Q(0)
    )

    def key(u):
        c, a, b = data[u]
        net = c * (1 - b)
        return (a == 0 and net != 0, net / a if a else Q(0), u)

    order = sorted(data, key=key)
    reach = Q(1)
    extra = Q(0)
    for u in order:
        c, a, b = data[u]
        extra += reach * c * (1 - b)
        reach *= 1 - a
    leaf_first = center_first + extra - center_cost * reach if data else Q(0)
    return {
        "cost": str(min(center_first, leaf_first)),
        "center_first": center_first <= leaf_first,
        "leaf_order": order,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("problem", type=Path)
    a = p.parse_args()
    s = json.loads(a.problem.read_bytes())
    planner = FrontierPlan(**s)
    value, i = planner.optimum(planner.counts, 0)
    print(
        json.dumps(
            {
                "expected": str(value),
                "first_type": None if i is None else planner.names[i],
            },
            indent=2,
        )
    )
