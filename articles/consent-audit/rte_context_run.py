"""Check context-invariant entailment decisions on the entire GLUE RTE development split."""
import argparse
import csv
from hashlib import sha256
from io import TextIOWrapper
from itertools import batched
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import duckdb
import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_context_run import inputs
from point_runtime import batch_logits, make_session
from go_model_fetch import verify
from rte_context_fetch import FILES


def corpus(folder):
    for name, digest in FILES.items():
        verify(folder / name, digest)
    with ZipFile(folder / "RTE.zip") as archive, archive.open("RTE/dev.tsv") as raw:
        reader = csv.DictReader(TextIOWrapper(raw, encoding="utf8", newline=""), delimiter="\t", quoting=csv.QUOTE_NONE)
        rows = [(int(r["index"]), r["sentence1"], r["sentence2"], r["label"]) for r in reader]
    with duckdb.connect(":memory:") as db:
        pq = db.execute("SELECT idx,sentence1,sentence2,label FROM read_parquet(?) ORDER BY idx",
                        [str(folder / "validation.parquet")]).fetchall()
    decoded = [(i, p, h, {0: "entailment", 1: "not_entailment"}[g]) for i, p, h, g in pq]
    if sorted(rows) != decoded or len({k for k, *_ in rows}) != len(rows):
        raise ValueError("the two RTE source releases disagree on keys, texts or labels")
    return rows


def evaluate(folder, wrapped, dest):
    rows = corpus(folder)
    mapping = json.loads((folder / "config.json").read_bytes())["id2label"]
    if mapping != {"0": "ENTAILMENT", "1": "NEUTRAL", "2": "CONTRADICTION"}:
        raise ValueError("unexpected NLI label mapping")
    tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(512, strategy="longest_first")
    samples, gold = [], {}
    truncated = 0
    for k, premise, hypothesis, target in rows:
        item = tok.encode(premise, hypothesis)
        samples.append((str(k), item.ids))
        truncated += bool(item.overflowing)
        gold[str(k)] = target
    ordinary, point = (make_session(path) for path in (folder / "onnx/model_quantized.onnx", wrapped))
    results = {}
    for mode, model, size, shuffle in (("single", ordinary, 1, False), ("mixed", ordinary, 8, False),
                                      ("scan", point, 8, False), ("reordered", point, 8, True)):
        seq = sorted(samples, key=lambda t: sha256(t[0].encode()).digest()) if shuffle else samples
        outputs = {}
        for block in batched(seq, size):
            width = max(len(ids) for _, ids in block)
            feed = inputs(block, width, tok.token_to_id("[PAD]"))
            if model is point:
                values = batch_logits(model, **feed)
            else:
                values, = model.run(None, feed)
            if values.shape != (len(block), 3) or not np.isfinite(values).all():
                raise ValueError("invalid NLI output")
            outputs.update((key, v) for (key, _), v in zip(block, values))
        results[mode] = outputs
    with dest.open("x", encoding="utf8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "reference", *(f"{mode}_{label}" for mode in results for label in ("E", "N", "C"))])
        for key, _ in samples:
            writer.writerow([key, gold[key], *(f"{v:08x}" for mode in results for v in results[mode][key].view(np.uint32))])
    return {"rows": len(rows), "truncated_pairs": truncated, "verified_source_formats": 2}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("folder", "wrapped", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(evaluate(a.folder, a.wrapped, a.output), indent=2))
