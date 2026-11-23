"""Replay registered reciprocal entailment tests with fixed MoNLI and MNLI model inputs."""

import argparse
import csv
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import fetch_verified, verify
from go_scan_export import export
from point_reinfer import feed
from point_runtime import make_session, batch_logits
from rte_context_fetch import FILES


REV = "5bf388ad669a28500c1d46dba3b7d665d62b0536"
SOURCES = {
    "nmonli_test": "cd90bcdcf0bf8882e3444fbdc4d414952afda7b1",
    "pmonli": "c8696b058de83a2edb5cc9daf496ab779637ecd5",
}
SCAN = "6bc20b277f663d68e0cf3e1540d1a25f801eb3ab37f11d69d4b0186bc15830f3"
MODES = ("single", "mixed", "scan")


def dataset(folder, split):
    path = folder / (split + ".jsonl")
    verify(path, SOURCES[split])
    distinct = {}
    for line in path.read_bytes().splitlines():
        row = json.loads(line)
        key = row["sentence1"], row["sentence2"]
        gold = row["gold_label"]
        if gold not in ("neutral", "entailment") or distinct.setdefault(key, gold) != gold:
            raise ValueError("invalid or conflicting source label")
    if any(
        a == b or distinct.get((b, a)) not in ({"neutral", "entailment"} - {label})
        for (a, b), label in distinct.items()
    ):
        raise ValueError("the reciprocal exactly-one premise does not hold")
    return distinct


def fetch_data(folder, sources=SOURCES):
    for split, digest in sources.items():
        name = split + ".jsonl"
        url = f"https://raw.githubusercontent.com/atticusg/MoNLI/{REV}/{name}"
        try:
            fetch_verified(folder / name, url, digest)
        except subprocess.CalledProcessError:
            # A GitHub API route can serve the same pinned Git object.
            with TemporaryDirectory(dir=folder) as tmp:
                path = Path(tmp) / name
                with path.open("wb") as stream:
                    subprocess.run(
                        [
                            "gh",
                            "api",
                            "-H",
                            "Accept: application/vnd.github.raw+json",
                            "repos/atticusg/MoNLI/git/blobs/" + digest,
                        ],
                        stdout=stream,
                        check=True,
                    )
                verify(path, digest)
                path.replace(folder / name)


def run(data, model, graph, output):
    for n in ("config.json", "tokenizer.json", "onnx/model_quantized.onnx"):
        verify(model / n, FILES[n])
    label_map = json.loads((model / "config.json").read_bytes())["id2label"]
    if [label_map[str(i)].upper() for i in range(3)] != ["ENTAILMENT", "NEUTRAL", "CONTRADICTION"]:
        raise ValueError("unexpected model label mapping")
    if not graph.is_file():
        export(model / "onnx/model_quantized.onnx", graph, FILES["onnx/model_quantized.onnx"])
    verify(graph, SCAN)
    src, frozen = (make_session(x) for x in (model / "onnx/model_quantized.onnx", graph))
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.enable_truncation(512)
    tok.enable_padding(pad_id=tok.token_to_id("[PAD]"), pad_token="[PAD]")
    final = []
    for split in SOURCES:
        distinct = dataset(data, split)
        pairs = list(distinct)
        expected = 200 if split == "nmonli_test" else 1472
        if len(pairs) != expected:
            raise ValueError("unexpected number of unique ordered pairs")
        records = [{} for _ in pairs]
        for mode in MODES:
            indices = list(range(len(pairs)))
            if mode == "scan":
                indices.sort(key=lambda i: sha256(str(i).encode()).digest())
            for batch in batched(indices, 1 if mode == "single" else 8):
                feeds = feed(tok.encode_batch([pairs[i] for i in batch]))
                if mode == "scan":
                    logits = batch_logits(frozen, **feeds)
                else:
                    (logits,) = src.run(None, feeds)
                if logits.shape != (len(batch), 3) or not np.isfinite(logits).all():
                    raise ValueError("invalid model logits")
                for i, vec in zip(batch, logits):
                    records[i][mode] = [f"{v:08x}" for v in vec.view(np.uint32)]
        for i, ((a, b), record) in enumerate(zip(pairs, records)):
            if record["single"] != record["scan"]:
                raise ValueError("published singleton semantics did not transfer")
            final.append(
                [
                    split,
                    i,
                    sha256(a.encode()).hexdigest(),
                    sha256(b.encode()).hexdigest(),
                    distinct[a, b],
                    *(v for m in MODES for v in record[m]),
                ]
            )
    with output.open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "subset",
                "id",
                "premise",
                "hypothesis",
                "gold",
                *(m + "_" + l for m in MODES for l in "ENC"),
            ]
        )
        writer.writerows(final)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "scan", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    fetch_data(a.data)
    run(a.data, a.model, a.scan, a.output)
