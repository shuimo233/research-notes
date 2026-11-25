"""Independent dual, parity-witness, and raw-world verification."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations
import json
from math import comb, prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_depth_check import certify_upper
from incomparable_odds_check import derive
from multi_odds_check import PINS
from slack_certificate_check import potential


def selected(path, kind):
    raw = path.read_bytes()
    assert sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == PINS[kind]
    ordered = sorted(
        json.loads(gzip.decompress(raw)),
        key=lambda p: (p["repo"], int(p["run"]), int(p["job"])),
    )
    seen = Counter()
    start, end = (24, 32) if kind == "CI" else (144, 216)
    for packet in ordered:
        key = packet["repo"] if kind == "CI" else kind
        if start <= seen[key] < end:
            yield packet
        seen[key] += 1


def masks_of(n, base, labels):
    stack = [(0, 0, base)]
    masks = []
    while stack:
        i, mask, edges = stack.pop()
        if i == len(labels):
            masks.append(mask)
            continue
        for truth in (1, 2, 3):
            add = []
            for j, (a, b, t) in enumerate(labels[i : i + 2]):
                add.append((b, a, -t) if truth >> j & 1 else (a, b, t - 1))
            trial = [*edges, *add]
            if potential(n, trial) is not None:
                stack.append((i + 2, mask | (truth << i), trial))
    return sorted(masks)


def opposing(masks, n):
    best = []
    result = None
    for a, b in combinations(masks, 2):
        differences = []
        for i in range(n):
            if {a >> (2 * i) & 3, b >> (2 * i) & 3} == {1, 2}:
                differences.append(i)
        if len(differences) > len(best):
            result = [a, b, differences]
            best = differences
            if len(best) == n:
                break
    return result if len(best) >= 4 else None


def check_bilateral(w, depth, p, floor, ratio, residual, proof):
    left, right = [list(map(F, l)) for l in residual]
    for r in (left, right):
        assert len(r) == w + 1 and min(r) >= 0 and sum(r) == 1
        assert sum(j * m for j, m in enumerate(r)) == w * p
    assert sum(v > 0 for law in (left, right) for v in law) <= depth + 3
    for u in range(1, depth + 1):
        assert (
            sum(
                comb(w - j, u) * (x - y)
                for j, (x, y) in enumerate(zip(left, right, strict=True))
            )
            == 0
        )
    scaled_floor = floor * (1 - p) ** w / (1 - floor)
    assert ratio == (scaled_floor + left[0]) / (scaled_floor + right[0])
    normalize, x_mean, y_mean, *moments, goal = map(F, proof)
    assert goal == ratio - 1 and len(moments) == depth - 1
    for j in range(w + 1):
        moment = sum(v * comb(w - j, u) for u, v in enumerate(moments, start=2))
        assert normalize + x_mean * (j - w * p) + moment >= int(j == 0)
        assert -normalize + y_mean * (j - w * p) - moment + goal * (
            scaled_floor + int(j == 0)
        ) >= -int(j == 0)


def check_direction(w, k, p, floor, cap, counts):
    X, Y = [list(map(F, q)) for q in counts]
    for z in (X, Y):
        assert (
            len(z) == w + 1
            and sum(z) == 1
            and sum(j * m for j, m in enumerate(z)) == w * p
        )
        assert all(
            x >= floor * comb(w, j) * p**j * (1 - p) ** (w - j) for j, x in enumerate(z)
        )
    for u in range(1, k + 1):
        assert (
            sum(
                comb(w - j, u) * (x - y)
                for j, (x, y) in enumerate(zip(X, Y, strict=True))
            )
            <= 0
        )
    assert X[0] == cap * Y[0]
    certify_upper(w, k, p, floor, cap)


def check_heterogeneous(rates, floor, ratio, alpha, parts):
    w = len(rates)
    allowed = 2 * min(min(p, 1 - p) for p in rates)
    assert 0 <= alpha <= allowed
    support = {m: F(q) for m, q in parts}
    assert len(support) == len(parts) and all(
        0 <= m < 1 << w and q > 0 for m, q in support.items()
    )
    assert sum(support.values()) == 1 - alpha
    for i, p in enumerate(rates):
        assert sum(q for m, q in support.items() if m >> i & 1) + alpha / 2 == p
    scaled = floor * prod(1 - a for a in rates) / (1 - floor)
    actual_zero = support.get(0, 0)
    assert ratio == 1 + F(alpha, 2 ** (w - 1)) / (scaled + actual_zero)
    slope = F(w, 2) - 1
    offset = 1 - sum(rates)
    vertices = [F(0), allowed]
    if slope and 0 < -offset / slope < allowed:
        vertices.append(-offset / slope)
    for weight in vertices:
        floor_zero = max(0, offset + weight * slope)
        assert 1 + F(weight, 2 ** (w - 1)) / (scaled + floor_zero) <= ratio


def check(ci, bart, out):
    rows = json.loads(
        gzip.decompress((out / "audit-parity-policies.json.gz").read_bytes())
    )
    saved = json.loads((out / "audit-parity-results.json").read_bytes())
    packets = [
        (kind, p)
        for kind, path in (("CI", ci), ("BART", bart))
        for p in selected(path, kind)
    ]
    counters = defaultdict(Counter)
    count_shapes = defaultdict(Counter)
    support_patterns = defaultdict(set)
    max_reduction = defaultdict(lambda: F(1))
    for (kind, p), row in zip(packets, rows, strict=True):
        assert row["domain"] == kind and all(
            p[k] == row[k] for k in ("repo", "job", "run")
        )
        dims, base, labels = derive(p, width=6)
        assert labels == row["labels"]
        groups = ("all", kind)
        for tag in groups:
            counters[tag]["sampled"] += 1
        if len(labels) < 8:
            assert row["status"] == "fewer_than_four"
            continue
        modes = masks_of(dims, base, labels)
        assert row["modes"] == modes
        pair = opposing(modes, len(labels) // 2)
        if pair is None:
            assert row["status"] == "no_opposing_four"
            continue
        assert row["status"] == "scored" and row["pair"] == pair
        w = len(pair[2])
        ratios = []
        assert set(row["profiles"]) == {"1/5", "1/2", "4/5"}
        for rate, values in row["profiles"].items():
            rate = F(rate)
            assert set(values) == set(map(str, {2, 3, w - 1}))
            for depth, profile in values.items():
                d = int(depth)
                r, one = F(profile["ratio"]), F(profile["one_direction"])
                check_bilateral(
                    w, d, rate, F(1, 2), r, profile["residual"], profile["dual"]
                )
                check_direction(w, d, rate, F(1, 2), one, profile["one_counts"])
                assert r <= one
                ratios.append(one / r)
        z = row["heterogeneous"]
        rates = [F(1, 5) + F(3 * i, 5 * (w - 1)) for i in range(w)]
        assert list(map(F, z["rates"])) == rates
        check_heterogeneous(rates, F(1, 2), F(z["ratio"]), F(z["alpha"]), z["common"])
        for tag in groups:
            counters[tag]["scored"] += 1
            counters[tag]["profiles"] += len(ratios)
            counters[tag]["tightened_profiles"] += sum(x > 1 for x in ratios)
            counters[tag]["tightened_archives"] += any(x > 1 for x in ratios)
            count_shapes[tag][str(w)] += 1
            support_patterns[tag].add((len(labels), tuple(modes)))
            max_reduction[tag] = max(max_reduction[tag], *ratios)
    report = {
        k: dict(
            v,
            widths=dict(count_shapes[k]),
            distinct_families=len(support_patterns[k]),
            reduction=str(max_reduction[k]),
        )
        for k, v in counters.items()
    }
    assert saved == dict(
        results=report,
        gate=report["all"]["scored"] >= 40
        and report["all"]["tightened_archives"] >= 10,
    )
    return saved | {"verified": True}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("ci", type=Path)
    cli.add_argument("bart", type=Path)
    cli.add_argument("output", type=Path)
    a = cli.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.ci, a.bart, a.output)))
