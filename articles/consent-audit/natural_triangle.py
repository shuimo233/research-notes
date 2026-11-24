"""Enumerate semantic triangles in complete frozen natural corpora and certify private mixed-query costs."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
import json
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from mixed_sense_game import solve
from wordnet_paths import NounPaths
from semcor_clarification import S_DIGEST, W_DIGEST
from wsd_clarification import FILES


def sentences(semcor, wsd, index):
    gold = {}
    for line in (wsd / "ALL.gold.key.txt").read_text(encoding="utf8").splitlines():
        ident, *keys = line.split()
        offsets = {index.get(k) for k in keys}
        if len(offsets) == 1 and None not in offsets:
            gold[ident] = offsets.pop()
    for sent in ET.parse(wsd / "ALL.data.xml").iter("sentence"):
        items = [
            (node.get("lemma"), node.get("id"), gold[node.get("id")])
            for node in sent.findall("instance")
            if node.get("pos") == "NOUN" and node.get("id") in gold
        ]
        yield "wsd", sent.get("id"), items
    with ZipFile(semcor) as archive:
        for name in sorted(
            n for n in archive.namelist() if "/tagfiles/" in n and not n.endswith("/")
        ):
            with archive.open(name) as stream:
                root = ET.parse(stream)
            for num, sent in enumerate(root.iter("s"), 1):
                items = []
                for pos, node in enumerate(sent, 1):
                    word = node.get("lemma", "")
                    key = word + "%" + node.get("lexsn", "")
                    if key in index:
                        items.append((word, f"{pos:04d}", index[key]))
                yield "semcor", name + "/" + str(num), items


def run(wordnet, semcor, wsd, out):
    verify(wordnet, W_DIGEST)
    verify(semcor, S_DIGEST)
    for name, digest in FILES.items():
        verify(wsd / name, digest)
    graph = NounPaths(wordnet)
    senses = lru_cache(None)(graph.senses)

    @lru_cache(None)
    def above(u):
        return set().union(*(graph.ancestors(x) for x in senses(u)))

    @lru_cache(65536)
    def edge(u, v):
        left, right = senses(u), senses(v)
        if not (left & right or above(u) & right or above(v) & left):
            return None
        grid = {(x, y): graph.relation(x, y) for x, y in product(left, right)}
        if len(set(grid.values())) <= 1:
            return None
        return (
            {x for x in left if len({grid[x, y] for y in right}) > 1},
            {y for y in right if len({grid[x, y] for x in left}) > 1},
        )

    def triggers(u, v):
        if u < v:
            return edge(u, v)[0]
        return edge(v, u)[1]

    def evaluate(names):
        groups = {}
        for u in names:
            groups[u] = [
                (
                    tuple(v for v in names if u != v and x in triggers(u, v)),
                    Q(1, len(senses(u))),
                )
                for x in sorted(senses(u))
            ]
        fixed = {}
        for later in names:
            first = [u for u in names if u != later]
            rates = [Q(len(triggers(u, later)), len(senses(u))) for u in first]
            fixed[later] = 2 + min(1, sum(rates))
        best = min(names, key=lambda u: (fixed[u], u))
        cover = [u for u in names if u != best]
        game = solve(groups, cover)
        assert game["covers"] == 3 and Q(game["value"]) <= fixed[best]
        return {"words": names, "pure_omit": best, "pure": str(fixed[best]), **game}

    previous = {
        (r["source"], r["sentence"])
        for line in (ROOT / "shared-sense-ledger.jsonl").read_bytes().splitlines()
        if (r := json.loads(line))["shared"]
    }
    with ZipFile(wordnet) as z:
        index = {
            k: int(o)
            for k, o, _, _ in (
                s.split() for s in z.read("wordnet/index.sense").decode().splitlines()
            )
            if "%1:" in k
        }
    tasks = {}
    cases = []
    census = defaultdict(Counter)
    for src, sent, items in sentences(semcor, wsd, index):
        group = "previous" if (src, sent) in previous else "new"
        bucket = census[src, group]
        bucket["all_sentences"] += 1
        eligible = sorted(
            (w, i, x) for w, i, x in items if x in senses(w) and len(senses(w)) >= 2
        )
        bucket["eligible_noun_positions"] += len(eligible)
        for trio in combinations(eligible, 3):
            names = tuple(u for u, _, _ in trio)
            if len(set(names)) < 3:
                continue
            bucket["distinct_lemma_position_triples"] += 1
            if not all(edge(u, v) is not None for u, v in combinations(names, 2)):
                continue
            if names not in tasks:
                tasks[names] = evaluate(names)
            task = tasks[names]
            truth = {w: x for w, _, x in trio}
            true_labels = [
                graph.relation(truth[u], truth[v]) for u, v in combinations(names, 2)
            ]
            payoff = {}
            for later in names:
                first = set(names) - {later}
                needed = any(truth[u] in triggers(u, later) for u in first)
                if not needed:
                    for x in senses(later):
                        completed = {**truth, later: x}
                        assert [
                            graph.relation(completed[u], completed[v])
                            for u, v in combinations(names, 2)
                        ] == true_labels
                payoff[later] = 2 + int(needed)
            gold = sum(
                Q(p) * payoff[next(u for u in names if u not in c)]
                for c, p in task["mixture"]
            )
            cases.append(
                {
                    "source": src,
                    "group": group,
                    "sentence": sent,
                    "words": names,
                    "ids": [i for _, i, _ in trio],
                    "truth": [truth[u] for u in names],
                    "labels": true_labels,
                    "gold_mixed": str(gold),
                    "gold_pure": payoff[task["pure_omit"]],
                }
            )
    report = {}
    for (src, group), bucket in sorted(census.items()):
        rows = [r for r in cases if (r["source"], r["group"]) == (src, group)]
        strict = [
            r
            for r in rows
            if Q(tasks[r["words"]]["value"]) < Q(tasks[r["words"]]["pure"])
        ]
        report.setdefault(src, {})[group] = {
            **bucket,
            "sentences_with_triangle": len({r["sentence"] for r in rows}),
            "triangles": len(rows),
            "different_word_triples": len({r["words"] for r in rows}),
            "strict_triangles": len(strict),
            "strict_sentences": len({r["sentence"] for r in strict}),
            "strict_word_triples": len({r["words"] for r in strict}),
            "pure_worst": str(sum(Q(tasks[r["words"]]["pure"]) for r in rows)),
            "mixed_worst": str(sum(Q(tasks[r["words"]]["value"]) for r in rows)),
            "gold_pure": sum(r["gold_pure"] for r in rows),
            "gold_mixed": str(sum(Q(r["gold_mixed"]) for r in rows)),
        }
    out.mkdir(parents=True, exist_ok=False)
    for name, content in (
        ("plans", [tasks[k] for k in sorted(tasks)]),
        ("cases", cases),
    ):
        (out / ("natural-triangle-" + name + ".jsonl")).write_bytes(
            (
                "".join(
                    json.dumps(row, separators=(",", ":")) + "\n" for row in content
                )
            ).encode()
        )
    (out / "natural-triangle-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("wordnet", "semcor", "wsd", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.semcor, a.wsd, a.output), indent=2))
