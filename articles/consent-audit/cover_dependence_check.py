"""Verify published joint distributions and dual prices without trusting an LP solver."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from fair_cover_budget import budget


def signed_tests():
    counted = 0
    for cycle in (False, True):
        for n in range(2, 8):
            edges = [(i, i + 1) for i in range(n - 1)]
            if cycle:
                edges.append((n - 1, 0))
            for orientations in product(range(2), repeat=len(edges)):
                choices = {i: [[], []] for i in range(n)}
                for k, ((i, j), side) in enumerate(
                    zip(edges, orientations, strict=True)
                ):
                    choices[i][1].append(k)
                    choices[j][side].append(k)
                report = budget(choices)

                def cost(w):
                    return len(set().union(*(choices[i][w[i]] for i in range(n))))

                possible = product(range(2), repeat=n)
                exact = max(Q(cost(w) + cost([1 - x for x in w]), 2) for w in possible)
                chosen, opposite = report["equal_mass_worlds"]
                assert (
                    exact
                    == Q(report["worst_extra"])
                    == Q(cost(chosen) + cost(opposite), 2)
                )
                counted += 1
    special = {"a": [["fixed", "single"], ["fixed"]], "b": [[], []]}
    assert budget(special)["worst_extra"] == "3/2"
    return counted + 1


def small_graphs():
    from scipy.optimize import linprog

    checked = 0
    for n in range(1, 6):
        bitstrings = list(product(range(2), repeat=n))
        matrix = [[1 for _ in bitstrings]] + [
            [w[i] for w in bitstrings] for i in range(n)
        ]
        marg = [Q(1)] + [Q(1, 2)] * n
        edges = list(combinations(range(n), 2))
        for graph in range(1 << len(edges)):
            pairs = [e for j, e in enumerate(edges) if graph >> j & 1]
            # Strict order consists solely of selected lower-to-upper edges.
            upper = {(("a", i, 1), ("b", k, 1)) for k, e in enumerate(pairs) for i in e}

            def unresolved(k, e, w):
                return any(
                    len({(("a", i, w[i]), ("b", k, y)) in upper for y in (0, 1)}) > 1
                    for i in e
                )

            cost = [
                sum(unresolved(k, e, w) for k, e in enumerate(pairs))
                for w in bitstrings
            ]
            cuts = [sum(w[i] != w[j] for i, j in pairs) for w in bitstrings]
            best = max(cuts)
            w = cuts.index(best)
            assert Q(cost[w] + cost[-1 - w], 2) == Q(len(pairs) + best, 2)
            lp = linprog(
                [-v for v in cost],
                A_eq=matrix,
                b_eq=list(map(float, marg)),
                method="highs",
            )
            assert lp.success
            dual = [Q(float(v)).limit_denominator(10000) for v in lp.eqlin.marginals]
            assert all(
                sum(p * row[j] for row, p in zip(matrix, dual)) <= -v
                for j, v in enumerate(cost)
            )
            assert -sum(p * v for p, v in zip(marg, dual)) == Q(len(pairs) + best, 2)
            checked += 1
    return checked


def validate(groups, row):
    sizes = list(map(len, groups))
    worlds = list(product(*(range(k) for k in sizes)))
    ids = [{v for i, k in enumerate(w) for v in groups[i][k][0]} for w in worlds]
    probs = [
        prod((groups[i][k][1] for i, k in enumerate(w)), start=Q(1)) for w in worlds
    ]
    assert len(worlds) == row["worlds"] and sum(probs) == 1
    assert sum(p * len(s) for p, s in zip(probs, ids)) == Q(row["independent"])
    vertices = set().union(*ids)
    bound = sum(
        min(1, sum(p for g in groups for vs, p in g if v in vs)) for v in vertices
    )
    assert bound == Q(row["local_upper"])
    for key, sign in (("minimum", 1), ("maximum", -1)):
        cert = row[key]
        mass = {int(j): Q(v) for j, v in cert["mass"].items()}
        assert sum(mass.values()) == 1 and all(
            p >= 0 and 0 <= j < len(worlds) for j, p in mass.items()
        )
        for i, g in enumerate(groups):
            for k, (_, m) in enumerate(g):
                assert sum(p for j, p in mass.items() if worlds[j][i] == k) == m
        v = Q(cert["extra"])
        assert sum(p * len(ids[j]) for j, p in mass.items()) == v
        price = iter(Q(r) for r in cert["dual"])
        base = next(price)
        local = [[next(price) for _ in range(k - 1)] + [Q(0)] for k in sizes]
        assert next(price, None) is None
        assert all(
            base + sum(local[i][k] for i, k in enumerate(w)) <= sign * len(ids[j])
            for j, w in enumerate(worlds)
        )
        assert (
            base
            + sum(
                pr * group[k][1]
                for group, l in zip(groups, local)
                for k, pr in enumerate(l)
            )
            == sign * v
        )
    return len(worlds)


def check(archive, directory):
    if not __debug__:
        raise RuntimeError("run without -O")
    import nltk
    from nltk.corpus import wordnet as wn

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")

    def read(folder, name):
        return [json.loads(l) for l in (folder / name).read_bytes().splitlines()]

    inputs = {
        (r["source"], r["sentence"]): r
        for r in read(ROOT, "shared-sense-ledger.jsonl")
        if r["shared"]
    }
    rows = read(directory, "cover-dependence-ledger.jsonl")
    states = 0
    with TemporaryDirectory() as temp:
        p = Path(temp) / "corpora"
        p.mkdir()
        shutil.copyfile(archive, p / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(w):
                return tuple(wn.synsets(w, pos="n"))

            @lru_cache(None)
            def ancestors(s):
                return set(v for path in s.hypernym_paths() for v in path[:-1])

            def relation(s, t):
                if s == t:
                    return 0
                if s in ancestors(t):
                    return 1
                if t in ancestors(s):
                    return 2
                return 3

            for row in rows:
                original = inputs.pop((row["source"], row["sentence"]))
                cover = set(original["cover_first_stage"])
                words = original["words"]
                assert list(row["groups"]) == sorted(cover) and row["paid"] == len(
                    cover
                )
                groups = []
                for u, choices in row["groups"].items():
                    neighbors = {
                        v
                        for a, b, _ in original["queries"]
                        if u in (a, b)
                        for v in (a, b)
                        if v != u and v not in cover
                    }
                    actual = Counter(
                        tuple(
                            sorted(
                                v
                                for v in neighbors
                                if len({relation(s, t) for t in senses(words[v])}) > 1
                            )
                        )
                        for s in senses(words[u])
                    )
                    expected = [
                        (k, Q(count, len(senses(words[u]))))
                        for k, count in sorted(actual.items())
                    ]
                    assert expected == [(tuple(k), Q(m)) for k, m in choices]
                    groups.append(expected)
                states += validate(groups, row)
                # Independently count edges and vertices in each nonconstant component.
                adjacent = {}
                for v in set().union(*(set(ids) for g in groups for ids, _ in g)):
                    probs = [sum(p for ids, p in g if v in ids) for g in groups]
                    if 1 in probs:
                        continue
                    for i, prob in enumerate(probs):
                        if prob:
                            adjacent.setdefault((0, i), set()).add((1, v))
                            adjacent.setdefault((1, v), set()).add((0, i))
                seen = set()
                forest = True
                for node in adjacent:
                    if node in seen:
                        continue
                    component = set()
                    pending = [node]
                    while pending:
                        n = pending.pop()
                        if n in component:
                            continue
                        component.add(n)
                        pending.extend(adjacent[n] - component)
                    seen.update(component)
                    forest &= sum(len(adjacent[n]) for n in component) == 2 * (
                        len(component) - 1
                    )
                tag = row["posthoc_forest_bounds"]
                assert (tag is not None) == forest
                if forest:
                    assert Q(tag["minimum_extra"]) == Q(row["minimum"]["extra"])
                    assert Q(tag["maximum_extra"]) == Q(row["maximum"]["extra"])
        finally:
            nltk.data.path.remove(temp)
    assert not inputs
    report = json.loads((directory / "cover-dependence-results.json").read_bytes())
    for src, s in report.items():
        subset = [r for r in rows if r["source"] == src]
        paid = sum(r["paid"] for r in subset)
        assert s["sentences"] == len(subset) and s["first_stage_cost"] == paid
        for k, total in s["total_with_first_stage"].items():
            assert Q(total) == paid + sum(
                Q(r[k]["extra"] if k in ("minimum", "maximum") else r[k])
                for r in subset
            )
        assert s["maximum_above_independent"] == sum(
            Q(r["maximum"]["extra"]) > Q(r["independent"]) for r in subset
        )
        assert s["local_upper_above_maximum"] == sum(
            Q(r["local_upper"]) > Q(r["maximum"]["extra"]) for r in subset
        )
        assert s["largest_compressed_state_count"] == max(r["worlds"] for r in subset)
        assert s["posthoc_certified_by_forest"] == sum(
            r["posthoc_forest_bounds"] is not None for r in subset
        )
    return {
        "verified_sentence_models": len(rows),
        "rational_primal_dual_certificates": 2 * len(rows),
        "joint_categories_checked": states,
        "labeled_simple_graphs_checked": small_graphs(),
        "signed_path_cycle_and_degenerate_checks": signed_tests(),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("results", type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.wordnet, a.results), indent=2))
