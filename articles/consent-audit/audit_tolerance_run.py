"""Audit endpoint-grouped release policies on a disjoint set of public archives."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
import gzip
from hashlib import sha1
from itertools import combinations
import json
from pathlib import Path

from audit_tolerance import needed_caps, worst_profile
from incomparable_odds_run import labels_of
from multi_odds_run import SOURCES
from selection_odds import patterns

RATES = (F(1, 5), F(1, 2), F(4, 5))


def read(path, kind):
    data = path.read_bytes()
    if sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != SOURCES[kind]:
        raise ValueError("expected the registered archive")
    buckets = defaultdict(list)
    for p in json.loads(gzip.decompress(data)):
        buckets[p["repo"] if kind == "CI" else kind].append(p)
    for key in sorted(buckets):
        rows = sorted(buckets[key], key=lambda p: (int(p["run"]), int(p["job"])))
        yield from rows[12:24] if kind == "CI" else rows[72:144]


def paired(modes):
    supported = set(modes)
    for s in modes:
        if (
            s < 255 ^ s
            and (255 ^ s) in supported
            and all((s >> (2 * k)) & 3 in (1, 2) for k in range(4))
        ):
            return [s, 255 ^ s]
    return None


def group_ids(labels, mask):
    return [labels[2 * i + ((mask >> (2 * i) & 3) == 2)][1] for i in range(4)]


def ratio_on(grouped, p, window):
    size = len(window)
    left, right = [len({g[k] for k in window}) for g in grouped]

    def refusal(g):
        return (7 * (1 - p) ** size + (1 - p) ** g) / 8

    return refusal(left) / refusal(right)


def result_for(grouped, p):
    cap = {
        k: max(ratio_on(grouped, p, w) for w in combinations(range(4), k))
        for k in (2, 3)
    }
    cap = {k: max(F(1), B) for k, B in cap.items()}
    actual = ratio_on(grouped, p, tuple(range(4)))
    configurations = {}
    for tag, limit in (
        ("observed", cap),
        ("loose_three", cap | {3: max(F(3), cap[3])}),
    ):
        optimum, best = worst_profile(4, p, F(1, 2), limit)
        deep, deep_law = worst_profile(4, p, F(1, 2), {3: limit[3]})
        assert actual <= optimum <= deep
        unified, _ = worst_profile(4, p, F(1, 2), {2: limit[3], 3: limit[3]})
        assert unified == deep
        configurations[tag] = dict(
            caps={str(k): str(B) for k, B in limit.items()},
            retained=list(needed_caps(limit)),
            ratio=str(optimum),
            deep_only=str(deep),
            counts=[list(map(str, r)) for r in best],
            deep_counts=[list(map(str, r)) for r in deep_law],
        )
    return dict(actual_full=str(actual), **configurations)


def evaluate(kind, packet):
    labels, dbm = labels_of(packet)
    identity = dict(
        domain=kind, repo=packet["repo"], run=packet["run"], job=packet["job"]
    )
    if len(labels) < 8:
        return identity | dict(status="fewer_than_four", labels=labels)
    modes, empty, _ = patterns(dbm, labels)
    assert not empty
    opp = paired(modes)
    if opp is None:
        return identity | dict(status="no_opposing_pair", labels=labels, modes=modes)
    grouped = [group_ids(labels, m) for m in opp]
    return identity | dict(
        status="scored",
        labels=labels,
        modes=modes,
        opposing=opp,
        groups=grouped,
        rates={str(p): result_for(grouped, p) for p in RATES},
    )


def summarize(rows):
    stats = defaultdict(Counter)
    families = defaultdict(set)
    biggest = defaultdict(lambda: F(1))
    for row in rows:
        for key in ("all", row["domain"]):
            stats[key]["sampled"] += 1
            if row["status"] != "scored":
                continue
            stats[key]["scored"] += 1
            families[key].add(tuple(row["modes"]))
            values = list(row["rates"].values())
            stats[key]["rate_profiles"] += len(values) * 2
            for config in ("observed", "loose_three"):
                ratios = [
                    F(v[config]["deep_only"]) / F(v[config]["ratio"]) for v in values
                ]
                stats[key][config + "_profiles_tighter"] += sum(v > 1 for v in ratios)
                stats[key][config + "_archives_tighter"] += any(v > 1 for v in ratios)
                biggest[key, config] = max(biggest[key, config], *ratios)
    results = {
        k: dict(
            v,
            distinct_families=len(families[k]),
            observed_factor=str(biggest[k, "observed"]),
            loose_three_factor=str(biggest[k, "loose_three"]),
        )
        for k, v in stats.items()
    }
    a = stats["all"]
    return dict(
        results=results,
        gate=a["scored"] >= 50 and a["loose_three_archives_tighter"] >= 10,
    )


def run(ci, bart, out):
    rows = [
        evaluate(kind, p)
        for kind, path in (("CI", ci), ("BART", bart))
        for p in read(path, kind)
    ]
    report = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit-tolerance-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode(), mtime=0
        )
    )
    (out / "audit-tolerance-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ci", type=Path)
    parser.add_argument("bart", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.ci, args.bart, args.output)
