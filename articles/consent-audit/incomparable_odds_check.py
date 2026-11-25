"""Verify all multi-label windows from raw public constraints and projected probabilities."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import permutations, product
import json
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multi_odds_check import sample
from public_optimality_check import model
from selection_odds_check import independent_patterns


def frozen(path, kind):
    seen = Counter()
    for p in sample(path, kind):
        key = p["repo"] if kind == "CI" else kind
        seen[key] += 1
        if seen[key] <= (12 if kind == "CI" else 72):
            yield p


def derive(packet, width=4):
    n, _, _, _, base, d, _ = model(packet)
    labels = []
    for i, j in sorted({tuple(r[:2]) for r in packet["archive"]["targets"]}):
        low, high = -d[j][i], d[i][j]
        if high - low < 2:
            continue
        slack = (high - low - 1) // 3
        labels += [[j, i, 1 + slack - high], [i, j, low + slack + 1]]
        if len(labels) == 2 * width:
            break
    return n, base, labels


def state_tables(m):
    truth = [tuple(v for v in (1, 2) if m >> (2 * i + v - 1) & 1) for i in range(4)]
    alph = [frozenset((0, *t)) for t in truth]
    first = [{0: 4} | {v: 4 // len(t) for v in t} for t in truth]
    second = [
        dict(
            zip(
                (0, *t),
                ((2, 1, 5) if len(t) == 2 else (4, 4) if t == (1,) else (2, 6)),
                strict=True,
            )
        )
        for t in truth
    ]
    result = []
    for w in range(16):
        indices = [i for i in range(4) if w >> i & 1]
        cells = {}
        for response in product(*(sorted(alph[i]) for i in indices)):
            seq = list(zip(indices, response, strict=True))
            cells[response] = prod(first[i][r] for i, r in seq) + prod(
                second[i][r] for i, r in seq
            )
        assert sum(cells.values()) == 2 * 8 ** len(indices)
        result.append(cells)
    return alph, result


def evidence(modes):
    worlds = list(map(state_tables, modes))
    row = Counter()
    results = {}
    pair_hash = sha256()
    best = old = full = F(1)
    for i, j in permutations(range(len(modes)), 2):
        X, top = worlds[i]
        Y, bottom = worlds[j]
        shown = hidden = obscure = 0
        for k, (x, y) in enumerate(zip(X, Y, strict=True)):
            if x.issubset(y):
                shown |= 1 << k
            elif len(y) == 1 or x.isdisjoint(y):
                hidden |= 1 << k
            if y < x and len(y) > 1:
                obscure |= 1 << k
                row["reverse_nested_coordinates"] += 1
            if not x.issubset(y) and not y.issubset(x):
                row["incomparable_coordinates"] += 1
        correct, retained, heuristic, last = (1, 1), (1, 1), (1, 1), (1, 1)
        for w, (left, right) in enumerate(zip(top, bottom, strict=True)):
            common = left.keys() & right.keys()
            row["comparisons"] += len(common)
            winner = (1, 1)
            for answer in common:
                a, b = left[answer], right[answer]
                if a * winner[1] > winner[0] * b:
                    winner = a, b
            if winner[0] * correct[1] > correct[0] * winner[1]:
                correct = winner
            if w & shown == shown and not w & hidden:
                row["retained"] += len(common)
                if winner[0] * retained[1] > retained[0] * winner[1]:
                    retained = winner
                if (
                    not w & obscure
                    and winner[0] * heuristic[1] > heuristic[0] * winner[1]
                ):
                    heuristic = winner
            if w == 15:
                last = winner
        exact = F(*correct)
        assert F(*retained) == exact
        a, b = F(*heuristic), F(*last)
        row["wrong_heuristic_pairs"] += a < exact
        row["wrong_full_pairs"] += b < exact
        pair_hash.update(f"{i},{j},{exact}\n".encode())
        results[i, j] = exact, a
        best, old, full = max(best, exact), max(old, a), max(full, b)
    return (
        dict(
            row,
            odds=str(best),
            heuristic_odds=str(old),
            full_only_odds=str(full),
            pair_digest=pair_hash.hexdigest(),
        ),
        worlds,
        results,
    )


NUMBERS = (
    "comparisons",
    "retained",
    "wrong_heuristic_pairs",
    "wrong_full_pairs",
    "reverse_nested_coordinates",
    "incomparable_coordinates",
)


def witness_value(w, worlds):
    i, j, k = (w[x] for x in ("numerator", "denominator", "window"))
    a = tuple(w["message"])
    return F(worlds[i][1][k][a], worlds[j][1][k][a])


def check(ci, bart, out):
    rows = json.loads(
        gzip.decompress((out / "incomparable-odds-policies.json.gz").read_bytes())
    )
    report = json.loads((out / "incomparable-odds-results.json").read_bytes())
    cache = {}
    aggregate = defaultdict(Counter)
    different = defaultdict(set)
    for p, row in zip([*frozen(ci, "CI"), *frozen(bart, "BART")], rows, strict=True):
        assert all(p[k] == row[k] for k in ("repo", "job", "run", "domain"))
        n, edges, expected = derive(p)
        assert expected == row["labels"]
        groups = ("all", p["domain"])
        for key in groups:
            aggregate[key]["sampled"] += 1
        if len(expected) < 8:
            assert row["status"] == "fewer_than_four"
            continue
        assert row["status"] == "scored"
        modes = independent_patterns(n, edges, [{"comparison": r} for r in expected])
        assert modes == row["modes"]
        key = tuple(modes)
        if key not in cache:
            cache[key] = evidence(modes)
        measurements, worlds, pairs = cache[key]
        assert all(val == row[name] for name, val in measurements.items())
        for w in (row["witness"], row["maximum"]):
            if w is not None:
                exact, old = pairs[w["numerator"], w["denominator"]]
                assert witness_value(w, worlds) == exact
                if w is row["witness"]:
                    assert exact == F(w["correct"]) > F(w["heuristic"]) == old
                else:
                    assert exact == F(row["odds"])
        assert (row["witness"] is not None) == (row["wrong_heuristic_pairs"] > 0)
        assert (row["maximum"] is not None) == (F(row["odds"]) > 1)
        for scope in groups:
            different[scope].add(key)
            c = aggregate[scope]
            c["scored"] += 1
            c["worlds"] += len(modes)
            for tag in NUMBERS:
                c[tag] += measurements[tag]
            c["has_heuristic_miss"] += bool(row["wrong_heuristic_pairs"])
            c["has_full_miss"] += bool(row["wrong_full_pairs"])
            c["underestimated_by_heuristic"] += F(row["heuristic_odds"]) < F(
                row["odds"]
            )
            c["underestimated_by_full"] += F(row["full_only_odds"]) < F(row["odds"])
    summary = {
        k: dict(v, distinct_mode_families=len(different[k]))
        for k, v in aggregate.items()
    }
    a = summary["all"]
    assert report == dict(
        results=summary,
        reduction=str(F(a["comparisons"], a["retained"])),
        gate=a["scored"] >= 50
        and a["comparisons"] * 2 >= a["retained"] * 3
        and a["has_heuristic_miss"] >= 10,
    )
    return report | {"verified": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.ci, args.bart, args.output)))
