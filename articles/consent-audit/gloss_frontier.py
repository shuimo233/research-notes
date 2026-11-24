"""Prospective replication on manually sense-tagged Princeton WordNet Gloss Corpus definitions."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
import hashlib
from itertools import combinations, product
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from calibrated_triangle import TriangleInquiry
from frontier_information import compare_profiles
from frontier_run import compile_task
from go_model_fetch import verify
from wordnet_paths import NounPaths

GLOSS_SHA = "a9233e1d0e1f4d11c5959c36fbe4d021aa4cb4e0bae0a348af118f4df6d558b6"
STRATA = ("noun", "verb", "adj", "adv")


def single_words(node):
    for child in node:
        if child.tag == "wf":
            yield child
        elif child.tag not in ("cf", "glob", "mwf", "ex"):
            yield from single_words(child)


def run(wordnet, semcor, glosses, out):
    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    verify(semcor, "19cdf8d8b1377016e9a0c3ec2a3147df1a778727")
    with glosses.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != GLOSS_SHA:
            raise ValueError("wrong Gloss Corpus release")
    graph = NounPaths(wordnet)
    senses = lru_cache(None)(graph.senses)
    with ZipFile(wordnet) as z:
        index = {
            k: int(x)
            for k, x, _, _ in (
                s.split() for s in z.read("wordnet/index.sense").decode().splitlines()
            )
            if "%1:" in k
        }
    training = defaultdict(Counter)
    with ZipFile(semcor) as z:
        for doc in z.namelist():
            if not doc.endswith("/") and "/tagfiles/" in doc:
                with z.open(doc) as f:
                    for _, node in ET.iterparse(f):
                        if node.tag != "s":
                            continue
                        for w in node:
                            lemma = w.get("lemma", "")
                            key = lemma + "%" + w.get("lexsn", "")
                            if key in index and index[key] in senses(lemma):
                                training[lemma][index[key]] += 1
                        node.clear()

    @lru_cache(100000)
    def needed(a, b):
        kinds = {graph.relation(x, y) for x, y in product(senses(a), senses(b))}
        return len(kinds) > 1

    @lru_cache(None)
    def local(a, b, c):
        return TriangleInquiry(graph, {w: training[w] for w in (a, b, c)})

    records = []
    counts = {s: Counter() for s in STRATA}
    with ZipFile(glosses) as z:
        for source in STRATA:
            filename = f"WordNet-3.0/glosstag/merged/{source}.xml"
            census = counts[source]
            with z.open(filename) as f:
                for _, syn in ET.iterparse(f):
                    if syn.tag != "synset":
                        continue
                    for definition in syn.findall("./gloss[@desc='wsd']/def"):
                        census["definitions"] += 1
                        mentions = []
                        for num, w in enumerate(single_words(definition)):
                            if w.get("tag") != "man" or not w.get("pos", "").startswith(
                                "NN"
                            ):
                                continue
                            lemmas = {
                                s[:-2]
                                for s in w.get("lemma", "").split("|")
                                if s.endswith("%1")
                            }
                            if len(lemmas) != 1:
                                continue
                            lemma = lemmas.pop()
                            keys = [s.get("sk", "") for s in w.findall("id")]
                            if not keys or not all(
                                k in index and k.startswith(lemma + "%1:") for k in keys
                            ):
                                continue
                            xs = {index[k] for k in keys}
                            if (
                                len(xs) != 1
                                or len(senses(lemma)) < 2
                                or not xs <= senses(lemma)
                            ):
                                continue
                            mentions.append(
                                (f"{num:05d}", w.get("id"), lemma, xs.pop())
                            )
                        census["eligible_positions"] += len(mentions)
                        triangles = []
                        for trio in combinations(mentions, 3):
                            names = [x[2] for x in trio]
                            if len(set(names)) != 3:
                                continue
                            census["distinct_lemma_triples"] += 1
                            if all(
                                needed(*sorted(pair)) for pair in combinations(names, 2)
                            ):
                                triangles.append(trio)
                        if not triangles:
                            continue
                        positions = {t[0]: t for tri in triangles for t in tri}
                        task = {
                            "words": {i: w for i, _, w, _ in positions.values()},
                            "truth": {i: x for i, _, _, x in positions.values()},
                            "counts": {
                                w: {str(x): training[w][x] for x in senses(w)}
                                for _, _, w, _ in positions.values()
                            },
                            "edges": {
                                (a[0], b[0])
                                for tri in triangles
                                for a, b in combinations(tri, 2)
                            },
                        }
                        service = compile_task(graph, task)
                        planner = service.plan
                        truth = task["truth"]
                        gold = {
                            e: graph.relation(truth[e[0]], truth[e[1]])
                            for e in task["edges"]
                        }
                        row = {
                            "stratum": source,
                            "definition": definition.get("id"),
                            "positions": sorted(positions.values()),
                            "triangles": [[v[0] for v in t] for t in triangles],
                            "edges": sorted(task["edges"]),
                            "labels": [gold[e] for e in sorted(gold)],
                        }
                        cache = {}
                        for trio in triangles:
                            ids = {w: i for i, _, w, _ in trio}
                            inq = local(*sorted(ids))
                            known = {w: cache[i] for w, i in ids.items() if i in cache}

                            def ask(batch):
                                assert all(ids[w] not in cache for w in batch)
                                cache.update((ids[w], truth[ids[w]]) for w in batch)
                                return {w: truth[ids[w]] for w in batch}

                            ans = inq.execute(ask, known=known)
                            assert all(
                                val == graph.relation(truth[ids[u]], truth[ids[v]])
                                for u, v, val in ans["relations"]
                            )
                        row["cached"] = list(cache)
                        row["oracle"] = service.service.certificate(truth)
                        exp = planner.root_value(4096)
                        row["expected_optimal"] = None if exp is None else str(exp)
                        row["expected_fixed"] = str(planner.fixed_cover()[1])
                        for method in ("fixed", "greedy", "optimal"):
                            path, answers, fallback = service.execute(
                                truth.__getitem__, method, limit=4096
                            )
                            assert answers == gold and len(path) >= len(row["oracle"])
                            row[method] = path
                            if method == "optimal":
                                row["fallback_decisions"] = fallback
                        if exp is not None:
                            row["information"] = compare_profiles(
                                graph, service, task, row["optimal"], exp
                            )
                        records.append(row)
                    syn.clear()

    def describe(rows, census):
        total = {
            k: sum(len(r[k]) for r in rows)
            for k in ("cached", "greedy", "fixed", "optimal", "oracle")
        }
        ex = [r for r in rows if "information" in r]
        measures = {}
        for mode in ("block", "independent", "nested"):
            ds = [
                Q(r["information"][mode]["actual_expected"]) - Q(r["expected_optimal"])
                for r in ex
            ]
            measures[mode] = {
                "incorrect_forecast": sum(
                    r["information"][mode]["forecast"] != r["expected_optimal"]
                    for r in ex
                ),
                "strict_expected_regret": sum(d > 0 for d in ds),
                "total_expected_regret": str(sum(ds)),
                "gold_queries": sum(r["information"][mode]["queries"] for r in ex),
            }
        return {
            **{
                k: census[k]
                for k in ("definitions", "eligible_positions", "distinct_lemma_triples")
            },
            "qualifying_definitions": len(rows),
            "triangles": sum(len(r["triangles"]) for r in rows),
            "shared_position_definitions": sum(
                3 * len(r["triangles"]) > len(r["positions"]) for r in rows
            ),
            "exact_roots": len(ex),
            "fallback_definitions": sum(bool(r["fallback_decisions"]) for r in rows),
            **total,
            "expected_fixed_on_exact": str(sum(Q(r["expected_fixed"]) for r in ex)),
            "expected_optimal_on_exact": str(sum(Q(r["expected_optimal"]) for r in ex)),
            "fewer_than_cached": sum(
                len(r["optimal"]) < len(r["cached"]) for r in rows
            ),
            "more_than_cached": sum(len(r["optimal"]) > len(r["cached"]) for r in rows),
            "primary_gate": bool(rows)
            and total["optimal"] * 100 <= 99 * total["cached"]
            and total["optimal"] < total["greedy"],
            "information": measures,
            "mechanism_gate": any(
                measures[m]["strict_expected_regret"] > 1
                for m in ("independent", "nested")
            ),
        }

    report = {
        s: describe([r for r in records if r["stratum"] == s], counts[s])
        for s in STRATA
    }
    report["all"] = describe(records, sum(counts.values(), Counter()))
    out.mkdir(parents=True, exist_ok=False)
    (out / "gloss-frontier-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    (out / "gloss-frontier-ledger.jsonl").write_bytes(
        ("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)).encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for n in ("wordnet", "semcor", "glosses", "out"):
        p.add_argument(n, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.semcor, a.glosses, a.out), indent=2))
