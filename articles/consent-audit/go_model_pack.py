"""Join frozen predictions to both previously released reference definitions and export a replay table."""
import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import REV
from goemotions_fetch import verify

COARSE = ("anger", "disgust", "fear", "joy", "sadness", "surprise", "neutral")


def pack(data, gold, fp, quant, output):
    for file in ("emotions.txt", "ekman_mapping.json"):
        verify(data / file, file)
    vocab = (data / "emotions.txt").read_text(encoding="utf8").splitlines()
    mapping = json.loads((data / "ekman_mapping.json").read_bytes())
    parent = {child: coarse for coarse, group in mapping.items() for child in group}
    parent["neutral"] = "neutral"
    def mask(labels):
        return sum(1 << COARSE.index(label) for label in set(labels))

    def coarse_bits(bits):
        return mask(parent[v] for i, v in enumerate(vocab) if bits & (1 << i))

    runs = []
    metadata = {}
    for mode, path in (("fp32", fp), ("int8", quant)):
        run = json.loads(path.read_bytes())
        if run["model_revision"] != REV or run["labels"] != vocab or run["mode"] != mode:
            raise ValueError("unexpected model or label order")
        preds = run.pop("predictions")
        by_id = {k: (bits, top) for k, bits, top in preds}
        if len(by_id) != len(preds) or any(not 0 <= b < 1 << len(vocab) or not 0 <= t < len(vocab)
                                           for b, t in by_id.values()):
            raise ValueError("invalid prediction table")
        runs.append(by_id)
        metadata[mode] = run
    with gold.open(encoding="utf8") as stream:
        records = [json.loads(line) for line in stream]
    keys = {r["id"] for r in records}
    if len(keys) != len(records) or any(run.keys() != keys for run in runs):
        raise ValueError("inconsistent prediction/reference keys")
    rows = []
    for row in sorted(records, key=lambda r: r["id"]):
        if row["status"] != "ok" or not row["fine_matches"]:
            raise ValueError("unresolved source labels")
        k = row["id"]
        old, new = mask(row["published_ekman"]), mask(row["two_reporters_ekman"])
        if old & ~new:
            raise ValueError("nested references required")
        (a, top), (b, _) = (run[k] for run in runs)
        rows.append((k, old, new, coarse_bits(a), coarse_bits(b), coarse_bits(1 << top), a, b, top))
    with output.open("x", encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("id", "released", "people", "fp32", "int8", "top1", "fine_fp32", "fine_int8", "fine_top1"))
        writer.writerows(rows)
    return {"rows": len(rows), "coarse_bit_order": COARSE, "deployments": metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("data", "paired_gold_jsonl", "fp32_json", "int8_json", "output_tsv"):
        parser.add_argument(arg, type=Path)
    a = parser.parse_args()
    print(json.dumps(pack(a.data, a.paired_gold_jsonl, a.fp32_json, a.int8_json, a.output_tsv), indent=2))
