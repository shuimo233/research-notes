"""A length-only reference policy for a fixed RTE classifier. Calibration never uses predictions."""

import argparse
from collections import Counter
import csv
from hashlib import sha256
from io import TextIOWrapper
from itertools import batched
import json
from math import comb
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_context_run import inputs
from go_model_fetch import verify
from go_scan_export import export
from point_runtime import make_session, batch_logits
from rte_context_fetch import FILES

MODES = ("single", "multiple32", "median", "mixed", "scan", "reordered")


def reference_width(lengths, peers=7):
    if peers < 1 or peers > len(lengths) or any(type(n) is not int or n < 1 for n in lengths):
        raise ValueError(
            "need a nonempty pool of positive token lengths at least as large as the peer set"
        )
    denom = comb(len(lengths), peers)
    count = 0
    for length, n in sorted(Counter(lengths).items()):
        count += n
        if 2 * comb(count, peers) >= denom:
            return length
    raise AssertionError("finite CDF did not reach one")


def in_pool(key):
    return sha256(("rte-width-v1:" + key).encode()).digest()[0] % 4 == 0


def load(folder):
    for name in ("RTE.zip", "onnx/model_quantized.onnx", "config.json", "tokenizer.json"):
        verify(folder / name, FILES[name])
    if json.loads((folder / "config.json").read_bytes())["id2label"]["0"] != "ENTAILMENT":
        raise ValueError("the fixed NLI mapping changed")
    tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(512, strategy="longest_first")
    sets = {"new": [], "dev": []}
    text_pairs = {"pool": set(), "new": set(), "dev": set()}
    gold = {}
    lengths = []
    with ZipFile(folder / "RTE.zip") as archive:
        for split in ("train", "dev"):
            with archive.open(f"RTE/{split}.tsv") as raw:
                seen = set()
                for r in csv.DictReader(
                    TextIOWrapper(raw, encoding="utf8", newline=""),
                    delimiter="\t",
                    quoting=csv.QUOTE_NONE,
                ):
                    key = str(int(r["index"]))
                    if key in seen:
                        raise ValueError("duplicate official ID")
                    seen.add(key)
                    pair = (r["sentence1"], r["sentence2"])
                    seq = tok.encode(*pair).ids
                    target = ("pool" if in_pool(key) else "new") if split == "train" else "dev"
                    text_pairs[target].add(pair)
                    if target == "pool":
                        lengths.append(len(seq))
                    else:
                        sets[target].append((key, seq))
                        gold[target, key] = r["label"]
    overlaps = {
        a + "_" + b: len(text_pairs[a] & text_pairs[b])
        for a, b in (("pool", "new"), ("pool", "dev"), ("new", "dev"))
    }
    return sets, gold, lengths, overlaps, tok.token_to_id("[PAD]")


def evaluate(folder, work, output):
    if work.exists() or output.exists():
        raise FileExistsError("choose a new graph and output file")
    sets, gold, lengths, overlaps, pad = load(folder)
    floor = reference_width(lengths)
    digest = export(
        folder / "onnx/model_quantized.onnx", work, FILES["onnx/model_quantized.onnx"], floor, pad
    )
    original, wrapped = make_session(folder / "onnx/model_quantized.onnx"), make_session(work)
    records = []
    for subset, samples in sets.items():
        base_width = {}
        scores = {}
        for mode in MODES:
            n = 8 if mode in ("mixed", "scan", "reordered") else 1
            seq = (
                sorted(samples, key=lambda r: sha256(r[0].encode()).digest())
                if mode == "reordered"
                else samples
            )
            scores[mode] = {}
            for block in batched(seq, n):
                w = max(len(t) for _, t in block)
                if mode == "multiple32":
                    w = min(512, ((w + 31) // 32) * 32)
                elif mode == "median":
                    w = max(w, floor)
                if mode == "mixed":
                    base_width.update((key, w) for key, _ in block)
                arr = inputs(block, w, pad)
                if mode in ("scan", "reordered"):
                    vals = batch_logits(wrapped, **arr)
                else:
                    (vals,) = original.run(None, arr)
                if vals.shape != (len(block), 3) or not np.isfinite(vals).all():
                    raise ValueError("invalid logits")
                scores[mode].update((k, v) for (k, _), v in zip(block, vals))
            print(f"{subset} {mode} {len(seq)}", file=sys.stderr, flush=True)
        for key, tokens in samples:
            size = len(tokens)
            records.append(
                [
                    subset,
                    key,
                    gold[subset, key],
                    size,
                    min(512, 32 * ((size + 31) // 32)),
                    max(size, floor),
                    base_width[key],
                    *(f"{v:08x}" for mode in MODES for v in scores[mode][key].view(np.uint32)),
                ]
            )
    with output.open("x", encoding="utf8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "subset",
                "id",
                "gold",
                "length",
                "multiple32_width",
                "median_width",
                "mixed_width",
                *(m + "_" + l for m in MODES for l in "ENC"),
            ]
        )
        writer.writerows(records)
    return {
        "reference_width": floor,
        "peers": 7,
        "calibration_items": len(lengths),
        "calibration_histogram": dict(sorted(Counter(lengths).items())),
        "text_pair_intersections": overlaps,
        "graph_sha256": digest,
        "items": {k: len(v) for k, v in sets.items()},
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("folder", "graph", "output"):
        p.add_argument(field, type=Path)
    a = p.parse_args()
    print(json.dumps(evaluate(a.folder, a.graph, a.output), indent=2))
