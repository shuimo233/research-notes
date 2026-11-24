"""Select a strict reveal cover and certify its worst expected cost against alternative covers."""

import argparse
from collections import Counter
from itertools import combinations
import json
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coupling_clock import canonical, certificate
from forest_cover_budget import forest_bounds


def minimal_covers(vertices, edges):
    for size in range(len(vertices) + 1):
        for subset in combinations(sorted(vertices), size):
            selected = set(subset)
            if all(selected.intersection(e) for e in edges) and all(
                any(selected.intersection(e) == {u} for e in edges) for u in selected
            ):
                yield subset


def estimate(marginals, cover):
    paid = set(cover)
    restricted = canonical(
        {u: [(set(vs) - paid, p) for vs, p in marginals[u]] for u in cover}
    )
    triggers = {}
    for u, choices in restricted.items():
        column = Counter()
        for vs, p in choices:
            for v in vs:
                column[v] += p
        for v, p in column.items():
            triggers.setdefault(v, []).append(p)
    independent = len(paid) + sum(
        1 - prod(1 - p for p in probs) for probs in triggers.values()
    )
    upper = len(paid) + sum(min(1, sum(probs)) for probs in triggers.values())
    if independent == upper:
        return upper, upper, "independence"
    if forest_bounds(restricted) is not None:
        return upper, upper, "forest"
    witness = certificate(restricted)
    if witness["status"] == "witness":
        return upper, upper, "clock"
    return independent, upper, "independence_lower_bound"


def plan(groups):
    marginals = canonical(groups)
    edges = set()
    for u, choices in marginals.items():
        for vs, _ in choices:
            for v in vs:
                if v == u or v not in marginals:
                    raise ValueError("each target must be a different input ID")
                edges.add(tuple(sorted((u, v))))
    options = {c: estimate(marginals, c) for c in minimal_covers(marginals, edges)}
    chosen = min(options, key=lambda c: (options[c][1], len(c), c))
    lo, hi, source = options[chosen]
    others = [v[0] for c, v in options.items() if c != chosen]
    best_alternative = min(others, default=None)
    return {
        "cover": list(chosen),
        "cost_interval": [str(lo), str(hi)],
        "bound_source": source,
        "alternatives_checked": len(others),
        "best_alternative_lower_bound": None
        if best_alternative is None
        else str(best_alternative),
        "certified_optimal": best_alternative is None or hi <= best_alternative,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "groups",
        type=Path,
        help="JSON mapping every token to alternatives [IDs it may force, mass]",
    )
    a = p.parse_args()
    print(json.dumps(plan(json.loads(a.groups.read_bytes())), indent=2))
