"""Archive four intervened decisions plus two Scan runs and compare their raw float bits."""
import argparse
import csv
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_context_run import encode
from go_layout import HEADER, PRED, table

MODES = ("single", "padded", "repeat", "mixed", "scan-original", "scan-shuffled")


def build(data, model, runs, old, patch, output):
    samples, _ = encode(data, model)
    keys = [k for k, _ in samples]
    canonical = sorted(keys)
    baseline = table(old, HEADER)
    delta = table(patch, ("id", *PRED))
    if set(keys) != baseline.keys():
        raise ValueError("original predictions have different keys")
    info, arrays, decisions = {}, {}, {}
    for mode in MODES:
        with np.load(runs / f"context-{mode}.npz", allow_pickle=False) as f:
            src = list(map(str, f["ids"]))
            expected_order = sorted(keys, key=lambda k: sha256(k.encode()).digest()) if mode == "scan-shuffled" else keys
            if src != expected_order or str(f["condition"]) != mode.split("-")[0] or bool(f["shuffled"]) != (mode == "scan-shuffled"):
                raise ValueError(f"unexpected evaluation conditions or order in {mode}")
            index = np.argsort(f["ids"])
            mat = f["logits"][index]
            if mat.shape != (len(keys), 28) or mat.dtype != np.float32 or not np.isfinite(mat).all():
                raise ValueError("incomplete or invalid logits")
            arrays[mode] = mat
            masks = (mat >= 0).astype(np.int64) @ (1 << np.arange(28, dtype=np.int64))
            decisions[mode] = dict(zip(canonical, zip(map(int, masks), map(int, np.argmax(mat, axis=1)))))
            info[mode] = {"sorted_logits_float32le_sha256": sha256(mat.astype("<f4").tobytes()).hexdigest(),
                          "clone_row_decision_disagreements": int(f["clone_disagreement"]),
                          "max_abs_disagreement_between_clones": float(f["clone_max_difference"])}
    differences = {}
    for a, b in (("single", "padded"), ("padded", "repeat"), ("repeat", "mixed"), ("single", "mixed"),
                 ("single", "scan-original"), ("single", "scan-shuffled")):
        x, y = arrays[a], arrays[b]
        unequal = x.view(np.uint32) != y.view(np.uint32)
        differences[a + "_to_" + b] = {"unequal_floats": int(unequal.sum()), "affected_rows": int(unequal.any(1).sum()),
                                        "max_abs_delta": float(np.max(np.abs(x - y)))}
    for key in keys:
        if decisions["single"][key][0] != baseline[key]["fine_int8"] or decisions["mixed"][key][0] != delta.get(key, baseline[key])["fine_int8"]:
            raise ValueError("failed to reproduce the published endpoint masks")
    with output.open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "length", "width", "batch_size", "slot", *(f"{m}_{v}" for m in MODES for v in ("mask", "top"))])
        for block in batched(samples, 8):
            width = max(len(seq) for _, seq in block)
            for slot, (key, seq) in enumerate(block):
                writer.writerow([key, len(seq), width, len(block), slot, *(v for m in MODES for v in decisions[m][key])])
    return {"samples": len(keys), "classes": 28, "logits_per_run": 28 * len(keys),
            "runs": info, "raw_comparisons": differences}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for v in ("data", "model", "runs", "original", "batch8_patch", "out"):
        parser.add_argument(v, type=Path)
    a = parser.parse_args()
    print(json.dumps(build(a.data, a.model, a.runs, a.original, a.batch8_patch, a.out), indent=2))
