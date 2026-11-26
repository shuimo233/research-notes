"""Check the priced-batch theorem against raw transcripts and the wheel ledgers."""

import argparse
from collections import Counter
from functools import cache
from hashlib import sha256
from itertools import combinations, combinations_with_replacement, product
import json
from math import inf
from pathlib import Path
from random import Random
from zipfile import ZipFile

from reproduce import PREDICTIONS, predict, sql_read
from weighted_batches import (
    BatchPlan,
    best_prefix,
    execute,
    guaranteed,
    optimal,
    sequential_bound,
)
from weighted_diagnose import attribute_with_prices


def branches(n, old, allowance, batch):
    replies = {
        sum((q == i) << j for j, q in enumerate(batch))
        for i in range(n)
        if old & (1 << i)
    }
    for count in range(min(len(batch), allowance) + 1):
        replies.update(
            sum(1 << i for i in group)
            for group in combinations(range(len(batch)), count)
        )
    for reply in replies:
        masks = [sum((q == i) << j for j, q in enumerate(batch)) for i in range(n)]
        compatible = sum(
            1 << i for i, m in enumerate(masks) if (old & (1 << i)) and m == reply
        )
        yield compatible, allowance - reply.bit_count()


def transcript_oracle(costs, errors):
    n = len(costs)
    initial = ((1 << n) - 1, errors)
    fixed_options = sorted(
        (
            sum(c * x for c, x in zip(costs, counts)),
            tuple(i for i, k in enumerate(counts) for _ in range(k)),
        )
        for counts in product(range(errors + 3), repeat=n)
    )

    @cache
    def after_fixed(old, f):
        if not old or f < 0:
            return 0
        for c, batch in fixed_options:
            replies = [
                tuple(int(q == i) for q in batch) for i in range(n) if old & (1 << i)
            ]
            if all(sum(row) > f for row in replies):
                return c
        raise AssertionError("finite price list must allow full discrimination")

    @cache
    def sequential(old, f):
        if not old or f < 0:
            return 0
        options = []
        for q, unit in enumerate(costs):
            replies = tuple(branches(n, old, f, (q,)))
            if (old, f) not in replies:
                options.append(unit + max(sequential(*s) for s in replies))
        return min(options, default=inf)

    two = after_fixed(*initial)
    for c, batch in fixed_options:
        if c >= two:
            break
        worst = max(after_fixed(*s) for s in branches(n, *initial, batch))
        two = min(two, c + worst)
    return sequential(*initial), two


def score_cost(costs, f, first):
    assert len(set(first)) == len(first) and all(0 <= i < len(costs) for i in first)
    total_first = sum(costs[i] for i in first)
    continuation = [(f + 1) * sum(c for i, c in enumerate(costs) if i not in first)]
    continuation.extend(f * costs[i] for i in first)
    return total_first + max(continuation)


def possible_at(costs, f, cap):
    # Direct feasibility of a first-batch cost window for a given ceiling.
    t = sum(costs)
    if cap >= (f + 1) * t:
        return True
    if f == 0:
        return False
    min_first = ((f + 1) * t - cap + f - 1) // f
    attainable = 1
    for p in sorted(costs):
        lo = max(0, min_first - p)
        hi = cap - (f + 1) * p
        if lo <= hi and (attainable >> lo) & ((1 << (hi - lo + 1)) - 1):
            return True
        attainable |= attainable << p
    return False


def check_execution(costs, f):
    checked = 0
    for plan in (
        optimal(costs, f),
        guaranteed(costs, f),
        BatchPlan((), (f + 1) * sum(costs)),
    ):
        max_calls = max(
            len(plan.first) + f,
            len(plan.first) + (f + 1) * (len(costs) - len(plan.first)),
        )
        for changed in range(len(costs)):
            actual = execute(
                plan,
                len(costs),
                f,
                lambda batch: tuple(int(i == changed) for i in batch),
            )
            assert actual.family == "old" and actual.possible_old == (changed,)
            assert (
                sum(costs[i] for a in actual.batches for i, _ in a) <= plan.worst_cost
            )
            checked += 1
        for k in range(f + 1):
            for positions in combinations(range(max_calls), k):
                at = 0

                def observations(batch):
                    nonlocal at
                    b = [int(i in positions) for i in range(at, at + len(batch))]
                    at += len(batch)
                    return b

                actual = execute(plan, len(costs), f, observations)
                assert actual.family == "extension"
                assert (
                    sum(costs[i] for a in actual.batches for i, _ in a)
                    <= plan.worst_cost
                )
                checked += 1
    return checked


