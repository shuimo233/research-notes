"""Reconstruct cached batches from raw cross-sense matrices without using the deployed inquiry service."""

import argparse
from collections import defaultdict
from functools import lru_cache
from itertools import combinations, product
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from wordnet_paths import NounPaths


def check(archive, folder):
    if not __debug__:
        raise RuntimeError("enable assertions")
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)

    def lines(name):
        return [json.loads(x) for x in name.read_bytes().splitlines()]

    fits = lines(ROOT / "heldout-triangle-plans.jsonl")
    uniform = {
        tuple(r["words"]): r["pure_omit"]
        for r in lines(ROOT / "natural-triangle-plans.jsonl")
    }
    sessions = defaultdict(list)
    frozen = lines(ROOT / "natural-triangle-cases.jsonl")
    for r, f in zip(frozen, lines(ROOT / "heldout-triangle-cases.jsonl"), strict=True):
        ctx = fits[f["context"]]
        sessions[r["source"], r["group"], r["sentence"]].append(
            (
                r,
                dict(
                    uniform=uniform[tuple(r["words"])],
                    fitted=ctx["pure_omit"],
                    independent=ctx["independent_omit"],
                ),
            )
        )
    senses = lru_cache(None)(graph.senses)

    @lru_cache(None)
    def possible(a, b, x, y):
        return {
            graph.relation(i, j)
            for i, j in product(
                senses(a) if x is None else (x,), senses(b) if y is None else (y,)
            )
        }

    results = lines(folder / "cached-triangle-ledger.jsonl")
    runs = 0
    for record in results:
        tasks = sessions.pop((record["source"], record["group"], record["sentence"]))
        ordered = sorted(tasks, key=lambda item: tuple(sorted(item[0]["ids"])))
        assert record["positions"] == len(
            {i for r, _ in ordered for i in r["ids"]}
        ) and record["triples"] == len(ordered)
        for reverse in (False, True):
            key = "reverse" if reverse else "forward"
            for mode, published in record[key].items():
                cache = {}
                for r, choices in reversed(ordered) if reverse else ordered:
                    word = dict(zip(r["ids"], r["words"]))
                    truth = dict(zip(r["ids"], r["truth"]))
                    later = r["ids"][r["words"].index(choices[mode])]
                    edges = list(combinations(r["ids"], 2))

                    def remaining(edge):
                        a, b = edge
                        return possible(word[a], word[b], cache.get(a), cache.get(b))

                    missing = set()
                    for e in edges:
                        if len(remaining(e)) > 1:
                            missing.update(set(e) - {later} - cache.keys())
                    for i in missing:
                        cache[i] = truth[i]
                    if any(len(remaining(e)) > 1 for e in edges):
                        assert later not in cache
                        cache[later] = truth[later]
                    assert all(
                        remaining(e) == {ans} for e, ans in zip(edges, r["labels"])
                    )
                    runs += 1
                assert set(cache) == set(published) and len(cache) == len(published)
    assert not sessions and runs == len(frozen) * 6
    summary = json.loads((folder / "cached-triangle-results.json").read_bytes())
    for src in ("semcor", "wsd"):
        for group in ("new", "previous"):
            rows = [r for r in results if r["source"] == src and r["group"] == group]
            s = summary[src][group]
            assert (s["sentences"], s["ask_every_position_once"], s["triples"]) == (
                len(rows),
                sum(r["positions"] for r in rows),
                sum(r["triples"] for r in rows),
            )
            for d in ("forward", "reverse"):
                for mode in ("uniform", "fitted", "independent"):
                    assert sum(len(r[d][mode]) for r in rows) == s[d][mode]
                changes = [len(r[d]["uniform"]) - len(r[d]["fitted"]) for r in rows]
                assert [
                    sum(x > 0 for x in changes),
                    changes.count(0),
                    sum(x < 0 for x in changes),
                ] == [
                    s[d][f]
                    for f in ("fewer_sentences", "equal_sentences", "more_sentences")
                ]
    print(
        f"{len(results)} sentences; {runs} cached task replays independently verified"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("folder", type=Path)
    a = p.parse_args()
    check(a.wordnet, a.folder)
