"""Run one frozen GoEmotions deployment on official test text, without reading paired gold labels."""

import argparse
import csv
import json
from itertools import batched
from os import fdopen, link
from pathlib import Path
import platform
import sys
from tempfile import mkstemp

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import tokenizers

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import FILES, REV, verify
from goemotions_fetch import verify as verify_data


def run(data, model, mode, output, threads, batch_size=1):
    artifact = "onnx/model.onnx" if mode == "fp32" else "onnx/model_quantized.onnx"
    for name in ("config.json", "tokenizer.json", artifact):
        verify(model / name, FILES[name])
    verify_data(data / "test.tsv", "test.tsv")
    verify_data(data / "emotions.txt", "emotions.txt")
    labels = json.loads((model / "config.json").read_bytes())["id2label"]
    vocab = (data / "emotions.txt").read_text(encoding="utf8").splitlines()
    if [labels[str(i)] for i in range(len(labels))] != vocab:
        raise ValueError("model and corpus label order differ")
    tokenizer = Tokenizer.from_file(str(model / "tokenizer.json"))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    pad_id = tokenizer.token_to_id("<pad>")
    if pad_id is None:
        raise ValueError("missing tokenizer padding id")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(model / artifact), opts, providers=["CPUExecutionProvider"])
    input_names = {x.name for x in session.get_inputs()}
    if input_names != {"input_ids", "attention_mask"}:
        raise ValueError("unexpected model inputs")
    predictions, seen = [], set()
    truncated = 0
    zero_logits = 0
    with (data / "test.tsv").open(encoding="utf8", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        for batch in batched(reader, batch_size):
            sequences, keys = [], []
            for text, _, key in batch:
                if key in seen:
                    raise ValueError("duplicate test key")
                seen.add(key)
                keys.append(key)
                ids = tokenizer.encode(text).ids
                if len(ids) > 128:
                    truncated += 1
                    # RoBERTa keeps its final separator token after right truncation.
                    ids = ids[:127] + ids[-1:]
                sequences.append(ids)
            width = max(map(len, sequences))
            values = np.full((len(batch), width), pad_id, dtype=np.int64)
            attention = np.zeros_like(values)
            for i, ids in enumerate(sequences):
                values[i, :len(ids)] = ids
                attention[i, :len(ids)] = 1
            logits, = session.run(None, {"input_ids": values, "attention_mask": attention})
            if logits.shape != (len(batch), len(vocab)) or not np.isfinite(logits).all():
                raise ValueError("unexpected logits")
            zero_logits += int(np.count_nonzero(logits == 0))
            for key, vector in zip(keys, logits):
                mask = sum(1 << i for i, logit in enumerate(vector) if logit >= 0)
                predictions.append([key, mask, int(np.argmax(vector))])
            if len(predictions) % 1000 == 0:
                print(f"{mode} {len(predictions)}", file=sys.stderr, flush=True)
    record = {"model_revision": REV, "mode": mode, "platform": platform.platform(),
              "cpu": platform.processor(), "python": platform.python_version(),
              "onnxruntime": ort.__version__, "numpy": np.__version__, "tokenizers": tokenizers.__version__,
              "providers": session.get_providers(), "threads": threads, "batch_size": batch_size,
              "truncated": truncated, "exact_zero_logits": zero_logits,
              "labels": vocab, "predictions": sorted(predictions)}
    # Persist only complete predictions. Do not replace an existing run.
    fd, temp = mkstemp(dir=output.parent, suffix=".partial")
    tmp = Path(temp)
    try:
        with fdopen(fd, "w", encoding="utf8", newline="\n") as dst:
            json.dump(record, dst, separators=(",", ":"))
            dst.write("\n")
        link(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{mode} archived {len(predictions)} predictions; {truncated} truncated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("mode", choices=("fp32", "int8"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=1, help="pad each consecutive batch to its longest input")
    args = parser.parse_args()
    if args.output.exists() or min(args.threads, args.batch_size) < 1:
        parser.error("choose a new output path, a positive thread count, and a positive batch size")
    run(args.data, args.model, args.mode, args.output, args.threads, args.batch_size)
