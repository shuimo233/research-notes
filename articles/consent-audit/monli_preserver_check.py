"""Validate evidence packages by raw-source closure and independent multi-commodity flow optimization."""

import argparse
from collections import defaultdict
import csv
from graphlib import TopologicalSorter
import json
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from monli_preserver import requirements, optimal_frontier


def reachable(edges):
    outgoing = defaultdict(set)
    for a, b in edges:
        outgoing[a].add(b)
    closure = {}
    for node in TopologicalSorter(outgoing).static_order():
        targets = outgoing.get(node, ())
        closure[node] = set(targets)
        for t in targets:
            closure[node] |= closure[t]
    return closure


def verdict(closure, a, b, fallback):
    if b in closure.get(a, ()):
        return "reverse", True
    if a in closure.get(b, ()):
        return "forward", True
    return fallback, False


def optimization(edges, weights, required, full):
    candidates = {}
    for a, b in weights:
        candidates[a, b] = [
            e
            for e in edges
            if (e[0] == a or e[0] in full.get(a, ())) and (e[1] == b or b in full.get(e[1], ()))
        ]
    arcs = sorted(set().union(*map(set, candidates.values())))
    x = {e: i for i, e in enumerate(arcs)}
    y = {k: i + len(x) for i, k in enumerate(weights)}
    integer_count = len(x) + len(y)
    index = integer_count
    rows = []
    lows = []
    highs = []

    def constraint(terms, lo, hi):
        rows.append(terms)
        lows.append(lo)
        highs.append(hi)

    for (a, b), group in candidates.items():
        flow = defaultdict(dict)
        for e in group:
            u, v = e
            flow[u][index] = 1
            flow[v][index] = -1
            constraint({index: 1, x[e]: -1}, -np.inf, 0)
            index += 1
        flow[a][y[a, b]] = -1
        flow[b][y[a, b]] = 1
        for terms in flow.values():
            constraint(terms, 0, 0)
    constraint({v: 1 for v in x.values()}, -np.inf, 0)
    entries = [(i, j, v) for i, terms in enumerate(rows) for j, v in terms.items()]
    ri, ci, values = zip(*entries)
    matrix = coo_matrix((values, (ri, ci)), shape=(len(rows), index)).tocsc()
    lower = np.zeros(index)
    for k in required:
        lower[y[k]] = 1
    cost = np.zeros(index)
    for k, w in weights.items():
        cost[y[k]] = -w
    integrality = np.zeros(index, dtype=int)
    integrality[:integer_count] = 1

    def solve(budget):
        highs[-1] = budget
        res = milp(
            cost,
            integrality=integrality,
            bounds=Bounds(lower, np.ones(index)),
            constraints=LinearConstraint(matrix, lows, highs),
            options={"mip_rel_gap": 0},
        )
        if res.status == 2:
            return None
        assert res.status == 0 and abs(res.fun - res.mip_dual_bound) < 1e-6
        return int(round(-res.fun))

    return solve


def fixtures():
    # Two separate short paths, or a longer shared path whose union uses fewer edges.
    edges = {
        "a": {"p": 1, "x": 7},
        "p": {"q": 2},
        "q": {"t": 3},
        "b": {"r": 4, "x": 8},
        "r": {"s": 5},
        "s": {"t": 6},
        "x": {"y": 9},
        "y": {"z": 10},
        "z": {"t": 11},
    }
    q = [("a", "t", "forward"), ("b", "t", "forward")]
    costs, _ = optimal_frontier(requirements(edges, q))
    assert min(costs) == 5 and costs[5] == (2, (7, 8, 9, 10, 11))
    # Reducing the whole graph first could throw away the single useful shortcut.
    g = {"a": {"b": 1, "c": 3}, "b": {"c": 2}}
    p, _ = optimal_frontier(requirements(g, [("a", "c", "abstain")]))
    assert min(p) == 1 and p[1][1] == (3,)
    assert optimal_frontier(requirements(g, []))[0] == {0: (0, ())}
    # If a query's evidence agrees with fallback, it is optional but still saves a call pair.
    p, _ = optimal_frontier(requirements(g, [("a", "c", "reverse"), ("a", "c", "reverse")]))
    assert p[0][0] == 0 and p[1][0] == 2


def check(source, ledger, frontier):
    fixtures()
    verify(source, "c8696b058de83a2edb5cc9daf496ab779637ecd5")
    edges = {}
    for line, r in enumerate((json.loads(v) for v in source.read_bytes().splitlines()), 1):
        if r["gold_label"] == "entailment":
            edges.setdefault((r["sentence1_lex"].casefold(), r["sentence2_lex"].casefold()), line)
    source_lines = {v: k for k, v in edges.items()}
    full = reachable(edges)
    with ledger.open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    queries = []
    weights = defaultdict(int)
    required = set()
    for r in rows:
        a, b = r["a_term"], r["b_term"]
        fallback = r["invert_affirmative"]
        pick, proof = verdict(full, a, b, fallback)
        assert pick == r["evidence_first"]
        queries.append((a, b, fallback, pick))
        if proof:
            k = (a, b) if pick == "reverse" else (b, a)
            weights[k] += 1
            if pick != fallback:
                required.add(k)
    with frontier.open(encoding="utf8", newline="") as f:
        entries = list(csv.DictReader(f, delimiter="\t"))
    budgets = [int(e["source_edges"]) for e in entries]
    assert budgets == list(range(min(budgets), max(budgets) + 1))
    solve = optimization(edges, weights, required, full)
    assert solve(min(budgets) - 1) is None
    for r, budget in zip(entries, budgets):
        ids = list(map(int, r["pmonli_source_lines"].split()))
        assert len(ids) == len(set(ids)) == budget
        retained = reachable(source_lines[i] for i in ids)
        served = 0
        for a, b, fallback, pick in queries:
            actual, proof = verdict(retained, a, b, fallback)
            assert actual == pick
            served += proof
        assert served == int(r["evidence_pairs"]) == solve(budget)
        assert 2 * (len(queries) - served) == int(r["fallback_forward_calls"])
    return {
        "optimal_budgets": len(budgets),
        "infeasible_budget_checked": min(budgets) - 1,
        "individual_answers_replayed": len(queries) * len(budgets),
        "source_edges": len(edges),
        "alternative_path_fixtures": 4,
        "milp_zero_gap": True,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("positive", "ledger", "frontier"):
        p.add_argument(n, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.positive, a.ledger, a.frontier), indent=2))
