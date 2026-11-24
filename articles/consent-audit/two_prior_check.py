"""Verify two-prior witnesses by literal history enumeration and reproduce real replays."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_inquiry import RelationInquiry
from frontier_information import actual_cost
from frontier_theory_check import plan_for, raw_optimum
from mandatory_reuse_run import pair_data
from mixture_query_check import raw_minimum
from two_prior import TwoPrior, controller_for


def pareto(pairs):
    best = []
    for a, b in sorted(set(pairs)):
        if not best or b < best[-1][1]:
            best.append((a, b))
    return tuple(best)


def literal_vectors(domains, tables, models):
    """Enumerate nondominated cost vectors without using a posterior or a query-state quotient."""

    @lru_cache(None)
    def search(history):
        known = dict(history)
        terminal = all(
            len(
                {
                    table[x, y]
                    for x, y in product(
                        (known[u],) if u in known else domains[u],
                        (known[v],) if v in known else domains[v],
                    )
                }
            )
            == 1
            for (u, v), table in tables.items()
        )
        if terminal:
            return ((Q(0), Q(0)),)
        options = []
        for u, xs in domains.items():
            if u in known:
                continue
            costs = ((Q(1), Q(1)),)
            for x in xs:
                a, b = (m[u][x] for m in models)
                future = search(tuple(sorted((*history, (u, x)))))
                costs = pareto(
                    (s + a * p, t + b * q) for (s, t), (p, q) in product(costs, future)
                )
            options.extend(costs)
        return pareto(options)

    return search(())


def literal_minimax(vectors, budgets):
    r = [(a - budgets[0], b - budgets[1]) for a, b in vectors]
    optimum = min(map(max, r))
    for (a, b), (c, d) in combinations(r, 2):
        if (a - b) * (c - d) < 0:
            w = (d - c) / (a - b - c + d)
            optimum = min(optimum, w * a + (1 - w) * c)
    return optimum


def build(domains, tables, weights):
    tags = {u: [(u, x) for x in xs] for u, xs in domains.items()}

    def lookup(a, b):
        return tables[a[0], b[0]][a[1], b[1]]

    models = [{u: {(u, x): p for x, p in m[u].items()} for u in m} for m in weights]
    p, q = [RelationInquiry(tags, tables, lookup, m) for m in models]
    return controller_for(p, q, models)


def signal():
    names = {"a": (0, 1), "b": (0, 1), "u": tuple(product((0, 1), repeat=3))}
    eps = Q(1, 10)
    tables = {
        ("a", "b"): {(a, b): a & b for a, b in product((0, 1), repeat=2)},
        ("a", "u"): {
            (a, (h, t, s)): h ^ (t & a) for a in (0, 1) for h, t, s in names["u"]
        },
    }
    laws = []
    for z in range(2):
        p = eps if not z else 1 - eps
        laws.append(
            dict(
                a={0: 1 - p, 1: p},
                b={0: p, 1: 1 - p},
                u={
                    (h, t, s): Q(1, 2)
                    * (Q(1, 4) if t else Q(3, 4))
                    * (1 - eps if s == z else eps)
                    for h, t, s in names["u"]
                },
            )
        )
    return names, tables, laws


def independent_midpoint_witness():
    tables = {(0, 1): [[0, 0], [0, 1]], (0, 2): [[0, 0], [0, 1]]}
    rates = [
        (Q(29, 50), Q(1, 10), Q(1, 10)),
        (Q(47, 50), Q(7, 10), Q(7, 10)),
        (Q(19, 25), Q(2, 5), Q(2, 5)),
    ]
    weights = [[[1 - p, p] for p in row] for row in rates]
    old, new, mid = [plan_for(q, tables, [1] * 3) for q in weights]
    assert actual_cost(old, new) == new.root_value()
    assert [p.root_value() for p in (old, new, mid)] == [
        raw_optimum(w, tables, [1] * 3) for w in weights
    ]
    assert actual_cost(old, mid) - mid.root_value() == Q(3, 125)


def synthetic():
    d = {"a": (0, 1), "b": (0, 1)}
    t = {("a", "b"): {(a, b): a & b for a, b in product((0, 1), repeat=2)}}
    w = [
        {"a": {0: Q(9, 10), 1: Q(1, 10)}, "b": {0: Q(1, 10), 1: Q(9, 10)}},
        {"a": {0: Q(1, 10), 1: Q(9, 10)}, "b": {0: Q(9, 10), 1: Q(1, 10)}},
    ]
    forced_lottery = build(d, t, w)
    assert forced_lottery.solve()["worst_regret"] == Q(2, 5)
    assert min(
        max(a - forced_lottery.budgets[0], b - forced_lottery.budgets[1])
        for a, b in literal_vectors(d, t, w)
    ) == Q(4, 5)
    domains, tables, models = signal()
    program = build(domains, tables, models)
    result = program.solve()
    assert (
        result["worst_regret"]
        == literal_minimax(literal_vectors(domains, tables, models), program.budgets)
        == Q(3, 50)
    )
    assert result["reference_regret"] == Q(3, 10)
    # All states within a trigger class are still legal for certificate verification.
    p, q = program.services
    masked = TwoPrior(p, q, program.conditional, observe_values=False)
    assert masked.solve()["worst_regret"] == Q(3, 10)
    assert result["policies"] == [
        dict(prior=Q(1, 2), probability=Q(1), regrets=(Q(3, 50), Q(3, 50)))
    ]
    independent_midpoint_witness()
    rng = Random(2266551)
    for case in range(72):
        names = "abcd"[: 3 + case % 2]
        domain = {u: (0, 1) for u in names}
        edges = [e for e in combinations(names, 2) if rng.randrange(3)]
        tables = {
            e: {x: rng.randrange(3) for x in product((0, 1), repeat=2)} for e in edges
        }
        models = [
            {
                u: {b: Q(x if b else 10 - x, 10) for b in (0, 1)}
                for u, x in zip(names, [rng.randint(1, 9) for _ in names])
            }
            for _ in range(2)
        ]
        solver = build(domain, tables, models)
        truth = literal_vectors(domain, tables, models)
        budgets = tuple(min(pair[z] for pair in truth) for z in range(2))
        assert solver.budgets == budgets
        witness = solver.solve()
        optimum = literal_minimax(truth, budgets)
        assert optimum == witness["worst_regret"]
        t = witness["environment_weight"]
        assert (
            min((1 - t) * (a - budgets[0]) + t * (b - budgets[1]) for a, b in truth)
            == optimum
        )
    return dict(
        literal_policy_games=72,
        informative_values_example="3/50",
        trigger_only_example="3/10",
        product_interpolation_regret="3/125",
    )


def verify(snapshot, wordnet, semcor, folder):
    with gzip.open(folder / "two-prior-ledger.jsonl.gz", "rt", encoding="utf-8") as f:
        expected = {tuple(r["task"]): r for r in map(json.loads, f)}
    findings = Counter()
    for key, p, q, truth, weights in pair_data(snapshot, wordnet, semcor):
        row = expected.pop(key)
        s = controller_for(p, q, weights)
        cert = Q(row["worst_regret"])
        prior = Q(row["environment_weight"])
        averaged = [Q(0), Q(0)]
        probability = Q(0)
        listed = []
        for policy in row["policies"]:
            nominal, mass = map(Q, (policy["prior"], policy["probability"]))
            regrets = s.regrets_at(nominal)
            assert regrets == tuple(map(Q, policy["regrets"]))
            probability += mass
            listed.append(nominal)
            assert mass > 0
            for z in range(2):
                averaged[z] += mass * regrets[z]
        assert probability == 1 and max(averaged) == cert
        assert Q(row["selected"]) in listed
        trace, labels = s.execute(Q(row["selected"]), truth.__getitem__)
        assert (
            trace == row["trace"]
            and [[list(e), x] for e, x in labels.items()] == row["labels"]
        )
        if cert:
            model = s._oracle(prior)
            nominal_cost = model.optimum(*model.initial())[0]
            assert (
                nominal_cost - (1 - prior) * s.budgets[0] - prior * s.budgets[1] == cert
            )
            domains = p.service.domains
            if len(domains) == 3 and max(map(len, domains.values())) <= 12:
                raw_tables = {e: lookup.cells for e, lookup in p.service.tables.items()}
                model_weights = {u: [a[u] for a in weights] for u in domains}
                actual = raw_minimum(
                    sorted(domains),
                    domains,
                    raw_tables,
                    (1 - prior, prior),
                    model_weights,
                    dict.fromkeys(domains, 1),
                )
                assert actual == nominal_cost
                findings["literal_dual_roots"] += 1
            masked = controller_for(p, q, weights, observe_values=False)
            mask_cost = masked.solve()["worst_regret"]
            assert mask_cost >= cert
            findings["raw_values_strictly_help"] += mask_cost > cert
            masked.clear()
            findings["positive_dual_witnesses"] += 1
        seen = {u: truth[u] for u in row["trace"]}
        assert len(seen) == len(row["trace"])
        for (u, v), label in row["labels"]:
            dom = q.service.domains
            assert all(
                q.service.tables[u, v].cells[x, y] == label
                for x, y in product(
                    [seen[u]] if u in seen else dom[u],
                    [seen[v]] if v in seen else dom[v],
                )
            )
        s.clear()
        findings["replay_certificates"] += 1
    assert not expected
    return findings


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("snapshot", "wordnet", "semcor", "folder"):
        p.add_argument(key, type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    result = synthetic()
    result.update(verify(a.snapshot, a.wordnet, a.semcor, a.folder))
    print(json.dumps(result, indent=2))
