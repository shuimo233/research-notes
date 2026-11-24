"""Bound the value of adapting by revealing the latent mode in a relaxed problem."""

from fractions import Fraction as Q
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_information import actual_cost
from frontier_plan import FrontierPlan, bits


def independent_policy_certificate(solver):
    """Return a root-marginal policy, its cost, and a perfect-information lower bound."""
    names = solver.names
    edges = [
        (u, names[j])
        for i, u in enumerate(names)
        for j in bits(solver.neighbors[i])
        if i < j
    ]
    variables = dict.fromkeys(names, 1)
    prices = dict(zip(names, solver.cost))
    weights = solver.weights

    def build(mode):
        choices = {}
        for u, groups in zip(names, solver.compact):
            choices[u] = [
                (
                    tuple(names[j] for j in bits(mask)),
                    sum(w * p for w, p in zip(weights, law))
                    if mode is None
                    else law[mode],
                )
                for mask, law in groups
            ]
        return FrontierPlan(variables, choices, edges, prices)

    policy = build(None)
    lower = Q(0)
    upper = Q(0)
    for z, w in enumerate(weights):
        conditional = build(z)
        lower += w * conditional.root_value()
        upper += w * actual_cost(policy, conditional)
    return policy, lower, upper


def certified_plan(solver, tolerance=0):
    """Use a certified product policy when possible, else solve the correlated problem."""
    tolerance = Q(tolerance)
    if tolerance < 0:
        raise ValueError("the expected-cost tolerance must be nonnegative")
    policy, lower, upper = independent_policy_certificate(solver)
    if upper - lower <= tolerance:
        return policy, lower, upper
    value = solver.optimum(*solver.initial())[0]
    return None, value, value
