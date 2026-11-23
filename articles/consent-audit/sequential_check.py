"""Decision-tree oracle. Enumerates full policies, affordable probes and all joint reports."""

from collections import Counter
from functools import lru_cache
from itertools import product
import json
from math import inf
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sequential import recommend


def honest(mask, row):
    if row["consent"]:
        return {3}
    return {2 * ((mask >> (price - 1)) & 1) for price in range(row["low"], row["high"] + 1)}


def oracle(problem, implementation, totals):
    masks = range(1 << problem["max_offer"])
    f = problem["errors"]
    history = problem["history"]
    items = problem["menu"]
    capacities = tuple(x["capacity"] for x in items)
    future = [[honest(mask, {**item, "consent": False}) for mask in masks] for item in items]

    def fits(mask, row):
        return any(bool(word & 1) == row["effect"] and
                   (row["request"] is None or bool(word & 2) == row["request"])
                   for word in honest(mask, row))

    residual = tuple(max(-1, f - sum(not fits(mask, row) for row in history)) for mask in masks)

    def branches(budgets, stock, probe):
        left = list(stock)
        left[probe] -= 1
        distinct = set()
        for raw_log in range(4):
            child = tuple(max(-1, r - int(raw_log not in options))
                          for r, options in zip(budgets, future[probe]))
            if max(child) >= 0:
                distinct.add(child)
        return [(child, tuple(left)) for child in distinct]

    @lru_cache(maxsize=None)
    def best(budgets, stock):
        if budgets[0] < 0 or max(budgets[1:]) < 0:
            return 0
        depths = [1 + max(best(*child) for child in branches(budgets, stock, j))
                  for j, cap in enumerate(stock) if cap]
        return min(depths, default=inf)

    depth = best(residual, capacities)
    if residual[0] < 0:
        expected = "safe_baseline_refuted"
    elif max(residual[1:]) < 0:
        expected = "safe_through_bound"
    elif depth == inf:
        expected = "menu_insufficient"
    else:
        expected = "unresolved"
    assert implementation["status"] == expected, (problem, depth, implementation)
    if expected == "unresolved":
        choice = next(i for i, item in enumerate(items) if item["name"] == implementation["next_probe"]["name"])
        first_depth = 1 + max(best(*child) for child in branches(residual, capacities, choice))
        assert implementation["worst_case_probes"] == depth == first_depth, (problem, depth, first_depth)
        if implementation["fixed_batch_probes"] > depth:
            totals["strict_savings"] += 1
    totals["decision_tree_states"] += best.cache_info().currsize
    totals[expected] += 1


def offer(low, high, capacity):
    return {"name": f"{low}-{high}", "low": low, "high": high, "cost": 1, "capacity": capacity}


def run():
    totals = Counter()

    def check(b, f, rows, menu):
        p = {"max_offer": b, "errors": f, "history": rows, "menu": menu}
        oracle(p, recommend(p), totals)

    grid = 0
    for f in range(3):
        for a, b, wide in product(range(2*f+2), range(2*f+2), range(2)):
            check(2, f, [], [offer(1, 1, a), offer(2, 2, b), offer(1, 2, wide)])
            grid += 1
    rng = Random(923117)
    for case in range(180):
        b = rng.choice((2, 3))
        f = rng.choice((0, 1))
        rows = []
        for _ in range(rng.randrange(5)):
            low = rng.randint(1, b)
            consent = rng.randrange(5) == 0
            rows.append({"low": low, "high": rng.randint(low, b), "consent": consent,
                         "effect": consent if rng.randrange(5) else not consent,
                         "request": rng.choice((True, False, None))})
        menu = [offer(i, i, 2*f+1 if case % 2 else rng.randrange(2*f+2)) for i in range(1, b+1)]
        menu.append(offer(1, b, rng.randrange(3)))
        check(b, f, rows, menu)
    # Nontrivial interval history and a multi-price alternative that can fit its positive row.
    for pos, neg, f in product(((1, 2), (2, 3)), ((1, 3), (1, 1)), (1, 2)):
        rows = [{"consent": False, "low": l, "high": h, "request": q, "effect": False}
                for (l, h), q in ((pos, True), (neg, False))]
        check(3, f, rows, [offer(i, i, 2*f+1) for i in range(1, 4)] + [offer(1, 3, 1)])
    for f in range(3):
        rows = [{"low": i, "high": i, "consent": False, "request": False, "effect": False}
                for i in (1, 2) for _ in range(f+1)]
        check(2, f, rows, [])
    # A real interval history and an exact-answer pattern can differ on the doubleton
    # while inducing the same remaining resources on the all-zero input and both singletons.
    menu = [offer(i, i, 4) for i in (1, 2)] + [offer(1, 2, 2)]
    def request(low, high):
        return {"low": low, "high": high, "consent": False, "request": True, "effect": False}
    first = {"max_offer": 2, "errors": 2, "history": [request(1, 2)], "menu": menu}
    second = {**first, "errors": 3, "history": [request(1, 1), request(2, 2)]}
    assert recommend(first) == recommend(second)
    for scenario in (first, second):
        oracle(scenario, recommend(scenario), totals)
    return {"seed": 923117, "empty_history_capacity_grid": grid, "random_history_scenarios": 180,
            "targeted_interval_cases": 8, "already_safe_cases": 3, "matched_history_cases": 2,
            "oracle": dict(sorted(totals.items()))}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
