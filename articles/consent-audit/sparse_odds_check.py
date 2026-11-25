"""Rebuild public supports and independently test every observable window."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multi_odds_check import sample
from public_optimality_check import model
from selection_odds_check import independent_patterns
from slack_certificate_check import potential


def labels_of(packet):
    n, _, _, _, base, d, _ = model(packet)
    labels = []
    fixed = list(base)
    for i, j in sorted({tuple(x[:2]) for x in packet["archive"]["targets"]}):
        lo, hi = -d[j][i], d[i][j]
        if hi - lo < 2:
            continue
        h = (hi - lo - 1) // 3
        new_edges = [(j, i, -(lo + h) - 1), (i, j, hi - h - 1)]
        if potential(n, [*fixed, *new_edges]) is None:
            continue
        labels += [[j, i, -(lo + h)], [i, j, hi - h]]
        fixed.extend(new_edges)
        if len(labels) == 6:
            break
    return n, base, labels


def compare(rows, windows):
    W = tuple(windows)
    count = 0
    largest = F(1)
    for w in W:
        projected = {}
        for s, row in rows.items():
            dist = defaultdict(F)
            for reply, p in row.items():
                dist[reply & w] += p
            projected[s] = dist
        for s, u in projected.items():
            for t, v in projected.items():
                if s == t:
                    continue
                for a in u.keys() & v.keys():
                    count += 1
                    if u[a] > largest * v[a]:
                        largest = u[a] / v[a]
    return largest, count


def verify_anchor(modes, proof):
    key = proof["lower"]
    d = max(s.bit_count() for s in modes)
    if key in ("1", "2", "8/3", "16/5"):
        assert d == {"1": 0, "2": 1, "8/3": 2, "16/5": 3}[key]
    elif key in ("3", "32/7"):
        s = proof["world"]
        patterns = [x & s for x in proof["anchors"]]
        assert s in modes and all(x in modes for x in proof["anchors"])
        assert all(x.bit_count() == 1 for x in patterns)
        assert s.bit_count() == d == {"3": 2, "32/7": 3}[key]
        assert len(set(patterns)) >= d - 1
    else:
        assert key == "2+sqrt(7)"
        s, t = proof["denominator"], proof["numerator"]
        assert s in modes and t in modes and s.bit_count() == t.bit_count() == d == 3
        shared = s & t
        x, y, z = proof["anchors"]
        assert all(h in modes for h in (x, y, z))
        assert shared.bit_count() == 2 and t & z == t ^ shared
        assert (x & s).bit_count() == (y & s).bit_count() == 1
        assert ((x & s) | (y & s)) == shared
    return key


def check_row(packet, row):
    assert all(row[k] == packet[k] for k in ("domain", "repo", "run", "job"))
    n, base, labels = labels_of(packet)
    assert labels == row["labels"]
    if len(labels) < 6:
        assert row["status"] == "fewer_than_six"
        return False
    assert row["status"] == "scored"
    modes = independent_patterns(n, base, [{"comparison": claim} for claim in labels])
    assert modes == row["modes"] and modes[0] == 0
    d = max(s.bit_count() for s in modes)
    assert d == row["rank"] <= 3
    overlap = any(
        s.bit_count() == t.bit_count() == 3 and s != t and (s & t).bit_count() == 2
        for s in modes
        for t in modes
    )
    assert overlap is row["overlapping_triples"]
    cap = F(93, 20) if overlap else (F(1), F(2), F(3), F(32, 7))[d]
    assert cap == F(row["upper"])
    probabilities = {}
    for s, packed in zip(modes, row["rows"], strict=True):
        indices = [i for i in range(64) if i & ~s == 0]
        outcomes = dict(zip(indices, map(F, packed), strict=True))
        assert min(outcomes.values()) >= F(1, 2 ** (s.bit_count() + 1))
        assert sum(outcomes.values()) == 1
        for i in range(6):
            if s >> i & 1:
                assert sum(p for a, p in outcomes.items() if a >> i & 1) == F(1, 2)
        probabilities[s] = outcomes
    cap_observed, exp = compare(probabilities, range(1, 64))
    assert cap_observed == F(row["actual"]) <= cap
    assert exp == row["all_windows"]
    val = F(1)
    count = 0
    for s in modes:
        for t in modes:
            if s == t:
                continue
            for a, p in probabilities[t].items():
                top = sum(w for b, w in probabilities[s].items() if b & t == a)
                if top:
                    count += 1
                    if top > val * p:
                        val = top / p
    assert val == cap_observed and count == row["canonical"]
    if val > 1:
        s, t, a = row["witness"]
        assert (
            s != t
            and sum(p for b, p in probabilities[s].items() if b & t == a)
            == val * probabilities[t][a]
        )
    independent = 2 ** max((t & ~s).bit_count() for s in modes for t in modes)
    assert F(row["independent"]) == independent
    lower = verify_anchor(modes, row["lower"])
    if lower == "2+sqrt(7)":
        assert val > 2 and (val - 2) ** 2 >= 7
        assert cap - (F(1, 200)) > 2 and (cap - F(1, 200) - 2) ** 2 < 7
    else:
        assert F(lower) <= val
    assert row["exact"] is (lower == "2+sqrt(7)" or F(lower) == cap)
    return True


def check(ci, bart, output):
    rows = json.loads(
        gzip.decompress((output / "sparse-odds-policies.json.gz").read_bytes())
    )
    packets = [*sample(ci, "CI"), *sample(bart, "BART")]
    report = json.loads((output / "sparse-odds-results.json").read_bytes())
    counts = defaultdict(Counter)
    families = defaultdict(set)
    for packet, row in zip(packets, rows, strict=True):
        verified = check_row(packet, row)
        for k in ("total", packet["domain"]):
            c = counts[k]
            c["sampled"] += 1
            if not verified:
                continue
            c["scored"] += 1
            c["rank_three"] += row["rank"] == 3
            c["all_windows"] += row["all_windows"]
            c["canonical"] += row["canonical"]
            c["exact"] += row["exact"]
            c["nonoverlap"] += row["rank"] == 3 and not row["overlapping_triples"]
            c["sharp_overlap"] += row["lower"]["lower"] == "2+sqrt(7)"
            c["strictly_better_than_independent"] += F(row["actual"]) < F(
                row["independent"]
            )
            families[k].add(tuple(row["modes"]))
    tables = {k: dict(v, distinct_modes=len(families[k])) for k, v in counts.items()}
    a, b = tables["total"]["all_windows"], tables["total"]["canonical"]
    assert report == dict(
        results=tables,
        comparison_reduction=str(F(a, b)),
        gate=tables["total"]["scored"] >= 40 and a >= 4 * b,
    )
    return report | {"verified": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.ci, a.bart, a.output)))
