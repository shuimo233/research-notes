"""Run the correlated query planner on finite relation tables from a JSON instance."""

import argparse
from fractions import Fraction as Q
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from mixture_budget_bound import certified_plan
from mixture_query import MixturePlan


def compile_instance(values, edges, weights, conditional, costs=None):
    domains = {u: [(u, k) for k in range(len(xs))] for u, xs in values.items()}
    weights = tuple(map(Q, weights))
    if set(conditional) != set(domains) or any(len(xs) < 2 for xs in domains.values()):
        raise ValueError(
            "each location needs two or more candidates and conditional laws"
        )
    laws = {}
    for u, xs in domains.items():
        rows = conditional[u]
        if len(rows) != len(weights) or any(len(row) != len(xs) for row in rows):
            raise ValueError("one full probability row per latent mode and location")
        laws[u] = [dict(zip(xs, map(Q, row))) for row in rows]
    marginals = {
        u: {x: sum(w * r[x] for w, r in zip(weights, rows)) for x in domains[u]}
        for u, rows in laws.items()
    }
    tables = {}
    for row in edges:
        u, v = row["positions"]
        grid = row["labels"]
        if (u, v) in tables or (v, u) in tables:
            raise ValueError("duplicate relation")
        if len(grid) != len(domains[u]) or any(len(r) != len(domains[v]) for r in grid):
            raise ValueError("relation table shape does not match candidates")
        if any(type(cell) not in (str, bool, int) for r in grid for cell in r):
            raise ValueError("relation labels must be strings, booleans or integers")
        tables[u, v] = grid

    def relation(a, b):
        u, i = a
        v, j = b
        return tables[u, v][i][j]

    svc = RelationInquiry(domains, tables, relation, marginals)
    return MixturePlan(svc, weights, laws, costs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    p.add_argument("--ask", action="store_true")
    p.add_argument("--tolerance", type=Q, default=Q(0))
    args = p.parse_args()
    instance = json.loads(args.instance.read_bytes())
    solver = compile_instance(**instance)
    independent, lower, upper = certified_plan(solver, args.tolerance)
    live, forced, belief = solver.initial()
    initial = (
        solver.optimum(live, forced, belief)[1]
        if independent is None
        else independent.action(independent.counts, forced)[0]
    )
    answer = {
        "method": "posterior" if independent is None else "certified_independent",
        "optimal_budget_interval": [str(lower), str(upper)],
        "first": None if initial is None else solver.names[initial],
    }
    if args.ask:

        def read(u):
            candidates = instance["values"][u]
            formatted = " | ".join(
                f"{i}: {value}" for i, value in enumerate(candidates)
            )
            choice = int(input(f"{u} ({formatted}) > "))
            if not 0 <= choice < len(candidates):
                raise ValueError("selection is outside the candidate list")
            return u, choice

        if independent is None:
            path, answers = solver.execute(read)
        else:
            path, answers, _ = solver.service.execute(read, planner=independent)
        answer["asked"] = path
        answer["labels"] = [dict(positions=e, label=x) for e, x in answers.items()]
    print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
