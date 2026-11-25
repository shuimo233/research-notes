"""Publish the replayable exact routing partition experiment."""

import argparse
from fractions import Fraction as F
from functools import cache
import gzip
import json
from pathlib import Path

from audit_runtime_partition import matching_partition, mean_distinct
from audit_runtime_partition_check import FILES, records, summary


@cache
def solve(rates):
    return matching_partition(rates)


def run(ledger, archive, drift, destination):
    result = []
    for key, rates, previous in records(ledger, archive, drift):
        cert = solve(rates)
        modes = len(rates[0][0])
        weights = (F(1, modes),) * modes
        full = mean_distinct(len(rates[0]), weights)
        our = (full + mean_distinct(len(cert["blocks"]), weights)) / 2
        old_lo = full - F(previous["ceiling"]) * (full - 1)
        old_hi = full - F(previous["safe"]) * (full - 1)
        result.append(
            dict(
                case=key[0], partition=cert, costs=list(map(str, (our, old_lo, old_hi)))
            )
        )
    report = summary(ledger, archive, drift, result, verify=False)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / FILES[0]).write_bytes(
        gzip.compress(
            json.dumps(result, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (destination / FILES[1]).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: report["sections"][k] for k in ("main", "diagnostic")}
            | {"gate": report["gate"]}
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("ledger", "archive", "drift", "destination"):
        cli.add_argument(key, type=Path)
    args = cli.parse_args()
    run(args.ledger, args.archive, args.drift, args.destination)
