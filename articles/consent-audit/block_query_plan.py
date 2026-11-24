"""Compile exact adaptive-query plans from within-block trigger profiles only."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_plan import FrontierPlan


def scopes(counts, edges):
    """Neighbor classes in the same component after deleting one occurrence of the source."""
    graph = {u: set() for u in counts}
    for u, v in edges:
        if u == v:
            raise ValueError("within-type edges require separate occurrence types")
        graph[u].add(v)
        graph[v].add(u)
    result = {}
    for u, targets in graph.items():
        if counts[u] > 1:
            result[u] = [tuple(sorted(targets))] if targets else []
            continue
        pending = set(targets)
        parts = []
        while pending:
            stack = [min(pending)]
            reached = {u}
            while stack:
                v = stack.pop()
                if v in reached:
                    continue
                reached.add(v)
                stack.extend(graph[v] - reached)
            local = pending & reached
            pending -= local
            parts.append(tuple(sorted(local)))
        result[u] = sorted(parts)
    return result


def compile_blocks(multiplicities, edges, profiles, costs=None):
    """For each type supply one categorical trigger distribution per structural scope."""
    expected = scopes(multiplicities, edges)
    choices = {}
    if set(profiles) != set(expected):
        raise ValueError("missing or extra type profiles")
    for u, parts in expected.items():
        supplied = {}
        cuts = {Q(0), Q(1)}
        for record in profiles[u]:
            scope = tuple(sorted(record["scope"]))
            if scope in supplied:
                raise ValueError("duplicate scope")
            end = Q(0)
            cells = []
            seen = set()
            for targets, p in record["outcomes"]:
                t = frozenset(targets)
                p = Q(p)
                if not t <= set(scope) or p <= 0 or t in seen:
                    raise ValueError("invalid local outcome")
                seen.add(t)
                end += p
                cells.append((end, t))
                cuts.add(end)
            if end != 1:
                raise ValueError("each scope needs a probability distribution")
            supplied[scope] = cells
        if set(parts) != set(supplied):
            raise ValueError("profile scopes must match the structural partition")
        # Align the per-scope quantile intervals on one uniform variable. Every local law
        # is preserved. The block invariance theorem allows this artificial coupling.
        ordered = sorted(cuts)
        out = Counter()
        cursor = {scope: 0 for scope in parts}
        for a, b in zip(ordered, ordered[1:]):
            mask = set()
            for scope in parts:
                cells = supplied[scope]
                i = cursor[scope]
                while cells[i][0] <= a:
                    i += 1
                cursor[scope] = i
                mask.update(cells[i][1])
            out[tuple(sorted(mask))] += b - a
        choices[u] = list(out.items())
    return FrontierPlan(multiplicities, choices, edges, costs)


def marginal_profiles(planner):
    names = planner.names
    edges = [
        (u, names[j])
        for i, u in enumerate(names)
        for j in range(i + 1, len(names))
        if planner.neighbors[i] >> j & 1
    ]
    counts = dict(zip(names, planner.counts))
    parts = scopes(counts, edges)
    profiles = {}
    for i, u in enumerate(names):
        fields = []
        for scope in parts[u]:
            scope_mask = sum(1 << planner.indices[v] for v in scope)
            fields.append(
                {
                    "scope": list(scope),
                    "outcomes": [
                        [[v for v in scope if mask >> planner.indices[v] & 1], str(p)]
                        for mask, p in planner.projections(i, scope_mask)
                    ],
                }
            )
        profiles[u] = fields
    return {
        "multiplicities": counts,
        "edges": edges,
        "profiles": profiles,
        "costs": dict(zip(names, map(str, planner.cost))),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    a = p.parse_args()
    planner = compile_blocks(**json.loads(a.instance.read_bytes()))
    value, first = planner.optimum(planner.counts, 0)
    print(
        json.dumps(
            {
                "expected": str(value),
                "first_type": None if first is None else planner.names[first],
            },
            indent=2,
        )
    )
