"""Run ordinary, matched-width, repeated-row or Scan evaluations on the pinned test inputs."""
import argparse
from hashlib import sha256
from itertools import batched
import csv
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import FILES, verify
from goemotions_fetch import verify as verify_data
from point_runtime import batch_logits, make_session


def encode(data, model):
    verify_data(data / "test.tsv", "test.tsv")
    verify(model / "tokenizer.json", FILES["tokenizer.json"])
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.no_padding()
    tok.no_truncation()
    samples = []
    with (data / "test.tsv").open(encoding="utf8", newline="") as f:
        for text, _, key in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            ids = tok.encode(text).ids
            if len(ids) > 128:
                ids = ids[:127] + ids[-1:]
            samples.append((key, ids))
    if len({k for k, _ in samples}) != len(samples):
        raise ValueError("duplicate corpus key")
    return samples, tok.token_to_id("<pad>")


def inputs(group, width, pad):
    ids = np.full((len(group), width), pad, dtype=np.int64)
    mask = np.zeros_like(ids)
    for i, (_, row) in enumerate(group):
        ids[i, :len(row)] = row
        mask[i, :len(row)] = 1
    return {"input_ids": ids, "attention_mask": mask}


def run(data, model, condition, out, wrapped=None, shuffled=False):
    if out.exists():
        raise FileExistsError(out)
    if (condition == "scan") != (wrapped is not None):
        raise ValueError("pass the exported graph only for the scan condition")
    ordinary = model / "onnx/model_quantized.onnx"
    verify(ordinary, FILES["onnx/model_quantized.onnx"])
    sess = make_session(wrapped or ordinary)
    samples, pad = encode(data, model)
    if shuffled:
        samples.sort(key=lambda row: sha256(row[0].encode()).digest())
    keys, outputs = [], []
    clone_disagreement = 0
    clone_max_difference = 0.0
    seconds = 0.0
    def forward(feed):
        nonlocal seconds
        start = perf_counter()
        if condition == "scan":
            values = batch_logits(sess, **feed)
        else:
            values, = sess.run(None, feed)
        seconds += perf_counter() - start
        if values.shape != (feed["input_ids"].shape[0], 28) or not np.isfinite(values).all():
            raise ValueError("invalid logits")
        return values
    for ix, group in enumerate(batched(samples, 8)):
        width = max(len(ids) for _, ids in group)
        keys.extend(k for k, _ in group)
        if condition in ("mixed", "scan"):
            outputs.extend(forward(inputs(group, width, pad)))
        else:
            for j, row in enumerate(group):
                peers = (row,) * len(group) if condition == "repeat" else (row,)
                n = len(row[1]) if condition == "single" else width
                batch = forward(inputs(peers, n, pad))
                if condition == "repeat":
                    chosen = batch[j]
                    clone_disagreement += bool(np.any((batch >= 0) != (chosen >= 0)) or
                                               np.any(np.argmax(batch, axis=1) != np.argmax(chosen)))
                    clone_max_difference = max(clone_max_difference, float(np.max(np.abs(batch - chosen))))
                else:
                    chosen = batch[0]
                outputs.append(chosen)
        if (ix + 1) % 200 == 0:
            print(f"{condition} {min((ix + 1)*8, len(samples))}/{len(samples)}", file=sys.stderr, flush=True)
    with out.open("xb") as f:
        np.savez_compressed(f, ids=np.asarray(keys), logits=np.asarray(outputs), condition=condition,
                            shuffled=shuffled, forward_seconds=seconds, clone_disagreement=clone_disagreement,
                            clone_max_difference=clone_max_difference)
    print(f"{condition} complete; {len(keys)} samples, {seconds:.1f}s in ONNX Runtime")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("condition", choices=("single", "padded", "repeat", "mixed", "scan"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--wrapped", type=Path)
    parser.add_argument("--shuffled", action="store_true")
    args = parser.parse_args()
    run(args.data, args.model, args.condition, args.output, args.wrapped, args.shuffled)
