"""Check a public optimality packet with optional attested comparisons."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted, ShorterWorlds, impose, new_exact
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit


def inspect(entry, limit):
    packet = entry["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    added = entry["attested"]
    grid = entry["grid"]
    if type(grid) is not int or grid < 1:
        raise ValueError("comparison grid must be a positive integer")
    for u, v, b in added:
        if (
            any(type(k) is not int for k in (u, v, b))
            or not 0 <= u < len(audit.fibre)
            or not 0 <= v < len(audit.fibre)
            or u == v
            or b % grid
        ):
            raise ValueError("invalid attested comparison")
    oracle = ShorterWorlds(audit, entry.get("groups", []))
    witness = oracle.find(added, limit)
    return dict(
        job=packet.get("job"),
        proved=witness is None,
        readings_in_public_certificate=len(audit.disclosed),
        attestation_count=len(added),
        newly_exact_positions=new_exact(audit.fibre, impose(audit.fibre, added)),
        counterexample=witness,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_packet", type=Path)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--budget", type=int, default=100_000)
    args = parser.parse_args()
    if args.index < 0 or args.budget < 0:
        parser.error("index and budget must be non-negative")
    try:
        raw = args.public_packet.read_bytes()
        record = json.loads(
            gzip.decompress(raw) if args.public_packet.suffix == ".gz" else raw
        )
        result = inspect(
            record[args.index] if isinstance(record, list) else record, args.budget
        )
    except (IndexError, KeyError, TypeError, ValueError) as err:
        parser.exit(2, f"{err}\n")
    except Exhausted as err:
        result = dict(proved=None, status="unresolved", reason=str(err))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
