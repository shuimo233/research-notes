"""Use priced scheduling from a history of conflicting binary observations."""

from dataclasses import dataclass

from diagnose import Result, bit
from weighted_batches import best_prefix, execute, guaranteed, optimal


@dataclass(frozen=True)
class PricedDiagnosis:
    result: Result
    booked_upper_bound: int | None
    actual_booked: int
    batches: tuple


def attribute_with_prices(
    existing,
    extension,
    prices,
    history,
    read_batch,
    *,
    extension_errors=1,
    budget=None,
    exact=False,
):
    """Attribute an observation conflict with a finite, priced test catalogue.

    Each old rule has one lifetime error. The extension has its own allowance.
    Only cases where every live old rule has used its error and differs from
    the extension at one available probe use this scheduler.
    """
    if type(extension_errors) is not int or extension_errors < 0:
        raise ValueError("extension_errors must be a nonnegative integer")
    if budget is not None and (type(budget) is not int or budget < 0):
        raise ValueError("budget must be a nonnegative integer")
    if any(type(c) is not int or c <= 0 for c in prices.values()):
        raise ValueError("each probe price must be a positive integer")
    history = tuple((q, bit(y)) for q, y in history)

    def mismatches(rule):
        return sum(bit(rule(q)) != y for q, y in history)

    used = {name: mismatches(rule) for name, rule in existing.items()}
    live = tuple(name for name, n in used.items() if n <= 1)
    remaining = extension_errors - mismatches(extension)

    def stop(reason, upper):
        if live:
            family = "existing" if remaining < 0 else "ambiguous"
        else:
            family = "inconsistent" if remaining < 0 else "extension"
        return PricedDiagnosis(
            Result(family, live, remaining >= 0, (), reason), upper, 0, ()
        )

    if not live or remaining < 0:
        return stop("history", 0)
    if any(used[name] == 0 for name in live):
        return stop("existing_error_allowance_remains", None)
    predicted = {q: bit(extension(q)) for q in prices}
    buckets = {}
    for name in live:
        different = [q for q, y in predicted.items() if bit(existing[name](q)) != y]
        if not different:
            return stop("indistinguishable_old_rule", None)
        if len(different) != 1:
            return stop("overlapping_difference_sets", None)
        buckets.setdefault(different[0], []).append(name)
    probes = tuple(q for q in prices if q in buckets)
    costs = tuple(prices[q] for q in probes)
    plan = (
        optimal(costs, remaining)
        if exact
        else min(
            (guaranteed(costs, remaining), best_prefix(costs, remaining)),
            key=lambda p: p.worst_cost,
        )
    )
    if budget is not None and plan.worst_cost > budget:
        return stop("budget", plan.worst_cost)

    def normalized(indices):
        questions = tuple(probes[i] for i in indices)
        answers = read_batch(questions)
        return tuple(
            bit(a) ^ predicted[q] for q, a in zip(questions, answers, strict=True)
        )

    evidence = execute(plan, len(costs), remaining, normalized)
    by_batch = tuple(
        tuple((probes[i], value ^ predicted[probes[i]]) for i, value in layer)
        for layer in evidence.batches
    )
    observations = tuple(item for layer in by_batch for item in layer)
    compatible = tuple(
        name for i in evidence.possible_old for name in buckets[probes[i]]
    )
    family = {
        "extension": "extension",
        "old": "existing",
        "out_of_contract": "inconsistent",
    }[evidence.family]
    return PricedDiagnosis(
        Result(
            family, compatible, evidence.extension_possible, observations, "evidence"
        ),
        plan.worst_cost,
        sum(prices[q] for q, _ in observations),
        by_batch,
    )
