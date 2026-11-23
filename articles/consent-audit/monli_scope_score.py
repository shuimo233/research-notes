"""Compute registered finite-cohort endpoints from the published scope ledger, without model libraries."""

import argparse
import csv
import json
from pathlib import Path
from struct import unpack
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monli_direction_score import choose_direction
from monli_scope import opposite


METHODS = ("original", "invert_original", "affirmative", "invert_affirmative", "evidence_first")


def summarize(rows):
    return {
        m: {
            "correct": sum(r[m] == r["gold"] for r in rows),
            "abstain": sum(r[m] == "abstain" for r in rows),
        }
        for m in METHODS
    }


def change(rows, after, before):
    wins = sum(r[after] == r["gold"] != r[before] for r in rows)
    losses = sum(r[before] == r["gold"] != r[after] for r in rows)
    return {"gained": wins, "lost": losses, "net": wins - losses}


def from_bits(row, condition, direction):
    return [unpack(">f", bytes.fromhex(row[f"{condition}_{direction}_{k}"]))[0] for k in "ENC"]


def length(row):
    return len(row["positive_source_lines"].split())


def assess(path):
    with path.open(encoding="utf8", newline="") as stream:
        table = list(csv.DictReader(stream, delimiter="\t"))
    for row in table:
        for cond, m in (("original", "original"), ("affirmative", "affirmative")):
            val = choose_direction(from_bits(row, cond, "ab"), from_bits(row, cond, "ba"))
            assert val == row[m] and opposite(val) == row["invert_" + m]
        assert bool(length(row)) == (row["basis"] == "evidence")
        if not length(row):
            assert row["evidence_first"] == row["invert_affirmative"]
    results = {}
    sets = {}
    for s, n in (("nmonli_train", 496), ("nmonli_test", 100)):
        rows = [r for r in table if r["subset"] == s]
        content = {(r["a_sha256"], r["b_sha256"]) for r in rows}
        assert len(rows) == len(content) == n
        sets[s] = content, {tuple(sorted([r["a_term"], r["b_term"]])) for r in rows}
        modes = summarize(rows)
        right = {m: d["correct"] for m, d in modes.items()}
        by_length = {}
        for size in sorted({length(r) for r in rows}):
            sub = [r for r in rows if length(r) == size]
            by_length[str(size)] = {"pairs": len(sub), "methods": summarize(sub)}
        rescued = [r for r in rows if length(r) and r["evidence_first"] != r["invert_affirmative"]]
        results[s] = {
            "pairs": n,
            "methods": modes,
            "by_path_length": by_length,
            "registered_D_beats_A_and_B": right["invert_affirmative"]
            > max(right["original"], right["invert_original"]),
            "registered_E_beats_A_B_D": right["evidence_first"]
            > max(right[m] for m in ("original", "invert_original", "invert_affirmative")),
            "signed_vs_direct": change(rows, "invert_affirmative", "original"),
            "signed_vs_blind_inversion": change(rows, "invert_affirmative", "invert_original"),
            "evidence_vs_signed": change(rows, "evidence_first", "invert_affirmative"),
            "pairs_where_evidence_changes_fallback": len(rescued),
            "counterfactual_forward_calls_avoided": 2 * sum(length(r) > 0 for r in rows),
        }
    a, b = sets.values()
    return {
        "subsets": results,
        "cross_split": {
            "identical_raw_pairs": len(a[0] & b[0]),
            "shared_unordered_lexical_pairs": len(a[1] & b[1]),
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    print(json.dumps(assess(parser.parse_args().ledger), indent=2))
