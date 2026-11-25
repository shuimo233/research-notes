"""Measure limited-window decisions on frozen holdout release catalogues."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations, permutations
import json
from pathlib import Path

from audit_depth import worst_full_ratio
from incomparable_odds import WindowAudit
from incomparable_odds_run import labels_of, weights
from multi_odds_run import SOURCES
from selection_odds import patterns

RATES = (F(1, 5), F(1, 2), F(4, 5))


def read(path, domain):
    data = path.read_bytes()
    if sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != SOURCES[domain]:
        raise ValueError("expected the registered public archive")
    groups = defaultdict(list)
    for case in json.loads(gzip.decompress(data)):
        groups[case["repo"] if domain == "CI" else domain].append(case)
    for key in sorted(groups):
        chosen = sorted(groups[key], key=lambda p: (int(p["run"]), int(p["job"])))
        yield from chosen[-12 if domain == "CI" else -72 :]


def profile(modes):
    audit = WindowAudit([weights(m) for m in modes])
    by_depth = [F(1)] * 4
    true_max = F(1)
    why = None
    groups = [[w for w in range(1, 16) if w.bit_count() <= k] for k in range(1, 4)]
    for i, j in permutations(range(len(modes)), 2):
        value, _, witness = audit.directed(i, j)
        if value > true_max:
            true_max = value
            why = dict(
                numerator=modes[i],
                denominator=modes[j],
                window=witness[0],
                message=list(witness[1]),
            )
        for k, windows in enumerate(groups):
            by_depth[k] = max(by_depth[k], audit.directed(i, j, windows)[0])
        by_depth[3] = max(by_depth[3], audit.directed(i, j, (15,))[0])
    return list(map(str, by_depth)), str(true_max), why


def opposing(modes):
    def slots(a, b):
        return [
            i
            for i in range(4)
            if (a >> (i * 2) & 3, b >> (i * 2) & 3) in ((1, 2), (2, 1))
        ]

    found = None
    for a, b in combinations(modes, 2):
        selected = slots(a, b)
        if len(selected) >= 3 and (found is None or len(selected) > len(found[2])):
            found = (a, b, selected)
    return found


def stress(modes):
    best = opposing(modes)
    if best is None:
        return None
    first, second, requests = best
    results = {}
    for p in RATES:
        ratio, counts = worst_full_ratio(len(requests), 2, p, F(1, 2))
        results[str(p)] = dict(
            ratio=str(ratio), counts=[list(map(str, c)) for c in counts]
        )
    return dict(pair=[first, second], requests=requests, case=results)


def evaluate(kind, p, cache):
    labels, zone = labels_of(p)
    keys = dict(domain=kind, repo=p["repo"], run=p["run"], job=p["job"], labels=labels)
    if len(labels) < 8:
        return keys | dict(status="fewer_than_four")
    modes, empty, _ = patterns(zone, labels)
    assert not empty
    key = tuple(modes)
    if key not in cache:
        small, worst, example = profile(modes)
        cache[key] = dict(
            modes=modes,
            by_cutoff=small[:3],
            full_only=small[3],
            all_windows=worst,
            witness=example,
            two_world_stress=stress(modes),
        )
    return keys | dict(status="scored") | cache[key]


def summary(data):
    totals = defaultdict(Counter)
    shapes = defaultdict(set)
    gap = defaultdict(lambda: F(1))
    stress_bound = defaultdict(lambda: F(1))
    for row in data:
        for scope in ("all", row["domain"]):
            c = totals[scope]
            c["sampled"] += 1
            if row["status"] != "scored":
                continue
            c["scored"] += 1
            shapes[scope].add(tuple(row["modes"]))
            exact = F(row["all_windows"])
            for i, r in enumerate(row["by_cutoff"], start=1):
                if i < 4:
                    c[f"miss_at_{i}"] += F(r) < exact
            gap[scope] = max(gap[scope], exact / F(row["by_cutoff"][1]))
            s = row["two_world_stress"]
            if s is not None:
                c["stress_cases"] += 1
                stress_bound[scope] = max(
                    stress_bound[scope], F(s["case"]["1/2"]["ratio"])
                )
    results = {
        k: dict(
            v,
            distinct_families=len(shapes[k]),
            pair_gap=str(gap[k]),
            fair_stress_peak=str(stress_bound[k]),
        )
        for k, v in totals.items()
    }
    a = totals["all"]
    return dict(results=results, gate=a["scored"] >= 50 and a["miss_at_2"] >= 10)


def run(ci, bart, out):
    cache = {}
    rows = [
        evaluate(kind, p, cache)
        for kind, file in (("CI", ci), ("BART", bart))
        for p in read(file, kind)
    ]
    result = summary(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit-depth-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode(), mtime=0
        )
    )
    (out / "audit-depth-results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.ci, a.bart, a.output)
