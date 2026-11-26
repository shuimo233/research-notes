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
