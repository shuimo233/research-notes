"""Exhaustively verify block-partition counterexamples on small graphs and their height-two order realizations."""

from collections import Counter, deque
from fractions import Fraction as Q
from itertools import combinations
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_theory_check import raw_optimum, plan_for, clique_case


def path_avoiding(edges, u, x, y):
    todo = deque([(x,)])
    seen = {u, x}
    while todo:
        path = todo.popleft()
        if path[-1] == y:
            return path
        for e in edges:
            if path[-1] not in e:
                continue
            for v in e:
                if v not in seen:
                    seen.add(v)
                    todo.append(path + (v,))
    return ()


def lift(weights, tables):
    # All comparisons are directed from the lower copy of one state to the upper copy of another.
    # Global transitivity is automatic because no strict chain has two steps.
    lifted = [[p / 2 for p in row for _ in (0, 1)] for row in weights]
    comparisons = {}
    for e, grid in tables.items():
        left = [len(set(row)) > 1 for row in grid]
        right = [len(set(col)) > 1 for col in zip(*grid)]
        if not any(left) or not any(right):
            raise ValueError("each relation must depend on both endpoints")
        comparisons[e] = [
            [
                0
                if i % 2 == j % 2 or not (left[i // 2] and right[j // 2])
                else 1
                if i % 2 == 0
                else 2
                for j in range(2 * len(grid[0]))
            ]
            for i in range(2 * len(grid))
        ]
    return lifted, comparisons


def verify_witness(n, edges, u, x, y, path):
    m = len(path)
    outside = set(range(n)) - {u, *path}
    p = Q(1, 100 * m * m)
    z = Q(1, 64 * m)
    rare = Q(1, 64 * max(1, len(outside)) * (m + 1))
    weights = [
        [(1 - z) / 2, z / 2, (1 - z) / 2, z / 2]
        if i == u
        else [1 - p, p]
        if i in path
        else [1 - rare, rare]
        for i in range(n)
    ]
    costs = [
        Q(1, 8) if i == u else Q(1) if i in path else Q(1, 32 * len(outside))
        for i in range(n)
    ]
    valued = []
    profiles = []
    n_lift = 0
    for flip in (False, True):

        def bit(i, j, k):
            if i != u:
                return k
            if j == x:
                return k // 2
            if j == y:
                return (k // 2) ^ flip
            return k % 2

        tables = {
            (i, j): [
                [int(bit(i, j, a) and bit(j, i, b)) for b in range(len(weights[j]))]
                for a in range(len(weights[i]))
            ]
            for i, j in edges
        }
        assert all(len(set(v for row in t for v in row)) == 2 for t in tables.values())
        plan = plan_for(weights, tables, costs)
        val = raw_optimum(weights, tables, costs)
        assert plan.root_value() == val
        valued.append(val)
        laws = []
        for i in range(n):
            q = plan.indices[str(i)]
            neighbor_names = {j for e in edges if i in e for j in e if j != i}
            groups = [{x}, neighbor_names - {x}] if i == u else [neighbor_names]
            for group in groups:
                law = Counter()
                for mask, prob in plan.groups[q]:
                    law[
                        tuple(
                            sorted(j for j in group if mask >> plan.indices[str(j)] & 1)
                        )
                    ] += prob
                laws.append(law)
        profiles.append(laws)
        ps, lifted = lift(weights, tables)
        new = plan_for(ps, lifted, costs)
        assert new.groups == plan.groups and new.root_value() == val
        if n <= 4:
            assert raw_optimum(ps, lifted, costs) == val
        n_lift += 1
    assert profiles[0] == profiles[1] and abs(valued[0] - valued[1]) > Q(1, 4)
    return n_lift


def check():
    if not __debug__:
        raise RuntimeError("enable assertions")
    count = checks = 0
    graphs = set()
    for n in (3, 4, 5):
        complete = list(combinations(range(n), 2))
        candidates = (
            (
                tuple(e for j, e in enumerate(complete) if mask >> j & 1)
                for mask in range(1 << len(complete))
            )
            if n < 5
            else [tuple(complete), ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2), (2, 4))]
        )
        for es in candidates:
            for u in range(n):
                neighbors = {v for e in es if u in e for v in e if v != u}
                for x, y in combinations(sorted(neighbors), 2):
                    path = path_avoiding(es, u, x, y)
                    if not path:
                        continue
                    checks += verify_witness(n, es, u, x, y, path)
                    count += 1
                    graphs.add((n, es))
    for k in range(2, 6):
        for parity in (0, 1):
            _, weights, tables = clique_case(k, parity)
            new, comparisons = lift(weights, tables)
            assert all(len(set(row)) == 1 for row in new)
            assert plan_for(
                new, comparisons, [1] * (k + 1)
            ).root_value() == raw_optimum(weights, tables, [1] * (k + 1))
    return {
        "graphs_with_tested_pair": len(graphs),
        "same_block_neighbor_splits": count,
        "height_two_lifts": checks,
        "equal_weight_parity_lifts": 8,
    }


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
