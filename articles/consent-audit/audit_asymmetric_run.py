"""Replay the frozen asymmetric refusal-rate experiment."""

import argparse
from fractions import Fraction as F
from functools import cache
import gzip
import json
from pathlib import Path

from audit_asymmetric import bounds, fixed
from audit_asymmetric_check import (
    CAPS,
    EXAMPLE,
    FLOOR,
    PEAK,
    SPLITS,
    TOLERANCE,
    archive_contracts,
    summarize,
)


@cache
def solve(lo, hi, q):
    return bounds(lo, hi, q, FLOOR, CAPS, TOLERANCE, SPLITS)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("source", type=Path)
    cli.add_argument("output", type=Path)
    a = cli.parse_args()
    rows = [
        dict(
            id=identity,
            directions=[
                solve(lo, hi, q)
                for (lo, hi), (q, _) in zip(boxes, reversed(boxes), strict=True)
            ],
        )
        for identity, boxes in archive_contracts(a.source)
    ]
    _, _, q, g, b = EXAMPLE
    counterexample = {
        "box": bounds(*EXAMPLE, F(101, 100), 64),
        "exact_peak": fixed(PEAK, q, g, b),
    }
    report = summarize(a.source, rows, counterexample, verify=False)
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "audit-asymmetric-policies.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                dict(cases=rows, counterexample=counterexample),
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode(),
            mtime=0,
        )
    )
    (a.output / "audit-asymmetric-results.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
