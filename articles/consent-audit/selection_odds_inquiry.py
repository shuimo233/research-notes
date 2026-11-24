"""Validate exact public odds or sample and cache a single weighted release."""

import argparse
from fractions import Fraction
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from selection_odds import likelihood, load_certificate, patterns, verify
from selection_protection_inquiry import checked, once


def inspect(bundle):
    catalogue = bundle["catalogue"]
    cert = bundle["odds"]
    record = catalogue["packet"]
    a = PublicAudit(*parse(record["archive"]), record["certificate"])
    labels = [r["comparison"] for r in catalogue["entries"]]
    masks, none, _ = patterns(a.fibre, labels)
    w, t, floor, given, lo, hi = load_certificate(cert)
    if (
        len(w) != len(labels)
        or floor != Fraction(1, 2 * len(labels))
        or masks != given
        or none != cert["no_release_possible"]
    ):
        raise ValueError(
            "pattern coverage, weight count, or minimum probability is wrong"
        )
    odds = verify(w, t, floor, masks, lo, hi)
    uniform = likelihood([Fraction(1)] * len(w), masks)
    if odds != Fraction(cert["weighted_ratio"]) or uniform != Fraction(
        cert["uniform_ratio"]
    ):
        raise ValueError("reported ratios do not match the verified policy")
    authority, labels = checked(catalogue)
    return (
        authority,
        labels,
        w,
        dict(
            job=catalogue["job"],
            labels=len(w),
            nonempty_patterns=len(masks),
            floor=str(floor),
            exact_worst_ratio=str(odds),
            uniform_worst_ratio=str(uniform),
        ),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("check", "publish"))
    p.add_argument("policies", type=Path)
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--record", type=Path)
    p.add_argument("--release-file", type=Path)
    a = p.parse_args()
    if a.index < 0:
        p.error("index must be non-negative")
    if a.action == "publish" and (a.record is None or a.release_file is None):
        p.error("publish requires --record and --release-file")
    try:
        raw = a.policies.read_bytes()
        packed = json.loads(gzip.decompress(raw) if a.policies.suffix == ".gz" else raw)
        b = packed[a.index] if isinstance(packed, list) else packed
        authority, labels, weights, status = inspect(b)
        if a.action == "publish":
            record = json.loads(a.record.read_bytes())
            status = once(
                record,
                b["catalogue"],
                authority,
                labels,
                "weighted",
                a.release_file,
                weights,
            )
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        ArithmeticError,
        AssertionError,
    ) as err:
        p.exit(2, f"{err}\n")
    except Exhausted as err:
        p.exit(3, f"{err}\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
