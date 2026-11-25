"""Replay the three-world audit on frozen SNLI model scores."""

import argparse
from functools import cache
import gzip
import json
from pathlib import Path

from audit_runtime_multiworld import compile_partition, conservative_partition
from audit_runtime_multiworld_check import NAMES, cost, failure_witness, inputs, report
from audit_runtime_partition import matching_partition


@cache
def solve(rates):
    old = matching_partition(rates[:2])
    new = compile_partition(rates)
    baseline = conservative_partition(rates)
    w = failure_witness(rates, old)
    b = len(new["blocks"])
    return {
        "old": old,
        "new": new,
        "conservative": baseline,
        "witness": w,
        "gains": [
            str((cost(len(baseline["blocks"]), 8) - cost(b, 8)) / 2),
            str((cost(8, 8) - cost(b, 8)) / 2),
        ],
    }


def run(ledger, folder):
    entries = [
        dict(case=i, threshold=t, **solve(rates)) for i, t, rates in inputs(ledger)
    ]
    out = report(ledger, entries, False)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / NAMES[0]).write_bytes(
        gzip.compress(json.dumps(entries, separators=(",", ":")).encode(), mtime=0)
    )
    (folder / NAMES[1]).write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(out))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("ledger", type=Path)
    cli.add_argument("folder", type=Path)
    a = cli.parse_args()
    run(a.ledger, a.folder)
