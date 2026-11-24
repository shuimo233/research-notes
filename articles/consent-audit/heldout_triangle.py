"""Fit sense marginals outside each document and evaluate frozen three-position planning tasks."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from math import prod
from pathlib import Path
import json
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from mixed_sense_game import solve
from wordnet_paths import NounPaths
from go_model_fetch import verify
from semcor_clarification import W_DIGEST, S_DIGEST


def run(wordnet, semcor, destination):
    verify(wordnet, W_DIGEST)
    verify(semcor, S_DIGEST)
    cases = [
        json.loads(l)
        for l in (ROOT / "natural-triangle-cases.jsonl").read_bytes().splitlines()
    ]
    words = {u for r in cases for u in r["words"]}
    graph = NounPaths(wordnet)
    candidates = {u: sorted(graph.senses(u)) for u in words}
    with ZipFile(wordnet) as z:
        index = {
            key: int(off)
            for key, off, _, _ in (
                s.split() for s in z.read("wordnet/index.sense").decode().splitlines()
            )
            if "%1:" in key and key.split("%")[0] in words
        }
    all_counts = Counter()
    docs = defaultdict(Counter)
    with ZipFile(semcor) as z:
        for doc in sorted(
            n for n in z.namelist() if "/tagfiles/" in n and not n.endswith("/")
        ):
            with z.open(doc) as stream:
                root = ET.parse(stream)
            for sent in root.iter("s"):
                for node in sent:
                    u = node.get("lemma", "")
                    if u not in words:
                        continue
                    x = index.get(u + "%" + node.get("lexsn", ""))
                    if x in candidates[u]:
                        all_counts[u, x] += 1
                        docs[doc][u, x] += 1

    @lru_cache(None)
    def triggers(u, x, v):
        return len({graph.relation(x, y) for y in candidates[v]}) > 1

    contexts = {}
    rows = []
    for r in cases:
        names = tuple(r["words"])
        src = r["source"]
        doc = r["sentence"].rsplit("/" if src == "semcor" else ".", 1)[0]
        key = (src, doc, names)
        if key not in contexts:
            excluded = docs[doc] if src == "semcor" else {}
            training = {
                u: {
                    x: all_counts[u, x] - excluded.get((u, x), 0) for x in candidates[u]
                }
                for u in names
            }
            groups = {}
            for u, counts in training.items():
                total = sum(counts.values()) + len(counts)
                groups[u] = [
                    (
                        tuple(v for v in names if u != v and triggers(u, x, v)),
                        Q(n + 1, total),
                    )
                    for x, n in counts.items()
                ]
            pure = {
                v: 2 + min(1, sum(p for g in groups.values() for f, p in g if v in f))
                for v in names
            }
            independent = {
                v: 3 - prod(1 - sum(p for f, p in g if v in f) for g in groups.values())
                for v in names
            }
            independent_omit = min(names, key=lambda u: (independent[u], u))
            best = min(names, key=lambda u: (pure[u], u))
            game = solve(groups, [u for u in names if u != best])
            contexts[key] = {
                "index": len(contexts),
                "source": src,
                "doc": doc,
                "training": training,
                "independent_omit": independent_omit,
                "pure_omit": best,
                "pure": str(pure[best]),
                **game,
            }
        ctx = contexts[key]
        payoff = {
            v: 2
            + int(any(triggers(u, x, v) for u, x in zip(names, r["truth"]) if u != v))
            for v in names
        }
        mixed = sum(
            Q(p) * payoff[next(v for v in names if v not in c)]
            for c, p in ctx["mixture"]
        )
        rows.append(
            {
                "source": src,
                "sentence": r["sentence"],
                "group": r["group"],
                "ids": r["ids"],
                "context": ctx["index"],
                "uniform_pure": r["gold_pure"],
                "independent": payoff[ctx["independent_omit"]],
                "pure": payoff[ctx["pure_omit"]],
                "mixed": str(mixed),
            }
        )
    policies = list(contexts.values())
    report = {}
    for source in ("semcor", "wsd"):
        report[source] = {}
        for fold in ("new", "previous"):
            selected = [r for r in rows if (r["source"], r["group"]) == (source, fold)]
            tasks = [policies[r["context"]] for r in selected]
            strict = [t for t in tasks if Q(t["pure"]) > Q(t["value"])]
            support = [
                sum(counts.values()) for t in tasks for counts in t["training"].values()
            ]

            def unseen(t):
                return any(0 in counts.values() for counts in t["training"].values())

            gold_pure = sum(r["pure"] for r in selected)
            gold_mixed = sum(Q(r["mixed"]) for r in selected)
            gain = gold_pure - gold_mixed
            per_document = Counter()
            for row, task in zip(selected, tasks):
                per_document[task["doc"]] += row["uniform_pure"] - row["pure"]
            report[source][fold] = {
                "uniform_to_fitted_documents": {
                    "fewer": sum(n > 0 for n in per_document.values()),
                    "equal": sum(n == 0 for n in per_document.values()),
                    "more": sum(n < 0 for n in per_document.values()),
                },
                "occurrences": len(tasks),
                "type_count": len({tuple(t["sources"]) for t in tasks}),
                "strict_instances": len(strict),
                "strict_types": len({tuple(t["sources"]) for t in strict}),
                "strict_documents": len({t["doc"] for t in strict}),
                "min_nonheldout_word_count": min(support, default=None),
                "max_nonheldout_word_count": max(support, default=None),
                "instances_with_unseen_sense": sum(unseen(t) for t in tasks),
                "strict_with_unseen_sense": sum(unseen(t) for t in strict),
                "robust_gain": str(sum(Q(t["pure"]) - Q(t["value"]) for t in tasks)),
                "gold_ask_all": 3 * len(tasks),
                "gold_uniform_pure": sum(r["uniform_pure"] for r in selected),
                "gold_independent": sum(r["independent"] for r in selected),
                "gold_pure": gold_pure,
                "gold_mixed": str(gold_mixed),
                "gold_gain": str(gain),
                "at_least_one_percent": bool(tasks) and gain >= Q(gold_pure, 100),
                "passes_registered_gate": len({t["doc"] for t in strict}) >= 2
                and gain >= 1,
            }
    destination.mkdir(parents=True, exist_ok=False)
    for name, content in (("plans", policies), ("cases", rows)):
        (destination / ("heldout-triangle-" + name + ".jsonl")).write_bytes(
            (
                "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in content)
            ).encode()
        )
    (destination / "heldout-triangle-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "output"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.wordnet, args.semcor, args.output), indent=2))
