"""Independently calculate one-parameter budget envelopes without the policy-cut solver."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair_budget_run import cases, select
from pair_budget import PairBudget


def evaluate(curve, t):
    for (a, x), (b, y) in zip(curve, curve[1:]):
        if a <= t <= b:
            return x + (y - x) * (t - a) / (b - a)
    raise ValueError("outside curve")


def simplify(points):
    kept = []
    for point in points:
        c, z = point
        while len(kept) >= 2:
            (a, x), (b, y) = kept[-2:]
            if (y - x) * (c - b) != (z - y) * (b - a):
                break
            kept.pop()
        kept.append(point)
    return tuple(kept)


def literal_envelope(family):
    left, right = family.plan(0), family.plan(1)
    n = len(left.names)
    source = left.indices[family.source]
    zero = ((Q(0), Q(0)), (Q(1), Q(0)))

    @lru_cache(None)
    def solve(live, forced):
        actions = []
        for i in range(n):
            bit = 1 << i
            if live & bit == 0 or (forced & bit == 0 and left.neighbors[i] & live == 0):
                continue
            rest = live ^ bit

            def branches(groups):
                return [(p, solve(rest, (forced | m) & rest)) for m, p in groups]

            a = branches(left.groups[i])
            if i == source:
                b = branches(right.groups[i])
                assert all(len(c) == 2 and c[0][1] == c[-1][1] for _, c in a + b)
                actions.append(
                    (
                        (Q(0), left.cost[i] + sum(p * c[0][1] for p, c in a)),
                        (Q(1), left.cost[i] + sum(p * c[-1][1] for p, c in b)),
                    )
                )
            else:
                ts = sorted({t for _, curve in a for t, _ in curve})
                actions.append(
                    tuple(
                        (t, left.cost[i] + sum(p * evaluate(c, t) for p, c in a))
                        for t in ts
                    )
                )
        if not actions:
            return zero
        ts = sorted({t for c in actions for t, _ in c})
        cuts = set(ts)
        for a, b in zip(ts, ts[1:]):
            endpoints = [(evaluate(c, a), evaluate(c, b)) for c in actions]
            for (al, ar), (bl, br) in combinations(endpoints, 2):
                d, e = al - bl, ar - br
                if d * e < 0:
                    cuts.add(a + (b - a) * d / (d - e))
        return simplify((t, min(evaluate(c, t) for c in actions)) for t in sorted(cuts))

    curve = solve((1 << n) - 1, 0)
    solve.cache_clear()
    return curve


def check(wordnet, semcor, results):
    fixture = Path(__file__).with_name("pair-budget-interior-example.json")
    family = PairBudget(**json.loads(fixture.read_bytes()))
    curve = literal_envelope(family)
    assert curve == (
        (Q(0), Q(5029, 1440)),
        (Q(17, 54), Q(149635, 42768)),
        (Q(1), Q(165887, 47520)),
    )
    assert family.exact_one_cell() == [curve[-1][1], curve[1][1]]
    records = [
        json.loads(line)
        for line in (results / "pair-budget-ledger.jsonl").read_bytes().splitlines()
    ]
    by_task = {tuple(r["task"]): r for r in records}
    assert len(records) == len(by_task)
    report = Counter()
    for key, value, plan in cases(wordnet, semcor):
        if key not in by_task:
            continue
        row = by_task.pop(key)
        family, width = select(plan)
        assert row["source"] == family.source and row["pair"] == [family.x, family.y]
        assert Q(row["width"]) == width
        curve = literal_envelope(family)
        low, high = min(v for _, v in curve), max(v for _, v in curve)
        assert [low, high] == list(map(Q, row["exact_interval"]))
        assert evaluate(curve, Q(1, 2)) == Q(row["center"])
        assert Q(value) == Q(row["truth"])
        assert high - low <= width * min(
            plan.cost[plan.indices[v]] for v in (family.x, family.y)
        )
        report["verified_intervals"] += 1
        report["piecewise_intervals"] += len(curve) > 2
        report["interior_maxima"] += high > max(curve[0][1], curve[-1][1])
    assert not by_task
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "results"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.semcor, a.results), indent=2))
