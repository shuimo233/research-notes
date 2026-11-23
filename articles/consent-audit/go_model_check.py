"""Verify endpoint scores, rank bounds and witnesses independently from the original optimization."""
import argparse
from collections import defaultdict
import csv
from fractions import Fraction
from itertools import accumulate, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_bounds import Baseline, Item, sharp


def score(tp, p, g):
    return Fraction(2 * tp, p + g) if p + g else Fraction(0)


def endpoints(records, field, ref):
    guesses = [(r[field], r[ref]) for r in records]
    g = sum(y.bit_count() for _, y in guesses)
    p = sum(x.bit_count() for x, _ in guesses)
    tp = sum((x & y).bit_count() for x, y in guesses)
    exact = sum(x == y for x, y in guesses)
    return {"true_positive": tp, "gold": g, "predicted": p, "micro_f1": str(score(tp, p, g)),
            "exact_matches": exact, "exact_accuracy": str(Fraction(exact, len(guesses)))}


def enumerate_sizes(base, choices):
    """Enumerate counts for EVERY observed item size, including singletons.

    For a fixed vector, total gold is fixed. Sort each size class independently
    and take its lowest/highest prefix. This uses no knapsack or backtracking.
    """
    groups = defaultdict(list)
    for n, a, b in choices:
        groups[n].append((a, b))
    sizes = sorted(groups)
    cache = {}
    low = high = start = base.delta()
    nearest = None
    for counts in product(*(range(len(groups[size]) + 1) for size in sizes)):
        k = sum(n * t for n, t in zip(sizes, counts))
        da = max(1, base.gold + base.predicted_a + k)
        db = max(1, base.gold + base.predicted_b + k)
        if k not in cache:
            prefixes = {}
            for n in sizes:
                gains = sorted(a * db - b * da for a, b in groups[n])
                prefixes[n] = (list(accumulate(gains, initial=0)), list(accumulate(reversed(gains), initial=0)))
            cache[k] = prefixes
        for order in (0, 1):
            s = sum(cache[k][n][order][t] for n, t in zip(sizes, counts))
            diff = Fraction(2 * (db * base.true_a - da * base.true_b + s), da * db)
            low, high = min(low, diff), max(high, diff)
            if start * diff < 0:
                nearest = sum(counts) if nearest is None else min(nearest, sum(counts))
    return low, high, nearest


def check_table(path, report):
    with path.open(encoding="utf8", newline="") as stream:
        rows = [{k: (v if k == "id" else int(v)) for k, v in r.items()} for r in csv.DictReader(stream, delimiter="\t")]
    rule_names = ("fp32", "int8", "top1")
    for model in rule_names:
        for r in ("released", "people"):
            assert endpoints(rows, model, r) == report["scores"][model][r]
    comparisons = 0
    witnesses = 0
    for name, pair in report["pairs"].items():
        a, b = name.split("_versus_")
        x, y = (endpoints(rows, rule, "released") for rule in (a, b))
        base = Baseline(x["gold"], x["predicted"], y["predicted"], x["true_positive"], y["true_positive"])
        groups, splits = [], []
        for row in rows:
            extra = row["people"] & ~row["released"]
            if extra:
                groups.append((extra.bit_count(), (row[a] & extra).bit_count(), (row[b] & extra).bit_count()))
            for bit in (1 << i for i in range(7)):
                if extra & bit:
                    splits.append((1, int(bool(row[a] & bit)), int(bool(row[b] & bit))))
        block = pair["whole_items"]
        for choices, min_value, max_value, nearest in (
                (groups, block["minimum"]["difference"], block["maximum"]["difference"], block["nearest_strict_reverse"]),
                (splits, pair["independent_labels"]["minimum"], pair["independent_labels"]["maximum"], "skip")):
            lo, hi, cost = enumerate_sizes(base, choices)
            assert (str(lo), str(hi)) == (min_value, max_value)
            if nearest != "skip":
                assert cost == (None if nearest is None else nearest["switches"])
            comparisons += 1
        for kind in ("minimum", "maximum", "nearest_strict_reverse"):
            witness = block[kind]
            if witness is None:
                continue
            chosen = set(witness["ids"])
            assert len(chosen) == witness["switches"]
            assert chosen <= {r["id"] for r in rows if r["released"] != r["people"]}
            paired = [{**r, "mixed": r["people"] if r["id"] in chosen else r["released"]} for r in rows]
            difference = Fraction(endpoints(paired, a, "mixed")["micro_f1"]) - Fraction(endpoints(paired, b, "mixed")["micro_f1"])
            assert str(difference) == witness["difference"]
            witnesses += 1
    return {"endpoint_tables": 6, "independent_extrema_pairs": comparisons, "full_batch_witnesses": witnesses}


def small_batches():
    rng = Random(281123)
    profiles = definitions = reverse_cases = 0
    for test in range(144):
        n = 1 + test % 8
        rows = []
        for i in range(n):
            old, new, a, b = (rng.randrange(8) for _ in range(4))
            rows.append((old, old | new, a, b))
        def diff(switches):
            gs = [y if flag else x for flag, (x, y, a, b) in zip(switches, rows)]
            def one(col):
                pp = [r[col] for r in rows]
                return score(sum((g & p).bit_count() for g, p in zip(gs, pp)),
                             sum(x.bit_count() for x in pp), sum(x.bit_count() for x in gs))
            return one(2) - one(3)
        def count(col):
            return sum(r[col].bit_count() for r in rows)
        base = Baseline(count(0), count(2), count(3), sum((x & a).bit_count() for x, _, a, _ in rows),
                        sum((x & b).bit_count() for x, _, _, b in rows))
        items = [Item(str(i), (x ^ y).bit_count(), ((x ^ y) & a).bit_count(), ((x ^ y) & b).bit_count())
                 for i, (x, y, a, b) in enumerate(rows) if x != y]
        vals = [(sum(flags), diff(flags)) for flags in product((0, 1), repeat=n)]
        start = vals[0][1]
        costs = [cost for cost, delta in vals if start * delta < 0]
        result = sharp(base, items)
        assert Fraction(result["minimum"]["difference"]) == min(d for _, d in vals)
        assert Fraction(result["maximum"]["difference"]) == max(d for _, d in vals)
        witness = result["nearest_strict_reverse"]
        assert (witness["switches"] if witness else None) == min(costs, default=None)
        profiles += 1
        definitions += len(vals)
        reverse_cases += bool(costs)
    return {"small_batches": profiles, "enumerated_assignments": definitions, "batches_with_strict_reversals": reverse_cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    print(json.dumps({**small_batches(), **check_table(args.table, json.loads(args.results.read_bytes()))}, indent=2))
