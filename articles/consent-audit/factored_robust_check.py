"""Verify factored regret on original tables and independent literal-history oracles."""

import argparse
from collections import Counter
from fractions import Fraction as Q
import gzip
from itertools import product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factored_robust import ContextGame, FactoredPlan
from factored_robust_run import global_laws, hard_problem, independent_laws
from frontier_inquiry import RelationInquiry
from mandatory_reuse_run import pair_data
from mixture_query_check import raw_minimum
from robust_game import solve_game


def raw_value(service, scenarios, prices):
    return raw_minimum(
        sorted(service.service.domains),
        service.service.domains,
        {e: table.cells for e, table in service.service.tables.items()},
        prices,
        {u: [law[u] for law in scenarios] for u in service.service.domains},
        {u: service.plan.cost[service.types_by_id[u]] for u in service.service.domains},
    )


def raw_examples():
    measured = 0
    for k in (2, 3):
        s, known, local = hard_problem(k)
        scenarios = list(global_laws(known, local))
        game = ContextGame(s, scenarios)
        m = len(scenarios)
        equal = (Q(1, m),) * m
        raw = raw_value(s, scenarios, equal)
        budgets = tuple(raw_value(s, [law], (Q(1),)) for law in scenarios)
        assert budgets == game.budgets
        assert raw == game.oracle_cost(equal)
        assert raw - sum(budgets) / m == Q(3 * k, 10)
        measured += m + 1

    s, a, local = hard_problem(2, Q(1, 10), uneven=True)
    b = {"u": {x: Q(1, 2) - p for x, p in a["u"].items()}}
    alternatives = [*global_laws(a, local), *global_laws(b, local)]
    m = len(alternatives)
    raw = raw_value(s, alternatives, (Q(1, m),) * m)
    endpoints = [raw_value(s, [law], (Q(1),)) for law in alternatives]
    assert raw - sum(endpoints) / m == Q(2, 5)
    assert ContextGame(s, alternatives).solve()["regret"] == Q(2, 5)
    measured += m + 1

    # Three modes exercise general finite-game row generation, including a new mixed-policy column.
    initial = {
        (Q(1), Q(0), Q(0)): (Q(0), Q(1), Q(1)),
        (Q(0), Q(1), Q(0)): (Q(1), Q(0), Q(1)),
        (Q(0), Q(0), Q(1)): (Q(1), Q(1), Q(0)),
    }
    vectors = [*initial.values(), (Q(1, 2),) * 3]
    answer = solve_game(
        initial, lambda w: min(vectors, key=lambda r: sum(a * b for a, b in zip(w, r)))
    )
    assert answer[0] == Q(1, 2)
    return measured


def shared_context():
    edges = [("a", "b"), ("b", "c")]
    tags = {u: [(u, 0), (u, 1)] for u in "abc"}
    rates = [(Q(3, 5), Q(3, 10), Q(7, 10)), (Q(1, 5), Q(7, 10), Q(1, 10))]
    laws = [
        {u: {(u, 0): 1 - p, (u, 1): p} for u, p in zip("abc", row)} for row in rates
    ]
    service = RelationInquiry(tags, edges, lambda x, y: x[1] & y[1], laws[0])
    a, c = (1 << service.plan.indices[u] for u in ("a", "c"))
    first = ContextGame(service, laws, {a: Q(1)})
    second = ContextGame(service, laws, {c: Q(1)})
    common = ContextGame(service, laws, {a: Q(1, 2), c: Q(1, 2)})
    per_context = (first.solve()["regret"] + second.solve()["regret"]) / 2
    together = common.solve()["regret"]
    assert per_context == Q(39, 400) and together == Q(3, 32)
    return str(together), str(per_context)


def verify(snapshot, wordnet, semcor, folder):
    with gzip.open(
        folder / "factored-robust-ledger.jsonl.gz", "rt", encoding="utf-8"
    ) as f:
        records = {tuple(r["task"]): r for r in map(json.loads, f)}
    counts = Counter()
    for key, old, _, truth, laws in pair_data(snapshot, wordnet, semcor):
        row = records.pop(key)
        local = independent_laws(old, laws)
        program = FactoredPlan(old, local)
        assert row["compulsory"] == program.sources
        assert row["trace"][: len(program.sources)] == program.sources
        seen = {x: truth[x] for x in row["trace"]}
        assert len(seen) == len(row["trace"])
        decoded_cost = Q(0)
        for (names, _, game), certificate in zip(
            program.components, row["components"], strict=True
        ):
            assert names == tuple(certificate["component"])
            upper = Q(certificate["regret"])
            scenarios = tuple(map(Q, certificate["least_favorable"]))
            assert sum(scenarios) == 1 and min(scenarios) >= 0
            expected = [Q(0)] * len(scenarios)
            total_probability = Q(0)
            for policy, prob in certificate["policies"]:
                prob = Q(prob)
                assert prob > 0
                total_probability += prob
                values = game.regrets(tuple(map(Q, policy)))
                expected = [p + prob * r for p, r in zip(expected, values, strict=True)]
            assert total_probability == 1 and max(expected) == upper
            assert tuple(map(Q, certificate["risks"])) == tuple(expected)
            if upper:
                assert (
                    game.oracle_cost(scenarios)
                    - sum(p * v for p, v in zip(scenarios, game.budgets))
                    == upper
                )
                counts["nonzero_local_certificates"] += 1
            decoded_cost += upper
        assert decoded_cost == Q(row["regret"])
        for (u, v), target in row["labels"]:
            a, b = old.service.tables[u, v].senses
            assert {
                old.service.tables[u, v].cells[x, y]
                for x, y in product(
                    [seen[u]] if u in seen else a, [seen[v]] if v in seen else b
                )
            } == {target}
        counts["replay_certificates"] += 1
        counts["full_configurations_verified"] += row["checked_globally"]
    assert not records
    return counts


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "wordnet", "semcor", "folder"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    report = dict(raw_values=raw_examples(), shared_context=shared_context())
    report.update(verify(a.snapshot, a.wordnet, a.semcor, a.folder))
    print(json.dumps(report, indent=2))
