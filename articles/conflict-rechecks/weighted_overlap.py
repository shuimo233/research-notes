"""Compile exact priced diagnostic batches with overlapping difference sets."""

from dataclasses import dataclass
from functools import cache
from math import inf

from weighted_batches import _read_observations, _validate


@dataclass(frozen=True)
class Plan:
    first: tuple[int, ...]
    worst: int
    examined_states: int
    cover_first: bool
    repeat_trigger: bool = False


@dataclass(frozen=True)
class Result:
    family: str
    possible_old: tuple[int, ...]
    extension_possible: bool
    observations: tuple


class Diagnostic:
    """Binary disagreement tests after the old explanations use their error budgets.

    The mask at position i contains old explanations separated by test i.
    Costs are positive integers. Each report has cost and may be repeated.
    The extension predicts 0 and can spend its remaining allowance on any replies.
    """

    def __init__(self, old_count, masks, costs):
        if type(old_count) is not int or old_count < 0:
            raise ValueError("old_count must be a nonnegative integer")
        self.old_count = old_count
        self.full = (1 << old_count) - 1
        self.costs = _validate(costs, 0)
        self.masks = tuple(masks)
        if len(self.costs) != len(self.masks) or any(
            type(m) is not int or m < 0 or m > self.full for m in self.masks
        ):
            raise ValueError("expected one valid disagreement mask per price")
        best = {}
        available = 0
        for i, (m, c) in enumerate(zip(self.masks, self.costs, strict=True)):
            available |= m
            if m and (m not in best or (c, i) < (self.costs[best[m]], best[m])):
                best[m] = i
        self.probes = tuple(sorted(best.values()))
        self.available = available
        self.optimal_universal = None
        if self.full in best:
            universal = best[self.full]
            weakest = max(
                min(self.costs[i] for i in self.probes if self.masks[i] & (1 << j))
                for j in range(old_count)
            )
            if self.costs[universal] == weakest:
                self.optimal_universal = universal
        self._cover = cache(self._cover_step)
        self._adaptive = cache(self._adaptive_step)

    def _cover_step(self, demand):
        if not any(demand):
            return 0, None
        choice = (inf, None)
        for i in self.probes:
            mask = self.masks[i]
            successor = tuple(
                max(0, d - ((mask >> u) & 1)) for u, d in enumerate(demand)
            )
            if successor != demand:
                value = self.costs[i] + self._cover(successor)[0]
                if value < choice[0]:
                    choice = value, i
        return choice

    def fixed(self, survivors, hits):
        """Minimum cost and tests of a fixed schedule separating the given survivors."""
        if type(survivors) is not int or not 0 <= survivors <= self.full:
            raise ValueError("invalid old-world mask")
        if type(hits) is not int or hits < 0:
            raise ValueError("hits must be a nonnegative integer")
        if survivors == self.full and self.optimal_universal is not None:
            i = self.optimal_universal
            return hits * self.costs[i], (i,) * hits
        demand = tuple(
            hits if survivors & (1 << i) else 0 for i in range(self.old_count)
        )
        cost, step = self._cover(demand)
        path = []
        while step is not None:
            path.append(step)
            mask = self.masks[step]
            demand = tuple(max(0, d - ((mask >> i) & 1)) for i, d in enumerate(demand))
            _, step = self._cover(demand)
        return None if cost == inf else (cost, tuple(path))

    def _adaptive_step(self, survivors, errors):
        if not survivors or errors < 0:
            return 0
        return min(
            (
                self.costs[i]
                + max(
                    self._adaptive(survivors & ~self.masks[i], errors),
                    self._adaptive(survivors & self.masks[i], errors - 1),
                )
                for i in self.probes
                if survivors & self.masks[i]
            ),
            default=inf,
        )

    def adaptive(self, errors):
        _validate((), errors)
        if self.optimal_universal is not None:
            return (errors + 1) * self.costs[self.optimal_universal]
        return (
            self._adaptive(self.full, errors) if self.full == self.available else None
        )

    def _advance(self, state, mask):
        out = [[] for _ in state]
        for depth, groups in enumerate(state):
            for active in groups:
                yes, no = active & mask, active & ~mask
                if no:
                    out[depth].append(no)
                if yes and depth + 1 < len(state):
                    out[depth + 1].append(yes)
        return tuple(tuple(sorted(g)) for g in out)

    def compile(self, errors, *, cover_first=False):
        """Compile an optimal two-batch plan and exact minimax budget.

        With cover_first, require that no old world predicts an all-zero first
        batch. This gives a strong comparator, including the optimal continuation.
        """
        _validate((), errors)
        if self.full != self.available:
            return None
        if not self.full:
            return Plan((), 0, 0, cover_first)
        if self.optimal_universal is not None:
            i = self.optimal_universal
            return Plan(
                (i,) if cover_first else (),
                (errors + 1) * self.costs[i],
                0,
                cover_first,
            )
        initial = ((self.full,),) + ((),) * errors

        @cache
        def visit(state):
            can_stop = not cover_first or not state[0]
            best = (
                max(
                    (
                        self._cover(
                            tuple(
                                errors + 1 - d if a & (1 << i) else 0
                                for i in range(self.old_count)
                            )
                        )[0]
                        for d, groups in enumerate(state)
                        for a in groups
                    ),
                    default=0,
                )
                if can_stop
                else inf,
                None,
            )
            useful = sum(
                a for groups in (state[:-1] if errors else state) for a in groups
            )
            for i in self.probes:
                mask = self.masks[i]
                # If every hit would exceed the extension allowance, this
                # test can be deferred into the affected second batches.
                if not (useful & mask):
                    continue
                successor = self._advance(state, mask)
                if successor != state:
                    value = self.costs[i] + visit(successor)[0]
                    if value < best[0]:
                        best = value, i
            return best

        total, step = visit(initial)
        count = visit.cache_info().currsize
        first = []
        state = initial
        while step is not None:
            first.append(step)
            state = self._advance(state, self.masks[step])
            _, step = visit(state)
        return Plan(tuple(first), total, count, cover_first)

    def compile_repeat(self, *, cover_first=False):
        """Exact one-error planner restricted to repeating the trigger on a one."""
        if self.full != self.available:
            return None
        if not self.full:
            return Plan((), 0, 0, cover_first, True)
        if self.optimal_universal is not None:
            i = self.optimal_universal
            return Plan(
                (i,) if cover_first else (), 2 * self.costs[i], 0, cover_first, True
            )
        best, examined = (inf, ()), 0
        limits = sorted({0, *(self.costs[i] for i in self.probes)})
        for limit in limits:
            options = [i for i in self.probes if self.costs[i] <= limit]
            reached = {0: (0, ())}
            for u in range(self.full + 1):
                if u not in reached:
                    continue
                paid, prior = reached[u]
                examined += 1
                if not cover_first or u == self.full:
                    demand = tuple(
                        0 if u & (1 << j) else 2 for j in range(self.old_count)
                    )
                    worst = paid + max(limit, self._cover(demand)[0])
                    if worst < best[0]:
                        best = (worst, prior)
                for i in options:
                    close = u | self.masks[i]
                    value = paid + self.costs[i]
                    if close != u and (
                        close not in reached or value < reached[close][0]
                    ):
                        reached[close] = (value, (*prior, i))
        return Plan(best[1], best[0], examined, cover_first, True)

    def run(self, plan, errors, read_batch):
        """Execute the compiled first batch and one optimal fixed confirmation."""
        _validate((), errors)
        if plan.repeat_trigger and errors != 1:
            raise ValueError("the repeat-trigger plan is compiled for one error")
        observed = []
        remaining, old = errors, self.full

        def read(q):
            nonlocal remaining, old
            if q:
                layer = _read_observations(tuple(q), read_batch)
                observed.append(layer)
                for i, bit in layer:
                    remaining -= bit
                    mask = self.masks[i]
                    old &= mask if bit else ~mask

        read(plan.first)
        if old and remaining >= 0:
            if plan.repeat_trigger and remaining == 0:
                read(tuple(i for layer in observed for i, bit in layer if bit))
            else:
                tail = self.fixed(old, remaining + 1)
                if tail is None:
                    raise ValueError(
                        "plan does not distinguish the surviving candidates"
                    )
                read(tail[1])
        if old and remaining >= 0:
            raise AssertionError("complete plan cannot leave both families alive")
        family = (
            "extension" if remaining >= 0 else ("old" if old else "out_of_contract")
        )
        compatible = tuple(i for i in range(self.old_count) if old & (1 << i))
        charge = sum(self.costs[q] for layer in observed for q, _ in layer)
        if charge > plan.worst:
            raise AssertionError("executed batch exceeded its quoted worst cost")
        return Result(family, compatible, remaining >= 0, tuple(observed))
