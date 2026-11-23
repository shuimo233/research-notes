"""Replay both gold definitions on frozen binary predictions, then audit whole-item rank stability."""

import argparse
from collections import Counter
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_bounds import Baseline, Item, sharp

LABELS = ("anger", "disgust", "fear", "joy", "sadness", "surprise", "neutral")
RULES = ("fp32", "int8", "top1")
PAIRS = (("fp32", "int8"), ("fp32", "top1"))


def read(path):
    with path.open(encoding="utf8", newline="") as f:
        result = []
        for r in csv.DictReader(f, delimiter="\t"):
            masks = {k: int(r[k]) for k in ("released", "people", *RULES)}
            if any(not 0 <= m < 1 << len(LABELS) for m in masks.values()):
                raise ValueError("invalid label mask")
            if masks["released"] & ~masks["people"]:
                raise ValueError("reference switch is not additive")
            result.append((r["id"], masks))
    if not result or len({k for k, _ in result}) != len(result):
        raise ValueError("expected unique nonempty batch")
    return result


def metrics(rows, rule, gold):
    p = g = tp = exact = 0
    for _, r in rows:
        pred, ref = r[rule], r[gold]
        p += pred.bit_count()
        g += ref.bit_count()
        tp += (pred & ref).bit_count()
        exact += pred == ref
    return {"predicted": p, "gold": g, "true_positive": tp,
            "micro_f1": str(Fraction(2 * tp, max(1, p + g))),
            "exact_matches": exact, "exact_accuracy": str(Fraction(exact, len(rows)))}


def audit(rows):
    results = {}
    for rule in RULES:
        ends = {g: metrics(rows, rule, g) for g in ("released", "people")}
        found = Counter({label: 0 for label in LABELS})
        for _, r in rows:
            bits = (r["people"] ^ r["released"]) & r[rule]
            for i, label in enumerate(LABELS):
                found[label] += (bits >> i) & 1
        if sum(found.values()) != ends["people"]["true_positive"] - ends["released"]["true_positive"]:
            raise AssertionError("added positives do not match added true positives")
        results[rule] = {**ends, "new_reference_hits_by_label": dict(found)}
    pairs, changed = {}, [(key, r) for key, r in rows if r["people"] != r["released"]]
    for a, b in PAIRS:
        x, y = (results[rule]["released"] for rule in (a, b))
        base = Baseline(x["gold"], x["predicted"], y["predicted"], x["true_positive"], y["true_positive"])
        items, separate = [], []
        incidence = dict.fromkeys(("both", "a_only", "b_only", "neither"), 0)
        for key, r in changed:
            added = r["people"] ^ r["released"]
            incidence["both"] += (added & r[a] & r[b]).bit_count()
            incidence["a_only"] += (added & r[a] & ~r[b]).bit_count()
            incidence["b_only"] += (added & r[b] & ~r[a]).bit_count()
            incidence["neither"] += (added & ~(r[a] | r[b])).bit_count()
            items.append(Item(key, added.bit_count(), (r[a] & added).bit_count(), (r[b] & added).bit_count()))
            for pos, label in enumerate(LABELS):
                bit = 1 << pos
                if bit & added:
                    separate.append(Item(f"{key}/{label}", 1, int(bool(bit & r[a])), int(bool(bit & r[b]))))
        block = sharp(base, items)
        relaxed = sharp(base, separate)
        if not (Fraction(relaxed["minimum"]["difference"]) <= Fraction(block["minimum"]["difference"]) <=
                Fraction(block["maximum"]["difference"]) <= Fraction(relaxed["maximum"]["difference"])):
            raise AssertionError("independent-label relaxation excluded an attainable result")
        end = Fraction(results[a]["people"]["micro_f1"]) - Fraction(results[b]["people"]["micro_f1"])
        pairs[a + "_versus_" + b] = {"released": str(base.delta()), "people": str(end), "whole_items": block,
             "predictions_on_added_labels": incidence,
             "independent_labels": {member: relaxed[member]["difference"] for member in ("minimum", "maximum")}}
    return {"records": len(rows), "changed_items": len(changed),
            "changed_item_sizes": dict(sorted(Counter((r["people"] ^ r["released"]).bit_count() for _, r in changed).items())),
            "scores": results, "pairs": pairs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(read(args.table)), indent=2, sort_keys=True))
