"""Verify batched states via literal decision trees and check the frozen reuse ledger."""

import argparse
from collections import Counter
from fractions import Fraction as Q
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from batched_query_plan import batched
from frontier_information import actual_cost
from frontier_plan import FrontierPlan, bits
from frontier_theory_check import plan_for, raw_optimum
from mandatory_reuse_run import hard_graph, pairs
from prior_reuse import mandatory_first_regret_bound, transfer_bound


def check_literal():
    rng = Random(88111)
    n_verified = 0
    for case in range(144):
        n = 2 + case % 4
        size = [rng.randint(2, 3) for _ in range(n)]
        edges = [e for e in combinations(range(n), 2) if rng.randrange(3)]
        table = {
            e: [
                [rng.randrange(3) for _ in range(size[e[1]])] for _ in range(size[e[0]])
            ]
            for e in edges
        }
        costs = [Q(rng.randint(1, 8), 3) for _ in size]
        laws = []
        for _ in range(2):
            weights = []
            for d in size:
                counts = [rng.randint(1, 7) for _ in range(d)]
                weights.append([Q(x, sum(counts)) for x in counts])
            laws.append(weights)
        old, new = (plan_for(w, table, costs) for w in laws)
        for model, weights in ((old, laws[0]), (new, laws[1])):
            macro = batched(model)
            expected = raw_optimum(weights, table, costs)
            assert macro.root_value() == model.root_value() == expected
            forced = {i for i in range(n) if rng.randrange(3) == 0}
            raw_tables = {
                **table,
                **{(i, n): [[x] for x in range(size[i])] for i in forced},
            }
            forced_value = raw_optimum([*weights, [Q(1)]], raw_tables, [*costs, Q(1)])
            mask = sum(1 << i for i in forced)
            assert macro.optimum(macro.counts, mask) == model.optimum(
                model.counts, mask
            )
            assert macro.optimum(macro.counts, mask)[0] == forced_value
            n_verified += 2
        stronger = mandatory_first_regret_bound(old, new)
        assert (
            0
            <= actual_cost(old, new) - new.root_value()
            <= stronger
            <= sum(transfer_bound(old, new))
        )
    return n_verified


def check_counts():
    # Compare identical-type batches against an explicit graph with every position expanded.
    for a, b, c in product((1, 2, 3), repeat=3):
        choices = {
            "a": [((), Q(1, 2)), (("b", "c"), Q(1, 2))],
            "b": [(("a",), Q(1, 2)), (("a", "c"), Q(1, 2))],
            "c": [(("a",), Q(1, 2)), (("a", "b"), Q(1, 2))],
        }
        edges = [("a", "b"), ("a", "c"), ("b", "c")]
        counts = dict(zip("abc", (a, b, c)))
        plan = FrontierPlan(counts, choices, edges)
        expanded = {u: [f"{u}{j}" for j in range(n)] for u, n in counts.items()}
        factor = FrontierPlan(
            {name: 1 for group in expanded.values() for name in group},
            {
                name: [
                    (tuple(x for v in targets for x in expanded[v]), p)
                    for targets, p in choices[u]
                ]
                for u, group in expanded.items()
                for name in group
            },
            [(x, y) for u, v in edges for x in expanded[u] for y in expanded[v]],
        )
        assert batched(plan).root_value() == plan.root_value() == factor.root_value()

    # Realize the classified support with literal pairwise XOR/AND tables.
    k = 3
    mandatory = list(product((0, 1), repeat=3))
    low = Q(1, 100)
    weights = [[(low if z else 1 - low) / 4 for _, _, z in mandatory] for _ in range(k)]
    weights.extend([[Q(1, 2)] * 2 for _ in range(k)])
    tables = {
        (i, k + j): [
            [h ^ ((on if i == j else z) & a) for a in range(2)]
            for h, on, z in mandatory
        ]
        for i in range(k)
        for j in range(k)
    }
    expected = raw_optimum(weights, tables, [1] * (2 * k))
    assert (
        expected
        == plan_for(weights, tables, [1] * (2 * k)).root_value()
        == hard_graph(k).root_value()
    )
    old = hard_graph(k)
    new = hard_graph(k, Q(1, 2))
    assert mandatory_first_regret_bound(old, new) == 0 < sum(transfer_bound(old, new))
    assert old.root_value() == Q(90597, 20000)
    assert new.root_value() == actual_cost(old, new) == Q(45, 8)
    return 27


def all_records(snapshot, wordnet, semcor, result):
    def table(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return {tuple(r["task"]): r for r in map(json.loads, f)}

    before = table(ROOT / "prior-reuse-ledger.jsonl.gz")
    after = table(result / "mandatory-reuse-ledger.jsonl.gz")
    summary = json.loads((result / "mandatory-reuse-results.json").read_bytes())[
        "by_source"
    ]["total"]
    count = Counter()
    for key, p, q, truth in pairs(snapshot, wordnet, semcor):
        old = before.pop(key)
        r = after.pop(key)
        for service in (p, q):
            table_rows = service.service.tables
            mandatory = set()
            for (u, v), lookup in table_rows.items():
                left, right = lookup.senses
                if all(len({lookup.cells[x, y] for x in left}) > 1 for y in right):
                    mandatory.add(u)
                if all(len({lookup.cells[x, y] for y in right}) > 1 for x in left):
                    mandatory.add(v)
            assert len(mandatory) == r["compulsory"]
            assert {service.types_by_id[u] for u in mandatory} == set(
                bits(service.plan.obligations(service.plan.counts, 0))
            )
        expected = sum(transfer_bound(p.plan, q.plan))
        residual = Q(r["new_bound"])
        loss = Q(old["reuse_expected"]) - Q(old["new_expected"])
        assert expected == Q(old["bound"]) == Q(r["old_bound"])
        assert loss == Q(r["expected_extra"])
        assert 0 <= loss <= residual <= expected
        keep = residual <= Q(1, 20)
        assert (
            keep == r["reuse"]
            and r["dispatch"] == old["paths"]["old" if keep else "new"]
        )
        known = {u: truth[u] for u in r["dispatch"]}
        for (u, v), answer in old["labels"]:
            domains = q.service.domains
            assert all(
                q.service.tables[u, v].cells[x, y] == answer
                for x, y in product(
                    [known[u]] if u in known else domains[u],
                    [known[v]] if v in known else domains[v],
                )
            )
        count["tasks"] += 1
        count["reused"] += keep
        count["dispatch_reads"] += len(known)
    assert not before and not after
    assert all(v == summary[k] for k, v in count.items())
    return count


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("snapshot", "wordnet", "semcor", "results"):
        p.add_argument(key, type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    report = all_records(a.snapshot, a.wordnet, a.semcor, a.results)
    report["raw_cost_checks"] = check_literal()
    report["expanded_multiplicity_cases"] = check_counts()
    print(json.dumps(report, indent=2))
