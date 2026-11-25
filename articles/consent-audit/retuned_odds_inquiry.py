"""Verify a drift certificate and optionally serve one component of a certified pair."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from joint_odds_check import read_source
from joint_odds_inquiry import once
from retuned_odds_check import check_result, read_published


def inspect(source, fixed, policy, target):
    available = check_result(source, fixed, policy)
    if available is None:
        raise ValueError("archive has only one request")
    limit = fixed[target]
    proof = policy["targets"][limit]
    status = dict(job=policy["job"], target=limit, verdict=proof["status"])
    if proof["status"] == "infeasible":
        status["refusal_budget"] = proof["refusal_budget"]
        return None, status
    drift, rows = available[limit]
    status.update(minimum_drift=str(drift), joint_ratio=proof["actual_joint"])
    return rows, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "publish"))
    parser.add_argument("source", type=Path)
    parser.add_argument("fixed", type=Path)
    parser.add_argument("policies", type=Path)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument(
        "--target", choices=("midpoint", "marginal"), default="midpoint"
    )
    parser.add_argument("--side", choices=("left", "right"))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--sealed-file", type=Path)
    args = parser.parse_args()
    if args.index < 0:
        parser.error("index must be non-negative")
    if args.action == "publish" and None in (args.record, args.sealed_file, args.side):
        parser.error("publish requires --record, --sealed-file, and --side")
    try:
        source = read_source(args.source)[args.index]
        fixed = read_published(args.fixed)[args.index]
        policy = json.loads(gzip.decompress(args.policies.read_bytes()))[args.index]
        rows, status = inspect(source, fixed, policy, args.target)
        if args.action == "publish":
            if rows is None:
                raise ValueError("no policy meets the selected target")
            record = json.loads(args.record.read_bytes())
            if not isinstance(record, list):
                raise ValueError("record must be a JSON array")
            scope = dict(fixed, retuned=policy)
            status = once(
                record,
                source,
                scope,
                rows,
                args.target,
                args.side == "right",
                args.sealed_file,
            )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        KeyError,
        AssertionError,
        IndexError,
        TypeError,
    ) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
