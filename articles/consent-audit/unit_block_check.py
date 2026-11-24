"""Check unit-cost block necessity against decision trees over literal relation tables."""

from collections import Counter
from fractions import Fraction as Q
from itertools import combinations, product
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_boundary_check import lift, path_avoiding
from frontier_theory_check import plan_for, raw_optimum


def witness(n, edges, u, path, flip, compact=False):
    m = len(path)
    inside = {u, *path}
    outside = {i for e in edges for i in e if i not in inside}
    t = len(outside)
    p = Q(1, 4 if compact else 100 * m * m)
    z = Q(1, 100 * m)
    rare = Q(1, 100 * m * max(1, t))
    states, weights = [], []
    for i in range(n):
        if i == u:
            states.append(
                list(product(range(2), range(2), (0,) if compact else range(2)))
            )
            weights.append(
                [
                    Q(1, 4) if compact else (z if gate else 1 - z) / 4
                    for _, _, gate in states[-1]
                ]
            )
        elif i in path:
            states.append([0, 1])
            weights.append([1 - p, p])
        elif i in outside:
            states.append(list(product(range(2), repeat=2)))
            weights.append([(rare if b else 1 - rare) / 2 for _, b in states[-1]])
        else:
            states.append([0])
            weights.append([Q(1)])

    def answer(i, a, j, b):
        if i in outside or j in outside:
            if i in outside and j in outside:
                return a[0] ^ b[0]
            if j in outside:
                i, a, j, b = j, b, i, a
            return a[0] ^ (a[1] & (b[2] if j == u else b))
        if u not in (i, j):
            return a & b
        if j == u:
            i, a, j, b = j, b, i, a
        x, h, gate = a
        if j in (path[0], path[-1]):
            return h ^ ((x ^ (flip and j == path[-1])) & b)
        return gate & b

    tables = {
        (i, j): [[answer(i, a, j, b) for b in states[j]] for a in states[i]]
        for i, j in edges
    }
    return weights, tables, t


def visible(plan, n, edges, u, x, y):
    """Test every group allowed in any partition separating x and y."""
    laws = {}
    for i in range(n):
        nb = sorted({v for e in edges if i in e for v in e if v != i})
        groups = (
            (
                s
                for k in range(len(nb) + 1)
                for s in combinations(nb, k)
                if x not in s or y not in s
            )
            if i == u
            else [nb]
        )
        for s in groups:
            group_mask = sum(1 << plan.indices[str(v)] for v in s)
            law = Counter()
            for mask, prob in plan.groups[plan.indices[str(i)]]:
                law[mask & group_mask] += prob
            laws[i, tuple(s)] = law
    return laws


def check_pair(n, edges, u, path):
    m = len(path)
    values, profiles = [], []
    for flip in (False, True):
        weights, tables, t = witness(n, edges, u, path, flip)
        d = 400 * m * m * max(1, t)
        for ps in weights:
            assert all((q * d).denominator == 1 and q > 0 for q in ps) and sum(ps) == 1
        plan = plan_for(weights, tables, [1] * n)
        value = raw_optimum(weights, tables, [1] * n)
        assert value == plan.root_value()
        base_path = 1 + (m - 1) // 2 if flip else Q(m // 2 + 2 + (m - 2) // 2, 2)
        err = value - (1 + t + base_path)
        assert 0 <= err <= Q(3, 100)
        profiles.append(visible(plan, n, edges, u, path[0], path[-1]))
        values.append(value)
        ps, order = lift(weights, tables)
        order_plan = plan_for(ps, order, [1] * n)
        assert order_plan.groups == plan.groups and order_plan.root_value() == value
        if n <= 4:
            assert raw_optimum(ps, order, [1] * n) == value
    assert profiles[0] == profiles[1]
    assert (values[0] - values[1]) * (-1) ** m >= Q(47, 100)
    return values


def uniform_triangle():
    edges = ((0, 1), (0, 2), (1, 2))
    values = []
    for flip in (False, True):
        weights, tables, _ = witness(3, edges, 0, (1, 2), flip, compact=True)
        clones = [
            [j for j, q in enumerate(ps) for _ in range(int(4 * q))] for ps in weights
        ]
        assert all(len(ids) == 4 for ids in clones)
        grid = {
            (i, j): [[tab[a][b] for b in clones[j]] for a in clones[i]]
            for (i, j), tab in tables.items()
        }
        equal = [[Q(1, 4)] * 4 for _ in range(3)]
        ps, order = lift(equal, grid)
        assert all(row == [Q(1, 8)] * 8 for row in ps)
        v = raw_optimum(ps, order, [1] * 3)
        assert (
            v
            == raw_optimum(weights, tables, [1] * 3)
            == raw_optimum(equal, grid, [1] * 3)
        )
        values.append(v)
    assert values[0] != values[1]
    return list(map(str, values))


def check():
    if not __debug__:
        raise RuntimeError("enable assertions")
    count = 0
    min_gap = Q(1)
    for n in (3, 4, 5):
        all_edges = list(combinations(range(n), 2))
        samples = (
            (
                tuple(e for j, e in enumerate(all_edges) if mask >> j & 1)
                for mask in range(1 << len(all_edges))
            )
            if n < 5
            else [tuple(all_edges), ((0, 1), (1, 2), (2, 3), (0, 3), (0, 2), (2, 4))]
        )
        for edges in samples:
            for u in range(n):
                neighbors = sorted({v for e in edges if u in e for v in e if v != u})
                for x, y in combinations(neighbors, 2):
                    path = path_avoiding(edges, u, x, y)
                    if path:
                        a, b = check_pair(n, edges, u, path)
                        count += 1
                        min_gap = min(min_gap, abs(a - b))
    edges = ((0, 1), (0, 2), (0, 3), (1, 2), (2, 3), (0, 4), (2, 4), (3, 5), (4, 5))
    six = check_pair(6, edges, 0, (1, 2, 3))
    assert six == [Q(1313817122699, 291600000000), Q(874995288392699, 174960000000000)]
    return dict(
        small_graph_pair_checks=count,
        minimum_small_graph_gap=str(min_gap),
        six_vertex_costs=list(map(str, six)),
        uniform_eight_state_order_triangle=uniform_triangle(),
    )


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
