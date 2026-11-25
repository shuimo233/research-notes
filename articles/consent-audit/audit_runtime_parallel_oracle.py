"""Supplemental exact oracle for the squared-width scheduling proxy."""

import argparse
from fractions import Fraction as F
from functools import cache
import gzip
from itertools import product
import json
from pathlib import Path
from random import Random

from audit_runtime_latency_check import MODES
from audit_runtime_parallel_check import TRACE, records


@cache
def exact_peak(work, lanes):
    lower = max(work[0], (sum(work) + lanes - 1) // lanes)
    higher = sum(work)
    while lower < higher:
        cap = (lower + higher) // 2

        @cache
        def feasible(i, remaining):
            if i == len(work):
                return True
            value = work[i]
            previous = -1
            for j, r in enumerate(remaining):
                if r >= value and r != previous:
                    next_bins = tuple(
                        sorted((*remaining[:j], r - value, *remaining[j + 1 :]))
                    )
                    if feasible(i + 1, next_bins):
                        return True
                    previous = r
            return False

        if feasible(0, (cap,) * lanes):
            higher = cap
        else:
            lower = cap + 1
    return lower


def boundary():
    rng = Random(7655)
    count = 0
    for n, k in product(range(1, 8), range(1, 5)):
        if k > n:
            continue
        work = tuple(sorted((rng.randrange(1, 257) for _ in range(n)), reverse=True))
        brute = min(
            max(
                sum(w for w, j in zip(work, z, strict=True) if j == g) for g in range(k)
            )
            for z in product(range(k), repeat=n)
        )
        assert exact_peak(work, k) == brute
        count += 1
    return count


def compare(ledger, plans, folder):
    rows, _ = records(ledger, plans)
    trace = json.loads(gzip.decompress((folder / TRACE).read_bytes()))
    values = {}
    for route in ("independent", "stratified"):
        count, tight = 0, 0
        ratio = F(1)
        for b in trace["batches"]:
            c, w = b["key"][1:3]
            z = b["route"][route]
            jobs = b["jobs"][f"{route}_balanced"]
            loads = [
                max(int(row["length"]), MODES[i]) ** 2
                for row, i in zip(rows[c, w], z, strict=True)
            ]
            optimum = exact_peak(tuple(sorted(loads, reverse=True)), len(jobs))
            actual = max(sum(loads[i] for i in job) for job in jobs)
            assert actual >= optimum
            ratio = max(ratio, F(actual, optimum))
            count += 1
            tight += actual == optimum
        values[route] = {"layouts": count, "exact": tight, "max_peak_ratio": str(ratio)}
    return {"brute_force_checks": boundary(), "proxy": values}


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for k in ("ledger", "plans", "folder"):
        cli.add_argument(k, type=Path)
    args = cli.parse_args()
    print(json.dumps(compare(args.ledger, args.plans, args.folder), indent=2))
