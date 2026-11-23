"""Score all registered RTE width policies from the published float32 bit patterns."""

import argparse
from collections import Counter
import csv
from itertools import batched
import json
import math
from pathlib import Path
import struct


POLICIES = {
    "single": "length",
    "multiple32": "multiple32_width",
    "median": "median_width",
    "mixed": "mixed_width",
}


def table(path):
    with path.open(encoding="utf8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def bits(row, mode):
    return tuple(row[f"{mode}_{label}"] for label in "ENC")


def verdict(row, mode):
    values = [struct.unpack(">f", bytes.fromhex(x))[0] for x in bits(row, mode)]
    assert all(math.isfinite(v) for v in values)
    return values.index(max(values))


def width_counterexamples(rows):
    """Exploratory row-level audit, kept separate from the registered endpoints."""
    closer = new_mismatches = repaired = exact = exact_mismatches = 0
    lost_ids = []
    for row in rows:
        actual = int(row["mixed_width"])
        reference = int(row["median_width"])
        single, median, mixed = (verdict(row, mode) == 0 for mode in ("single", "median", "mixed"))
        if actual == reference:
            exact += 1
            exact_mismatches += median != mixed
        if abs(reference - actual) < abs(int(row["length"]) - actual):
            closer += 1
            new_mismatches += single == mixed and median != mixed
            repaired += single != mixed and median == mixed
            if single == mixed == (row["gold"] == "entailment") and median != mixed:
                lost_ids.append(row["id"])
    return {
        "closer_width": closer,
        "new_mismatches_on_closer": new_mismatches,
        "repaired_mismatches_on_closer": repaired,
        "exact_width": exact,
        "mismatches_at_exact_width": exact_mismatches,
        "closer_but_lost_previously_agreed_correct_ids": lost_ids,
    }


def subset_result(rows, floor):
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["gold"] in ("entailment", "not_entailment") for r in rows)
    for block in batched(rows, 8):
        assert all(int(r["mixed_width"]) == max(int(q["length"]) for q in block) for r in block)
    for row in rows:
        length = int(row["length"])
        assert 1 <= length <= 512
        assert int(row["median_width"]) == max(length, floor)
        assert int(row["multiple32_width"]) == min(512, 32 * ((length + 31) // 32))
        assert bits(row, "median") == bits(row, "scan") == bits(row, "reordered")
    modes = {}
    for mode, width in POLICIES.items():
        counts = Counter(
            dict.fromkeys(
                (
                    "binary_correct",
                    "binary_different_from_mixed",
                    "three_way_different_from_mixed",
                    "absolute_width_difference_sum",
                    "corrected_from_single",
                    "lost_from_single",
                    "recovered_single_errors_mixed_correct",
                    "lost_single_correct_mixed_correct",
                ),
                0,
            )
        )
        for r in rows:
            predicted, single, mixed = (verdict(r, m) for m in (mode, "single", "mixed"))
            gold = r["gold"] == "entailment"
            correct, was_correct, mixed_correct = (
                (v == 0) == gold for v in (predicted, single, mixed)
            )
            counts["binary_correct"] += correct
            counts["binary_different_from_mixed"] += (predicted == 0) != (mixed == 0)
            counts["three_way_different_from_mixed"] += predicted != mixed
            counts["absolute_width_difference_sum"] += abs(int(r[width]) - int(r["mixed_width"]))
            counts["corrected_from_single"] += correct and not was_correct
            counts["lost_from_single"] += was_correct and not correct
            counts["recovered_single_errors_mixed_correct"] += (
                correct and not was_correct and mixed_correct
            )
            counts["lost_single_correct_mixed_correct"] += (
                not correct and was_correct and mixed_correct
            )
        modes[mode] = dict(counts)
    return {
        "items": len(rows),
        "partial_final_batch": len(rows) % 8,
        "identical_float32_per_scan_order": len(rows) * 3,
        "policies": modes,
        "exploratory_counterexamples": width_counterexamples(rows),
    }


def score(logits, calibration, historical):
    info = json.loads(calibration.read_bytes())
    data = table(logits)
    assert {r["subset"] for r in data} == {"new", "dev"}
    hist = {int(k): v for k, v in info["calibration_histogram"].items()}
    assert sum(hist.values()) == info["calibration_items"]
    denom = math.comb(sum(hist.values()), info["peers"])
    cdf = lambda a: math.comb(sum(v for k, v in hist.items() if k <= a), info["peers"])
    h = info["reference_width"]
    assert 2 * cdf(h - 1) < denom <= 2 * cdf(h)
    subsets = {s: [r for r in data if r["subset"] == s] for s in ("new", "dev")}
    assert {s: len(rs) for s, rs in subsets.items()} == info["items"]
    old = {r["id"]: r for r in table(historical)}
    assert old.keys() == {r["id"] for r in subsets["dev"]}
    for r in subsets["dev"]:
        prior = old[r["id"]]
        assert r["gold"] == prior["reference"]
        assert all(bits(r, m) == bits(prior, m) for m in ("single", "mixed"))
    results = {s: subset_result(rows, h) for s, rows in subsets.items()}
    new, dev = (results[s]["policies"] for s in ("new", "dev"))
    return {
        "reference_width": h,
        "subsets": results,
        "prior_dev_float32_rechecked": len(old) * 6,
        "new_prediction_support": (
            new["median"]["binary_different_from_mixed"] < new["single"]["binary_different_from_mixed"]
            and new["median"]["binary_correct"] >= new["single"]["binary_correct"]
        ),
        "dev_half_net_gain": dev["median"]["binary_correct"] >= 199,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("logits", "calibration", "historical"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    print(json.dumps(score(a.logits, a.calibration, a.historical), indent=2))
