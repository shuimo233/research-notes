"""Run the predeclared policy samples through the actual pinned ONNX runtime."""

import argparse
import csv
from fractions import Fraction as F
import gzip
from hashlib import sha256
import json
from pathlib import Path
from random import Random

import numpy as np
from tokenizers import Tokenizer

from audit_runtime import MODES, guard, signed
from audit_runtime_drift_check import pinned, PREVIOUS, LOGITS
from audit_runtime_infer import SOURCES
from audit_runtime_partition import draw_modes
from audit_runtime_partition_check import PIN
from go_model_fetch import verify
from point_runtime import make_session
from rte_context_fetch import FILES


def trace(ledger, archive, drift, plans, source, model, output):
    prior = json.loads(gzip.decompress(pinned(archive.read_bytes(), PREVIOUS)))
    shift = json.loads(gzip.decompress(pinned(drift.read_bytes(), PIN)))
    certified = json.loads(gzip.decompress(plans.read_bytes()))
    rows = {
        (row["subset"], row["id"]): row
        for row in csv.DictReader(
            pinned(ledger.read_bytes().replace(b"\r\n", b"\n"), LOGITS)
            .decode()
            .splitlines(),
            delimiter="\t",
        )
    }
    for name in ("tokenizer.json", "config.json", "onnx/model_quantized.onnx"):
        verify(model / name, FILES[name])
    tok = Tokenizer.from_file(str(model / "tokenizer.json"))
    tok.enable_truncation(512)
    tok.no_padding()
    pad = tok.token_to_id("[PAD]")
    assert pad is not None
    session = make_session(model / "onnx/model_quantized.onnx")
    path = source / "pmonli.jsonl"
    verify(path, SOURCES["pmonli"])
    corpus = {}
    for text in path.read_bytes().splitlines():
        item = json.loads(text)
        corpus.setdefault((item["sentence1"], item["sentence2"]), item["gold_label"])
    encoded = {}
    for i, ((a, b), gold) in enumerate(corpus.items()):
        key = "pmonli", str(i)
        log = rows[key]
        assert (log["premise"], log["hypothesis"], log["gold"]) == (
            sha256(a.encode()).hexdigest(),
            sha256(b.encode()).hexdigest(),
            gold,
        )
        encoded[key] = tok.encode(a, b).ids

    def invoke(key, mode, cutoff, checksum):
        ids = encoded[key]
        width = max(len(ids), MODES[mode])
        mask = [1] * len(ids) + [0] * (width - len(ids))
        x = list(ids) + [pad] * (width - len(ids))
        (logits,) = session.run(
            ["logits"],
            {
                "input_ids": np.asarray([x], dtype=np.int64),
                "attention_mask": np.asarray([mask], dtype=np.int64),
            },
        )
        bits = [f"{a:08x}" for a in logits[0].view(np.uint32)]
        row = rows[key]
        assert bits == [row[f"w{MODES[mode]}_{c}"] for c in "ENC"]
        checksum.update(("/".join((key[0], key[1], str(mode), *bits)) + "\n").encode())
        return guard(signed(row, f"w{MODES[mode]}"), cutoff)

    rng = Random(10441168)
    captured = []
    for index in (1044, 1168):
        split, threshold, kind, old = prior[index]
        assert split == "pmonli" and kind == "main"
        pairs = old["pairs"]
        cutoff = F(threshold)
        w0 = (F(1, 8),) * 8
        old_floors = shift[index]
        u = tuple(map(F, old_floors["witness"]["contamination"]))
        given = tuple(F(3, 32) + v / 4 for v in u)
        new_blocks = certified[index]["partition"]["blocks"]
        for label, weights in (("center", w0), ("witness", given)):
            for policy, blocks, floor in (
                ("independent", [[i] for i in range(4)], F(1)),
                ("scalar", [[0, 1, 2, 3]], 1 - F(old_floors["safe"])),
                ("partition", new_blocks, F(1, 2)),
            ):
                log = []
                checksum = sha256()
                for _ in range(24):
                    modes = draw_modes(blocks, weights, floor, rng)
                    denied, coins = [], []
                    for world in range(2):
                        result, picks = [], []
                        for i, mode in enumerate(modes):
                            releases = invoke(
                                (split, pairs[i][world]), mode, cutoff, checksum
                            )
                            coin = rng.randrange(20)
                            picks.append(coin)
                            result.append(
                                int(coin == 0 or (coin != 1 and not releases))
                            )
                        denied.append(result)
                        coins.append(picks)
                    log.append(dict(modes=modes, coins=coins, denied=denied))
                captured.append(
                    dict(
                        case=index,
                        distribution=label,
                        policy=policy,
                        weights=list(map(str, weights)),
                        batches=log,
                        mean_configurations=str(
                            F(sum(len(set(x["modes"])) for x in log), len(log))
                        ),
                        score_sha256=checksum.hexdigest(),
                    )
                )
        print(json.dumps(dict(case=index, batches=144, scalars=3456)), flush=True)
    output.write_bytes(
        gzip.compress(json.dumps(captured, separators=(",", ":")).encode(), mtime=0)
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("ledger", "archive", "drift", "plans", "source", "model", "output"):
        cli.add_argument(key, type=Path)
    options = cli.parse_args()
    trace(
        options.ledger,
        options.archive,
        options.drift,
        options.plans,
        options.source,
        options.model,
        options.output,
    )
