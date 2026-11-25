"""Replay the registered distribution-shift study."""

import argparse
from functools import cache
import gzip
import json
from pathlib import Path

from audit_runtime_drift import plan
from audit_runtime_drift_check import NAMES, inputs, summarize


@cache
def solve(rates):
    return plan(rates)


def run(ledger, previous, output):
    policies = []
    for info, rates in inputs(ledger, previous):
        policies.append(dict(case=info[0], **solve(rates)))
    report = summarize(ledger, previous, policies, False)
    output.mkdir(parents=True, exist_ok=True)
    (output / NAMES[0]).write_bytes(
        gzip.compress(
            json.dumps(policies, separators=(",", ":"), ensure_ascii=True).encode(),
            mtime=0,
        )
    )
    (output / NAMES[1]).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {k: report["sections"][k] for k in ("main", "diagnostic")}
            | {"precision_passed": report["precision_passed"], "gate": report["gate"]}
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("ledger", "previous", "output"):
        cli.add_argument(n, type=Path)
    options = cli.parse_args()
    run(options.ledger, options.previous, options.output)
