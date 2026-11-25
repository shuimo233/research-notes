"""Collect deterministic MoNLI scores under registered CPU input widths."""

import argparse
import csv
from hashlib import sha256
from pathlib import Path
import json

import numpy as np
from tokenizers import Tokenizer

from go_model_fetch import fetch_verified, verify
from point_runtime import make_session
from rte_context_fetch import FILES, MODEL, REV
from audit_runtime import MODES, prior_rows

MONLI_REV = "5bf388ad669a28500c1d46dba3b7d665d62b0536"
SOURCES = {
    "nmonli_test": "cd90bcdcf0bf8882e3444fbdc4d414952afda7b1",
    "pmonli": "c8696b058de83a2edb5cc9daf496ab779637ecd5",
}


def collect(data, model, prior, output, fetch):
    for name in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
        path = model / name
        if fetch:
            fetch_verified(
                path,
                f"https://huggingface.co/{MODEL}/resolve/{REV}/{name}",
                FILES[name],
            )
        verify(path, FILES[name])

    labels = json.loads((model / "config.json").read_bytes())["id2label"]
    if tuple(labels[str(i)].lower() for i in range(3)) != (
        "entailment",
        "neutral",
        "contradiction",
    ):
        raise ValueError("unexpected label order")
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.enable_truncation(512)
    tok.no_padding()
    pad = tok.token_to_id("[PAD]")
    if pad is None:
        raise ValueError("missing padding token")
    sess = make_session(model / "onnx/model_quantized.onnx")
    previous = prior_rows(prior)
    rows = []
    for subset, digest in SOURCES.items():
        path = data / f"{subset}.jsonl"
        if fetch:
            fetch_verified(
                path,
                f"https://raw.githubusercontent.com/atticusg/MoNLI/{MONLI_REV}/{path.name}",
                digest,
            )
        verify(path, digest)
        source = {}
        for line in path.read_bytes().splitlines():
            row = json.loads(line)
            text_pair = row["sentence1"], row["sentence2"]
            label = row["gold_label"]
            if source.setdefault(text_pair, label) != label:
                raise ValueError("inconsistent duplicate source labels")
        for i, ((a, b), gold) in enumerate(source.items()):
            key = (subset, str(i))
            anchor = previous[key]
            aa, bb = sha256(a.encode()).hexdigest(), sha256(b.encode()).hexdigest()
            if (aa, bb, gold) != (
                anchor["premise"],
                anchor["hypothesis"],
                anchor["gold"],
            ):
                raise ValueError(f"misaligned source record {key}")
            ids = tok.encode(a, b).ids
            length = len(ids)
            by_width = {}
            for width in sorted({max(length, mode) for mode in MODES}):
                (logits,) = sess.run(
                    ["logits"],
                    {
                        "input_ids": np.array(
                            [ids + [pad] * (width - length)], dtype=np.int64
                        ),
                        "attention_mask": np.array(
                            [[1] * length + [0] * (width - length)], dtype=np.int64
                        ),
                    },
                )
                if (
                    logits.shape != (1, 3)
                    or logits.dtype != np.float32
                    or not np.isfinite(logits).all()
                ):
                    raise ValueError(f"invalid model result {key}")
                by_width[width] = [f"{v:08x}" for v in logits[0].view(np.uint32)]
            if by_width[length] != [anchor[f"single_{name}"] for name in "ENC"]:
                raise ValueError(f"unregistered singleton change {key}")
            rows.append(
                [
                    subset,
                    i,
                    aa,
                    bb,
                    gold,
                    length,
                    *(v for mode in MODES for v in by_width[max(length, mode)]),
                ]
            )
        print(json.dumps(dict(subset=subset, completed=len(source))), flush=True)
    if len(rows) != len(previous):
        raise ValueError("record count differs from published input")
    with output.open("x", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter="\t", lineterminator="\n").writerows(
            [
                [
                    "subset",
                    "id",
                    "premise",
                    "hypothesis",
                    "gold",
                    "length",
                    *(f"w{j}_{c}" for j in MODES for c in "ENC"),
                ],
                *rows,
            ]
        )
    print(
        json.dumps(
            dict(
                records=len(rows),
                floats=len(rows) * len(MODES) * 3,
                sha256=sha256(output.read_bytes()).hexdigest(),
            )
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "prior", "output"):
        cli.add_argument(name, type=Path)
    cli.add_argument("--fetch", action="store_true")
    arg = cli.parse_args()
    collect(arg.data, arg.model, arg.prior, arg.output, arg.fetch)
