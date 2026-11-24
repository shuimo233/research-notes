"""Interactive exact controller for separately calibrated pairwise query components."""

import argparse
from fractions import Fraction
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factored_robust import FactoredPlan
from mixture_inquiry import compile_instance


def compile_factored(values, edges, base, components):
    whole = compile_instance(
        values, edges, ["1"], {u: [p] for u, p in base.items()}
    ).service
    local = {}
    for group in components:
        names = tuple(sorted(group["locations"]))
        if names in local:
            raise ValueError("duplicate component")
        local[names] = []
        for model in group["models"]:
            if set(model) != set(names):
                raise ValueError(
                    "a mode must give a law of every location in its component"
                )
            law = {}
            for u, weights in model.items():
                support = whole.service.domains[u]
                if len(weights) != len(support):
                    raise ValueError(
                        "mode probabilities must follow the candidate list"
                    )
                law[u] = {x: Fraction(p) for x, p in zip(support, weights, strict=True)}
            local[names].append(law)
    return FactoredPlan(whole, local)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    p.add_argument("--ask", action="store_true")
    p.add_argument("--seed", type=int)
    a = p.parse_args()
    data = json.loads(a.instance.read_bytes())
    solver = compile_factored(**data)
    result = solver.solve()
    result["compulsory"] = solver.sources
    if a.ask:

        def ask(u):
            values = data["values"][u]
            options = " | ".join(f"{i}: {value}" for i, value in enumerate(values))
            idx = int(input(f"{u} ({options}) > "))
            if not 0 <= idx < len(values):
                raise ValueError("selection is outside the candidate list")
            return u, idx

        asked, labels = solver.execute(result, ask, Random(a.seed))
        result["asked"] = asked
        result["labels"] = [dict(positions=e, label=v) for e, v in labels.items()]
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
