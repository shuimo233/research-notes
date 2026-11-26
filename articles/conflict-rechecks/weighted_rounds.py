"""Exact descending-order rechecks with a cap on synchronous batches."""

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate

from weighted_batches import (
    _order,
    _read_observations,
    _validate,
    _verdict,
    sequential_bound,
)


@dataclass(frozen=True)
class RoundPlan:
    blocks: tuple[tuple[int, ...], ...]
    tail: tuple[int, ...]
    worst_cost: int


def ordered_plan(costs, errors, rounds):
    """Minimize worst cost among plans with consecutive descending-price blocks.

    An all-matching transcript progresses through blocks and finally checks
    the tail. A lone disagreement immediately switches to one confirmation
    batch. No transcript uses more than rounds nonempty batches.
    """
    costs = _validate(costs, errors)
    if type(rounds) is not int or rounds < 1:
        raise ValueError("rounds must be a positive integer")
    order = _order(costs)
    prefix = tuple(accumulate((costs[i] for i in order), initial=0))
    total = prefix[-1]
    if errors == 0 or not order:
        return RoundPlan((), order, total)

    def at_cap(cap):
        start = 0
        ends = []
        while total + errors * (total - prefix[start]) > cap:
            if len(ends) == rounds - 1:
                return None
            room = cap - errors * costs[order[start]]
            end = bisect_right(prefix, room, lo=start + 1) - 1
            if end <= start:
                return None
            ends.append(end)
            start = end
        return ends

    low, high = sequential_bound(costs, errors), (errors + 1) * total
    while low < high:
        mid = (low + high) // 2
        if at_cap(mid) is None:
            low = mid + 1
        else:
            high = mid
    ends = at_cap(low)
    assert ends is not None
    boundaries = [0, *ends]
    blocks = tuple(order[i:j] for i, j in zip(boundaries, ends))
    return RoundPlan(blocks, order[boundaries[-1] :], low)


def three_round_guarantee(costs):
    """Construct a three-batch, one-error plan within 8/7 of the sequential optimum."""
    costs = _validate(costs, 1)
    order = _order(costs)
    if not order:
        return RoundPlan((), (), 0)
    prefix = tuple(accumulate((costs[i] for i in order), initial=0))
    total = prefix[-1]
    cap = (8 * sequential_bound(costs, 1) - 1) // 7
    end = bisect_right(prefix, cap - costs[order[0]]) - 1
    first = order[:end]
    first_cost = prefix[end] + costs[order[0]]
    if end == len(order):
        return RoundPlan((first,), (), first_cost)
    largest = costs[order[end]]
    rest = order[end + 1 :]
    # Aim to leave half the highest remaining price for the fixed tail.
    # Keep the comparison in doubled integer units.
    if 2 * (total - prefix[end + 1]) < largest:
        tail = rest
    else:
        deferred = []
        remaining = largest
        for i in rest:
            if 2 * costs[i] <= remaining:
                deferred.append(i)
                remaining -= 2 * costs[i]
        tail = tuple(deferred)
    omitted = set(tail)
    second = tuple(i for i in order[end:] if i not in omitted)
    tail_cost = sum(costs[i] for i in tail)
    worst = max(first_cost, total - tail_cost + largest, total + tail_cost)
    assert worst <= cap
    return RoundPlan((first, second), tail, worst)


def execute_rounds(plan, size, errors, read_batch):
    """Execute a plan on a batch adapter returning ordered 0/1 disagreements."""
    if type(size) is not int or size < 0 or type(errors) is not int or errors < 0:
        raise ValueError("size and errors must be nonnegative integers")
    keys = tuple(i for layer in (*plan.blocks, plan.tail) for i in layer)
    if (
        any(not block for block in plan.blocks)
        or any(type(i) is not int for i in keys)
        or sorted(keys) != list(range(size))
    ):
        raise ValueError("expected a partition into distinct valid test indices")
    observed = []
    for block in plan.blocks:
        layer = _read_observations(block, read_batch)
        observed.append(layer)
        hits = tuple(i for i, bit in layer if bit)
        if hits:
            if len(hits) == 1 and errors:
                observed.append(_read_observations(hits * errors, read_batch))
            break
    else:
        suffix = tuple(i for i in plan.tail for _ in range(errors + 1))
        if suffix:
            observed.append(_read_observations(suffix, read_batch))
    return _verdict(size, errors, observed)
