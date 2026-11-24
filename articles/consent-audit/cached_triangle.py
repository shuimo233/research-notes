"""Replay frozen clarification choices with one shared gold-sense cache per sentence."""

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from calibrated_triangle import TriangleInquiry
from wordnet_paths import NounPaths
from go_model_fetch import verify


def run(wordnet, destination):
    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")

    def lines(name):
        return [json.loads(l) for l in (ROOT / name).read_bytes().splitlines()]

    natural = lines("natural-triangle-cases.jsonl")
    fitted = lines("heldout-triangle-cases.jsonl")
    policies = lines("heldout-triangle-plans.jsonl")
    uniform = {
        tuple(r["words"]): r["pure_omit"] for r in lines("natural-triangle-plans.jsonl")
    }
    sentences = defaultdict(list)
    assert len(fitted) == len(natural)
    for r, f in zip(natural, fitted):
        assert all(r[k] == f[k] for k in ("source", "sentence", "ids", "group"))
        t = policies[f["context"]]
        names = tuple(r["words"])
        sentences[r["source"], r["group"], r["sentence"]].append(
            (
                r,
                {
                    "uniform": uniform[names],
                    "fitted": t["pure_omit"],
                    "independent": t["independent_omit"],
                },
            )
        )
    graph = NounPaths(wordnet)

    @lru_cache(None)
    def inquiry(names):
        return TriangleInquiry(graph, {u: {} for u in names})

    ledger = []
    modes = ("uniform", "fitted", "independent")
    for (src, group, sent), tasks in sorted(sentences.items()):
        order = sorted(tasks, key=lambda t: tuple(sorted(t[0]["ids"])))
        total_ids = {ident for r, _ in order for ident in r["ids"]}
        record = {
            "source": src,
            "group": group,
            "sentence": sent,
            "positions": len(total_ids),
            "triples": len(tasks),
        }
        for direction, ordered in (("forward", order), ("reverse", order[::-1])):
            record[direction] = {}
            for mode in modes:
                cache = {}
                for r, choices in ordered:
                    names = tuple(r["words"])
                    svc = inquiry(names)
                    ids = dict(zip(names, r["ids"]))
                    truth = dict(zip(names, r["truth"]))
                    local = {u: cache[i] for u, i in ids.items() if i in cache}
                    assert all(x == truth[u] for u, x in local.items())

                    def ask(batch):
                        assert all(ids[u] not in cache for u in batch)
                        cache.update((ids[u], truth[u]) for u in batch)
                        return {u: truth[u] for u in batch}

                    result = svc.execute(ask, choices[mode], known=local)
                    assert [entry[2] for entry in result["relations"]] == r["labels"]
                record[direction][mode] = sorted(cache)
        ledger.append(record)
    report = {}
    for src in ("semcor", "wsd"):
        report[src] = {}
        for group in ("new", "previous"):
            rows = [r for r in ledger if (r["source"], r["group"]) == (src, group)]
            entry = {
                "sentences": len(rows),
                "triples": sum(r["triples"] for r in rows),
                "ask_every_position_once": sum(r["positions"] for r in rows),
            }
            for direction in ("forward", "reverse"):
                costs = {
                    mode: sum(len(r[direction][mode]) for r in rows) for mode in modes
                }
                changes = Counter(
                    len(r[direction]["uniform"]) - len(r[direction]["fitted"])
                    for r in rows
                )
                entry[direction] = {
                    **costs,
                    "fewer_sentences": sum(n for k, n in changes.items() if k > 0),
                    "equal_sentences": changes[0],
                    "more_sentences": sum(n for k, n in changes.items() if k < 0),
                }
            report[src][group] = entry
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "cached-triangle-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    (destination / "cached-triangle-ledger.jsonl").write_bytes(
        ("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in ledger)).encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.output), indent=2))
