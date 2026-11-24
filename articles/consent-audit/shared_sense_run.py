"""Rebuild joint-reveal traces from two frozen single-query audits."""

import argparse
from collections import defaultdict
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from shared_sense import SharedInquiry
from wordnet_paths import NounPaths

POLICIES = (
    "forward_table",
    "forward_more",
    "reverse_table",
    "reverse_more",
    "greedy",
    "cover",
)


def source_rows(name, digest):
    data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
    if (
        hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        != digest
    ):
        raise ValueError(f"changed input ledger: {name}")
    return data.decode().splitlines()


def groups(graph):
    batches = defaultdict(list)
    for line in source_rows(
        "wsd-clarification-ledger.jsonl", "6d0376d332dcd095482da87b0e585fd801168909"
    ):
        row = json.loads(line)
        if row["broad"] and len(row["worlds"]) == 1:
            x, y, label, _ = row["worlds"][0]
            batches["wsd", row["sentence"]].append(
                (row["ids"], row["words"], (x, y), label)
            )
    for row in csv.DictReader(
        source_rows(
            "semcor-clarification-ledger.tsv",
            "e311faf838fc19c5e12e384b06dc5991f2ea9a5b",
        ),
        delimiter="\t",
    ):
        words = row["left_word"], row["right_word"]
        if min(len(graph.senses(w)) for w in words) < 2:
            continue
        ids = [f"{int(row[s + '_position']):04d}" for s in ("left", "right")]
        senses = [int(row[s + "_offset"]) for s in ("left", "right")]
        batches["semcor", row["document"] + "/" + row["sentence"]].append(
            (ids, words, senses, row["relation"])
        )
    return batches


def evaluate(graph, source, sentence, rows):
    words, truth, labels = {}, {}, {}
    for ids, lemmas, offsets, label in rows:
        for u, w, x in zip(ids, lemmas, offsets, strict=True):
            if words.setdefault(u, w) != w or truth.setdefault(u, x) != x:
                raise ValueError(f"inconsistent annotation {source} {sentence} {u}")
        labels[tuple(ids)] = label
    if len(labels) != len(rows):
        raise ValueError("duplicate occurrence pair")
    service = SharedInquiry(
        {u: graph.senses(w) for u, w in words.items()}, labels, graph.relation
    )
    independent = sum(
        len(service.tables[e].replay(tuple(truth[u] for u in e))[1]) for e in labels
    )
    traces = {}
    for p in POLICIES:
        observed = {}
        while True:
            action, val = service.next(observed, p)
            if action == "answers":
                if val != labels:
                    raise ValueError("wrong joint answer")
                break
            if val in observed:
                raise ValueError("duplicate query")
            observed[val] = truth[val]
        traces[p] = list(observed)
    return {
        "source": source,
        "sentence": sentence,
        "words": dict(sorted(words.items())),
        "truth": dict(sorted(truth.items())),
        "queries": [[*e, labels[e]] for e in service.order],
        "shared": len(words) < 2 * len(labels),
        "uncached": independent,
        "certificate": service.certificate(truth),
        "cover_first_stage": sorted(service.cover),
        "traces": traces,
    }


def summary(rows):
    totals = {p: sum(len(r["traces"][p]) for r in rows) for p in POLICIES}
    ratios = [
        Fraction(len(r["traces"]["cover"]), len(r["certificate"]))
        for r in rows
        if r["certificate"]
    ]
    return {
        "sentences": len(rows),
        "relations": sum(len(r["queries"]) for r in rows),
        "distinct_positions_summed": sum(len(r["words"]) for r in rows),
        "uncached": sum(r["uncached"] for r in rows),
        "totals": totals,
        "offline_minimum": sum(len(r["certificate"]) for r in rows),
        "cover_exact_sentences": sum(
            len(r["certificate"]) == len(r["traces"]["cover"]) for r in rows
        ),
        "maximum_cover_ratio": str(max(ratios)) if ratios else None,
        "cover_beats_best_serial_total": bool(rows)
        and totals["cover"] < min(totals[p] for p in POLICIES[:4]),
    }


def run(archive, directory):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    rows = [
        evaluate(graph, src, sent, values)
        for (src, sent), values in sorted(groups(graph).items())
    ]
    result = {
        src: {
            s: summary(
                [r for r in rows if r["source"] == src and (s == "all" or r["shared"])]
            )
            for s in ("all", "shared")
        }
        for src in ("wsd", "semcor")
    }
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "shared-sense-ledger.jsonl").write_bytes(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode()
    )
    (directory / "shared-sense-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("new_directory", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.new_directory), indent=2))
