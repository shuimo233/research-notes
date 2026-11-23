"""Replay the published decisions without model libraries. Hexadecimal NLI cells are raw float32 bits."""
import argparse
from collections import Counter
import csv
from fractions import Fraction
import json
import math
from pathlib import Path
from struct import unpack

MODES = ("single", "padded", "repeat", "mixed", "scan-original", "scan-shuffled")
COARSE = ("anger", "disgust", "fear", "joy", "sadness", "surprise", "neutral")


def nli(path):
    with path.open(encoding="utf8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("empty batch or duplicate NLI ID")
    result = {}
    for mode in ("single", "mixed", "scan", "reordered"):
        totals = Counter(dict.fromkeys(("binary_correct", "three_class_changes", "binary_changes",
                                        "unequal_float32", "rows_with_unequal_float32", "gained_correct", "lost_correct"), 0))
        example = None
        for row in rows:
            def view(name):
                raw = [row[name + "_" + col] for col in ("E", "N", "C")]
                vec = [unpack(">f", bytes.fromhex(x))[0] for x in raw]
                if not all(math.isfinite(x) for x in vec):
                    raise ValueError("nonfinite RTE value")
                return raw, vec.index(max(vec))
            single, a = view("single")
            target, b = view(mode)
            truth = {"entailment": True, "not_entailment": False}[row["reference"]]
            prev, correct = ((a == 0) == truth), ((b == 0) == truth)
            totals["binary_correct"] += correct
            totals["gained_correct"] += correct and not prev
            totals["lost_correct"] += prev and not correct
            totals["three_class_changes"] += a != b
            totals["binary_changes"] += (a == 0) != (b == 0)
            unequal = sum(x != y for x, y in zip(single, target))
            totals["unequal_float32"] += unequal
            totals["rows_with_unequal_float32"] += unequal > 0
            if (a == 0) != (b == 0) and example is None:
                example = {"id": row["id"], "single": ("E", "N", "C")[a], "condition": ("E", "N", "C")[b],
                           "reference": row["reference"]}
        result[mode] = {**totals, "first_binary_change": example}
    return {"items": len(rows), "labels_per_item": 3, "outcomes": result}


def go(rows_path, paired, data):
    with rows_path.open(encoding="utf8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    with paired.open(encoding="utf8", newline="") as stream:
        refs = {r["id"]: r for r in csv.DictReader(stream, delimiter="\t")}
    if len({r["id"] for r in rows}) != len(rows) or {r["id"] for r in rows} != refs.keys():
        raise ValueError("unmatched sample IDs")
    vocab = (data / "emotions.txt").read_text(encoding="utf8").splitlines()
    mapping = json.loads((data / "ekman_mapping.json").read_bytes())
    parent = {leaf: coarse for coarse, leaves in mapping.items() for leaf in leaves}
    parent["neutral"] = "neutral"
    def coarse(bits):
        labels = {parent[v] for j, v in enumerate(vocab) if bits & (1 << j)}
        return sum(1 << COARSE.index(v) for v in labels)
    counts = {}
    scores = {mode: [0, 0, 0] for mode in MODES}
    ref_counts = [sum(int(r[k]).bit_count() for r in refs.values()) for k in ("released", "people")]
    for name, fields, classes in (("fine", "mask", 28), ("coarse", "mask", 7), ("top1", "top", 0)):
        stage = Counter()
        pattern = Counter()
        changes = dict.fromkeys(("S_to_P", "P_to_R", "R_to_M", "S_to_M", "any_intermediate",
                                 "changed_then_restored", "scan_original", "scan_shuffled"), 0)
        for row in rows:
            vals = [int(row[m + "_" + fields]) for m in MODES]
            if name == "coarse":
                vals = list(map(coarse, vals))
                for m, pred in zip(MODES, vals):
                    scores[m][0] += pred.bit_count()
                    scores[m][1] += (pred & int(refs[row["id"]]["released"])).bit_count()
                    scores[m][2] += (pred & int(refs[row["id"]]["people"])).bit_count()
            a, b, c, e, so, sr = vals
            flags = [a != b, b != c, c != e]
            for key, flag in zip(changes, [*flags, a != e, any(flags), any(flags) and a == e, so != a, sr != a]):
                changes[key] += flag
            stage["".join(str(int(x)) for x in flags)] += 1
            for j in range(classes):
                pattern["".join(str((v >> j) & 1) for v in vals[:4])] += 1
        counts[name] = {"changed_items": changes, "adjacent_item_change_patterns": dict(sorted(stage.items())),
                        "per_label_four_state_paths": dict(sorted(pattern.items()))}
    outputs = {}
    for mode, (p, t0, t1) in scores.items():
        outputs[mode] = {"predicted": p, "true_positive_released": t0, "true_positive_people": t1,
                         "f1_released": str(Fraction(2*t0, p + ref_counts[0])),
                         "f1_people": str(Fraction(2*t1, p + ref_counts[1]))}
    return {"items": len(rows), "counts": counts, "coarse_micro": outputs}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("go_decisions", "go_reference", "go_data", "rte_logits"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps({"go": go(a.go_decisions, a.go_reference, a.go_data), "rte": nli(a.rte_logits)},
                     ensure_ascii=False, sort_keys=True, indent=2))
