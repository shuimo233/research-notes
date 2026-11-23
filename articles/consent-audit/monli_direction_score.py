"""Score a direction only when the registered sentence pair supports exactly one entailment."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from math import isfinite
from pathlib import Path
from struct import unpack


MODES = ("single", "mixed", "scan")
CATEGORIES = ("correct_direction", "reversed_direction", "both_entail", "neither_entails")


def entailment_margin(logits):
    """Expected order is entailment, neutral, contradiction. Promote before subtracting."""
    e, n, c = map(float, logits)
    if not all(map(isfinite, (e, n, c))):
        raise ValueError("nonfinite score")
    return e - max(n, c)


def choose_direction(forward_logits, reverse_logits):
    """Use only for a pair known to support exactly one direction. A tie abstains."""
    f, r = entailment_margin(forward_logits), entailment_margin(reverse_logits)
    if f == r:
        return "abstain"
    return "forward" if f > r else "reverse"


def logits(row, mode):
    return [unpack(">f", bytes.fromhex(row[mode + "_" + k]))[0] for k in "ENC"]


def audit_pairs(pairs):
    """Audit (forward logits, reverse logits, gold direction) triples under exactly-one truth."""
    categories = Counter(dict.fromkeys(CATEGORIES, 0))
    choices = Counter(dict.fromkeys(("correct", "reversed", "tie"), 0))
    repairs = Counter(dict.fromkeys(("correct", "reversed", "tie"), 0))
    for forward, reverse, gold in pairs:
        if gold not in ("forward", "reverse"):
            raise ValueError("gold must be forward or reverse")
        forward, reverse = tuple(forward), tuple(reverse)
        predicted = choose_direction(forward, reverse)
        raw_forward = entailment_margin(forward) >= 0
        raw_reverse = entailment_margin(reverse) >= 0
        if raw_forward == raw_reverse:
            category = "both_entail" if raw_forward else "neither_entails"
        else:
            category = (
                "correct_direction" if raw_forward == (gold == "forward") else "reversed_direction"
            )
        outcome = "tie" if predicted == "abstain" else ("correct" if predicted == gold else "reversed")
        categories[category] += 1
        choices[outcome] += 1
        if raw_forward == raw_reverse:
            repairs[outcome] += 1
    h = categories["both_entail"] + categories["neither_entails"]
    k = repairs["correct"]
    raw_pairs = categories["correct_direction"]
    raw_rows = 2 * raw_pairs + h
    fixed_pairs = choices["correct"]
    assert fixed_pairs - raw_pairs == k and 2 * fixed_pairs - raw_rows == 2 * k - h
    return {
        "raw_categories": dict(categories),
        "comparison_choices": dict(choices),
        "raw_row_correct": raw_rows,
        "raw_pair_correct": raw_pairs,
        "comparison_row_correct": 2 * fixed_pairs,
        "comparison_pair_correct": fixed_pairs,
        "net_row_change": 2 * fixed_pairs - raw_rows,
        "both_registered_endpoints_improved": 2 * fixed_pairs > raw_rows and fixed_pairs > raw_pairs,
        "above_random_direction_expectation": 2 * fixed_pairs > sum(categories.values()),
        "ambiguous_pairs_resolved_correctly": k,
        "ambiguous_pairs_resolved_wrongly": repairs["reversed"],
        "ambiguous_pairs_tied": repairs["tie"],
    }


def score(file):
    with file.open(encoding="utf8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    result = {}
    for split, n in (("nmonli_test", 100), ("pmonli", 736)):
        group = defaultdict(dict)
        split_rows = [r for r in rows if r["subset"] == split]
        if len(split_rows) != 2 * n or len({r["id"] for r in split_rows}) != 2 * n:
            raise ValueError("incomplete rows")
        for row in split_rows:
            a, b = row["premise"], row["hypothesis"]
            group[tuple(sorted((a, b)))][row["gold"]] = row
        if len(group) != n:
            raise ValueError("incomplete pairs")
        directed_pairs = []
        for key, pair in group.items():
            f, r = pair["entailment"], pair["neutral"]
            assert f["premise"] == r["hypothesis"] and f["hypothesis"] == r["premise"]
            assert all(x["scan_" + c] == x["single_" + c] for x in (f, r) for c in "ENC")
            # Orient by text digest, independent of the labels supplied to the evaluator.
            if f["premise"] == key[0]:
                directed_pairs.append((f, r, "forward"))
            else:
                directed_pairs.append((r, f, "reverse"))
        modes = {}
        for mode in MODES:
            report = audit_pairs(
                (logits(f, mode), logits(r, mode), gold) for f, r, gold in directed_pairs
            )
            report["raw_binary_changes_from_single"] = sum(
                (entailment_margin(logits(x, mode)) >= 0)
                != (entailment_margin(logits(x, "single")) >= 0)
                for x in split_rows
            )
            report["projected_pair_changes_from_single"] = sum(
                choose_direction(logits(f, mode), logits(r, mode))
                != choose_direction(logits(f, "single"), logits(r, "single"))
                for f, r, _ in directed_pairs
            )
            modes[mode] = report
        result[split] = {"pairs": n, "equal_scan_float32": 6 * n, "policies": modes}
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("table", type=Path)
    print(json.dumps(score(p.parse_args().table), indent=2))
