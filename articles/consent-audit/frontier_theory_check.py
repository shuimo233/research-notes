"""Independent decision trees for pairwise table queries. Exhaustive low-order checks and explicit witnesses."""

from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
from random import Random
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_plan import FrontierPlan, star
from block_query_plan import compile_blocks, marginal_profiles


def raw_optimum(weights, tables, costs):
    """Scalar DP over literal observed values; tests every unresolved endpoint, without mandatory-first or splitting."""
    n = len(weights)

    @lru_cache(None)
    def labels(edge, x, y):
        grid = tables[edge]
        a, b = edge
        return frozenset(
            grid[i][j]
            for i in (range(len(weights[a])) if x < 0 else (x,))
            for j in (range(len(weights[b])) if y < 0 else (y,))
        )

    @lru_cache(None)
    def value(state):
        candidates = set()
        for a, b in tables:
            if len(labels((a, b), state[a], state[b])) > 1:
                if state[a] < 0:
                    candidates.add(a)
                if state[b] < 0:
                    candidates.add(b)
        if not candidates:
            return Q(0)
        return min(
            costs[i]
            + sum(
                p * value(state[:i] + (k,) + state[i + 1 :])
                for k, p in enumerate(weights[i])
            )
            for i in candidates
        )

    return value((-1,) * n)


def plan_for(weights, tables, costs):
    names = list(map(str, range(len(weights))))
    choices = {}
    edges = []
    for i, (u, ps) in enumerate(zip(names, weights)):
        groups = []
        for k, p in enumerate(ps):
            out = []
            for (a, b), grid in tables.items():
                if i == a and len(set(grid[k])) > 1:
                    out.append(names[b])
                if i == b and len({row[k] for row in grid}) > 1:
                    out.append(names[a])
            groups.append((out, p))
        choices[u] = groups
    for (a, b), grid in tables.items():
        if len({x for row in grid for x in row}) > 1:
            edges.append((names[a], names[b]))
    return FrontierPlan(
        dict.fromkeys(names, 1), choices, edges, dict(zip(names, costs))
    )


def literal_table(mask):
    return tuple(tuple((mask >> (2 * i + j)) & 1 for j in range(2)) for i in range(2))


def clique_case(k, parity):
    masks = [s for s in range(1 << k) if s.bit_count() % 2 == parity]
    weights = [[Q(1, len(masks))] * len(masks)] + [[Q(1, 2)] * 2 for _ in range(k)]
    tables = {(a, b): literal_table(8) for a, b in combinations(range(1, k + 1), 2)}
    for j in range(k):
        tables[0, j + 1] = tuple((0, (s >> j) & 1) for s in masks)
    return masks, weights, tables


def check():
    if not __debug__:
        raise RuntimeError("enable assertions")
    rng = Random(9081)
    counts = Counter()
    for topology in (((0, 1), (1, 2)), ((0, 1), (1, 2), (0, 2))):
        for masks in product(range(1, 15), repeat=len(topology)):
            tables = {edge: literal_table(mask) for edge, mask in zip(topology, masks)}
            weights = [[Q(1, 3), Q(2, 3)], [Q(1, 2)] * 2, [Q(2, 3), Q(1, 3)]]
            costs = [Q(1), Q(3, 2), Q(2)]
            raw = raw_optimum(weights, tables, costs)
            planner = plan_for(weights, tables, costs)
            v = planner.root_value()
            assert raw == v
            block = compile_blocks(**marginal_profiles(planner))
            assert block.root_value() == raw
            counts["path_tables" if len(topology) == 2 else "triangle_tables"] += 1
    for d in range(1, 7):
        for _ in range(8):
            masks = [0, (1 << d) - 1, rng.randrange(1 << d), rng.randrange(1 << d)]
            center = [Q(1, 10), Q(3, 10), Q(2, 10), Q(4, 10)]
            ps = [Q(rng.randrange(1, 9), 9) for _ in range(d)]
            weights = [center] + [[1 - p, p] for p in ps]
            costs = [Q(rng.randrange(1, 7)) for _ in weights]
            tables = {
                (0, j + 1): tuple((0, (s >> j) & 1) for s in masks) for j in range(d)
            }
            leaves = {
                str(j): (
                    costs[j + 1],
                    ps[j],
                    sum(p for s, p in zip(masks, center) if (s >> j) & 1),
                )
                for j in range(d)
            }
            assert Q(star(costs[0], leaves)["cost"]) == raw_optimum(
                weights, tables, costs
            )
            counts["heterogeneous_stars"] += 1
    parity_values = {}
    for k in range(2, 7):
        vals = []
        laws = []
        for side in (0, 1):
            masks, weights, tables = clique_case(k, side)
            raw = raw_optimum(weights, tables, [Q(1)] * (k + 1))
            vals.append(raw)
            assert plan_for(weights, tables, [Q(1)] * (k + 1)).root_value() == raw
            contains_full = Q(int((1 << k) - 1 in masks), len(masks))
            q = Q(1, 2)
            assert raw == k + 1 - max(q**k, q ** (k - 1) * (1 - contains_full))
            laws.append([Counter(m & ~(1 << j) for m in masks) for j in range(k)])
        assert laws[0] == laws[1] and abs(vals[0] - vals[1]) == Q(1, 4 ** (k - 1))
        parity_values[k] = list(map(str, vals))
    cycle_values = {}
    for n in range(3, 9):
        m = n - 1
        p = Q(1, 100 * m * m)
        weights = [[Q(1, 2)] * 2] + [[1 - p, p] for _ in range(m)]
        costs = [Q(1, 8)] + [Q(1)] * m
        tables = {(i, i + 1): literal_table(8) for i in range(n - 1)}
        vals = []
        for flip in (False, True):
            tables[0, n - 1] = literal_table(2 if flip else 8)
            raw = raw_optimum(weights, tables, costs)
            assert raw == plan_for(weights, tables, costs).root_value()
            vals.append(raw)
        assert abs(vals[0] - vals[1]) > Q(1, 4)
        cycle_values[n] = list(map(str, vals))
    print(
        json.dumps(
            {
                **counts,
                "clique_parity_costs": parity_values,
                "positive_cost_cycle_witnesses": cycle_values,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    check()
