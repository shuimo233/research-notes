"""Verify a public coupling or emit one side of a sealed local publication."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from denial_odds import choose
from joint_odds import project
from joint_odds_check import check_case, read_source
from selection_protection_inquiry import cache_once, checked, record_indices


def inspect(source, result, target):
    feasible = check_case(source, result)
    if feasible is None:
        raise ValueError("catalogue does not define two distinct requests")
    key = result["marginal" if target == "marginal" else "midpoint"]
    verdict = result["targets"][key]
    status = dict(
        job=result["job"],
        target=key,
        verdict=verdict["status"],
        marginal_ratio=result["marginal"],
        independent_ratio=result["independent"],
    )
    rows = feasible.get(key)
    if rows is not None:
        status["verified_joint_ratio"] = verdict["actual_ratio"]
    return rows, status


def once(record, source, result, rows, target, side, destination):
    catalogue = source["catalogue"]
    authority, comparisons = checked(catalogue)
    found = sum(1 << i for i in record_indices(record, authority, comparisons))
    mode = [project(found, v["labels"]) for v in result["views"]]
    row = rows[result["modes"].index(mode)]
    packed = json.dumps(
        [catalogue, result, target], sort_keys=True, separators=(",", ":")
    ).encode()
    scope = sha256(packed).hexdigest()

    def build():
        return dict(policy=scope, pair=list(choose(row)))

    cache = cache_once(destination, build)
    pair = tuple(cache["pair"])
    if (
        cache != {"policy": scope, "pair": list(pair)}
        or any(type(i) is not int for i in pair)
        or pair not in row
    ):
        raise ValueError("sealed pair does not match this request")
    axis = result["views"][side]
    label = pair[side]
    output = dict(policy=scope, event=axis["event"], outcome="withheld")
    if label >= 0:
        index = axis["labels"][label]
        output.update(outcome="comparison", label=index, **catalogue["entries"][index])
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "publish"))
    parser.add_argument("source", type=Path)
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
        result = json.loads(gzip.decompress(args.policies.read_bytes()))[args.index]
        rows, status = inspect(source, result, args.target)
        if args.action == "publish":
            if rows is None:
                raise ValueError("no certified coupling at the selected target")
            record = json.loads(args.record.read_bytes())
            if not isinstance(record, list):
                raise ValueError("record must be a JSON array")
            status = once(
                record,
                source,
                result,
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
    ) as err:
        parser.exit(2, f"{err}\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
