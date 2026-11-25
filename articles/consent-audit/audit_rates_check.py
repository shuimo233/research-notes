"""Independently check grouped primal and dual endpoint certificates."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations, product
import json
from math import comb, prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

PIN = "7ff77c48087929f54a1c9cda41bd984b14ec5edf"


def check_proof(rates, k, gamma, proof):
    groups = sorted(Counter(rates).items())
    assert groups == [(F(p), n) for p, n in proof["groups"]]
    sizes = [n for _, n in groups]
    sites = [i for i, m in enumerate(sizes) for _ in range(m)]
    combinations_by_size = set()
    for depth in range(2, k + 1):
        for asked in combinations(range(len(sites)), depth):
            c = Counter(sites[i] for i in asked)
            combinations_by_size.add(tuple(c[j] for j in range(len(sizes))))
    types = sorted(combinations_by_size)
    A, B = [{tuple(c): F(v) for c, v in row} for row in proof["residual"]]
    assert all(len(a) == len(b) for a, b in zip((A, B), proof["residual"], strict=True))
    grid = tuple(product(*(range(n + 1) for n in sizes)))
    assert len(grid) == int(proof["cells"])
    assert all(
        a.keys() <= set(grid) and min(a.values()) > 0 and sum(a.values()) == 1
        for a in (A, B)
    )
    for index, (p, n) in enumerate(groups):
        for a in (A, B):
            assert sum(c[index] * mass for c, mass in a.items()) == n * p

    def feature(c, tag):
        return prod(comb(n - j, a) for n, j, a in zip(sizes, c, tag, strict=True))

    for signature in types:
        assert sum(mass * feature(c, signature) for c, mass in A.items()) == sum(
            mass * feature(c, signature) for c, mass in B.items()
        )
    floor = gamma / (1 - gamma) * prod(1 - p for p in rates)
    zero = (0,) * len(groups)
    ratio = F(proof["ratio"])
    assert ratio == (floor + A.get(zero, 0)) / (floor + B.get(zero, 0))
    g = len(groups)
    prices = list(map(F, proof["dual"]))
    assert len(prices) == 2 + 2 * g + len(types) and len(A) + len(B) <= len(prices)
    norm, first, second, moments, objective = (
        prices[0],
        prices[1 : g + 1],
        prices[g + 1 : 2 * g + 1],
        prices[2 * g + 1 : -1],
        prices[-1],
    )
    assert objective == ratio - 1
    for c in grid:
        z = int(c == zero)
        centered = [m - p * n for m, (p, n) in zip(c, groups, strict=True)]
        f = sum(y * feature(c, s) for y, s in zip(moments, types, strict=True))
        assert norm + sum(y * m for y, m in zip(first, centered, strict=True)) + f >= z
        assert (
            -norm
            + sum(y * m for y, m in zip(second, centered, strict=True))
            - f
            + objective * (floor + z)
            >= -z
        )
    return ratio


def source(path):
    data = path.read_bytes()
    assert sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == PIN
    return [r for r in json.loads(gzip.decompress(data)) if r["status"] == "scored"]


def nominal(row):
    rates = []
    for i in row["pair"][2]:
        p = row["labels"][2 * i][2]
        q = row["labels"][2 * i + 1][2]
        overlap = (-p) - q + 1
        assert overlap > 0
        rates.append(F(1 if overlap <= 5 else 2 if overlap <= 30 else 4, 10))
    return rates


def identity(row):
    return [row[e] for e in ("domain", "repo", "run", "job")]


def check(inp, out):
    cohort = source(inp)
    emitted = json.loads(
        gzip.decompress((out / "audit-rates-policies.json.gz").read_bytes())
    )
    before = json.loads((out / "audit-rates-results.json").read_bytes())
    tallies = defaultdict(Counter)
    families = defaultdict(set)
    peak = defaultdict(lambda: F(1))
    for p, row in zip(cohort, emitted["cases"], strict=True):
        assert identity(p) == row["id"]
        rates = nominal(p)
        assert rates == list(map(F, row["nominal"]))
        low, high = [r - F(1, 100) for r in rates], [r + F(1, 100) for r in rates]
        checks = [
            check_proof(vector, 2, F(1, 2), row[key])
            for key, vector in (
                ("lower", low),
                ("upper", high),
                ("all_max", [max(high)] * len(high)),
                ("mean", [sum(high) / len(high)] * len(high)),
            )
        ]
        lb, ub, max_bound, average = checks
        assert lb <= ub <= max_bound
        for key in ("all", p["domain"]):
            c = tallies[key]
            c["certified"] += 1
            c["versus_all_max"] += ub < max_bound
            c["unsafe_mean"] += ub > average
            c["original_cells"] += 2 ** len(rates)
            c["grouped_cells"] += row["upper"]["cells"]
            families[key].add(tuple(map(tuple, row["upper"]["groups"])))
            peak[key] = max(peak[key], ub / lb)
    wide = []
    specs = []
    for domain in ("CI", "BART"):
        items = [q for q in cohort if q["domain"] == domain][:6]
        for i in (0, 3):
            specs.append((domain, items[i : i + 3]))
    for row, (domain, args) in zip(emitted["wide"], specs, strict=True):
        assert row["domain"] == domain and row["archives"] == list(map(identity, args))
        high = [r + F(1, 100) for p in args for r in nominal(p)]
        checked = check_proof(high, 2, F(1, 2), row["certificate"])
        assert checked >= 1
        assert row["width"] == len(high) and row["atomic"] == 2 ** len(high)
        assert row["grouped"] == row["certificate"]["cells"]
        wide.append({k: row[k] for k in ("domain", "width", "atomic", "grouped")})
    tally = {
        k: dict(v, rate_families=len(families[k]), interval_factor=str(peak[k]))
        for k, v in tallies.items()
    }
    assert before == dict(
        results=tally,
        wide=wide,
        gate=tally["all"]["certified"] >= 40
        and tally["all"]["versus_all_max"] >= 10
        and len(wide) == 4,
    )
    return before | {"verified": True}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.source, args.output)))
