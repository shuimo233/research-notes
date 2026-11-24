"""Check simultaneous local union upper bounds for fair binary sources with pair triggers."""

import argparse
from collections import defaultdict
import json
from pathlib import Path


def certify(choices):
    certain = set()
    events = defaultdict(list)
    for u, parts in choices.items():
        if len(parts) != 2:
            raise ValueError("each source needs two equally probable alternatives")
        a, b = map(set, parts)
        certain.update(a & b)
        for i, targets in enumerate((a - b, b - a)):
            for v in targets:
                events[v].append((u, i))
    adjacent = {u: [] for u in choices}
    wide = []
    for v, inputs in events.items():
        if v in certain or len(inputs) < 2:
            continue
        if len(inputs) > 2:
            wide.append(v)
            continue
        (i, a), (j, b) = inputs
        parity = 1 ^ a ^ b
        adjacent[i].append((j, parity, v))
        adjacent[j].append((i, parity, v))
    paint = {}
    parent = {}

    def path(u):
        result = set()
        while u in parent:
            u, edge = parent[u]
            result.add(edge)
        return result

    for start in adjacent:
        if start in paint:
            continue
        paint[start] = 0
        queue = [start]
        while queue:
            u = queue.pop()
            for v, p, edge in adjacent[u]:
                required = paint[u] ^ p
                if v not in paint:
                    paint[v] = required
                    parent[v] = (u, edge)
                    queue.append(v)
                elif paint[v] != required:
                    cycle = path(u) ^ path(v) ^ {edge}
                    return {
                        "status": "unattainable",
                        "odd_parity_obstruction": [target for target in events if target in cycle],
                    }
    if wide:
        return {"status": "outside_pair_test", "higher_arity_targets": wide}
    return {
        "status": "attainable",
        "equal_mass_worlds": [paint, {u: 1 - k for u, k in paint.items()}],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "choices",
        type=Path,
        help="JSON mapping each source ID to two lists of triggered target IDs",
    )
    a = p.parse_args()
    print(json.dumps(certify(json.loads(a.choices.read_bytes())), indent=2))
