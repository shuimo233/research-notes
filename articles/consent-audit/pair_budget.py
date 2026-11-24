"""Bound the optimal query budget when two outgoing trigger bits have unknown dependence."""

import argparse
from fractions import Fraction as Q
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_query_plan import scopes
from frontier_plan import FrontierPlan
from frontier_information import actual_cost


class PairBudget:
    """One source occurrence, a full law at every other vertex, two overlapping views at the source."""

    def __init__(self, vertices, edges, choices, source, pair, strata, costs=None):
        self.counts = dict.fromkeys(vertices, 1)
        self.edges = edges
        self.source = source
        self.choices = choices
        self.costs = costs
        self.x, self.y = pair
        if (
            len(vertices) != len(self.counts)
            or source not in self.counts
            or set(choices) != set(vertices) - {source}
        ):
            raise ValueError(
                "name each vertex once and supply the other vertices' complete laws"
            )
        parts = scopes(self.counts, edges)[source]
        neighbors = {v for part in parts for v in part}
        if self.x == self.y or not {self.x, self.y} <= neighbors:
            raise ValueError("choose two different neighbors of the source")
        self.same_block = any({self.x, self.y} <= set(part) for part in parts)
        self.cells = []
        seen = set()
        for record in strata:
            rest = frozenset(record["rest"])
            if rest in seen or not rest <= neighbors - {self.x, self.y}:
                raise ValueError("invalid or repeated conditioning mask")
            seen.add(rest)
            mass, a, b = (Q(record[k]) for k in ("mass", "x_mass", "y_mass"))
            if mass <= 0 or not (0 <= a <= mass and 0 <= b <= mass):
                raise ValueError(
                    "each flag mass must lie between zero and its stratum mass"
                )
            lo, hi = max(0, a + b - mass), min(a, b)
            self.cells.append((rest, mass, a, b, lo, hi))
        if sum(row[1] for row in self.cells) != 1:
            raise ValueError("stratum masses must add to one")
        self.ambiguous = sum(lo < hi for *_, lo, hi in self.cells)

    def plan(self, fraction):
        """Interpolate within each cell at the same relative position."""
        fraction = Q(fraction)
        if not 0 <= fraction <= 1:
            raise ValueError("interpolation fraction outside [0,1]")
        return self._complete(lo + (hi - lo) * fraction for *_, lo, hi in self.cells)

    def independent_plan(self):
        return self._complete(a * b / mass for _, mass, a, b, _, _ in self.cells)

    def _complete(self, both_masses):
        outcomes = []
        for (rest, mass, a, b, _, _), both in zip(self.cells, both_masses, strict=True):
            for extra, p in [
                ((), mass - a - b + both),
                ((self.x,), a - both),
                ((self.y,), b - both),
                ((self.x, self.y), both),
            ]:
                if p:
                    outcomes.append((sorted(rest.union(extra)), p))
        return FrontierPlan(
            self.counts, {**self.choices, self.source: outcomes}, self.edges, self.costs
        )

    def forecast(self):
        center = self.plan(Q(1, 2))
        value = center.root_value()
        unit = min(center.cost[center.indices[v]] for v in (self.x, self.y))
        radius = (
            unit * sum(hi - lo for *_, lo, hi in self.cells) / 2
            if self.same_block
            else Q(0)
        )
        answer = dict(
            center=value,
            guaranteed_radius=radius,
            guaranteed_interval=[
                max(Q(0), value - radius),
                min(sum(center.cost), value + radius),
            ],
        )
        if radius == 0:
            answer["exact_interval"] = [value, value]
        elif self.ambiguous == 1:
            answer["exact_interval"] = self.exact_one_cell()
        if "exact_interval" in answer:
            a, b = answer["exact_interval"]
            answer.update(interval_midpoint=(a + b) / 2, minimax_radius=(b - a) / 2)
        return answer

    def exact_one_cell(self):
        """A policy has an affine cost across this line of completions. The optimum is their lower envelope."""
        if self.ambiguous != 1:
            raise ValueError("exact envelope requires one ambiguous conditioning mask")
        endpoints = [self.plan(0), self.plan(1)]
        low = min(p.root_value() for p in endpoints)

        def support(plan):
            a, b = (actual_cost(plan, truth) for truth in endpoints)
            return a, b - a

        lines = {support(p) for p in endpoints}
        while True:
            points = {Q(0), Q(1)}
            for (a, b), (c, d) in combinations(lines, 2):
                if b != d:
                    t = (c - a) / (b - d)
                    if 0 < t < 1:
                        points.add(t)
            upper, t = max((min(a + b * t for a, b in lines), t) for t in points)
            p = self.plan(t)
            if p.root_value() == upper:
                return [low, upper]
            line = support(p)
            if line in lines or line[0] + line[1] * t != p.root_value():
                raise RuntimeError("invalid affine policy certificate")
            lines.add(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    family = PairBudget(**json.loads(parser.parse_args().instance.read_bytes()))
    print(json.dumps(family.forecast(), default=str, indent=2))
