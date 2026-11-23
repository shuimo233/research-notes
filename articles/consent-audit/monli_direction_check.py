"""Replay all directions using individual tokenization and independently score the paired decisions."""

import argparse
import csv
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
import sys

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_context_run import inputs
from go_model_fetch import verify
from monli_direction import SOURCES, SCAN
from monli_direction_score import audit_pairs, choose_direction
from point_runtime import make_session
from rte_context_fetch import FILES


def accounting_fixture():
    # Independent labels for all combinations of positive, zero and negative margins.
    count = 0
    for forward in (-2, -1, 0, 1, 2):
        for reverse in (-2, -1, 0, 1, 2):
            a, b = (forward, 0, -1), (reverse, 0, -1)
            direction = choose_direction(a, b)
            swapped = {"forward": "reverse", "reverse": "forward", "abstain": "abstain"}
            assert choose_direction(b, a) == swapped[direction]
            for truth in ("forward", "reverse"):
                raw = int((forward >= 0) == (truth == "forward")) + int(
                    (reverse >= 0) == (truth == "reverse")
                )
                repaired = int(direction == truth)
                needs_repair = (forward >= 0) == (reverse >= 0)
                good_repair = needs_repair and repaired
                assert repaired - int(raw == 2) == good_repair
                assert 2 * repaired - raw == 2 * good_repair - int(needs_repair)
                report = audit_pairs([(a, b, truth)])
                assert (
                    report["raw_row_correct"] == raw and report["comparison_pair_correct"] == repaired
                )
                assert report["net_row_change"] == 2 * repaired - raw
                count += 1
    return count


def check(data, model, graph, table, scores):
    for file in ("onnx/model_quantized.onnx", "tokenizer.json"):
        verify(model / file, FILES[file])
    verify(graph, SCAN)
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(512)
    sessions = [make_session(model / "onnx/model_quantized.onnx"), make_session(graph)]
    recorded = json.loads(scores.read_bytes())
    with table.open(encoding="utf8", newline="") as stream:
        all_rows = list(csv.DictReader(stream, delimiter="\t"))
    out = {}
    for subset, digest in SOURCES.items():
        source = data / (subset + ".jsonl")
        verify(source, digest)
        distinct = {}
        for raw in source.read_bytes().splitlines():
            r = json.loads(raw)
            a, b = r["sentence1"], r["sentence2"]
            assert distinct.setdefault((a, b), r["gold_label"]) == r["gold_label"]
        rows = [r for r in all_rows if r["subset"] == subset]
        indices = {pair: i for i, pair in enumerate(distinct)}
        assert len(rows) == len(indices)
        gold = np.array([g == "entailment" for g in distinct.values()])
        reverse = np.array([indices[b, a] for a, b in indices])
        assert np.array_equal(gold, ~gold[reverse])
        vectors = {}
        for i, ((a, b), r) in enumerate(zip(distinct, rows)):
            assert (int(r["id"]), r["premise"], r["hypothesis"], r["gold"]) == (
                i,
                sha256(a.encode()).hexdigest(),
                sha256(b.encode()).hexdigest(),
                distinct[a, b],
            )
            vectors[i] = tok.encode(a, b).ids
        cells = 0
        for mode in ("single", "mixed", "scan"):
            order = list(indices.values())
            if mode == "scan":
                order.sort(key=lambda i: sha256(str(i).encode()).digest())
            actual = np.empty((len(rows), 3), dtype=np.float32)
            for group in batched(order, 1 if mode == "single" else 8):
                block = [(i, vectors[i]) for i in group]
                args = inputs(block, max(len(t) for _, t in block), tok.token_to_id("[PAD]"))
                (values,) = sessions[int(mode == "scan")].run(None, args)
                actual[list(group)] = values
            archive = np.asarray(
                [[int(r[f"{mode}_{k}"], 16) for k in "ENC"] for r in rows], dtype=np.uint32
            )
            np.testing.assert_array_equal(actual.view(np.uint32), archive)
            cells += archive.size
            pos = actual.argmax(axis=1) == 0
            by_gold = np.flatnonzero(gold)
            a, b = pos[by_gold], pos[reverse[by_gold]]
            t = actual.astype(np.float64)
            mg = t[:, 0] - t[:, 1:].max(axis=1)
            diff = mg[by_gold] - mg[reverse[by_gold]]
            result = recorded[subset]["policies"][mode]
            assert result["raw_categories"] == {
                "correct_direction": np.sum(a & ~b),
                "reversed_direction": np.sum(~a & b),
                "both_entail": np.sum(a & b),
                "neither_entails": np.sum(~a & ~b),
            }
            assert result["comparison_choices"] == {
                "correct": np.sum(diff > 0),
                "reversed": np.sum(diff < 0),
                "tie": np.sum(diff == 0),
            }
            assert result["raw_row_correct"] == np.sum(pos == gold)
            assert result["comparison_row_correct"] == 2 * np.sum(diff > 0)
        out[subset] = {"verified_float32": cells, "pairs": len(rows) // 2, "distinct_rows": len(rows)}
    return {"subsets": out, "accounting_fixture_cases": accounting_fixture()}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "graph", "table", "scores"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(check(args.data, args.model, args.graph, args.table, args.scores), indent=2))
