"""Independently rebuild game tables with NLTK and verify both rational bounds without using an optimizer."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from math import prod
from pathlib import Path
import json
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify


def check(archive, results):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn

    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    with TemporaryDirectory() as temp:
        corpora = Path(temp) / "corpora"
        corpora.mkdir()
        shutil.copyfile(archive, corpora / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(word):
                return tuple(wn.synsets(word, pos="n"))

            @lru_cache(None)
            def ancestors(s):
                return {a for path in s.hypernym_paths() for a in path[:-1]}

            def rel(x, y):
                if x == y:
                    return "same"
                if y in ancestors(x):
                    return "left_narrower"
                if x in ancestors(y):
                    return "right_narrower"
                return "neither"

            def rows(path):
                return [json.loads(l) for l in path.read_bytes().splitlines()]

            tasks = {
                (t["source"], t["sentence"]): t
                for t in rows(ROOT / "shared-sense-ledger.jsonl")
                if t["shared"]
            }
            old = {
                (t["source"], t["sentence"]): t
                for t in rows(ROOT / "coupling-witness-ledger.jsonl")
            }
            totals = {}
            for r in rows(results / "mixed-cover-ledger.jsonl"):
                s = r["source"]
                t = tasks.pop((s, r["sentence"]))
                names = sorted(t["words"])
                assert names == r["sources"]
                tables = {u: {x: set() for x in senses(t["words"][u])} for u in names}
                edges = []
                for u, v, label in t["queries"]:
                    tab = {(x, y): rel(x, y) for x, y in product(tables[u], tables[v])}
                    assert {
                        f
                        for (x, y), f in tab.items()
                        if (x.offset(), y.offset()) == (t["truth"][u], t["truth"][v])
                    } == {label}
                    if len(set(tab.values())) > 1:
                        edges.append({u, v})
                    for a, b, side in ((u, v, 0), (v, u, 1)):
                        for x, triggers in tables[a].items():
                            if (
                                len({f for pair, f in tab.items() if pair[side] == x})
                                > 1
                            ):
                                triggers.add(b)
                options = []
                observed = set()
                for u in names:
                    freq = Counter(
                        tuple(sorted(forced)) for forced in tables[u].values()
                    )
                    options.append(
                        [
                            (set(f), Q(count, len(tables[u])))
                            for f, count in sorted(freq.items())
                        ]
                    )
                    observed.update(
                        next(
                            forced
                            for x, forced in tables[u].items()
                            if x.offset() == t["truth"][u]
                        )
                    )
                masks = [
                    set(c)
                    for n in range(len(names) + 1)
                    for c in combinations(names, n)
                    if all(set(c) & e for e in edges)
                ]
                covers = [c for c in masks if not any(a < c for a in masks)]
                assert len(covers) == r["covers"]
                worlds = list(product(*(range(len(g)) for g in options)))
                assert len(worlds) == r["world_count"]
                forced = {
                    w: set().union(*(g[k][0] for g, k in zip(options, w)))
                    for w in worlds
                }
                law = {tuple(w): Q(p) for w, p in r["adverse"]}
                assert (
                    len(law) == len(r["adverse"])
                    and law.keys() <= forced.keys()
                    and sum(law.values()) == 1
                    and all(p > 0 for p in law.values())
                )
                for i, g in enumerate(options):
                    for j, (_, p) in enumerate(g):
                        assert sum(m for w, m in law.items() if w[i] == j) == p
                expected = {
                    u: sum(m for w, m in law.items() if u in forced[w]) for u in names
                }
                value = Q(r["value"])
                assert (
                    min(
                        len(c) + sum(expected[u] for u in names if u not in c)
                        for c in masks
                    )
                    == value
                )
                plans = [(set(c), Q(m)) for c, m in r["mixture"]]
                assert (
                    all(c in covers and m > 0 for c, m in plans)
                    and sum(m for _, m in plans) == 1
                )
                price = list(map(Q, r["prices"]))
                assert len(price) == 1 + sum(len(g) - 1 for g in options)
                offset = 1
                entries = []
                average = price[0]
                for g in options:
                    entry = price[offset : offset + len(g) - 1] + [Q(0)]
                    average += sum(y * p for y, (_, p) in zip(entry, g))
                    entries.append(entry)
                    offset += len(g) - 1
                assert average == value
                for w, f in forced.items():
                    assert price[0] + sum(row[k] for row, k in zip(entries, w)) >= sum(
                        m * len(c | f) for c, m in plans
                    )
                independent = {
                    u: 1 - prod(1 - sum(p for f, p in g if u in f) for g in options)
                    for u in names
                }
                ed = min(
                    len(c) + sum(independent[u] for u in names if u not in c)
                    for c in covers
                )
                assert ed == Q(r["independent"])
                adjacent = {}
                for u in names:
                    chances = [sum(p for f, p in g if u in f) for g in options]
                    if 1 in chances:
                        continue
                    for v, chance in zip(names, chances):
                        if chance:
                            a, b = ("target", u), ("source", v)
                            adjacent.setdefault(a, set()).add(b)
                            adjacent.setdefault(b, set()).add(a)
                leaves = [u for u, vs in adjacent.items() if len(vs) <= 1]
                while leaves:
                    u = leaves.pop()
                    for v in adjacent.pop(u, set()):
                        adjacent[v].discard(u)
                        if len(adjacent[v]) == 1:
                            leaves.append(v)
                assert r["forest"] == (not adjacent)
                # Cross-check pure comparison against the previously published, independently certified transport extrema.
                ref = old.pop((s, t["sentence"]))
                pc = ref["plans"][ref["chosen"]["maximum"]]
                assert r["pure_cover"] == pc["cover"] and Q(r["pure"]) == min(
                    len(p["cover"]) + Q(p["maximum"]["extra"]) for p in ref["plans"]
                )
                gold = sum(m * len(c | observed) for c, m in plans)
                assert (
                    gold == Q(r["observed"])
                    and len(set(r["pure_cover"]) | observed) == r["pure_observed"]
                )
                ag = totals.setdefault(s, Counter())
                ag.update(
                    {
                        "sentences": 1,
                        "covers": len(covers),
                        "joint_categories_checked": len(worlds),
                        "strict_improvements": int(value < Q(r["pure"])),
                        "full_forest": int(r["forest"]),
                        "independent_bound_tight": int(ed == value),
                        "pure_worst": Q(r["pure"]),
                        "mixed_worst": value,
                        "independent_optimum": ed,
                        "gold_pure": r["pure_observed"],
                        "gold_mixed": gold,
                    }
                )
                ag["largest_joint_space"] = max(ag["largest_joint_space"], len(worlds))
            assert not tasks and not old
            report = json.loads((results / "mixed-cover-results.json").read_bytes())
            assert set(report) == set(totals)
            for s, ag in totals.items():
                assert {k: Q(v) for k, v in report[s].items()} == dict(ag)
            print(
                "Verified",
                sum(a["sentences"] for a in totals.values()),
                "sentence saddle points and",
                sum(a["joint_categories_checked"] for a in totals.values()),
                "joint-category upper inequalities.",
            )
        finally:
            nltk.data.path.remove(temp)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("results", type=Path)
    args = p.parse_args()
    check(args.wordnet, args.results)
