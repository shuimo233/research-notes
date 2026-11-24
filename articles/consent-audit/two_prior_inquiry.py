"""Plan and execute finite pairwise queries under two possible unit-cost priors."""

import argparse
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mixture_inquiry import compile_instance
from two_prior import controller_for, draw


def compile_two_prior(values, edges, conditional):
    if set(values) != set(conditional) or any(
        len(rows) != 2 for rows in conditional.values()
    ):
        raise ValueError("supply exactly two conditional rows for every location")
    modes = [
        compile_instance(
            values, edges, ["1"], {u: [rows[z]] for u, rows in conditional.items()}
        )
        for z in range(2)
    ]
    weights = [
        {
            u: {x: p[0] for x, p in law.items()}
            for u, law in zip(mode.locations, mode.likelihood)
        }
        for mode in modes
    ]
    return controller_for(modes[0].service, modes[1].service, weights)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    p.add_argument("--ask", action="store_true")
    p.add_argument("--seed", type=int)
    a = p.parse_args()
    data = json.loads(a.instance.read_bytes())
    solver = compile_two_prior(**data)
    answer = solver.solve()
    if a.ask:

        def ask(u):
            values = data["values"][u]
            shown = " | ".join(f"{i}: {value}" for i, value in enumerate(values))
            idx = int(input(f"{u} ({shown}) > "))
            if not 0 <= idx < len(values):
                raise ValueError("selection is outside the candidate list")
            return (u, idx)

        selected = draw(answer["policies"], Random(a.seed))
        path, labels = solver.execute(selected, ask)
        answer.update(
            selected=selected,
            asked=path,
            labels=[dict(positions=e, label=v) for e, v in labels.items()],
        )
    print(json.dumps(answer, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
