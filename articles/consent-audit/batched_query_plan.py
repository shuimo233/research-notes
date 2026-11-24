"""Exact query planning that combines all presently compulsory reads in one Bellman update."""

import argparse
from collections import Counter
from fractions import Fraction as Q
import json
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_plan import FrontierPlan, bits


class BatchedPlan(FrontierPlan):
    def after_cost(self, i, counts, forced):
        if not forced >> i & 1 or sum(counts[j] for j in bits(forced)) < 2:
            return super().after_cost(i, counts, forced)
        return self.batch_cost(counts, forced)

    def batch_cost(self, counts, forced):
        sources = tuple(bits(forced))
        remaining = tuple(0 if forced >> i & 1 else n for i, n in enumerate(counts))
        expected = sum(counts[i] * self.cost[i] for i in sources)
        for block, local in self.parts(remaining):
            if block.bit_count() == 1:
                j = next(bits(block))
                skip = prod((1 - self.rates[i].get(j, 0)) ** counts[i] for i in sources)
                expected += counts[j] * self.cost[j] * (1 - skip)
                continue
            mass = {0: Q(1)}
            for i in sources:
                if not self.neighbors[i] & block:
                    continue
                projected = self.projections(i, block)
                for _ in range(counts[i]):
                    next_mass = Counter()
                    for known, p in mass.items():
                        for seen, q in projected:
                            next_mass[known | seen] += p * q
                    mass = next_mass
            expected += sum(
                p * self.optimum(local, mask)[0] for mask, p in mass.items()
            )
        return expected


def batched(model):
    names = model.names
    counts = dict(zip(names, model.counts))
    costs = dict(zip(names, model.cost))
    choices = {
        u: [(tuple(names[j] for j in bits(mask)), p) for mask, p in row]
        for u, row in zip(names, model.groups)
    }
    edges = [
        (u, names[j])
        for i, u in enumerate(names)
        for j in bits(model.neighbors[i])
        if i < j
    ]
    return BatchedPlan(counts, choices, edges, costs)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    args = p.parse_args()
    model = BatchedPlan(**json.loads(args.instance.read_bytes()))
    value, i = model.optimum(model.counts, 0)
    print(
        json.dumps(
            dict(expected=str(value), first=None if i is None else model.names[i]),
            indent=2,
        )
    )
