"""Rebuild the RTE width study from pinned inputs and compare with its published artifacts."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rte_context_fetch import fetch
from rte_width import evaluate
from rte_width_check import check
from rte_width_score import score


def write_json(path, obj):
    path.write_bytes((json.dumps(obj, indent=2) + "\n").encode())


def tsv_digest(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def reproduce(folder, output, host):
    root = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=False)
    fetch(folder, host)
    graph = output / "rte-width.onnx"
    logits = output / "rte-width-logits.tsv"
    calibration = output / "rte-width-calibration.json"
    meta = evaluate(folder, graph, logits)
    write_json(calibration, meta)
    scores = score(logits, calibration, root / "rte-point-logits.tsv")
    independent = check(folder, graph, logits, calibration, host)
    values = {
        calibration.name: meta,
        "rte-width-scores.json": scores,
        "rte-width-checks.json": independent,
    }
    equal = {logits.name: tsv_digest(logits) == tsv_digest(root / logits.name)}
    for name, obj in values.items():
        write_json(output / name, obj)
        equal[name] = json.loads((output / name).read_bytes()) == json.loads(
            (root / name).read_bytes()
        )
    if not all(equal.values()):
        raise ValueError(f"public artifact mismatch: {equal}")
    return {"matched": equal, "generated_graph_sha256": meta["graph_sha256"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--host", default="https://huggingface.co")
    args = p.parse_args()
    print(json.dumps(reproduce(args.folder, args.output, args.host.rstrip("/")), indent=2))
