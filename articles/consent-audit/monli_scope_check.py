"""Independently replay the scope study using source lexical annotations, path closure and batched Scan."""

import argparse
from collections import defaultdict
import csv
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
import re
import sys

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from go_scan_export import export
from monli_direction import SCAN
from monli_scope_run import ALL_SOURCES
from point_reinfer import feed
from point_runtime import make_session
from rte_context_fetch import FILES


def rewrite(s):
    # An independent spelling of the registered transformation for these source frames.
    tokens = s.split(" ")
    assert [w.lower() for w in tokens].count("not") == 1
    if [w.lower() for w in tokens[:5]] == ["there", "is", "not", "a", "single"]:
        tokens = tokens[:2] + ["at", "least", "one"] + tokens[5:]
    else:
        tokens = [w for w in tokens if w.lower() != "not"]
    text = " ".join("some" if w.lower() == "any" else w for w in tokens)
    return re.sub(r" at all(?=\W|$)", "", text, flags=re.I)


def load_rows(folder, name):
    p = folder / (name + ".jsonl")
    verify(p, ALL_SOURCES[name])
    return [json.loads(v) for v in p.read_bytes().splitlines()]


def closure(pos):
    adjacent = defaultdict(set)
    for r in pos:
        if r["gold_label"] == "entailment":
            adjacent[r["sentence1_lex"].casefold()].add(r["sentence2_lex"].casefold())
    dist = {}
    for start in adjacent:
        reached = {start}
        frontier = {start}
        depth = 0
        while frontier:
            depth += 1
            frontier = {t for w in frontier for t in adjacent.get(w, ())} - reached
            for t in frontier:
                dist[start, t] = depth
            reached.update(frontier)
    return dist


def audit(data, model, graph, ledger, historical):
    positive = load_rows(data, "pmonli")
    dist = closure(positive)
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    verify(model / "tokenizer.json", FILES["tokenizer.json"])
    if not graph.exists():
        export(model / "onnx/model_quantized.onnx", graph, FILES["onnx/model_quantized.onnx"])
    verify(graph, SCAN)
    sess = make_session(graph)
    tok.enable_truncation(512)
    tok.enable_padding(pad_id=tok.token_to_id("[PAD]"), pad_token="[PAD]")
    with ledger.open(encoding="utf8", newline="") as f:
        saved = list(csv.DictReader(f, delimiter="\t"))
    with historical.open(encoding="utf8", newline="") as f:
        old = {
            (r["premise"], r["hypothesis"]): r
            for r in csv.DictReader(f, delimiter="\t")
            if r["subset"] == "nmonli_test"
        }
    report = {}
    for split in ("nmonli_train", "nmonli_test"):
        raw = load_rows(data, split)
        index = {}
        for i, r in enumerate(raw, 1):
            k = (r["sentence1"], r["sentence2"])
            assert raw[index.setdefault(k, i) - 1]["gold_label"] == r["gold_label"]
        expected = {(a, b) for a, b in index if a < b and (b, a) in index}
        rows = [r for r in saved if r["subset"] == split]
        assert len(rows) == len(expected)
        jobs = []
        held = verified_paths = 0
        for r in rows:
            line = int(r["ab_line"])
            source = raw[line - 1]
            a, b = source["sentence1"], source["sentence2"]
            expected.remove((a, b))
            assert (line, int(r["ba_line"])) == (index[a, b], index[b, a])
            src_rev = raw[index[b, a] - 1]
            assert source["gold_label"] != src_rev["gold_label"]
            assert r["gold"] == ("forward" if source["gold_label"] == "entailment" else "reverse")
            assert (r["a_sha256"], r["b_sha256"]) == tuple(
                sha256(x.encode()).hexdigest() for x in (a, b)
            )
            u, v = source["sentence1_lex"].casefold(), source["sentence2_lex"].casefold()
            assert (r["a_term"], r["b_term"]) == (u, v)
            paths = [int(z) for z in r["positive_source_lines"].split()]
            if ((u, v) in dist) != ((v, u) in dist):
                start, end = (u, v) if (u, v) in dist else (v, u)
                assert len(paths) == dist[start, end] and r["basis"] == "evidence"
                assert r["evidence_first"] == ("reverse" if start == u else "forward")
                current = start
                for source_id in paths:
                    e = positive[source_id - 1]
                    assert e["gold_label"] == "entailment" and current == e["sentence1_lex"].casefold()
                    current = e["sentence2_lex"].casefold()
                assert current == end
                verified_paths += 1
            else:
                assert (
                    not paths
                    and r["basis"] == "affirmative-model"
                    and r["evidence_first"] == r["invert_affirmative"]
                )
            for name, (x, y) in (("original", (a, b)), ("affirmative", (rewrite(a), rewrite(b)))):
                for orient, pair in (("ab", (x, y)), ("ba", (y, x))):
                    cells = [r[f"{name}_{orient}_{k}"] for k in "ENC"]
                    jobs.append((pair, cells))
                    if split == "nmonli_test" and name == "original":
                        prior = old[tuple(sha256(s.encode()).hexdigest() for s in pair)]
                        assert cells == [prior["single_" + k] for k in "ENC"]
                        held += 3
        assert not expected
        ordered = sorted(jobs, key=lambda j: sha256(json.dumps(j[0]).encode()).digest())
        for block in batched(ordered, 8):
            (vals,) = sess.run(None, feed(tok.encode_batch([pair for pair, _ in block])))
            for v, (_, cells) in zip(vals, block):
                assert list(v.view(np.uint32)) == [int(c, 16) for c in cells]
        report[split] = {
            "verified_float32": 3 * len(jobs),
            "source_rows": len(raw),
            "duplicate_rows": len(raw) - len(index),
            "unpaired_rows": len(index) - 2 * len(rows),
            "independent_path_checks": verified_paths,
            "historical_score_cells": held,
        }
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "graph", "ledger", "historical"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(audit(a.data, a.model, a.graph, a.ledger, a.historical), indent=2))
