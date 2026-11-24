"""Exact certificates for a finite regret game with a policy best-response oracle."""

from fractions import Fraction as Q
from itertools import combinations

from two_prior import lower_envelope_peak


def linear_solution(rows, targets):
    """Solve a small square rational system, or return None if singular."""
    matrix = [list(map(Q, row)) + [Q(y)] for row, y in zip(rows, targets, strict=True)]
    n = len(matrix)
    for i in range(n):
        pivot = next((j for j in range(i, n) if matrix[j][i]), None)
        if pivot is None:
            return None
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        value = matrix[i][i]
        matrix[i] = [v / value for v in matrix[i]]
        for j in range(n):
            if i != j and (factor := matrix[j][i]):
                matrix[j] = [
                    v - factor * p for v, p in zip(matrix[j], matrix[i], strict=True)
                ]
    return tuple(row[-1] for row in matrix)


def restricted_dual(vectors):
    m = len(vectors[0])
    if m == 1:
        return min(row[0] for row in vectors), (Q(1),)
    if m == 2:
        value, t = lower_envelope_peak(vectors)
        return value, (1 - t, t)
    cuts = [tuple(int(i == j) for i in range(m)) + (0,) for j in range(m)]
    cuts += [tuple(-x for x in row) + (1,) for row in vectors]
    result = None
    for chosen in combinations(cuts, m):
        hit = linear_solution([(1,) * m + (0,), *chosen], [1] + [0] * m)
        if hit is None:
            continue
        weight, value = hit[:-1], hit[-1]
        if min(weight) < 0 or any(
            sum(p * x for p, x in zip(weight, row)) < value for row in vectors
        ):
            continue
        candidate = (value, weight)
        if result is None or candidate > result:
            result = candidate
    if result is None:
        raise ArithmeticError("no vertex of the restricted regret game")
    return result


def distributions(rows, weight, value):
    active = [
        i for i, v in enumerate(rows) if sum(w * x for w, x in zip(weight, v)) == value
    ]
    m = len(weight)
    for k in range(1, min(len(active), m) + 1):
        for policies in combinations(active, k):
            for models in combinations(range(m), k - 1):
                probs = linear_solution(
                    [(1,) * k, *(tuple(rows[i][z] for i in policies) for z in models)],
                    [1] + [value] * (k - 1),
                )
                if probs is None or min(probs) <= 0:
                    continue
                risks = tuple(
                    sum(p * rows[i][z] for i, p in zip(policies, probs))
                    for z in range(m)
                )
                if max(risks) == value:
                    return tuple(zip(policies, probs)), risks
    raise ArithmeticError("no primal certificate with the verified upper value")


def solve_game(initial, best_response):
    rows_by_value = {}
    for policy, row in initial.items():
        rows_by_value.setdefault(row, policy)
    policies = list(rows_by_value.values())
    rows = list(rows_by_value)
    while True:
        pure = next((i for i, r in enumerate(rows) if not any(r)), None)
        if pure is not None:
            return Q(0), policies[0], ((policies[pure], Q(1)),), rows[pure]
        value, weight = restricted_dual(rows)
        new = best_response(weight)
        lower = sum(p * r for p, r in zip(weight, new, strict=True))
        if lower == value:
            picked, risks = distributions(rows, weight, value)
            return value, weight, tuple((policies[i], p) for i, p in picked), risks
        if lower > value or new in rows:
            raise ArithmeticError("inconsistent best-response certificate")
        policies.append(weight)
        rows.append(new)
