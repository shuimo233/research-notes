"""Supplemental exact width-budget planner for an already-certified partition."""

import argparse
from collections import defaultdict
from fractions import Fraction as F
from itertools import combinations, product
import json
from math import lcm, prod
from pathlib import Path

from audit_runtime_latency_check import CASES, MODES, load_records


def work_distribution(lengths, blocks, mode_weights, power):
    denominator = lcm(*(p.denominator for _, p in mode_weights))
    total = {0: 1}
    for block in blocks:
        shape = defaultdict(int)
        for width, p in mode_weights:
            value = sum(max(lengths[i], width) ** power for i in block)
            shape[value] += int(p * denominator)
        extended = defaultdict(int)
        for a, mass in total.items():
            for b, q in shape.items():
                extended[a + b] += mass * q
        total = extended
    total_mass = denominator ** len(blocks)
    assert sum(total.values()) == total_mass
    return {n: F(v, total_mass) for n, v in total.items() if v}


def expected_buckets(lengths, blocks, mode_weights, setup=None):
    all_widths = set(lengths) | {w for w, _ in mode_weights}
    count = F(0)
    for t in all_widths:
        qs = [sum(p for w, p in mode_weights if max(n, w) == t) for n in lengths]
        cost = 1 if setup is None else setup.get(t, 0)
        if cost < 0:
            raise ValueError("expected nonnegative width setup costs")
        count += cost * (1 - prod(1 - max(qs[i] for i in group) for group in blocks))
    return count


def quantile(law, p):
    cumul = 0
    for value, mass in sorted(law.items()):
        cumul += mass
        if cumul >= p:
            return value
    raise ArithmeticError("probability mass is incomplete")


def workload_budget(
    world_lengths, blocks, mode_weights, maximum=F(1, 2), quality=F(19, 20)
):
    """Choose the largest shared portion preserving baseline workload quantiles."""
    contexts = tuple(tuple(seq) for seq in world_lengths)
    mode_weights = tuple((i, F(p)) for i, p in mode_weights)
    if (
        not contexts
        or len({len(z) for z in contexts}) != 1
        or any(
            not value or type(value) is not int or value > 512 or value < 0
            for row in contexts
            for value in row
        )
    ):
        raise ValueError("expected equally many positive input lengths in each world")
    width = len(contexts[0])
    if (
        not blocks
        or not all(blocks)
        or sorted(i for b in blocks for i in b) != list(range(width))
    ):
        raise ValueError("expected a partition of the declared requests")
    if (
        not mode_weights
        or sum(p for _, p in mode_weights) != 1
        or any(
            p < 0 or type(i) is not int or not 0 <= i <= 512 for i, p in mode_weights
        )
    ):
        raise ValueError("expected a valid width distribution")
    maximum, quality = F(maximum), F(quality)
    if not 0 <= maximum <= 1 or not 0 < quality < 1:
        raise ValueError("invalid sharing or quantile target")
    independent = [(i,) for i in range(width)]
    upper = maximum
    cuts = []
    bucket = []
    for lengths in contexts:
        base = expected_buckets(lengths, independent, mode_weights)
        shared = expected_buckets(lengths, blocks, mode_weights)
        assert shared <= base
        bucket.append((base, shared))
        for power in (1, 2):
            a = work_distribution(lengths, independent, mode_weights, power)
            b = work_distribution(lengths, blocks, mode_weights, power)
            assert sum(k * v for k, v in a.items()) == sum(k * v for k, v in b.items())
            threshold = quantile(a, quality)
            p = sum(v for k, v in a.items() if k > threshold)
            q = sum(v for k, v in b.items() if k > threshold)
            if q > p:
                upper = min(upper, (1 - quality - p) / (q - p))
            cuts.append((power, threshold, p, q))
    return {
        "shared_cap": str(upper),
        "bounds": [
            {
                "power": power,
                "p95_limit": t,
                "independent_tail": str(p),
                "group_tail": str(q),
                "deployed_tail": str(p + upper * (q - p)),
            }
            for power, t, p, q in cuts
        ],
        "per_world_configurations": [
            [str(a), str(a + upper * (b - a))] for a, b in bucket
        ],
    }


def check_width_counterexample():
    # The conflicts A-B, B-C, C-D make the two-color allocation unique.
    lengths = (1, 2, 2, 1)
    weights = ((0, F(1, 2)), (2, F(1, 2)))
    two = ((0, 2), (1, 3))
    three = ((0, 3), (1,), (2,))
    upper = []
    for blocks, target in ((two, F(7, 4)), (three, F(3, 2))):
        exact = F(0)
        states = defaultdict(F)
        for picks in product(weights, repeat=len(blocks)):
            widths = {
                max(lengths[i], m)
                for group, (m, _) in zip(blocks, picks, strict=True)
                for i in group
            }
            mass = prod(p for _, p in picks)
            exact += mass * len(widths)
            states[
                sum(
                    max(lengths[i], m)
                    for group, (m, _) in zip(blocks, picks, strict=True)
                    for i in group
                )
            ] += mass
        assert exact == target == expected_buckets(lengths, blocks, weights)
        assert states == work_distribution(lengths, blocks, weights, 1)
        upper.append(str(exact))
    return upper


def run(ledger, plans):
    rows, by_case = load_records(ledger, plans)
    weights = tuple((mode, F(1, 8)) for mode in MODES)
    cases = {}
    for c in CASES:
        lengths = tuple(tuple(int(x["length"]) for x in rows[c, w]) for w in range(3))
        out = workload_budget(lengths, by_case[c], weights)
        assert all(F(q["deployed_tail"]) <= F(1, 20) for q in out["bounds"])
        winner, saving = None, F(0)
        for block in by_case[c]:
            for i, j in combinations(block, 2):
                # Refining a certified partition preserves its all-window parity.
                smaller = [[i, j]] + [[k] for k in range(8) if k not in (i, j)]
                option = workload_budget(lengths, smaller, weights)
                gain = (
                    sum(F(a) - F(b) for a, b in option["per_world_configurations"]) / 3
                )
                if gain > saving:
                    winner = {"pair": [i, j], "budget": option}
                    saving = gain
        cases[str(c)] = {
            "original_partition": out,
            "best_single_pair": winner,
            "pair_mean_width_saving": str(saving),
        }
    return {
        "effective_width_counterexample": check_width_counterexample(),
        "cases": cases,
    }


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("ledger", type=Path)
    cli.add_argument("plans", type=Path)
    a = cli.parse_args()
    print(json.dumps(run(a.ledger, a.plans), indent=2))
