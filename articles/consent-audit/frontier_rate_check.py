"""Verify scalar-completion forecasts and cross-model policy costs with an unrestricted full-mask Bellman recurrence."""

from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
from math import prod


def all_actions(options, neighbor):
    @lru_cache(None)
    def after(i, remaining, forced):
        next_counts = tuple(c - int(j == i) for j, c in enumerate(remaining))
        live = sum(1 << j for j, c in enumerate(next_counts) if c)
        return 1 + sum(
            p * value(next_counts, (forced | f) & live) for f, p in options[i]
        )

    @lru_cache(None)
    def value(remaining, forced):
        candidates = [
            i
            for i, c in enumerate(remaining)
            if c and (forced >> i & 1 or any(remaining[j] for j in neighbor[i]))
        ]
        return min((after(i, remaining, forced) for i in candidates), default=Q(0))

    return value, after


def verify_completions(
    record, true_value, options, neighbor, mult, members, observed_masks
):
    assert Q(record["exact"]) == true_value
    assert (
        Q(record["block"]["forecast"])
        == Q(record["block"]["actual_expected"])
        == true_value
        and record["block"]["queries"] == record["gold"]
    )
    for mode in ("independent", "nested"):
        alternate = []
        must = []
        for i, actual in enumerate(options):
            adj = sorted(neighbor[i])
            rates = [sum(p for m, p in actual if m >> j & 1) for j in adj]
            alternatives = []
            # Compute every joint cell independently, including intersections in the nested model.
            for signature in product((False, True), repeat=len(adj)):
                if mode == "independent":
                    weight = prod(p if on else 1 - p for p, on in zip(rates, signature))
                else:
                    top = min(
                        (p for p, on in zip(rates, signature) if on), default=Q(1)
                    )
                    bottom = max(
                        (p for p, on in zip(rates, signature) if not on), default=Q(0)
                    )
                    weight = max(Q(0), top - bottom)
                if weight:
                    alternatives.append(
                        (sum(1 << j for j, on in zip(adj, signature) if on), weight)
                    )
            alternate.append(alternatives)
            must.append(sum(1 << j for j, r in zip(adj, rates) if r == 1))
        value, after = all_actions(alternate, neighbor)
        target = record[mode]
        assert value(mult, 0) == Q(target["forecast"])

        @lru_cache(None)
        def action(counts, forced):
            vertices = {i for i, n in enumerate(counts) if n}
            compulsory = set()
            for i in vertices:
                compulsory.update(j for j in vertices if must[i] >> j & 1)
            compulsory.update(i for i in vertices if forced >> i & 1)
            if compulsory:
                return min(compulsory)
            open_nodes = {i for i in vertices if neighbor[i] & vertices}
            if not open_nodes:
                return None
            component = {min(open_nodes)}
            while True:
                grown = component | set().union(
                    *(neighbor[i] & vertices for i in component)
                )
                if grown == component:
                    break
                component = grown
            return min(component, key=lambda i: (after(i, counts, forced), i))

        @lru_cache(None)
        def real(counts, forced):
            i = action(counts, forced)
            if i is None:
                return Q(0)
            nxt = tuple(n - int(j == i) for j, n in enumerate(counts))
            live = sum(1 << j for j, n in enumerate(nxt) if n)
            return 1 + sum(p * real(nxt, (forced | m) & live) for m, p in options[i])

        assert real(mult, 0) == Q(target["actual_expected"])
        counts = mult
        f = 0
        while (i := action(counts, f)) is not None:
            u = members[i][mult[i] - counts[i]]
            counts = tuple(n - int(j == i) for j, n in enumerate(counts))
            f = (f | observed_masks[u]) & sum(1 << j for j, n in enumerate(counts) if n)
        assert sum(mult) - sum(counts) == target["queries"]
        for func in (value, after, action, real):
            func.cache_clear()