def check_theory():
    oracle_cases = histories = 0
    for n in range(1, 5):
        for costs in combinations_with_replacement(range(1, 7), n):
            for f in (0, 1, 2):
                seq, two = transcript_oracle(costs, f)
                assert seq == sequential_bound(costs, f)
                assert two == optimal(costs, f).worst_cost
                assert two <= guaranteed(costs, f).worst_cost
                assert guaranteed(costs, f).worst_cost * (f + 1) ** 2 <= seq * (
                    (f + 1) ** 2 + f * f
                )
                oracle_cases += 1
                if n <= 3:
                    histories += check_execution(costs, f)
    rnd = Random(412263)
    for _ in range(800):
        prices = [rnd.randrange(1, 500) for i in range(rnd.randrange(1, 35))]
        f = rnd.randrange(1, 10)
        exact = optimal(prices, f)
        assert score_cost(prices, f, exact.first) == exact.worst_cost
        assert not possible_at(prices, f, exact.worst_cost - 1)
        cap = guaranteed(prices, f).worst_cost
        assert exact.worst_cost <= cap
        assert cap * (f + 1) ** 2 <= sequential_bound(prices, f) * (
            (f + 1) ** 2 + f * f
        )
        assert best_prefix(prices, f).worst_cost * (f + 2) <= sequential_bound(
            prices, f
        ) * (2 * f + 2)
    for f in range(1, 6):
        for k in (1, 2, 4, 20):
            p = (f + 1) * k
            prices = [p] + [1] * (f * p - f)
            s = sequential_bound(prices, f)
            b = optimal(prices, f)
            assert s == (f + 1) * p
            assert b.worst_cost == s - f + f * f * k
    for f in range(1, 6):
        for k in (f * (f + 1), 2 * f * (f + 1), 100):
            p = (f + 2) * k
            prices = [p] + [k] * (f * f + f) + [1] * (f * k - f)
            s = sequential_bound(prices, f)
            prefix = best_prefix(prices, f)
            assert s == (f + 1) * p
            assert prefix.worst_cost == sum(prices) + f * (f + 1) * k - f * f
    assert (
        sequential_bound((9, 3, 3), 1) == 18 and optimal((9, 3, 3), 1).worst_cost == 21
    )
    too_many = execute(BatchPlan((0, 1), 4), 2, 1, lambda batch: [1] * len(batch))
    assert too_many.family == "out_of_contract"
    return {
        "exhaustive_price_and_allowance_cases": oracle_cases,
        "explicit_executed_reply_histories": histories,
        "random_wider_price_cases": 800,
        "tight_family_cases": 20,
        "price_prefix_tight_family_cases": 15,
    }


