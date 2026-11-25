"""Replay robust heterogeneous service-rate bounds on frozen truth certificates."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha1
import json
from pathlib import Path

from audit_rates import rate_groups, serialize

PIN = "7ff77c48087929f54a1c9cda41bd984b14ec5edf"
TOL = F(1, 100)
GAMMA = F(1, 2)
DEPTH = 2


def packets(path):
    raw = path.read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PIN:
        raise ValueError("expected the registered prior certificate bundle")
    return [r for r in json.loads(gzip.decompress(raw)) if r["status"] == "scored"]


def service_rates(item):
    chosen = []
    for i in item["pair"][2]:
        early, late = item["labels"][2 * i : 2 * i + 2]
        shared = 1 - early[2] - late[2]
        chosen.append(F(1, 10) if shared <= 5 else F(1, 5) if shared <= 30 else F(2, 5))
    return chosen


@cache
def solve_cached(groups):
    rates = [p for p, n in groups for _ in range(n)]
    return serialize(rates, DEPTH, GAMMA)


def proof(rates):
    return solve_cached(rate_groups(rates))


def identify(packet):
    return [packet[k] for k in ("domain", "repo", "run", "job")]


def run(source, output):
    cases = packets(source)
    rows = []
    for row in cases:
        descriptor = identify(row)
        rates = service_rates(row)
        lower, upper = [p - TOL for p in rates], [p + TOL for p in rates]
        robust = proof(upper)
        top = [max(upper)] * len(rates)
        mean = [sum(upper) / len(rates)] * len(rates)
        worst_all = proof(top)
        pooled = proof(mean)
        minimum = proof(lower)
        assert F(minimum["ratio"]) <= F(robust["ratio"]) <= F(worst_all["ratio"])
        rows.append(
            dict(
                id=descriptor,
                nominal=list(map(str, rates)),
                lower=minimum,
                upper=robust,
                all_max=worst_all,
                mean=pooled,
            )
        )
    wide = []
    for domain in ("CI", "BART"):
        group = [r for r in cases if r["domain"] == domain][:6]
        assert len(group) == 6
        for i in (0, 3):
            chosen = group[i : i + 3]
            rates = [p + TOL for row in chosen for p in service_rates(row)]
            certificate = proof(rates)
            wide.append(
                dict(
                    domain=domain,
                    archives=[identify(r) for r in chosen],
                    width=len(rates),
                    atomic=2 ** len(rates),
                    grouped=certificate["cells"],
                    certificate=certificate,
                )
            )
    report = summarize(rows, wide)
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit-rates-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                dict(cases=rows, wide=wide), separators=(",", ":"), ensure_ascii=True
            ).encode(),
            mtime=0,
        )
    )
    (output / "audit-rates-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


def summarize(rows, wide):
    tally = defaultdict(Counter)
    shapes = defaultdict(set)
    peak = defaultdict(lambda: F(1))
    for row in rows:
        for group in ("all", row["id"][0]):
            up = F(row["upper"]["ratio"])
            low = F(row["lower"]["ratio"])
            c = tally[group]
            c["certified"] += 1
            c["versus_all_max"] += up < F(row["all_max"]["ratio"])
            c["unsafe_mean"] += up > F(row["mean"]["ratio"])
            c["original_cells"] += 2 ** len(row["nominal"])
            c["grouped_cells"] += row["upper"]["cells"]
            shapes[group].add(tuple(map(tuple, row["upper"]["groups"])))
            peak[group] = max(peak[group], up / low)
    results = {
        k: dict(v, rate_families=len(shapes[k]), interval_factor=str(peak[k]))
        for k, v in tally.items()
    }
    wide_summary = [
        {k: w[k] for k in ("domain", "width", "atomic", "grouped")} for w in wide
    ]
    all_rows = tally["all"]
    return dict(
        results=results,
        wide=wide_summary,
        gate=all_rows["certified"] >= 40
        and all_rows["versus_all_max"] >= 10
        and len(wide) == 4,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.source, a.output)
