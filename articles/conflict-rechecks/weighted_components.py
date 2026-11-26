"""Exact two-batch rechecks without constructing the product of local worlds."""

from dataclasses import dataclass
from itertools import combinations
from math import prod

from weighted_batches import _read_observations, _validate


@dataclass(frozen=True)
class Profile:
    first: tuple[int, ...]
    charge: int
    zero: int
    positive: int


@dataclass(frozen=True)
class ProductPlan:
    profiles: tuple[Profile, ...]
    worst: int
    cover_first: bool
    convolution_states: int


@dataclass(frozen=True)
class ProductResult:
    family: str
    compatible_choices: tuple[tuple[int, ...], ...]
    target_possible: bool
    observations: tuple


def local_profiles(diagnostic, errors):
    if diagnostic.available != diagnostic.full:
        raise ValueError("some component versions have no distinguishing probe")
    options = []
    for count in range(len(diagnostic.probes) + 1):
        for first in combinations(diagnostic.probes, count):
            groups = {}
            for j in range(diagnostic.old_count):
                signature = tuple(i for i in first if diagnostic.masks[i] & (1 << j))
                groups[signature] = groups.get(signature, 0) | (1 << j)
            zero = diagnostic.fixed(groups.get((), 0), errors + 1)[0]
            positive = max(
                (
                    diagnostic.fixed(old, errors + 1 - len(bits))[0]
                    for bits, old in groups.items()
                    if 0 < len(bits) <= errors
                ),
                default=0,
            )
            options.append(
                Profile(first, sum(diagnostic.costs[i] for i in first), zero, positive)
            )
    return tuple(options)


def nondominated(states):
    out = {}
    best = None
    for b, (a, path) in sorted(states.items()):
        if best is None or a < best:
            out[b] = (a, path)
            best = a
    return out


class ComponentDiagnosis:
    """Each question is a (component index, local test index) pair.

    All non-target products of the component candidates are supported.
    The target has a global per-reply error budget, old products have none.
    """

    def __init__(self, components):
        self.components = tuple(components)
        self.product_size = prod(d.old_count + 1 for d in self.components)

    def compile(self, errors, *, cover_first=False):
        _validate((), errors)
        if any(d.available != d.full for d in self.components):
            return None
        parts = tuple(
            tuple(p for p in local_profiles(d, errors) if not cover_first or not p.zero)
            for d in self.components
        )
        caps = sorted({0, *(p.positive for row in parts for p in row)})
        best, states = None, 0
        for limit in caps:
            if any(all(p.positive > limit for p in row) for row in parts):
                continue
            frontier = {0: (0, ())}
            for row in parts:
                updated = {}
                for b, (a, path) in frontier.items():
                    for p in row:
                        if p.positive > limit:
                            continue
                        x, y = b + p.zero, a + p.charge
                        if x not in updated or y < updated[x][0]:
                            updated[x] = (y, (*path, p))
                frontier = nondominated(updated)
                states += len(frontier)
            for b, (a, path) in frontier.items():
                value = a + max(b, limit)
                if best is None or value < best[0]:
                    best = (value, path)
        assert best is not None
        value, chosen = best
        quote = sum(p.charge for p in chosen) + max(
            sum(p.zero for p in chosen), max((p.positive for p in chosen), default=0)
        )
        assert quote == value
        return ProductPlan(chosen, value, cover_first, states)

    def fixed_cost(self, errors):
        _validate((), errors)
        if any(d.available != d.full for d in self.components):
            return None
        return sum(d.fixed(d.full, errors + 1)[0] for d in self.components)

    def run(self, plan, errors, read_batch):
        _validate((), errors)
        if len(plan.profiles) != len(self.components):
            raise ValueError("plan does not cover this component catalog")
        seen = []
        active = [d.full for d in self.components]
        positive = [0] * len(active)

        def read(keys):
            if keys:
                row = _read_observations(tuple(keys), read_batch)
                seen.append(row)
                for (c, q), bit in row:
                    m = self.components[c].masks[q]
                    active[c] &= m if bit else ~m
                    positive[c] += bit

        def old_possible():
            return any(active) and all(
                a or not p for a, p in zip(active, positive, strict=True)
            )

        read([(c, q) for c, p in enumerate(plan.profiles) for q in p.first])
        used = sum(positive)
        if old_possible() and used <= errors:
            if used:
                choices = []
                for c, (d, a, p) in enumerate(
                    zip(self.components, active, positive, strict=True)
                ):
                    if p:
                        budget, queries = d.fixed(a, errors + 1 - used)
                        choices.append((budget, c, queries))
                _, c, qs = min(choices)
                tail = [(c, q) for q in qs]
            else:
                tail = [
                    (c, q)
                    for c, (d, a) in enumerate(
                        zip(self.components, active, strict=True)
                    )
                    for q in d.fixed(a, errors + 1)[1]
                ]
            read(tail)

        target = sum(positive) <= errors
        old = old_possible()
        if target and old:
            raise AssertionError("both explanation families remain")
        family = "target" if target else "old" if old else "out_of_contract"
        choices = tuple(
            tuple(i for i in range(d.old_count) if (a >> i) & 1)
            + (() if p else (d.old_count,))
            for d, a, p in zip(self.components, active, positive, strict=True)
        )
        cost = sum(self.components[c].costs[q] for row in seen for (c, q), _ in row)
        if cost > plan.worst:
            raise AssertionError("executed quote exceeds the minimax bound")
        return ProductResult(family, choices, target, tuple(seen))
