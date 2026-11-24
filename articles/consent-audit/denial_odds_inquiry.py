"""Verify a public denial policy or perform one persistent sampled publication."""

import argparse
from fractions import Fraction
import gzip
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted
from conclusion_replay_inquiry import parse
from denial_odds import choose, distribution, unpack, verify
from public_optimality import PublicAudit
from selection_odds import patterns
from selection_protection_inquiry import cache_once, checked, record_indices


def inspect(bundle, service):
    catalogue = bundle["catalogue"]
    proof = bundle["rates"][str(service)]
    authority, labels = checked(catalogue)
    packet = catalogue["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    masks, has_empty, _ = patterns(audit.fibre, labels)
    weights, r, floor, certified_service, cap, lower, upper = unpack(proof)
    if (
        not has_empty
        or masks != bundle["patterns"]
        or len(weights) != len(labels)
        or floor != Fraction(1, 2 * len(labels))
        or certified_service != service
    ):
        raise ValueError(
            "catalogue, support or policy constraints differ from the certificate"
        )
    odds = verify(weights, r, floor, service, masks, cap, lower, upper)
    if odds != Fraction(proof["ratio"]):
        raise ValueError("reported ratio does not match the certificate")
    return (
        authority,
        labels,
        weights,
        dict(
            job=catalogue["job"],
            service=str(service),
            labels=len(labels),
            nonempty_patterns=len(masks),
            floor=str(floor),
            exact_worst_ratio=str(odds),
        ),
    )


def once(record, catalogue, authority, labels, weights, service, destination):
    ids = record_indices(record, authority, labels)
    mask = sum(1 << j for j in ids)
    encoded = json.dumps(
        dict(
            catalogue=catalogue, weights=list(map(str, weights)), service=str(service)
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    scope = sha256(encoded).hexdigest()

    def outcome(index):
        if index == -1:
            return dict(policy=scope, outcome="withheld")
        return dict(
            policy=scope,
            outcome="comparison",
            label=index,
            **catalogue["entries"][index],
        )

    def build():
        return outcome(choose(distribution(weights, mask, service)))

    received = cache_once(destination, build)
    label = received.get("label", -1)
    if (
        type(label) is not int
        or (label != -1 and label not in ids)
        or received != outcome(label)
    ):
        raise ValueError("cached release does not match this request")
    return received


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "publish"))
    parser.add_argument("policies", type=Path)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--service", type=Fraction, default=Fraction(1, 2))
    parser.add_argument("--record", type=Path)
    parser.add_argument("--release-file", type=Path)
    args = parser.parse_args()
    if args.index < 0:
        parser.error("index must be non-negative")
    if args.action == "publish" and (args.record is None or args.release_file is None):
        parser.error("publish requires --record and --release-file")
    try:
        raw = args.policies.read_bytes()
        bundles = json.loads(
            gzip.decompress(raw) if args.policies.suffix == ".gz" else raw
        )
        bundle = bundles[args.index] if isinstance(bundles, list) else bundles
        authority, labels, weights, status = inspect(bundle, args.service)
        if args.action == "publish":
            record = json.loads(args.record.read_bytes())
            if not isinstance(record, list):
                raise ValueError("record must be a JSON array of integers")
            status = once(
                record,
                bundle["catalogue"],
                authority,
                labels,
                weights,
                args.service,
                args.release_file,
            )
    except Exhausted as error:
        parser.exit(3, f"{error}\n")
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        ArithmeticError,
        AssertionError,
    ) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    main()
