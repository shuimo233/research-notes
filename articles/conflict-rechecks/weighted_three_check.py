"""Independently check arbitrary three-batch plans for one remaining error."""

from argparse import ArgumentParser
from functools import cache
from itertools import combinations_with_replacement, product
import json
from pathlib import Path
from random import Random

from weighted_batches_check import branches
from weighted_rounds import execute_rounds, three_round_guarantee


def partition_optimum(costs):
    best = 2 * sum(costs)
    for assignment in product(range(3), repeat=len(costs)):
        rows = [[], [], []]
        for c, b in zip(costs, assignment, strict=True):
            rows[b].append(c)
        a, b, c = rows
        value = max(
            sum(a) + max(a, default=0),
            sum(a) + sum(b) + max(b, default=0),
            sum(a) + sum(b) + 2 * sum(c),
        )
        best = min(best, value)
    return best


def transcript_optimum(costs):
    n = len(costs)
    batches = sorted(
        (
            sum(c * k for c, k in zip(costs, counts, strict=True)),
            tuple(i for i, k in enumerate(counts) for _ in range(k)),
        )
        for counts in product(range(4), repeat=n)
        if any(counts)
    )

    @cache
    def visit(old, e, remaining):
        if not old or e < 0:
            return 0
        if not remaining:
            return float("inf")
        result = visit(old, e, remaining - 1)
        for price, qs in batches:
            if price >= result:
                break
            charge = max(visit(a, b, remaining - 1) for a, b in branches(n, old, e, qs))
            result = min(result, price + charge)
        return result

    return visit((1 << n) - 1, 1, 3)


def confirm(costs, plan):
    values = sorted(costs, reverse=True)
    A = max(sum(values[: i + 1]) + v for i, v in enumerate(values))
    assert 7 * plan.worst_cost <= 8 * A
    trace_cases = 0
    if len(costs) > 8:
        sources = [None, max(range(len(costs)), key=costs.__getitem__)]
        maximum = len(costs) * 2
        flips = [-1, 0, maximum - 1]
    else:
        sources = [None, *range(len(costs))]
        flips = range(-1, len(costs) * 2)
    for q in sources:
        for at in flips if q is None else (-1,):
            bought = reads = calls = 0

            def observe(keys):
                nonlocal bought, reads, calls
                calls += 1
                bought += sum(costs[i] for i in keys)
                replies = [
                    int(i == q) ^ int(reads + j == at) for j, i in enumerate(keys)
                ]
                reads += len(keys)
                return replies

            v = execute_rounds(plan, len(costs), 1, observe)
            assert v.family == ("extension" if q is None else "old")
            assert v.possible_old == (() if q is None else (q,))
            assert bought <= plan.worst_cost and calls <= 3
            trace_cases += 1
    return trace_cases


def run(archived):
    checked = direct = histories = 0
    for n in range(1, 7):
        for costs in combinations_with_replacement(range(1, 6), n):
            proof = three_round_guarantee(costs)
            assert partition_optimum(costs) <= proof.worst_cost
            if n <= 3:
                assert transcript_optimum(costs) == partition_optimum(costs)
                direct += 1
            histories += confirm(costs, proof)
            checked += 1
    for k in (1, 2, 3, 4, 10, 25, 100):
        prices = [3 * k, 2 * k] + [1] * (2 * k - 1)
        assert three_round_guarantee(prices).worst_cost == 8 * k - 1
        if k <= 4:
            assert partition_optimum(prices) == 8 * k - 1
    rng = Random(476016)
    for _ in range(500):
        prices = [rng.randrange(1, 20000) for _ in range(rng.randrange(1, 70))]
        histories += confirm(prices, three_round_guarantee(prices))

    # Follow-up on the already unblinded npm cohort. This is not a new holdout.
    jobs = {}
    for name, row in archived["packages"].items():
        costs = [r["price"] for r in row["members"]]
        p = three_round_guarantee(costs)
        proof = confirm(costs, p)
        jobs[name] = {
            "new_bound_plan": p.worst_cost,
            "ordered3": row["results"]["1"]["ordered"]["3"]["cost"],
            "exact2": row["results"]["1"]["exact2"],
            "executed_histories": proof,
        }
    return {
        "brute_partitions": checked,
        "independent_transcript_optima": direct,
        "small_and_random_reply_histories": histories,
        "tight_family_cases": 7,
        "npm_post_hoc": jobs,
    }


if __name__ == "__main__":
    p = ArgumentParser(description=__doc__)
    p.add_argument("record", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    result = run(json.loads(a.record.read_bytes()))
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "npm_post_hoc"}))
