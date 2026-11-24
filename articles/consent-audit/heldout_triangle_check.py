"""Verify held-out counts, rational games, deployed query traces and preregistered scores."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
from pathlib import Path
import json
import shutil
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from calibrated_triangle import TriangleInquiry
from go_model_fetch import verify
from natural_triangle_check import certify
from wordnet_paths import NounPaths


def check(wordnet, semcor, folder):
    if not __debug__:
        raise RuntimeError("enable assertions")
    import nltk
    from nltk.corpus import wordnet as wn
    from nltk.corpus.reader.wordnet import WordNetError

    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    verify(semcor, "19cdf8d8b1377016e9a0c3ec2a3147df1a778727")

    def lines(path):
        return [json.loads(l) for l in path.read_bytes().splitlines()]

    contexts = lines(folder / "heldout-triangle-plans.jsonl")
    old = lines(ROOT / "natural-triangle-cases.jsonl")
    rows = lines(folder / "heldout-triangle-cases.jsonl")
    assert len(old) == len(rows)
    words = {u for t in contexts for u in t["sources"]}
    trace_count = 0
    totals = defaultdict(list)
    deployed = {}
    graph = NounPaths(wordnet)
    with TemporaryDirectory() as temp:
        d = Path(temp) / "corpora"
        d.mkdir()
        shutil.copyfile(wordnet, d / "wordnet.zip")
        nltk.data.path.insert(0, temp)
        try:
            by_sense = defaultdict(Counter)

            @lru_cache(None)
            def offset(key):
                try:
                    lemma = wn.lemma_from_key(key)
                except (WordNetError, KeyError, ValueError):
                    return None
                return lemma.synset().offset() if lemma.key() == key else None

            with ZipFile(semcor) as z:
                for info in z.infolist():
                    if info.is_dir() or "/tagfiles/" not in info.filename:
                        continue
                    with z.open(info) as stream:
                        for _, node in ET.iterparse(stream):
                            if node.tag != "s":
                                continue
                            for x in node:
                                word = x.get("lemma")
                                sense = x.get("lexsn", "")
                                if (
                                    word not in words
                                    or not sense.startswith("1:")
                                    or sense.count(":") != 4
                                ):
                                    continue
                                syn = offset(word + "%" + sense)
                                if syn is not None:
                                    by_sense[word, syn][info.filename] += 1
                            node.clear()

            @lru_cache(None)
            def domain(u):
                return {s.offset(): s for s in wn.synsets(u, pos="n")}

            @lru_cache(None)
            def ancestors(x):
                return {s for path in x.hypernym_paths() for s in path[:-1]}

            def label(x, y):
                if x == y:
                    return 0
                if x in ancestors(y):
                    return 1
                if y in ancestors(x):
                    return 2
                return 3

            @lru_cache(None)
            def unresolved(u, x, v):
                return len({label(domain(u)[x], y) for y in domain(v).values()}) > 1

            for i, t in enumerate(contexts):
                names = tuple(t["sources"])
                assert t["index"] == i
                groups = []
                for u in names:
                    counted = {
                        x: sum(
                            n
                            for doc, n in by_sense[u, x].items()
                            if t["source"] != "semcor" or doc != t["doc"]
                        )
                        for x in domain(u)
                    }
                    assert counted == {int(x): n for x, n in t["training"][u].items()}
                    freq = Counter()
                    for x, n in counted.items():
                        freq[
                            tuple(v for v in names if u != v and unresolved(u, x, v))
                        ] += n + 1
                    groups.append(
                        [
                            (set(opts), Q(n, freq.total()))
                            for opts, n in sorted(freq.items())
                        ]
                    )
                certify(names, t, groups)
                prodcost = {
                    v: sum(
                        p1 * p2 * p3 * (2 + int(v in a | b | c))
                        for (a, p1), (b, p2), (c, p3) in product(*groups)
                    )
                    for v in names
                }
                assert t["independent_omit"] == min(
                    names, key=lambda u: (prodcost[u], u)
                )
                inquiry = TriangleInquiry(graph, t["training"])
                assert inquiry.omit == t["pure_omit"] and inquiry.worst_cost == Q(
                    t["pure"]
                )
                deployed[i] = inquiry
            used = set()
            for t, r in zip(old, rows):
                assert all(r[k] == t[k] for k in ("source", "sentence", "group", "ids"))
                i = r["context"]
                used.add(i)
                ctx = contexts[i]
                assert t["words"] == ctx["sources"] and t["source"] == ctx["source"]
                assert (
                    t["sentence"].rsplit("/" if t["source"] == "semcor" else ".", 1)[0]
                    == ctx["doc"]
                )
                truth = dict(zip(t["words"], t["truth"]))
                costs = {}
                for u in truth:
                    observed = []

                    def ask(batch):
                        assert not set(observed).intersection(batch)
                        observed.extend(batch)
                        return {v: truth[v] for v in batch}

                    res = deployed[i].execute(ask, omit=u)
                    assert [s[2] for s in res["relations"]] == t["labels"]
                    assert res["batches"][0] == [v for v in t["words"] if v != u]
                    costs[u] = len(observed)
                    trace_count += 1
                assert (
                    r["uniform_pure"] == t["gold_pure"]
                    and r["pure"] == costs[ctx["pure_omit"]]
                    and r["independent"] == costs[ctx["independent_omit"]]
                )
                assert Q(r["mixed"]) == sum(
                    Q(p) * costs[next(u for u in truth if u not in c)]
                    for c, p in ctx["mixture"]
                )
                totals[t["source"], t["group"]].append(r)
            assert used == set(range(len(contexts)))
        finally:
            nltk.data.path.remove(temp)
    report = json.loads((folder / "heldout-triangle-results.json").read_bytes())
    for src in ("wsd", "semcor"):
        for fold in ("new", "previous"):
            sel = totals[src, fold]
            ts = [contexts[r["context"]] for r in sel]
            strict = [t for t in ts if Q(t["pure"]) > Q(t["value"])]
            docs = len({t["doc"] for t in strict})
            gold = sum(r["pure"] for r in sel)
            mix = sum(Q(r["mixed"]) for r in sel)
            gain = gold - mix
            sizes = [sum(c.values()) for t in ts for c in t["training"].values()]

            def unobserved(t):
                return any(min(c.values()) == 0 for c in t["training"].values())

            doc_changes = defaultdict(list)
            for r in sel:
                doc_changes[contexts[r["context"]]["doc"]].append(
                    r["uniform_pure"] - r["pure"]
                )
            changes = [sum(nums) for nums in doc_changes.values()]
            expected = {
                "uniform_to_fitted_documents": {
                    "fewer": sum(n > 0 for n in changes),
                    "equal": changes.count(0),
                    "more": sum(n < 0 for n in changes),
                },
                "occurrences": len(sel),
                "type_count": len({tuple(t["sources"]) for t in ts}),
                "strict_instances": len(strict),
                "strict_types": len({tuple(t["sources"]) for t in strict}),
                "strict_documents": docs,
                "min_nonheldout_word_count": min(sizes, default=None),
                "max_nonheldout_word_count": max(sizes, default=None),
                "instances_with_unseen_sense": sum(map(unobserved, ts)),
                "strict_with_unseen_sense": sum(map(unobserved, strict)),
                "robust_gain": str(sum(Q(t["pure"]) - Q(t["value"]) for t in ts)),
                "gold_ask_all": 3 * len(sel),
                "gold_uniform_pure": sum(r["uniform_pure"] for r in sel),
                "gold_independent": sum(r["independent"] for r in sel),
                "gold_pure": gold,
                "gold_mixed": str(mix),
                "gold_gain": str(gain),
                "at_least_one_percent": bool(sel) and gain >= Q(gold, 100),
                "passes_registered_gate": docs >= 2 and gain >= 1,
            }
            assert expected == report[src][fold], (src, fold)
    print(
        f"{len(contexts)} document/type fits independently recounted and certified; {len(rows)} occurrence records; {trace_count} deployed clarification traces verified"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("wordnet", "semcor", "folder"):
        p.add_argument(n, type=Path)
    a = p.parse_args()
    check(a.wordnet, a.semcor, a.folder)
