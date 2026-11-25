"""Produce sparse-catalogue odds certificates on registered public sources."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import gzip
import json
from pathlib import Path

from conclusion_replay_inquiry import parse
from multi_odds_run import read
from public_optimality import PublicAudit
from selection_odds import patterns
from selection_protection import comparison
from sparse_odds import anchor_lower, canonical_odds, catalogue_policy, has_overlap


def select(packet):
    fibre = PublicAudit(*parse(packet["archive"]), packet["certificate"]).fibre
    all_false = fibre
    labels = []
    for u, v in sorted({tuple(x[:2]) for x in packet["archive"]["targets"]}):
        low, high = -fibre[v][u], fibre[u][v]
        if high - low < 2:
            continue
        h = (high - low - 1) // 3
        early, late = [v, u, -(low + h)], [u, v, high - h]
        narrowed = comparison(comparison(all_false, early, False), late, False)
        if narrowed is not None:
            labels.extend((early, late))
            all_false = narrowed
            if len(labels) == 6:
                break
    return labels, fibre


def evaluate(domain, packet):
    labels, fibre = select(packet)
    case = {k: packet[k] for k in ("repo", "run", "job")}
    if len(labels) != 6:
        return dict(domain=domain, **case, status="fewer_than_six", labels=labels)
    feasible, empty, _ = patterns(fibre, labels)
    assert empty
    modes = [0, *feasible]
    rank = max(m.bit_count() for m in modes)
    upper, rows = catalogue_policy(modes)
    actual, count, witness = canonical_odds(rows)
    assert actual <= upper
    opposite_windows = sum(
        2 ** (6 - c) * 3**c - 1
        for s in modes
        for t in modes
        if s != t
        for c in [(s & t).bit_count()]
    )
    lower = anchor_lower(modes)
    exact = lower["lower"] == str(upper) or lower["lower"] == "2+sqrt(7)"
    return dict(
        domain=domain,
        **case,
        status="scored",
        labels=labels,
        modes=modes,
        rank=rank,
        overlapping_triples=has_overlap(modes),
        upper=str(upper),
        actual=str(actual),
        independent=str(2**rank),
        rows=[[str(row[k]) for k in sorted(row)] for row in rows.values()],
        canonical=count,
        all_windows=opposite_windows,
        lower=lower,
        exact=exact,
        witness=witness,
    )


def summary(records):
    counts = defaultdict(Counter)
    layouts = defaultdict(set)
    for row in records:
        for k in ("total", row["domain"]):
            counts[k]["sampled"] += 1
            if row["status"] != "scored":
                continue
            layouts[k].add(tuple(row["modes"]))
            counts[k]["scored"] += 1
            counts[k]["rank_three"] += row["rank"] == 3
            counts[k]["canonical"] += row["canonical"]
            counts[k]["all_windows"] += row["all_windows"]
            counts[k]["exact"] += row["exact"]
            counts[k]["sharp_overlap"] += row["lower"]["lower"] == "2+sqrt(7)"
            counts[k]["nonoverlap"] += (
                row["rank"] == 3 and not row["overlapping_triples"]
            )
            counts[k]["strictly_better_than_independent"] += Fraction(
                row["actual"]
            ) < Fraction(row["independent"])
    result = {k: dict(v, distinct_modes=len(layouts[k])) for k, v in counts.items()}
    total = result["total"]
    return dict(
        results=result,
        comparison_reduction=str(Fraction(total["all_windows"], total["canonical"])),
        gate=total["scored"] >= 40 and total["all_windows"] >= 4 * total["canonical"],
    )


def run(ci, bart, output):
    records = [
        evaluate(kind, p)
        for kind, path in (("CI", ci), ("BART", bart))
        for p in read(path, kind)
    ]
    report = summary(records)
    output.mkdir(parents=True, exist_ok=True)
    (output / "sparse-odds-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(records, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / "sparse-odds-results.json").write_text(
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
