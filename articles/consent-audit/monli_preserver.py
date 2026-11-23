"""Exact evidence storage versus fallback calls for a finite batch with a frozen fallback."""

import argparse
from collections import defaultdict
import csv
from functools import lru_cache
from graphlib import TopologicalSorter
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from monli_scope import LexicalEvidence, opposite
from monli_scope_score import from_bits
from monli_direction_score import choose_direction


def requirements(edges, queries):
    """queries contains (left term, right term, fallback direction); no reference answers."""
    tuple(TopologicalSorter(edges).static_order())
    labels = [line for values in edges.values() for line in values.values()]
    if len(set(labels)) != len(labels):
        raise ValueError("each stored edge needs its own ID")

    @lru_cache(None)
    def paths(a, b):
        if a == b:
            return (frozenset(),)
        result = []
        for n, line in edges.get(a, {}).items():
            for suffix in paths(n, b):
                result.append(suffix | {line})
                if len(result) > 20000:
                    raise ValueError("path enumeration limit reached")
        return tuple(result)

    demand = {}
    for a, b, fallback in queries:
        if fallback not in ("forward", "reverse", "abstain"):
            raise ValueError("invalid fallback")
        if a == b:
            continue
        forward, reverse = paths(a, b), paths(b, a)
        if not forward and not reverse:
            continue
        assert not (forward and reverse)
        term_pair = (a, b) if forward else (b, a)
        output = "reverse" if forward else "forward"
        options, weight, must = demand.get(term_pair, (forward or reverse, 0, False))
        demand[term_pair] = options, weight + 1, must or output != fallback
    return demand


def retain_best(table, cost, value, lines):
    old = table.get(cost)
    if old is None or value > old[0] or (value == old[0] and lines < old[1]):
        table[cost] = value, lines


def optimal_frontier(demand):
    neighbors = defaultdict(set)
    by_edge = defaultdict(list)
    for routes, weight, must in demand.values():
        involved = set().union(*routes)
        anchor = min(involved)
        for line in involved:
            neighbors[line].add(anchor)
            neighbors[anchor].add(line)
        by_edge[anchor].append((routes, weight, must))
    seen = set()
    global_profile = {0: (0, ())}
    sizes = []
    for root in sorted(neighbors):
        if root in seen:
            continue
        component = {root}
        work = [root]
        while work:
            fresh = neighbors[work.pop()] - component
            component.update(fresh)
            work.extend(fresh)
        seen.update(component)
        size = len(component)
        sizes.append(size)
        if size > 22:
            raise ValueError("component exceeds exact subset-enumeration limit")
        local = [r for line in component for r in by_edge[line]]
        local_profile = {}
        for cost in range(size + 1):
            for subset in combinations(sorted(component), cost):
                retained = frozenset(subset)
                value = 0
                for routes, weight, must in local:
                    if any(route <= retained for route in routes):
                        value += weight
                    elif must:
                        break
                else:
                    retain_best(local_profile, cost, value, subset)
        updated = {}
        for c1, (v1, s1) in global_profile.items():
            for c2, (v2, s2) in local_profile.items():
                retain_best(updated, c1 + c2, v1 + v2, tuple(sorted((*s1, *s2))))
        global_profile = updated
    return global_profile, sizes


def queries_from_ledger(path):
    with path.open(encoding="utf8", newline="") as stream:
        out = []
        for row in csv.DictReader(stream, delimiter="\t"):
            fallback = opposite(
                choose_direction(
                    from_bits(row, "affirmative", "ab"), from_bits(row, "affirmative", "ba")
                )
            )
            out.append((row["a_term"], row["b_term"], fallback))
        return out


def compute(source, ledger, output):
    verify(source, "c8696b058de83a2edb5cc9daf496ab779637ecd5")
    edges = LexicalEvidence(json.loads(s) for s in source.read_bytes().splitlines()).edges
    queries = queries_from_ledger(ledger)
    demand = requirements(edges, queries)
    profile, sizes = optimal_frontier(demand)
    with output.open("x", encoding="utf8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ("source_edges", "evidence_pairs", "fallback_forward_calls", "pmonli_source_lines")
        )
        for cost, (r, lines) in sorted(profile.items()):
            writer.writerow((cost, r, 2 * (len(queries) - r), " ".join(map(str, lines))))
    c0, c1 = min(profile), max(profile)
    return {
        "source_edges": sum(map(len, edges.values())),
        "queries": len(queries),
        "reachable_distinct_term_pairs": len(demand),
        "behavior_required_distinct_term_pairs": sum(x[2] for x in demand.values()),
        "max_paths_per_required_or_optional_relation": max(
            map(lambda x: len(x[0]), demand.values()), default=0
        ),
        "components": len(sizes),
        "max_component_size": max(sizes, default=0),
        "min_edges_same_answers": c0,
        "most_evidence_pairs_at_min_edges": profile[c0][0],
        "min_edges_full_evidence_coverage": min(
            c for c, (v, _) in profile.items() if v == profile[c1][0]
        ),
        "full_coverage": profile[c1][0],
        "frontier_rows": len(profile),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("positive_jsonl", "ledger", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(compute(a.positive_jsonl, a.ledger, a.output), indent=2))
