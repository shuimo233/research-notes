"""Sharp worst expected extra reveals for fair binary triggers on paths and cycles."""

import argparse
from collections import defaultdict
from fractions import Fraction
import json
from pathlib import Path


def budget(choices):
    """For each first-stage ID supply its two lists of forced outside IDs."""
    triggers = defaultdict(list)
    certain = set()
    for u, pair in choices.items():
        if len(pair) != 2:
            raise ValueError(
                "each first-stage ID needs two equally probable alternatives"
            )
        left, right = map(set, pair)
        certain.update(left & right)
        for k, items in enumerate((left - right, right - left)):
            for v in items:
                triggers[v].append((u, k))
    graph = {u: [] for u in choices}
    local = Fraction(len(certain))
    for v, values in triggers.items():
        if v in certain:
            continue
        if len(values) == 1:
            local += Fraction(1, 2)
        elif len(values) == 2:
            (u, i), (w, j) = values
            parity = 1 ^ i ^ j
            graph[u].append((w, parity))
            graph[w].append((u, parity))
            local += 1
        else:
            raise ValueError("a residual target has more than two triggers")
    if any(len(adj) > 2 for adj in graph.values()):
        raise ValueError("the residual signed graph exceeds degree two")
    coloring = {}
    frustrated = 0
    for start in graph:
        if start in coloring:
            continue
        coloring[start] = 0
        queue = [start]
        conflict = False
        while queue:
            u = queue.pop()
            for v, parity in graph[u]:
                predicted = coloring[u] ^ parity
                if v not in coloring:
                    coloring[v] = predicted
                    queue.append(v)
                elif coloring[v] != predicted:
                    conflict = True
        frustrated += conflict
    worst = local - Fraction(frustrated, 2)
    return {
        "worst_extra": str(worst),
        "local_upper": str(local),
        "inconsistent_cycles": frustrated,
        "equal_mass_worlds": [coloring, {u: 1 - k for u, k in coloring.items()}],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "choices",
        type=Path,
        help="JSON mapping each first-stage ID to two lists of forced IDs",
    )
    args = p.parse_args()
    print(json.dumps(budget(json.loads(args.choices.read_bytes())), indent=2))
