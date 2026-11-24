"""Check transport by brute assignment and replay the frozen proof certificates."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
import gzip
from itertools import combinations, permutations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_information import actual_cost
from frontier_theory_check import plan_for, raw_optimum
from prior_reuse import transfer_bound, transport
from prior_reuse_run import word_tasks
from station_query import EDGES, STATIONS
from station_query_check import category, certified, data, reference


def synthetic():
    rng = Random(128013)
    for _ in range(180):
        a = [rng.randrange(8) for _ in range(6)]
        b = [rng.randrange(8) for _ in range(6)]
        costs = [Q(rng.randint(1, 7), 4) for _ in range(3)]
        exact = (
            min(
                sum(
                    sum(c for k, c in enumerate(costs) if ((x ^ y) >> k) & 1)
                    for x, y in zip(a, perm)
                )
                for perm in set(permutations(b))
            )
            / 6
        )
        assert exact == transport(
            {k: Q(v, 6) for k, v in Counter(a).items()},
            {k: Q(v, 6) for k, v in Counter(b).items()},
            costs,
        )

    for _ in range(160):
        n = rng.randrange(2, 6)
        support = [rng.randrange(2, 4) for _ in range(n)]
        tables = {
            e: [
                [rng.randrange(3) for _ in range(support[e[1]])]
                for _ in range(support[e[0]])
            ]
            for e in combinations(range(n), 2)
            if rng.random() < 0.6
        }
        costs = [Q(rng.randint(1, 7), 4) for _ in range(n)]
        models = []
        for _ in range(2):
            counts = [[rng.randint(1, 8) for _ in range(d)] for d in support]
            models.append([[Q(v, sum(row)) for v in row] for row in counts])
        a, b = models
        p, q = (plan_for(w, tables, costs) for w in models)
        delta = transfer_bound(p, q)
        values = [raw_optimum(w, tables, costs) for w in models]
        assert values == [p.root_value(), q.root_value()]
        live_cost = actual_cost(p, q)
        for rhs in (values[1], live_cost):
            assert -delta[0] <= rhs - values[0] <= delta[1]
        assert 0 <= live_cost - values[1] <= sum(delta)
        fitted = []
        for x, y in zip(a, b):
            shrink = Q(rng.randint(0, 6), 6)
            fitted.append([u + shrink * (v - u) for u, v in zip(x, y)])
        mid = plan_for(fitted, tables, costs)
        assert sum(transfer_bound(p, mid)) <= sum(delta)
        assert actual_cost(p, mid) - raw_optimum(fitted, tables, costs) <= sum(delta)

    and_table = {(0, 1): [[0, 0], [0, 1]]}
    old = plan_for([[Q(501, 1000), Q(499, 1000)], [Q(1, 2)] * 2], and_table, [1, 1])
    updated = plan_for([[Q(1, 5), Q(4, 5)], [Q(1, 2)] * 2], and_table, [1, 1])
    assert transfer_bound(old, updated) == (0, Q(301, 1000))
    assert actual_cost(old, updated) - updated.root_value() == Q(3, 10)

    tables = {
        (0, j): [[(state >> (j - 1) & 1) * x for x in (0, 1)] for state in range(4)]
        for j in (1, 2)
    }
    aligned = [
        [Q(49, 100), Q(1, 100), Q(1, 100), Q(49, 100)],
        [Q(1, 2)] * 2,
        [Q(1, 2)] * 2,
    ]
    opposite = [
        [Q(1, 100), Q(49, 100), Q(49, 100), Q(1, 100)],
        [Q(1, 2)] * 2,
        [Q(1, 2)] * 2,
    ]
    a, b = (plan_for(w, tables, [1] * 3) for w in (aligned, opposite))
    assert transfer_bound(a, b) == (0, 0)
    assert transport(dict(a.groups[0]), dict(b.groups[0]), [1] * 3) == Q(24, 25)
    assert actual_cost(a, b) == raw_optimum(opposite, tables, [1] * 3)
    return Counter(
        brute_transport=180,
        raw_decision_roots=320,
        partial_updates=160,
        sharp_regret_example=1,
        block_zero_example=1,
    )


def weather(snapshot, manifest, by_task, raw):
    readings = data(snapshot, manifest, raw, last_year=2025)
    checked = Counter()
    for group, codes in STATIONS.items():
        ids = {u: "USW000" + v for u, v in codes.items()}
        dates = set.intersection(*(set(readings[s]) for s in ids.values()))
        a, b = defaultdict(Counter), defaultdict(Counter)
        for u, sid in ids.items():
            for day, t in readings[sid].items():
                month = int(day[5:7])
                if day < "2025":
                    b[u, month][t] += 1
                if day < "2018":
                    a[u, month][t] += 1
        med = {}
        for k, row in a.items():
            t = sorted(row.elements())
            med[k] = t[(len(t) - 1) // 2]
        roots = {}
        for day in sorted(d for d in dates if d.startswith("2025-")):
            row = by_task.pop(("temperature", group, day))
            truth = {u: readings[sid][day] for u, sid in ids.items()}
            month = int(day[5:7])
            lo = {u: x - (x - med[u, month]) % 20 for u, x in truth.items()}
            ranges = {u: (t, t + 19) for u, t in lo.items()}
            key = month, tuple(lo.values())
            if key not in roots:
                models = []
                rates = []
                for history in (a, b):
                    probs = {}
                    for u, low in lo.items():
                        hist = history[u, month]
                        xs = range(low, low + 20)
                        den = sum(1 + hist[x] for x in xs)
                        probs[u] = {x: Q(1 + hist[x], den) for x in xs}
                    models.append(reference(ranges, probs, EDGES)[0])
                    rates.append(
                        {
                            (u, v): sum(
                                p
                                for x, p in probs[u].items()
                                if category(x - ranges[v][0])
                                != category(x - ranges[v][1])
                            )
                            for e in EDGES
                            for u, v in (e, e[::-1])
                        }
                    )
                diffs = [n - rates[0][k] for k, n in rates[1].items()]
                roots[key] = (
                    models,
                    sum(max(0, -d) for d in diffs),
                    sum(max(0, d) for d in diffs),
                )
            roots_expected, down, up = roots[key]
            assert roots_expected == list(
                map(Q, (row["old_expected"], row["new_expected"]))
            )
            assert (down, up) == (Q(row["down"]), Q(row["up"]))
            assert row["labels"] == [
                [list(e), category(truth[e[0]] - truth[e[1]])]
                for e in sorted(EDGES, key=lambda e: tuple(sorted(e)))
            ]
            for path in row["paths"].values():
                assert len(set(path)) == len(path)
                assert certified(EDGES, ranges, {u: truth[u] for u in path}) == [
                    category(truth[u] - truth[v]) for u, v in EDGES
                ]
            checked["weather_certificates"] += 1
        checked["weather_roots_per_model"] += len(roots)
    return checked


def words(wordnet, semcor, by_task):
    checked = Counter()
    for key, exact, graph, task in word_tasks(wordnet, semcor):
        if key not in by_task:
            continue
        row = by_task.pop(key)
        words = task["words"]
        truth = task["truth"]
        domain = {u: tuple(sorted(graph.senses(w))) for u, w in words.items()}
        edges = sorted(tuple(e) for e in task["edges"])
        gold = {e: graph.relation(truth[e[0]], truth[e[1]]) for e in edges}
        assert {tuple(e): ans for e, ans in row["labels"]} == gold
        for path in row["paths"].values():
            assert len(set(path)) == len(path)
            seen = set(path)
            for (u, v), label in gold.items():
                src = [truth[u]] if u in seen else domain[u]
                dst = [truth[v]] if v in seen else domain[v]
                assert all(graph.relation(x, y) == label for x, y in product(src, dst))
        checked["word_certificates"] += 1
        if len(words) == 3 and max(len(d) for d in domain.values()) <= 12:
            names = sorted(words)
            i = {u: j for j, u in enumerate(names)}
            grids = {
                (i[u], i[v]): [
                    [graph.relation(x, y) for y in domain[v]] for x in domain[u]
                ]
                for u, v in edges
            }
            for add, field in [(1, "old_expected"), (2, "new_expected")]:
                probabilities = []
                for u in names:
                    masses = [add + task["counts"][words[u]][str(x)] for x in domain[u]]
                    probabilities.append([Q(m, sum(masses)) for m in masses])
                assert raw_optimum(probabilities, grids, [1] * 3) == Q(row[field])
            checked["word_literal_roots_per_model"] += 1
    return checked


def verify(snapshot, manifest, wordnet, semcor, folder, raw):
    with gzip.open(folder / "prior-reuse-ledger.jsonl.gz", "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    by_task = {tuple(r["task"]): r for r in rows}
    assert len(rows) == len(by_task)
    for r in rows:
        old, new, reuse, down, up, bound = map(
            Q,
            (
                r[k]
                for k in (
                    "old_expected",
                    "new_expected",
                    "reuse_expected",
                    "down",
                    "up",
                    "bound",
                )
            ),
        )
        assert bound == down + up
        assert -down <= new - old <= up and -down <= reuse - old <= up
        assert 0 <= reuse - new <= bound
        assert r["reuse"] == (bound <= Q(1, 20))
        assert r["paths"]["dispatch"] == r["paths"]["old" if r["reuse"] else "new"]
        assert all(len(path) == r[name + "_reads"] for name, path in r["paths"].items())
    result = synthetic()
    result.update(weather(snapshot, manifest, by_task, raw))
    result.update(words(wordnet, semcor, by_task))
    assert not by_task
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "manifest", "wordnet", "semcor", "folder"):
        p.add_argument(name, type=Path)
    p.add_argument("--raw-directory", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            verify(
                a.snapshot, a.manifest, a.wordnet, a.semcor, a.folder, a.raw_directory
            ),
            indent=2,
        )
    )
