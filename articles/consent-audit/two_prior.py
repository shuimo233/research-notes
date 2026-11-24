"""Solve two-scenario minimax regret for exact finite pairwise queries."""

from collections import Counter
from fractions import Fraction as Q
from itertools import combinations
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_information import actual_cost
from mixture_query import MixturePlan
from prior_reuse import common_structure


def lower_envelope_peak(costs):
    """Maximum lower envelope of affine regret lines, evaluated at their intersections."""
    points = {Q(0), Q(1)}
    for (a, b), (c, d) in combinations(costs, 2):
        denominator = (b - a) - (d - c)
        if denominator:
            t = (c - a) / denominator
            if 0 < t < 1:
                points.add(t)
    return max((min((1 - t) * a + t * b for a, b in costs), t) for t in points)


class TwoPrior:
    """Complete policies after a one-time choice, with rational primal and dual witnesses."""

    def __init__(self, old, new, conditional, *, observe_values=True):
        common_structure(old.plan, new.plan)
        if (
            old.service.domains != new.service.domains
            or old.service.order != new.service.order
            or any(
                old.service.tables[e].cells != new.service.tables[e].cells
                for e in old.service.order
            )
            or old.members != new.members
        ):
            raise ValueError(
                "both models must share candidate values and relation tables"
            )
        if set(conditional) != set(old.plan.names):
            raise ValueError("conditional laws must match the planned locations")
        for i, u in enumerate(old.plan.names):
            location = old.members[i][0]
            rows = conditional[u]
            if len(rows) != 2:
                raise ValueError("two complete positive conditional laws are required")
            for service, law in zip((old, new), rows, strict=True):
                if set(law) != set(old.service.domains[location]) or any(
                    Q(p) <= 0 for p in law.values()
                ):
                    raise ValueError("conditional laws must preserve candidate support")
                group = Counter()
                for x, p in law.items():
                    group[old.masks[location][x]] += Q(p)
                if dict(group) != dict(service.plan.groups[i]):
                    raise ValueError(
                        "conditional laws must reproduce each endpoint's trigger profile"
                    )
        self.services = (old, new)
        self.conditional = conditional
        self.observe_values = observe_values
        self.budgets = tuple(s.plan.root_value() for s in self.services)
        self.costs = dict(zip(old.plan.names, old.plan.cost))
        self.oracles = {}
        a, b = old.plan, new.plan
        self.endpoints = {
            Q(0): (Q(0), actual_cost(a, b) - self.budgets[1]),
            Q(1): (actual_cost(b, a) - self.budgets[0], Q(0)),
        }

    def _oracle(self, t):
        if not 0 < t < 1:
            raise ValueError("use endpoint controllers for degenerate mixtures")
        if t not in self.oracles:
            self.oracles[t] = MixturePlan(
                self.services[0],
                (1 - t, t),
                self.conditional,
                self.costs,
                observe_values=self.observe_values,
            )
        return self.oracles[t]

    def regrets_at(self, t):
        if t in self.endpoints:
            return self.endpoints[t]
        model = self._oracle(t)
        return tuple(model.cost_in_mode(z) - v for z, v in enumerate(self.budgets))

    def solve(self):
        x = self.endpoints[0][1]
        y = self.endpoints[1][0]
        endpoint_mix = x * y / (x + y) if x + y else Q(0)
        costs = dict(self.endpoints)
        while True:
            bound, t = lower_envelope_peak(costs.values())
            if not bound:
                policy = next(w for w, r in costs.items() if max(r) == 0)
                chosen = [(policy, Q(1))]
                break
            values = self.regrets_at(t)
            oracle = (1 - t) * values[0] + t * values[1]
            assert oracle <= bound
            if oracle < bound:
                assert t not in costs
                costs[t] = values
                continue
            cost = self._oracle(t).optimum(*self._oracle(t).initial())[0]
            assert oracle == cost - ((1 - t) * self.budgets[0] + t * self.budgets[1])
            active = [
                (w, b - a)
                for w, (a, b) in costs.items()
                if (1 - t) * a + t * b == bound
            ]
            equal = next((w for w, s in active if not s), None)
            if equal is not None:
                chosen = [(equal, Q(1))]
            else:
                a, l = next((w, s) for w, s in active if s < 0)
                b, h = next((w, s) for w, s in active if s > 0)
                p = h / (h - l)
                chosen = [(a, p), (b, 1 - p)]
            break
        averaged = tuple(sum(p * costs[w][z] for w, p in chosen) for z in range(2))
        assert all(r >= 0 for r in averaged) and max(averaged) == bound <= endpoint_mix
        return dict(
            worst_regret=bound,
            reference_regret=endpoint_mix,
            environment_weight=t,
            endpoint_regrets=tuple(self.endpoints[Q(z)] for z in (0, 1)),
            conditional_regrets=averaged,
            policies=[
                dict(prior=w, probability=p, regrets=costs[w]) for w, p in chosen
            ],
            candidate_count=len(costs),
        )

    def execute(self, nominal, ask):
        if nominal in self.endpoints:
            seq, labels, _ = self.services[int(nominal)].execute(ask)
            return seq, labels
        return self._oracle(nominal).execute(ask)

    def clear(self):
        for oracle in self.oracles.values():
            oracle.clear()


def controller_for(old, new, weights, **options):
    conditions = {
        name: [w[old.members[i][0]] for w in weights]
        for i, name in enumerate(old.plan.names)
    }
    return TwoPrior(old, new, conditions, **options)


def draw(policies, rng):
    if len(policies) == 1:
        return policies[0]["prior"]
    p = policies[0]["probability"]
    return policies[0 if rng.randrange(p.denominator) < p.numerator else 1]["prior"]
