"""Replay bilateral low-window contracts on another frozen archive slice."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha1
from itertools import combinations
import json
from pathlib import Path

from audit_depth import worst_full_ratio
from audit_parity import last_window, worst_equal
from incomparable_odds_run import labels_of
from multi_odds_run import SOURCES
from selection_odds import patterns

RATES = (F(1, 5), F(1, 2), F(4, 5))


def sample(path, kind):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != SOURCES[kind]:
        raise ValueError("expected the registered archive")
    groups = defaultdict(list)
    for p in json.loads(gzip.decompress(raw)):
        groups[p["repo"] if kind == "CI" else kind].append(p)
    for repo in sorted(groups):
        cases = sorted(groups[repo], key=lambda p: (int(p["run"]), int(p["job"])))
        yield from cases[24:32] if kind == "CI" else cases[144:216]


def select_pair(modes, n):
    bits = sum(1 << (2 * i) for i in range(n))
    single = {}
    for mask in modes:
        early, late = mask & bits, (mask >> 1) & bits
        single[mask] = (early & ~late, late & ~early)
    best = 0
    output = None
    for a, b in combinations(modes, 2):
        x, y = single[a]
        r, s = single[b]
        opposite = (x & s) | (y & r)
        size = opposite.bit_count()
        if size > best:
            best = size
            output = [a, b, [i for i in range(n) if (opposite >> (2 * i)) & 1]]
            if size == n:
                break
    return output if best >= 4 else None


@cache
def laws(width):
    rate_cases = {}
    for p in RATES:
        jobs = {}
        for k in sorted({2, 3, width - 1}):
            ratio, residual, dual = worst_equal(width, k, p, F(1, 2))
            ordinary, one_witness = worst_full_ratio(width, k, p, F(1, 2))
            assert ratio <= ordinary
            jobs[str(k)] = dict(
                ratio=str(ratio),
                one_direction=str(ordinary),
                one_counts=[list(map(str, c)) for c in one_witness],
                residual=[list(map(str, c)) for c in residual],
                dual=list(map(str, dual)),
            )
        rate_cases[str(p)] = jobs
    p = [F(1, 5) + F(3 * i, 5 * (width - 1)) for i in range(width)]
    ratio, alpha, common = last_window(p, F(1, 2))
    return rate_cases, dict(
        rates=list(map(str, p)),
        ratio=str(ratio),
        alpha=str(alpha),
        common=[[m, str(x)] for m, x in common.items()],
    )


def assess(kind, packet):
    labels, zone = labels_of(packet, width=6)
    meta = dict(
        domain=kind,
        repo=packet["repo"],
        run=packet["run"],
        job=packet["job"],
        labels=labels,
    )
    if len(labels) < 8:
        return meta | dict(status="fewer_than_four")
    modes, empty, _ = patterns(zone, labels)
    assert not empty
    pair = select_pair(modes, len(labels) // 2)
    if pair is None:
        return meta | dict(status="no_opposing_four", modes=modes)
    profiles, heterogeneous = laws(len(pair[2]))
    return meta | dict(
        status="scored",
        modes=modes,
        pair=pair,
        profiles=profiles,
        heterogeneous=heterogeneous,
    )


def summarize(rows):
    totals = defaultdict(Counter)
    families = defaultdict(set)
    widths = defaultdict(Counter)
    gap = defaultdict(lambda: F(1))
    for row in rows:
        for tag in ("all", row["domain"]):
            c = totals[tag]
            c["sampled"] += 1
            if row["status"] != "scored":
                continue
            c["scored"] += 1
            slots = len(row["pair"][2])
            widths[tag][str(slots)] += 1
            families[tag].add((len(row["labels"]), tuple(row["modes"])))
            repeated = [
                F(p["one_direction"]) / F(p["ratio"])
                for cases in row["profiles"].values()
                for p in cases.values()
            ]
            c["profiles"] += len(repeated)
            c["tightened_profiles"] += sum(v > 1 for v in repeated)
            c["tightened_archives"] += max(repeated) > 1
            gap[tag] = max(gap[tag], *repeated)
    result = {
        tag: dict(
            c,
            widths=dict(widths[tag]),
            distinct_families=len(families[tag]),
            reduction=str(gap[tag]),
        )
        for tag, c in totals.items()
    }
    a = totals["all"]
    return dict(
        results=result, gate=a["scored"] >= 40 and a["tightened_archives"] >= 10
    )


def run(ci, bart, out):
    rows = [
        assess(kind, case)
        for kind, path in (("CI", ci), ("BART", bart))
        for case in sample(path, kind)
    ]
    report = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit-parity-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode(), mtime=0
        )
    )
    (out / "audit-parity-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ci", type=Path)
    p.add_argument("bart", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.ci, a.bart, a.output)
