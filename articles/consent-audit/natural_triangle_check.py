"""Independent raw-corpus triangle census, NLTK relationship replay and rational certificate verification."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import json
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify


def check(wordnet, semcor, wsd, folder):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError

    for path, sha in (
        (wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f"),
        (semcor, "19cdf8d8b1377016e9a0c3ec2a3147df1a778727"),
        (wsd / "ALL.data.xml", "7d5cb8f9f6a1055091976a6816288a621475b41f"),
        (wsd / "ALL.gold.key.txt", "d5bd595ebb0d83a149f8a2dc09851f23fc1521f1"),
    ):
        verify(path, sha)

    def lines(path):
        return [json.loads(l) for l in path.read_bytes().splitlines()]

    plans = {
        tuple(r["words"]): r for r in lines(folder / "natural-triangle-plans.jsonl")
    }
    cases = {
        (r["source"], r["sentence"], tuple(r["ids"])): r
        for r in lines(folder / "natural-triangle-cases.jsonl")
    }
    old = {
        (r["source"], r["sentence"])
        for r in lines(ROOT / "shared-sense-ledger.jsonl")
        if r["shared"]
    }
    report = json.loads((folder / "natural-triangle-results.json").read_bytes())
    seen = set()
    totals = defaultdict(Counter)
    unique = defaultdict(lambda: defaultdict(set))
    with TemporaryDirectory() as temp:
        p = Path(temp) / "corpora"
        p.mkdir()
        shutil.copyfile(wordnet, p / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:

            @lru_cache(None)
            def senses(u):
                return {s.offset(): s for s in wn.synsets(u, pos="n")}

            @lru_cache(None)
            def ancestors(x):
                return {a.offset() for path in x.hypernym_paths() for a in path[:-1]}

            def relation(x, y):
                if x == y:
                    return "same"
                if y.offset() in ancestors(x):
                    return "left_narrower"
                if x.offset() in ancestors(y):
                    return "right_narrower"
                return "neither"

            @lru_cache(80000)
            def needed(u, v):
                values = set()
                for x in senses(u).values():
                    for y in senses(v).values():
                        values.add(relation(x, y))
                        if len(values) > 1:
                            return True
                return False

            @lru_cache(None)
            def mapped(key):
                if "%1:" not in key or key.count(":") != 4 or key.count("%") != 1:
                    return None
                try:
                    lemma = wn.lemma_from_key(key)
                except (WordNetError, KeyError, ValueError):
                    return None
                return lemma.synset().offset() if lemma.key() == key else None

            def collect(src, sent, tokens):
                group = "previous" if (src, sent) in old else "new"
                k = (src, group)
                ag = totals[k]
                sets = unique[k]
                ag["all_sentences"] += 1
                eligible = sorted(
                    (u, ident, x)
                    for u, ident, x in tokens
                    if x in senses(u) and len(senses(u)) >= 2
                )
                ag["eligible_noun_positions"] += len(eligible)
                groups = defaultdict(list)
                for u, ident, x in eligible:
                    groups[u].append((ident, x))
                # Count occurrence triples from products of type counts; find triangles by joining informative pairs.
                for a, b, c in combinations(groups, 3):
                    ag["distinct_lemma_position_triples"] += (
                        len(groups[a]) * len(groups[b]) * len(groups[c])
                    )
                adj = {u: set() for u in groups}
                for u, v in combinations(groups, 2):
                    if needed(u, v):
                        adj[u].add(v)
                        adj[v].add(u)
                for u in adj:
                    for v in adj[u]:
                        if u >= v:
                            continue
                        for w in adj[u] & adj[v]:
                            if v >= w:
                                continue
                            names = (u, v, w)
                            t = plans[names]
                            seen.add(names)
                            options, forces = build(names)
                            if names not in certified:
                                certify(names, t, options)
                                certified.add(names)
                            for xs in product(*(groups[a] for a in names)):
                                ids, offsets = zip(*xs)
                                row = cases.pop((src, sent, ids))
                                assert (
                                    row["words"] == list(names)
                                    and row["truth"] == list(offsets)
                                    and row["group"] == group
                                )
                                labels = [
                                    relation(
                                        senses(a)[offsets[i]], senses(b)[offsets[j]]
                                    )
                                    for (i, a), (j, b) in combinations(
                                        enumerate(names), 2
                                    )
                                ]
                                assert row["labels"] == labels
                                forced = set().union(
                                    *(forces[i][x] for i, x in enumerate(offsets))
                                )
                                actual = sum(
                                    Q(m) * len(set(c) | forced) for c, m in t["mixture"]
                                )
                                pure = 2 + int(t["pure_omit"] in forced)
                                assert (
                                    actual == Q(row["gold_mixed"])
                                    and pure == row["gold_pure"]
                                )
                                ag["triangles"] += 1
                                ag["gold_mixed"] += actual
                                ag["gold_pure"] += pure
                                ag["pure_worst"] += Q(t["pure"])
                                ag["mixed_worst"] += Q(t["value"])
                                sets["sentences_with_triangle"].add(sent)
                                sets["different_word_triples"].add(names)
                                if Q(t["value"]) < Q(t["pure"]):
                                    ag["strict_triangles"] += 1
                                    sets["strict_sentences"].add(sent)
                                    sets["strict_word_triples"].add(names)

            @lru_cache(None)
            def build(names):
                groups = []
                forces = []
                for u in names:
                    table = {
                        i: {
                            v
                            for v in names
                            if v != u
                            and len({relation(x, y) for y in senses(v).values()}) > 1
                        }
                        for i, x in senses(u).items()
                    }
                    freq = Counter(tuple(sorted(f)) for f in table.values())
                    groups.append(
                        [(set(f), Q(n, len(table))) for f, n in sorted(freq.items())]
                    )
                    forces.append(table)
                return groups, forces

            certified = set()

            def certify(names, t, groups):
                assert t["sources"] == list(names) and t["covers"] == 3
                value = Q(t["value"])
                law = {tuple(w): Q(m) for w, m in t["adverse"]}
                worlds = list(product(*(range(len(g)) for g in groups)))
                assert (
                    t["world_count"] == len(worlds)
                    and law.keys() <= set(worlds)
                    and min(law.values()) > 0
                    and sum(law.values()) == 1
                )
                for i, g in enumerate(groups):
                    for j, (_, p) in enumerate(g):
                        assert sum(m for w, m in law.items() if w[i] == j) == p
                forced = {
                    w: set().union(*(g[j][0] for j, g in zip(w, groups)))
                    for w in worlds
                }
                assert (
                    min(
                        2 + sum(m for w, m in law.items() if u in forced[w])
                        for u in names
                    )
                    == value
                )
                mix = {tuple(c): Q(m) for c, m in t["mixture"]}
                assert (
                    all(
                        len(c) == 2
                        and len(set(c)) == 2
                        and set(c) <= set(names)
                        and m > 0
                        for c, m in mix.items()
                    )
                    and sum(mix.values()) == 1
                )
                prices = list(map(Q, t["prices"]))
                base = prices.pop(0)
                parts = []
                for g in groups:
                    parts.append(prices[: len(g) - 1] + [Q(0)])
                    del prices[: len(g) - 1]
                assert (
                    not prices
                    and base
                    + sum(
                        y * p
                        for ys, g in zip(parts, groups)
                        for y, (_, p) in zip(ys, g)
                    )
                    == value
                )
                for w, f in forced.items():
                    assert base + sum(y[j] for y, j in zip(parts, w)) >= sum(
                        m * len(set(c) | f) for c, m in mix.items()
                    )
                pure = {
                    u: 2 + min(1, sum(p for g in groups for f, p in g if u in f))
                    for u in names
                }
                chosen = min(names, key=lambda u: (pure[u], u))
                assert t["pure_omit"] == chosen and pure[chosen] == Q(t["pure"])
                if pure[chosen] == value:
                    assert mix == {tuple(u for u in names if u != chosen): 1}

            answers = {}
            for l in (wsd / "ALL.gold.key.txt").read_text(encoding="utf8").splitlines():
                ident, *keys = l.split()
                xs = {mapped(key) for key in keys}
                if len(xs) == 1 and None not in xs:
                    answers[ident] = xs.pop()
            for _, node in ET.iterparse(wsd / "ALL.data.xml"):
                if node.tag == "sentence":
                    ts = [
                        (x.get("lemma"), x.get("id"), answers[x.get("id")])
                        for x in node
                        if x.tag == "instance"
                        and x.get("pos") == "NOUN"
                        and x.get("id") in answers
                    ]
                    collect("wsd", node.get("id"), ts)
                    node.clear()
            with ZipFile(semcor) as z:
                for item in z.infolist():
                    if item.is_dir() or "/tagfiles/" not in item.filename:
                        continue
                    with z.open(item) as f:
                        sn = 0
                        for _, node in ET.iterparse(f):
                            if node.tag != "s":
                                continue
                            sn += 1
                            ts = []
                            for j, x in enumerate(node, 1):
                                lemma = x.get("lemma", "")
                                off = mapped(lemma + "%" + x.get("lexsn", ""))
                                if off is not None:
                                    ts.append((lemma, f"{j:04d}", off))
                            collect("semcor", item.filename + "/" + str(sn), ts)
                            node.clear()
            assert not cases and set(plans) == seen
            for (src, group), ag in totals.items():
                expected = report[src][group]
                for field, val in expected.items():
                    value = (
                        len(unique[src, group][field])
                        if field
                        in (
                            "sentences_with_triangle",
                            "different_word_triples",
                            "strict_sentences",
                            "strict_word_triples",
                        )
                        else ag[field]
                    )
                    assert Q(val) == value, (src, group, field, val, str(value))
            print(
                f"{len(certified)} type certificates; {sum(r['triangles'] for r in totals.values())} occurrence triples; {sum(r['all_sentences'] for r in totals.values())} raw sentence units verified"
            )
        finally:
            nltk.data.path.remove(temp)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "wsd", "folder"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    check(a.wordnet, a.semcor, a.wsd, a.folder)
