"""Certify finite paired-score changes with partial directional labels and no sampling assumptions."""

import argparse
import csv
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monli_direction_score import choose_direction, entailment_margin, logits


def review_bounds(pairs, judgments=None):
    """pairs maps stable IDs to (forward scores, reverse scores). judgments maps reviewed IDs to gold directions."""
    if judgments is None:
        judgments = {}
    if not judgments.keys() <= pairs.keys():
        raise ValueError("unrecognized reviewed pair")
    if any(x not in ("forward", "reverse") for x in judgments.values()):
        raise ValueError("expected directional labels")
    same = correct = ties = 0
    pending = []
    for key, (forward, reverse) in pairs.items():
        f, r = tuple(forward), tuple(reverse)
        if (entailment_margin(f) >= 0) != (entailment_margin(r) >= 0):
            continue
        same += 1
        choice = choose_direction(f, r)
        if choice == "abstain":
            ties += 1
        elif key in judgments:
            correct += int(judgments[key] == choice)
        else:
            pending.append(key)
    upper = correct + len(pending)
    return {
        "same_raw_decision": same,
        "ties": ties,
        "pending": sorted(pending),
        "pair_gain_bounds": [correct, upper],
        "row_gain_bounds": [2 * correct - same, 2 * upper - same],
    }


def source_pairs(rows):
    pairs, truth = {}, {}
    for row in rows:
        a, b = row["premise"], row["hypothesis"]
        low, high = sorted((a, b))
        key = sha256(("monli-review-v1\n" + low + "\n" + high).encode()).hexdigest()
        index = int(a != low)
        pair = pairs.setdefault(key, [None, None])
        if pair[index] is not None:
            raise ValueError("duplicate direction")
        pair[index] = logits(row, "single")
        if row["gold"] == "entailment":
            if key in truth:
                raise ValueError("duplicate gold direction")
            truth[key] = ("forward", "reverse")[index]
    if pairs.keys() != truth.keys() or any(None in p for p in pairs.values()):
        raise ValueError("each pair must have exactly one annotated direction")
    return pairs, truth


def replay(table):
    with table.open(encoding="utf8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    result = {}
    for subset in ("nmonli_test", "pmonli"):
        pairs, labels = source_pairs([r for r in rows if r["subset"] == subset])
        blind = review_bounds(pairs)
        order = blind["pending"]
        reviewed = {}
        first = None
        for key in order:
            reviewed[key] = labels[key]
            step = review_bounds(pairs, reviewed)
            lo, hi = step["row_gain_bounds"]
            if first is None and (lo > 0 or hi < 0):
                first = {"read_pairs": len(reviewed), "interval": [lo, hi], "last_reviewed": key}
        final = review_bounds(pairs, reviewed)
        assert not final["pending"]
        result[subset] = {
            "pairs": len(pairs),
            "distinct_reference_pairs_for_exact_gain": len(order),
            "initial_row_range": blind["row_gain_bounds"],
            "strict_sign_first_certified": first,
            "final_row_change": final["row_gain_bounds"][0],
            "final_pair_gain": final["pair_gain_bounds"][0],
            "queue_sha256": sha256("\n".join(order).encode()).hexdigest(),
        }
    return result


def check_bounds():
    # Exhaust all gold completions and every partial labeling of an illustrative queue.
    a, b, c = (2, 0, 0), (1, 0, 0), (-1, 0, 0)
    pairs = {"coherent": (a, c), "same_yes": (a, b), "same_no": (c, (-2, 0, 0)), "tie": (b, b)}
    keys = list(pairs)
    cases = 0
    for partial in product((None, "forward", "reverse"), repeat=len(keys)):
        known = {k: v for k, v in zip(keys, partial) if v is not None}
        bounds = review_bounds(pairs, known)
        observed = []
        for labels in product(("forward", "reverse"), repeat=len(keys)):
            if any(t != known.get(k, t) for k, t in zip(keys, labels)):
                continue
            rows = pairs_gained = 0
            for k, truth in zip(keys, labels):
                f, r = pairs[k]
                old = int((max(f) == f[0]) == (truth == "forward")) + int(
                    (max(r) == r[0]) == (truth == "reverse")
                )
                right = choose_direction(f, r) == truth
                rows += 2 * right - old
                pairs_gained += right - int(old == 2)
            observed.append((rows, pairs_gained))
        for index, key in enumerate(("row_gain_bounds", "pair_gain_bounds")):
            values = [v[index] for v in observed]
            assert [min(values), max(values)] == bounds[key]
        cases += 1
    return cases


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--study", type=Path, help="replay the fixed MoNLI review order")
    g.add_argument(
        "--pairs", type=Path, help="JSON object mapping pair IDs to [forward logits, reverse logits]"
    )
    p.add_argument("--judgments", type=Path, help="JSON mapping reviewed IDs to forward/reverse")
    args = p.parse_args()
    if args.study:
        if args.judgments:
            p.error("--judgments is used with --pairs")
        result = {"subsets": replay(args.study), "exhaustive_partial_label_cases": check_bounds()}
    else:
        labels = json.loads(args.judgments.read_bytes()) if args.judgments else {}
        result = review_bounds(json.loads(args.pairs.read_bytes()), labels)
    print(json.dumps(result, indent=2))
