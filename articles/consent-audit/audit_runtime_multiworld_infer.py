"""Freeze SNLI triplets and collect real model logits under eight input widths."""

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

from go_model_fetch import fetch_verified, verify
from rte_context_fetch import FILES, MODEL, REV

DATA_REV = "cdb5c3d5eed6ead6e5a341c8e56e669bb666725b"
DATA_SHA = "4696deda851c4d2385f26b58f2e13f9ed9f08ea7b42a3f4c2b97a9d08448878c"
MODES = (0, 16, 24, 32, 48, 64, 96, 128)


def prepare(path, output, fetch):
    import duckdb

    if fetch:
        fetch_verified(
            path,
            f"https://huggingface.co/datasets/stanfordnlp/snli/resolve/{DATA_REV}/plain_text/test-00000-of-00001.parquet",
            DATA_SHA,
        )
    verify(path, DATA_SHA)
    with duckdb.connect() as db:
        rows = db.execute(
            "SELECT file_row_number,premise,hypothesis,label FROM read_parquet(?,file_row_number=true) ORDER BY file_row_number",
            [str(path)],
        ).fetchall()
    assert len(rows) == 10000
    grouped = {}
    for i, p, h, label in rows:
        if label in (0, 1, 2) and p and h:
            grouped.setdefault(p, {}).setdefault(label, (i, h))
    eligible = sorted(
        (sha256(("multiworld/v1/" + k).encode()).digest(), k)
        for k, v in grouped.items()
        if len(v) == 3
    )
    assert len(eligible) >= 480
    selected = []
    for rank, (tag, p) in enumerate(eligible[:480]):
        for world in range(3):
            label = (world + tag[-1]) % 3
            i, h = grouped[p][label]
            selected.append([rank // 8, rank % 8, world, i, p, h, label])
    output.write_text(
        json.dumps(selected, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps({"eligible": len(eligible), "premises": 480, "rows": len(selected)})
    )


def infer(source, model, output, fetch):
    import numpy as np
    from tokenizers import Tokenizer
    from point_runtime import make_session

    for name in ("tokenizer.json", "config.json", "onnx/model_quantized.onnx"):
        f = model / name
        if fetch:
            fetch_verified(
                f, f"https://huggingface.co/{MODEL}/resolve/{REV}/{name}", FILES[name]
            )
        verify(f, FILES[name])
    label_map = json.loads((model / "config.json").read_bytes())["id2label"]
    assert [label_map[str(i)].lower() for i in range(3)] == [
        "entailment",
        "neutral",
        "contradiction",
    ]
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.enable_truncation(512)
    tok.no_padding()
    pad = tok.token_to_id("[PAD]")
    assert pad is not None
    session = make_session(model / "onnx/model_quantized.onnx")
    table = json.loads(source.read_bytes())
    assert len(table) == 1440
    with output.open("x", encoding="utf-8", newline="") as f:
        out = csv.writer(f, delimiter="\t", lineterminator="\n")
        out.writerow(
            [
                "case",
                "slot",
                "world",
                "source",
                "premise",
                "hypothesis",
                "gold",
                "length",
                *(f"w{w}_{c}" for w in MODES for c in "ENC"),
            ]
        )
        for group, slot, world, i, p, h, label in table:
            ids = tok.encode(p, h).ids
            n = len(ids)
            logs = {}
            for w in sorted({max(n, x) for x in MODES}):
                (vec,) = session.run(
                    ["logits"],
                    {
                        "input_ids": np.asarray(
                            [ids + [pad] * (w - n)], dtype=np.int64
                        ),
                        "attention_mask": np.asarray(
                            [[1] * n + [0] * (w - n)], dtype=np.int64
                        ),
                    },
                )
                assert (
                    vec.dtype == np.float32
                    and vec.shape == (1, 3)
                    and np.isfinite(vec).all()
                )
                logs[w] = [f"{x:08x}" for x in vec[0].view(np.uint32)]
            out.writerow(
                [
                    group,
                    slot,
                    world,
                    i,
                    sha256(p.encode()).hexdigest(),
                    sha256(h.encode()).hexdigest(),
                    label,
                    n,
                    *(v for w in MODES for v in logs[max(n, w)]),
                ]
            )
            if slot == 7 and world == 2 and (group + 1) % 20 == 0:
                print(json.dumps({"catalogs_done": group + 1}), flush=True)
    print(
        json.dumps(
            {
                "rows": len(table),
                "scores": len(table) * 8 * 3,
                "sha256": sha256(output.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("parquet", type=Path)
    a.add_argument("selected", type=Path)
    a.add_argument("--fetch", action="store_true")
    b = sub.add_parser("infer")
    b.add_argument("selected", type=Path)
    b.add_argument("model", type=Path)
    b.add_argument("ledger", type=Path)
    b.add_argument("--fetch", action="store_true")
    opts = cli.parse_args()
    if opts.action == "prepare":
        prepare(opts.parquet, opts.selected, opts.fetch)
    else:
        infer(opts.selected, opts.model, opts.ledger, opts.fetch)
