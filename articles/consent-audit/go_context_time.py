"""Measure model-call wall time on the same warmed test batches in three rotated rounds."""
import argparse
from hashlib import sha256
from itertools import batched
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_context_run import encode, inputs, make_session
from go_model_fetch import FILES, verify


def measure(data, folder, wrapped):
    verify(folder / "onnx/model_quantized.onnx", FILES["onnx/model_quantized.onnx"])
    samples, pad = encode(data, folder)
    groups = sorted((b for b in batched(samples, 8) if len(b) == 8),
                    key=lambda g: sha256(g[0][0].encode()).digest())[:17]
    original = make_session(folder / "onnx/model_quantized.onnx")
    scan = make_session(wrapped)
    schedules = {}
    for mode in ("single", "mixed", "scan"):
        calls = []
        for group in groups:
            parts = [(s,) for s in group] if mode == "single" else [group]
            calls.append([inputs(part, max(len(seq) for _, seq in part), pad) for part in parts])
        schedules[mode] = calls
    def execute(mode, calls):
        session = scan if mode == "scan" else original
        start = perf_counter()
        for block in calls:
            for feed in block:
                session.run(None, feed)
        return perf_counter() - start
    names = tuple(schedules)
    times = {k: [] for k in names}
    for k in names:
        execute(k, schedules[k][:1])
    for turn in range(3):
        for k in names[turn:] + names[:turn]:
            times[k].append(execute(k, schedules[k][1:]))
    return {"items_per_round": 128, "warmup_items": 8, "rounds": 3, "threads": 4,
            "round_seconds": times, "median_ms_per_item": {k: 1000 * median(v) / 128 for k, v in times.items()}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("data", "folder", "wrapped"):
        parser.add_argument(arg, type=Path)
    a = parser.parse_args()
    print(json.dumps(measure(a.data, a.folder, a.wrapped), indent=2))
