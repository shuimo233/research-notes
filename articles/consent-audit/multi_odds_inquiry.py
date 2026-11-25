"""Check a public three-request policy and serve fixed views of a sealed release."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from denial_odds import choose
from multi_odds_check import allowed, check_case, sample, verify_policy
from public_optimality_check import model
from selection_protection_inquiry import cache_once


def publish(packet, policy, entry, record, window, destination):
    n, _, _, _, constraints, _, _ = model(packet)
    if (
        not isinstance(record, list)
        or len(record) != n
        or any(type(x) is not int for x in record)
        or record[0] != 0
        or any(record[j] - record[i] > u for i, j, u in constraints)
    ):
        raise ValueError("record does not satisfy the public archive")
    if not 1 <= window <= 7:
        raise ValueError("window must name one or more of the three views")
    truth = sum(
        1 << slot
        for slot, (i, j, c) in enumerate(policy["labels"])
        if record[j] - record[i] >= c
    )
    support = allowed(policy["modes"])[truth]
    packed = entry["rows"][policy["modes"].index(truth)]
    lottery = dict(zip(support, map(Fraction, packed), strict=True))
    description = json.dumps(
        [packet["domain"], packet["repo"], packet["run"], packet["job"], policy, entry],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    scope = sha256(description).hexdigest()

    def build():
        return dict(policy=scope, mask=choose(lottery))

    cached = cache_once(destination, build)
    reply = cached["mask"]
    if (
        cached != dict(policy=scope, mask=reply)
        or type(reply) is not int
        or reply not in lottery
    ):
        raise ValueError("sealed release does not match this request")
    result = []
    for i, claim in enumerate(policy["labels"]):
        if window >> i & 1:
            result.append(
                dict(request=i + 1, outcome="comparison", comparison=claim)
                if reply >> i & 1
                else dict(request=i + 1, outcome="withheld")
            )
    return dict(policy=scope, replies=result)


def inspect(packet, policy, ratio, lock):
    if check_case(packet, policy) is None:
        raise ValueError("this archive has fewer than three requests")
    entry = next(
        t for t in policy["targets"] if t["ratio"] == ratio and t["lock"] is lock
    )
    status = dict(job=packet["job"], ratio=ratio, lock=lock, verdict=entry["status"])
    if entry["status"] == "feasible":
        caps = {int(i): Fraction(r) for i, r in policy["pair"].items()} if lock else {}
        status["verified_odds"] = {
            w: str(r)
            for w, r in verify_policy(
                policy["modes"], entry["rows"], Fraction(ratio), caps
            ).items()
        }
    return entry, status


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("check", "publish"))
    p.add_argument("domain", choices=("CI", "BART"))
    p.add_argument("source", type=Path)
    p.add_argument("policies", type=Path)
    p.add_argument("--index", required=True, type=int)
    p.add_argument("--ratio", choices=("32/7", "5"), default="5")
    p.add_argument("--lock", action="store_true")
    p.add_argument("--visible", type=int, choices=range(1, 8))
    p.add_argument("--record", type=Path)
    p.add_argument("--sealed-file", type=Path)
    args = p.parse_args()
    if args.index < 0:
        p.error("index must be nonnegative")
    if args.action == "publish" and None in (
        args.record,
        args.sealed_file,
        args.visible,
    ):
        p.error("publish requires --record, --sealed-file, and --visible")
    try:
        packet = list(sample(args.source, args.domain))[args.index]
        records = json.loads(gzip.decompress(args.policies.read_bytes()))
        policy = [r for r in records if r["domain"] == args.domain][args.index]
        entry, status = inspect(packet, policy, args.ratio, args.lock)
        if args.action == "publish":
            if entry["status"] != "feasible":
                raise ValueError("the selected target is infeasible")
            record = json.loads(args.record.read_bytes())
            status = publish(
                packet, policy, entry, record, args.visible, args.sealed_file
            )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        KeyError,
        AssertionError,
        IndexError,
        StopIteration,
        TypeError,
    ) as error:
        p.exit(2, f"{error}\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
