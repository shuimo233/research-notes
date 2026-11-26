"""Priced, repeatable rechecks when each old explanation has one distinguishing test."""

from dataclasses import dataclass
from fractions import Fraction
from math import gcd


def _validate(costs, errors):
    costs = tuple(costs)
    if any(type(c) is not int or c <= 0 for c in costs):
        raise ValueError("expected positive integer test costs")
    if type(errors) is not int or errors < 0:
        raise ValueError("expected a nonnegative integer error allowance")
    return costs


def _order(costs):
    return tuple(sorted(range(len(costs)), key=lambda i: (-costs[i], i)))


@dataclass(frozen=True)
class BatchPlan:
    first: tuple
    worst_cost: int


@dataclass(frozen=True)
class Verdict:
    family: str
    possible_old: tuple
    extension_possible: bool
    batches: tuple


def sequential_bound(costs, errors):
    costs = _validate(costs, errors)
    spent = worst = 0
    for i in _order(costs):
        price = costs[i]
        spent += price
        worst = max(worst, spent + errors * price)
    return worst


def _bound(costs, errors, first):
    total = sum(costs)
    bought = sum(costs[i] for i in first)
    largest = max((costs[i] for i in first), default=0)
    return bought + max((errors + 1) * (total - bought), errors * largest)


def best_prefix(costs, errors):
    costs = _validate(costs, errors)
    total = sum(costs)
    order = _order(costs)
    largest = costs[order[0]] if order else 0
    bought = 0
    best = ((errors + 1) * total, 0)
    for j, i in enumerate(order, 1):
        bought += costs[i]
        best = min(
            best, (bought + max((errors + 1) * (total - bought), errors * largest), j)
        )
    return BatchPlan(order[: best[1]], best[0])


def guaranteed(costs, errors):
    """Construct a two-round plan within 1 + (errors/(errors+1))**2 of sequential."""
    costs = _validate(costs, errors)
    order = _order(costs)
    if not order or errors == 0:
        return BatchPlan((), sum(costs))
    first = [order[0]]
    fraction = Fraction(errors, errors + 1)
    target = (1 + fraction**2) * sequential_bound(costs, errors)
    budget = target - (errors + 1) * costs[order[0]]
    for i in order[1:]:
        if costs[i] <= budget:
            first.append(i)
            budget -= costs[i]
    return BatchPlan(tuple(first), _bound(costs, errors, first))


def _nearest(bits, point):
    """Yield the closest representable integers on either side of a bend."""
    bottom = point.numerator // point.denominator
    top = -(-point.numerator // point.denominator)
    if bottom >= 0:
        below = (bits & ((1 << (bottom + 1)) - 1)).bit_length() - 1
        if below >= 0:
            yield below
    above_set = bits >> max(0, top)
    if above_set:
        yield max(0, top) + ((above_set & -above_set).bit_length() - 1)


def optimal(costs, errors):
    """Exact two-batch plan. The subset-sum table stops at the largest price."""
    costs = _validate(costs, errors)
    if not costs or errors == 0:
        return BatchPlan((), sum(costs))
    order = _order(costs)
    factor = gcd(*costs)
    prices = [costs[i] // factor for i in order]
    total = sum(prices)
    largest = prices[0]
    # A first batch including this probe is always optimal. Its complement
    # only needs total price up to largest; all larger sums lose to zero.
    mask = (1 << (largest + 1)) - 1
    reachable = 1
    introduced = []
    for price in prices[1:]:
        added = ((reachable << price) & mask) & ~reachable
        introduced.append(added)
        reachable |= added
    value, deferred = min(
        (total + max(errors * k, errors * largest - k), k)
        for k in _nearest(reachable, Fraction(errors * largest, errors + 1))
    )
    omitted = set()
    for j in range(len(prices) - 1, 0, -1):
        if (introduced[j - 1] >> deferred) & 1:
            omitted.add(order[j])
            deferred -= prices[j]
    assert deferred == 0
    return BatchPlan(tuple(i for i in order if i not in omitted), value * factor)


def execute(plan, size, errors, read_batch):
    """Run at most two synchronous batches of binary disagreements with E.

    read_batch(tuple[int, ...]) supplies exactly one 0/1 result per request.
    Repetitions count independently under the per-reply fault contract.
    """
    if type(size) is not int or size < 0 or type(errors) is not int or errors < 0:
        raise ValueError("size and errors must be nonnegative integers")
    first = tuple(plan.first)
    if len(first) != len(set(first)) or any(
        type(i) is not int or not 0 <= i < size for i in first
    ):
        raise ValueError("first batch must contain distinct valid test indices")
    observed = []

    def read(indices):
        if indices:
            observed.append(_read_observations(indices, read_batch))

    read(first)
    first_hits = tuple(i for layer in observed for i, bit in layer if bit)
    if not first_hits:
        remaining = sorted(set(range(size)) - set(first))
        read(tuple(i for i in remaining for _ in range(errors + 1)))
    elif len(first_hits) == 1:
        read(first_hits * errors)

    return _verdict(size, errors, observed)


def _read_observations(indices, read_batch):
    answers = tuple(read_batch(indices))
    if len(answers) != len(indices) or any(
        type(x) not in (bool, int) or x not in (0, 1) for x in answers
    ):
        raise ValueError("adapter returned invalid binary observations")
    return tuple(zip(indices, answers, strict=True))


def _verdict(size, errors, observed):
    seen_zero = {i for layer in observed for i, bit in layer if not bit}
    ones = [i for layer in observed for i, bit in layer if bit]
    extension = len(ones) <= errors
    if not ones:
        old = tuple(i for i in range(size) if i not in seen_zero)
    elif len(set(ones)) == 1 and ones[0] not in seen_zero:
        old = (ones[0],)
    else:
        old = ()
    if old and extension:
        raise AssertionError("complete plan left both explanation families alive")
    family = "extension" if extension else ("old" if old else "out_of_contract")
    return Verdict(family, old, extension, tuple(observed))
