"""Independent count-polytope and public-archive verification for audit caps."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations
import json
from math import comb
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from incomparable_odds_check import derive
from multi_odds_check import PINS
from selection_odds_check import independent_patterns


def archives(path, kind):
    content = path.read_bytes()
    assert sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == PINS[kind]
    packets = sorted(
        json.loads(gzip.decompress(content)),
        key=lambda p: (p["repo"], int(p["run"]), int(p["job"])),
    )
    counts = Counter()
    low, high = (12, 24) if kind == "CI" else (72, 144)
    for p in packets:
        k = p["repo"] if kind == "CI" else kind
        if low <= counts[k] < high:
            yield p
        counts[k] += 1


def independent_upper(w, p, gamma, caps, bound):
    """Enumerate vertices of every exact conditional-count interval."""
    m = w * p
    start, end = max(F(0), 1 - m), 1 - p
    common = gamma * (1 - p) ** w
    for j in range(1, w):
        lo, hi = max(start, 1 - m / j), min(end, 1 - m / (j + 1))
        if lo > hi:
            continue
        edges = [(1, 0, hi), (-1, 0, -lo), (0, 1, end), (0, -1, -start)]
        for s, B in caps.items():
            if s == 1:
                continue
            norm = comb(w, s)
            a, b = F(comb(w - j, s), norm), F(comb(w - j - 1, s), norm)
            total = F(w - s, w - 1) * (1 - p)
            base = gamma * (1 - p) ** s / (1 - gamma)
            edges.append(
                (
                    1 - (j + 1) * a + j * b,
                    -B * F(s - 1, w - 1),
                    B * total + (B - 1) * base - (j + 1 - m) * a - (m - j) * b,
                )
            )
        for (a, b, s), (u, v, t) in combinations(edges, 2):
            d = a * v - b * u
            if d:
                x, y = (s * v - b * t) / d, (a * t - s * u) / d
                if all(u * x + v * y <= t for u, v, t in edges):
                    assert common + (1 - gamma) * x <= bound * (
                        common + (1 - gamma) * y
                    )


def verify_laws(w, p, gamma, caps, r, packed):
    first, second = [list(map(F, law)) for law in packed]
    for law in (first, second):
        assert (
            len(law) == w + 1
            and sum(law) == 1
            and sum(j * q for j, q in enumerate(law)) == w * p
        )
        assert all(
            q >= gamma * comb(w, j) * p**j * (1 - p) ** (w - j)
            for j, q in enumerate(law)
        )
    for k, cap in caps.items():
        assert sum(v * comb(w - j, k) for j, v in enumerate(first)) <= cap * sum(
            v * comb(w - j, k) for j, v in enumerate(second)
        )
    assert first[0] == r * second[0]
    independent_upper(w, p, gamma, caps, r)


def truth_pair(masks):
    for a, b in combinations(masks, 2):
        if (
            a & b == 0
            and a | b == 255
            and all(
                sum((a >> (2 * j + bit)) & 1 for bit in range(2)) == 1 for j in range(4)
            )
        ):
            return [a, b]
    return None


def observations(groups, p):
    results = []
    for g in groups:
        forced = {i: sum(g[j] == i for j in range(4)) for i in g}
        law = {}
        for s in range(16):
            yes = Counter(g[k] for k in range(4) if s >> k & 1)
            independent = p ** s.bit_count() * (1 - p) ** (4 - s.bit_count())
            grouped = (
                p ** len(yes) * (1 - p) ** (len(forced) - len(yes))
                if all(v == forced[tag] for tag, v in yes.items())
                else 0
            )
            law[s] = (7 * independent + grouped) / 8
        assert sum(law.values()) == 1
        assert all(sum(x for s, x in law.items() if s >> k & 1) == p for k in range(4))
        results.append(law)

    def odds(window):
        a, b = [sum(p for s, p in q.items() if not s & window) for q in results]
        return a / b

    return odds(15), {
        k: max([F(1), *(odds(w) for w in range(16) if w.bit_count() == k)])
        for k in (2, 3)
    }


def check_config(row, p, limits, actual):
    ratio, deep = F(row["ratio"]), F(row["deep_only"])
    assert {int(k): F(x) for k, x in row["caps"].items()} == limits
    assert actual <= ratio <= deep
    retained = sorted(
        (
            u
            for u, B in limits.items()
            if all(
                (B - 1) * (v - 1) < (C - 1) * (u - 1)
                for v, C in limits.items()
                if v > u
            )
        ),
        reverse=True,
    )
    assert row["retained"] == retained
    verify_laws(4, p, F(1, 2), limits, ratio, row["counts"])
    verify_laws(4, p, F(1, 2), {3: limits[3]}, deep, row["deep_counts"])
    verify_laws(4, p, F(1, 2), {2: limits[3], 3: limits[3]}, deep, row["deep_counts"])
    return deep / ratio


def check(ci, bart, out):
    entries = json.loads(
        gzip.decompress((out / "audit-tolerance-policies.json.gz").read_bytes())
    )
    before = json.loads((out / "audit-tolerance-results.json").read_bytes())
    source = [
        (kind, p)
        for kind, path in (("CI", ci), ("BART", bart))
        for p in archives(path, kind)
    ]
    tally = defaultdict(Counter)
    shapes = defaultdict(set)
    factors = defaultdict(lambda: F(1))
    for (kind, p), row in zip(source, entries, strict=True):
        assert kind == row["domain"] and all(
            p[k] == row[k] for k in ("repo", "job", "run")
        )
        for g in ("all", kind):
            tally[g]["sampled"] += 1
        dims, edges, expected = derive(p)
        assert expected == row["labels"]
        if len(expected) < 8:
            assert row["status"] == "fewer_than_four"
            continue
        modes = independent_patterns(dims, edges, [{"comparison": a} for a in expected])
        assert modes == row["modes"]
        pair = truth_pair(modes)
        if pair is None:
            assert row["status"] == "no_opposing_pair"
            continue
        assert row["status"] == "scored" and row["opposing"] == pair
        groups = [
            [
                expected[2 * i if (a >> (2 * i) & 3) == 1 else 2 * i + 1][1]
                for i in range(4)
            ]
            for a in pair
        ]
        assert groups == row["groups"] and set(row["rates"]) == {"1/5", "1/2", "4/5"}
        collected = defaultdict(list)
        for text, stage in row["rates"].items():
            rate = F(text)
            actual, caps = observations(groups, rate)
            assert actual == F(stage["actual_full"])
            for tag, limits in (
                ("observed", caps),
                ("loose_three", caps | {3: max(F(3), caps[3])}),
            ):
                collected[tag].append(check_config(stage[tag], rate, limits, actual))
        for k in ("all", kind):
            shapes[k].add(tuple(modes))
            c = tally[k]
            c["scored"] += 1
            c["rate_profiles"] += 6
            for tag, values in collected.items():
                c[tag + "_archives_tighter"] += max(values) > 1
                c[tag + "_profiles_tighter"] += sum(r > 1 for r in values)
                factors[k, tag] = max(factors[k, tag], *values)
    report = {
        k: dict(
            v,
            distinct_families=len(shapes[k]),
            observed_factor=str(factors[k, "observed"]),
            loose_three_factor=str(factors[k, "loose_three"]),
        )
        for k, v in tally.items()
    }
    a = report["all"]
    assert before == dict(
        results=report,
        gate=a["scored"] >= 50 and a["loose_three_archives_tighter"] >= 10,
    )
    return before | {"verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ci", type=Path)
    parser.add_argument("bart", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.ci, args.bart, args.output)))
