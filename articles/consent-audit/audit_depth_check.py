"""Independent public holdout, all-window, and extremal-ratio verifier."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations, permutations
import json
from math import comb
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incomparable_odds_check import derive, state_tables
from multi_odds_check import PINS
from selection_odds_check import independent_patterns


def sample(path, domain):
    data = path.read_bytes()
    assert sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == PINS[domain]
    groups = defaultdict(list)
    for case in json.loads(gzip.decompress(data)):
        groups[case["repo"] if domain == "CI" else domain].append(case)
    for key in sorted(groups):
        a = sorted(
            groups[key], key=lambda p: (int(p["run"]), int(p["job"])), reverse=True
        )
        yield from reversed(a[: 12 if domain == "CI" else 72])


def collect(modes):
    tables = {m: state_tables(m)[1] for m in modes}
    by_exact = [(1, 1)] * 5
    for p, q in permutations(tables.values(), 2):
        for w, (x, y) in enumerate(zip(p, q, strict=True)):
            k = w.bit_count()
            a, b = by_exact[k]
            for label, t in x.items():
                v = y.get(label)
                if v is not None and t * b > a * v:
                    a, b = t, v
            by_exact[k] = a, b
    odds = [F(*result) for result in by_exact]
    return ([max(odds[: k + 1]) for k in (1, 2, 3)], odds[4], max(odds), tables)


def certify_upper(width, depth, rate, floor, claimed):
    """Check every vertex of the count-polytope projection using exact lines."""
    mean = width * rate
    lo, hi = max(F(0), 1 - mean), 1 - rate
    zero = floor * (1 - rate) ** width
    gain = 1 - floor
    right_slope = F(depth - 1, width - 1)
    right_intercept = (1 - right_slope) * (1 - rate)
    for j in range(1, width):
        left, right = max(lo, 1 - mean / j), min(hi, 1 - mean / (j + 1))
        if left > right:
            continue
        a, b = (F(comb(width - j - i, depth), comb(width, depth)) for i in (0, 1))
        A = 1 - (j + 1) * a + j * b
        B = (j + 1 - mean) * a + (mean - j) * b
        rows = [
            (1, 0, right),
            (-1, 0, -left),
            (0, 1, hi),
            (0, -1, -lo),
            (A, -right_slope, right_intercept - B),
        ]
        for (u, v, r), (x, y, s) in combinations(rows, 2):
            determinant = u * y - v * x
            if not determinant:
                continue
            p0 = (r * y - v * s) / determinant
            q0 = (u * s - r * x) / determinant
            if all(a * p0 + b * q0 <= c for a, b, c in rows):
                assert zero + gain * p0 <= claimed * (zero + gain * q0)


def check_count_cases(s):
    p, q = s["pair"]
    slots = s["requests"]
    assert p < q and len(slots) >= 3
    assert set(s["case"]) == {"1/5", "1/2", "4/5"}
    for tag, case in s["case"].items():
        rate = F(tag)
        width = len(slots)
        left, right = [list(map(F, r)) for r in case["counts"]]
        for law in (left, right):
            assert len(law) == width + 1 and sum(law) == 1
            assert sum(i * m for i, m in enumerate(law)) == width * rate
            assert all(
                value >= F(comb(width, i), 2) * rate**i * (1 - rate) ** (width - i)
                for i, value in enumerate(law)
            )
        for count in (1, 2):
            assert sum(comb(width - i, count) * m for i, m in enumerate(left)) <= sum(
                comb(width - i, count) * m for i, m in enumerate(right)
            )
        peak = F(case["ratio"])
        assert peak == left[0] / right[0]
        certify_upper(width, 2, rate, F(1, 2), peak)


def opposite(modes):
    best = None
    for i, j in combinations(modes, 2):
        slots = [
            k
            for k in range(4)
            if {i & (3 << (2 * k)), j & (3 << (2 * k))}
            == {(1 << (2 * k)), (2 << (2 * k))}
        ]
        if len(slots) >= 3 and (best is None or len(slots) > len(best[2])):
            best = [i, j, slots]
    return best


def check(ci, bart, out):
    sources = [("CI", p) for p in sample(ci, "CI")] + [
        ("BART", p) for p in sample(bart, "BART")
    ]
    rows = json.loads(
        gzip.decompress((out / "audit-depth-policies.json.gz").read_bytes())
    )
    prior = json.loads((out / "audit-depth-results.json").read_bytes())
    tallies = defaultdict(Counter)
    families = defaultdict(set)
    gap = defaultdict(lambda: F(1))
    stress_peak = defaultdict(lambda: F(1))
    cache = {}
    for (kind, p), row in zip(sources, rows, strict=True):
        assert kind == row["domain"] and all(
            p[k] == row[k] for k in ("repo", "job", "run")
        )
        dims, edges, expected = derive(p)
        assert row["labels"] == expected
        groups = ("all", kind)
        for k in groups:
            tallies[k]["sampled"] += 1
        if len(expected) < 8:
            assert row["status"] == "fewer_than_four"
            continue
        assert row["status"] == "scored"
        modes = independent_patterns(dims, edges, [{"comparison": a} for a in expected])
        assert modes == row["modes"]
        key = tuple(modes)
        if key not in cache:
            cache[key] = collect(modes)
        small, full, overall, tables = cache[key]
        assert small == list(map(F, row["by_cutoff"]))
        assert full == F(row["full_only"]) and overall == F(row["all_windows"])
        witness = row["witness"]
        assert (witness is not None) == (overall > 1)
        if witness is not None:
            i, j, w = (witness[k] for k in ("numerator", "denominator", "window"))
            a = tuple(witness["message"])
            assert (
                i != j
                and 1 <= w <= 15
                and F(tables[i][w][a], tables[j][w][a]) == overall
            )
        stress = row["two_world_stress"]
        p = opposite(modes)
        assert (stress is None) == (p is None)
        if stress is not None:
            assert [*stress["pair"], stress["requests"]] == p
            check_count_cases(stress)
        for k in groups:
            c = tallies[k]
            c["scored"] += 1
            families[k].add(key)
            for i, limit in enumerate(small, start=1):
                c[f"miss_at_{i}"] += limit < overall
            gap[k] = max(gap[k], overall / small[1])
            if stress:
                c["stress_cases"] += 1
                stress_peak[k] = max(stress_peak[k], F(stress["case"]["1/2"]["ratio"]))
    report = {
        k: dict(
            v,
            distinct_families=len(families[k]),
            pair_gap=str(gap[k]),
            fair_stress_peak=str(stress_peak[k]),
        )
        for k, v in tallies.items()
    }
    assert prior == dict(
        results=report,
        gate=report["all"]["scored"] >= 50 and report["all"]["miss_at_2"] >= 10,
    )
    return prior | {"verified": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.ci, args.bart, args.output)))
