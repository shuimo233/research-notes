"""Score the registered dependence-masking experiment against the published word-sense tasks."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_query_plan import scopes
from frontier_plan import bits
from frontier_run import compile_task, inputs, lines
from gloss_frontier import semcor_counts
from pair_budget import PairBudget
from wordnet_paths import NounPaths


def select(planner):
    names = planner.names
    edges = [
        (u, names[j])
        for i, u in enumerate(names)
        for j in bits(planner.neighbors[i])
        if j > i
    ]
    candidate = None
    for u, parts in scopes(dict.fromkeys(names, 1), edges).items():
        i = planner.indices[u]
        for scope in parts:
            for x, y in combinations(scope, 2):
                left, right = (1 << planner.indices[v] for v in (x, y))
                cells = defaultdict(lambda: [Q(0), Q(0), Q(0)])
                for mask, p in planner.groups[i]:
                    stratum = cells[mask & ~(left | right)]
                    stratum[0] += p
                    stratum[1] += p * bool(mask & left)
                    stratum[2] += p * bool(mask & right)
                widths = [
                    min(a, b) - max(0, a + b - mass) for mass, a, b in cells.values()
                ]
                if sum(w > 0 for w in widths) != 1:
                    continue
                key = (-sum(widths), u, x, y)
                if candidate is None or key < candidate[0]:
                    candidate = (key, cells)
    if candidate is None:
        return None
    (neg_width, u, x, y), cells = candidate
    strata = [
        dict(rest=[names[j] for j in bits(m)], mass=mass, x_mass=a, y_mass=b)
        for m, (mass, a, b) in sorted(cells.items())
    ]
    laws = {
        v: [([names[j] for j in bits(m)], p) for m, p in law]
        for v, law in zip(names, planner.groups)
        if v != u
    }
    return PairBudget(names, edges, laws, u, (x, y), strata), -neg_width


def cases(wordnet, semcor):
    graph = NounPaths(wordnet)
    sem = inputs()
    for row in lines("frontier-ledger.jsonl"):
        if row["source"] == "semcor":
            key = ("semcor", row["group"], row["sentence"])
            yield key, row["expected_optimal"], compile_task(graph, sem[key]).plan
    senses = lru_cache(None)(graph.senses)
    _, training = semcor_counts(wordnet, semcor, senses)
    for row in lines("gloss-frontier-ledger.jsonl"):
        words = {u: w for u, _, w, _ in row["positions"]}
        task = dict(
            words=words,
            edges=row["edges"],
            counts={
                w: {str(x): training[w][x] for x in senses(w)}
                for w in set(words.values())
            },
        )
        yield (
            ("princeton", row["stratum"], row["definition"]),
            row["expected_optimal"],
            compile_task(graph, task).plan,
        )


def compare(family, truth, n):
    forecast = family.forecast()
    lo, hi = forecast["exact_interval"]
    safe_lo, safe_hi = forecast["guaranteed_interval"]
    independent = family.independent_plan().root_value()
    assert safe_lo <= lo <= truth <= hi <= safe_hi and lo <= independent <= hi
    counts = Counter(thresholds=4 * n + 1)
    for k in range(4 * n + 1):
        budget = Q(k, 4)
        actual = truth <= budget
        counts["point_errors"] += (independent <= budget) != actual
        counts["false_feasible_point"] += independent <= budget < truth
        for name, a, b in [("safe", safe_lo, safe_hi), ("exact", lo, hi)]:
            if b <= budget or a > budget:
                assert (b <= budget) == actual
                counts[name + "_decisions"] += 1
    return dict(
        **forecast,
        independent=independent,
        point_worst_error=max(independent - lo, hi - independent),
        strict_shrink=hi - lo < safe_hi - safe_lo,
        thresholds=dict(counts),
    )


def run(wordnet, semcor, out):
    summary = {"semcor": Counter(), "princeton": Counter()}
    rows = []
    for key, exact, planner in cases(wordnet, semcor):
        totals = summary[key[0]]
        totals["seen"] += 1
        if exact is None:
            totals["excluded_no_exact_root"] += 1
            continue
        if any(n != 1 for n in planner.counts):
            totals["excluded_coalesced"] += 1
            continue
        selected = select(planner)
        if selected is None:
            totals["excluded_no_single_ambiguous_stratum"] += 1
            continue
        truth = Q(exact)
        assert truth == planner.root_value()
        family, width = selected
        score = compare(family, truth, len(planner.names))
        rows.append(
            dict(
                task=key,
                source=family.source,
                pair=[family.x, family.y],
                width=width,
                truth=truth,
                **score,
            )
        )
        totals.update(score["thresholds"])
        totals["scored"] += 1
        totals["strict_shrink"] += score["strict_shrink"]
        totals["additional_decision_tasks"] += (
            score["thresholds"]["exact_decisions"]
            > score["thresholds"]["safe_decisions"]
        )
        for k in ("point_worst_error", "minimax_radius"):
            totals[k + "_sum"] += score[k]
    summary["total"] = Counter()
    for src in ("semcor", "princeton"):
        summary["total"].update(summary[src])
    grand = summary["total"]
    summary["registered_gate"] = (
        grand["scored"] >= 100 and 4 * grand["strict_shrink"] >= grand["scored"]
    )
    out.mkdir(parents=True, exist_ok=False)
    (out / "pair-budget-ledger.jsonl").write_bytes(
        (
            "".join(
                json.dumps(r, default=str, separators=(",", ":")) + "\n" for r in rows
            )
        ).encode()
    )
    (out / "pair-budget-results.json").write_bytes(
        (json.dumps(summary, default=str, indent=2) + "\n").encode()
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.semcor, a.output), default=str, indent=2))