def check_ledger(result, wheel_root):
    count = 0
    stats = Counter()
    total_replays = 0
    for record in result["packages"].values():
        paths = [wheel_root / item["file"] for item in record["sources"]]
        for path, item in zip(paths, record["sources"], strict=True):
            assert path.stat().st_size == item["size"]
            assert sha256(path.read_bytes()).hexdigest() == item["sha256"]
        costs = []
        with ZipFile(paths[0]) as old, ZipFile(paths[1]) as new:
            for row in record["members"]:
                contents = [z.read(row["path"]) for z in (old, new)]
                for tag, data in zip(("old", "new"), contents, strict=True):
                    assert (
                        len(data) == row[tag + "_length"]
                        and sha256(data).hexdigest() == row[tag + "_sha256"]
                    )
                assert contents[0] != contents[1]
                costs.append(max(map(len, contents)))
                assert costs[-1] == row["reserve"]
        if not costs:
            assert record["data_status"] == "no_selected_members"
            stats["excluded"] += 1
            continue
        count += len(costs)
        for f, block in record["by_error_allowance"].items():
            f = int(f)
            rows = block["policies"]
            for r in rows.values():
                assert r["worst_bytes"] == score_cost(costs, f, r["first"])
            assert not possible_at(costs, f, rows["optimal"]["worst_bytes"] - 1)
            assert block["sequential"] == sequential_bound(costs, f)
            assert (
                rows["best_prefix"]["worst_bytes"] == best_prefix(costs, f).worst_cost
            )
            assert rows["guaranteed"]["worst_bytes"] * (f + 1) ** 2 <= block[
                "sequential"
            ] * ((f + 1) ** 2 + f * f)
            for name, run in block["replays"].items():
                assert run["cases"] == len(costs) + 2
                assert run["boundary_flip_witness"]["flips"] == f
                assert (
                    run["worst_reserved_witness"]["reserved"]
                    == rows[name]["worst_bytes"]
                )
                assert run["max_actual_bytes"] <= rows[name]["worst_bytes"]
                total_replays += run["cases"]
            if f == 1:
                for name, row in rows.items():
                    stats[name] += row["worst_bytes"]
                stats["sequential"] += block["sequential"]
                stats["passed"] += (
                    100 * rows["guaranteed"]["worst_bytes"]
                    <= 85 * rows["fixed"]["worst_bytes"]
                )
    assert stats == result["f1_totals"]
    assert result["passed_primary_gate"] == (stats["passed"] >= 8)
    return {
        "verified_members_and_prices": count,
        "verified_wheel_pairs": len(result["packages"]),
        "reported_replays_checked": total_replays,
        "passed_primary_gate": result["passed_primary_gate"],
    }


def check_sqlite_adapter():
    extension = "FAIL"
    older = {
        name: (lambda q, name=name: predict(name, q))
        for name in PREDICTIONS
        if name != extension
    }
    new = lambda q: predict(extension, q)
    prices = {"key2": 9, "key3": 3}
    checks = 0
    for name in PREDICTIONS:
        true_prefix = [(q, sql_read(name, q)) for q in prices]
        flip = {"ROLLBACK": 0, "ABORT": 0, "FAIL": None, "IGNORE": 1, "REPLACE": 1}[
            name
        ]
        history = [(q, y ^ int(i == flip)) for i, (q, y) in enumerate(true_prefix)]
        assert tuple(y for _, y in history) == (1, 0)
        masks = [None, 0, 1, 2, 3] if name == extension else [None]
        for ordinal in masks:
            trace = []

            def read_batch(batch):
                replies = []
                for q in batch:
                    y = sql_read(name, q) ^ int(len(trace) == ordinal)
                    trace.append((q, y))
                    replies.append(y)
                return replies

            out = attribute_with_prices(
                older, new, prices, history, read_batch, exact=True
            )
            expected = "extension" if name == extension else "existing"
            assert out.result.family == expected and out.result.observations == tuple(
                trace
            )
            assert out.booked_upper_bound == 18
            assert out.actual_booked == sum(prices[q] for q, _ in trace) <= 18
            assert len(out.batches) <= 2
            if expected == "existing":
                assert name in out.result.existing_rules
            checks += 1

    def forbidden_read(_):
        raise AssertionError("this precondition must stop before reading")

    common = (older, new, prices, [("key2", 1), ("key3", 0)], forbidden_read)
    refusal = attribute_with_prices(*common, budget=17)
    assert refusal.result.reason == "budget" and refusal.actual_booked == 0
    unsupported = attribute_with_prices(
        older, new, {**prices, "key1": 1}, common[3], forbidden_read
    )
    assert unsupported.result.reason == "overlapping_difference_sets"
    return {"sqlite_actual_traces": checks, "budget_and_scope_checks": 2}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("wheels", "results", "output"):
        p.add_argument(field, type=Path)
    a = p.parse_args()
    audit = {
        "theory": check_theory(),
        "ledger": check_ledger(json.loads(a.results.read_bytes()), a.wheels),
        "adapter": check_sqlite_adapter(),
    }
    a.output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit))
