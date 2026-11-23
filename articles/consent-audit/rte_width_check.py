"""Independently reconstruct the RTE cohorts and replay reference scores using the Parquet release."""

import argparse
from collections import Counter
import csv
from hashlib import sha256
from io import TextIOWrapper
from itertools import batched, combinations
import json
from math import comb
from pathlib import Path
from statistics import median_low
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import duckdb
import numpy as np
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import fetch_verified, verify
from go_scan_export import export
from point_check import fixtures
from point_reinfer import feed
from point_runtime import make_session
from rte_context_fetch import DATA_REV, FILES
from rte_width import reference_width


TRAIN = "a6252ab17015d718f6de1effe0980f7b158df63e3d16207cd8bd396b608e5147"


def source_rows(folder, host):
    train = folder / "train-a6252a.parquet"
    fetch_verified(
        train,
        f"{host}/datasets/nyu-mll/glue/resolve/{DATA_REV}/rte/train-00000-of-00001.parquet",
        TRAIN,
    )
    for name in ("RTE.zip", "validation.parquet", "tokenizer.json", "onnx/model_quantized.onnx"):
        verify(folder / name, FILES[name])
    output = {}
    with duckdb.connect(":memory:") as sql, ZipFile(folder / "RTE.zip") as original:
        for split, path in (("train", train), ("dev", folder / "validation.parquet")):
            cols = sql.execute(
                "SELECT idx,sentence1,sentence2,label FROM read_parquet(?) ORDER BY idx", [str(path)]
            ).fetchall()
            with original.open("RTE/" + split + ".tsv") as raw:
                rows = csv.DictReader(
                    TextIOWrapper(raw, encoding="utf8", newline=""),
                    delimiter="\t",
                    quoting=csv.QUOTE_NONE,
                )
                assert [
                    (int(r["index"]), r["sentence1"], r["sentence2"], r["label"]) for r in rows
                ] == [(i, p, h, ("entailment", "not_entailment")[y]) for i, p, h, y in cols]
            output[split] = cols
    return output


def width_math(hist, floor):
    support, seen = [], 0
    for width, count in sorted(hist.items()):
        support.append((width, comb(seen + count, 7) - comb(seen, 7)))
        seen += count
    # Compute absolute-risk minimizers independently from the exported CDF formula.
    # Below a target length l the risk is identical once candidates are clipped at l.
    for length in range(1, 513):
        clipped = Counter()
        for w, mass in support:
            clipped[max(length, w)] += mass
        total = sum(clipped.values())
        risk = sum((w - length) * mass for w, mass in clipped.items())
        risks = [risk]
        left = 0
        for candidate in range(length, 512):
            left += clipped[candidate]
            risk += 2 * left - total
            risks.append(risk)
        assert length + risks.index(min(risks)) == max(length, floor)
    cases = 0
    for pool in ([1, 2, 3, 4], [1, 1, 2, 5, 7], [3] * 4 + [6, 9, 11, 12]):
        for peers in range(1, len(pool) + 1):
            maxima = [max(group) for group in combinations(pool, peers)]
            assert reference_width(pool, peers) == median_low(maxima)
            cases += 1
    return cases


def padding_fixtures(tmp):
    fixtures(tmp)
    for op in (11, 12, 13, 18):
        src, dst = tmp / f"original-{op}.onnx", tmp / f"floor-{op}.onnx"
        export(src, dst, sha256(src.read_bytes()).hexdigest(), 4, 11)
        sess = make_session(dst, 1)
        for ids, mask, expect in (
            ([[2, 3], [5, 99]], [[1, 1], [1, 0]], [27, 38]),
            ([[2, 3, 4, 5, 6], [7, 8, 9, 10, 99]], [[1, 1, 1, 1, 1], [1, 1, 1, 1, 0]], [20, 34]),
        ):
            (values,) = sess.run(
                None,
                {
                    "input_ids": np.asarray(ids, dtype=np.int64),
                    "attention_mask": np.asarray(mask, dtype=np.int64),
                },
            )
            np.testing.assert_array_equal(values[:, 0], expect)
    return 4


def check(folder, graph, log, calibration, host):
    meta = json.loads(calibration.read_bytes())
    verify(graph, meta["graph_sha256"])
    src = source_rows(folder, host)
    with log.open(encoding="utf8", newline="") as f:
        saved = {(r["subset"], int(r["id"])): r for r in csv.DictReader(f, delimiter="\t")}
    tok = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tok.no_padding()
    tok.enable_truncation(512)
    groups = {"pool": [], "new": [], "dev": src["dev"]}
    for row in src["train"]:
        digest = sha256(f"rte-width-v1:{row[0]}".encode("ascii")).hexdigest()
        groups["pool" if int(digest[:2], 16) % 4 == 0 else "new"].append(row)
    lengths = Counter()
    for group in batched(groups["pool"], 64):
        lengths.update(len(e.ids) for e in tok.encode_batch([(p, h) for _, p, h, _ in group]))
    assert dict(lengths) == {int(k): v for k, v in meta["calibration_histogram"].items()}
    pairs = {s: {(p, h) for _, p, h, _ in rows} for s, rows in groups.items()}
    assert meta["text_pair_intersections"] == {
        a + "_" + b: len(pairs[a] & pairs[b])
        for a, b in (("pool", "new"), ("pool", "dev"), ("new", "dev"))
    }
    assert set(saved) == {(s, i) for s in ("dev", "new") for i, *_ in groups[s]}
    floor = meta["reference_width"]
    toy_cases = width_math(lengths, floor)
    original, converted = make_session(folder / "onnx/model_quantized.onnx"), make_session(graph)
    verified = Counter()
    for s in ("new", "dev"):
        for mode in ("single", "multiple32", "median", "mixed", "scan", "reordered"):
            rows = groups[s]
            if mode == "reordered":
                rows = sorted(rows, key=lambda r: sha256(str(r[0]).encode()).digest())
            individual = mode in ("single", "median", "multiple32")
            for group in batched(rows, 1 if individual else 8):
                kw = {"pad_id": tok.token_to_id("[PAD]"), "pad_token": "[PAD]"}
                if mode == "multiple32":
                    kw["pad_to_multiple_of"] = 32
                if mode == "median":
                    kw["length"] = floor
                tok.enable_padding(**kw)
                batch = tok.encode_batch([(p, h) for _, p, h, _ in group])
                (scores,) = (converted if mode in ("scan", "reordered") else original).run(
                    None, feed(batch)
                )
                for (idx, _, _, gold), encoding, values in zip(group, batch, scores):
                    record = saved[s, idx]
                    assert int(record["length"]) == sum(encoding.attention_mask)
                    assert record["gold"] == ("entailment", "not_entailment")[gold]
                    assert list(values.view(np.uint32)) == [
                        int(record[mode + "_" + k], 16) for k in "ENC"
                    ]
                    verified[s] += len(values)
    with TemporaryDirectory() as tmp:
        fixtures_checked = padding_fixtures(Path(tmp))
    return {
        "matched_source_rows": {s: len(v) for s, v in src.items()},
        "verified_float32": dict(verified),
        "toy_pool_cases": toy_cases,
        "verified_absolute_risk_minima": 512,
        "nonzero_pad_opset_fixtures": fixtures_checked,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("folder", "graph", "logits", "calibration"):
        p.add_argument(field, type=Path)
    p.add_argument("--host", default="https://huggingface.co")
    a = p.parse_args()
    print(json.dumps(check(a.folder, a.graph, a.logits, a.calibration, a.host.rstrip("/")), indent=2))
