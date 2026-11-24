"""Check a group of potentially omitted observations on a public report packet."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from slack_certificate import verify_report
from universal_witness import outside, refutable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("group", type=int, nargs="+")
    parser.add_argument("--method", choices=("providers", "pairs"), default="providers")
    parser.add_argument("--budget", type=int, default=50_000)
    args = parser.parse_args()
    if args.budget < 0:
        parser.error("budget must be non-negative")
    try:
        packet = json.loads(args.packet.read_bytes())
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        points = frozenset(args.group)
        sample, work, limited = refutable(audit, points, args.method, args.budget)
        result = dict(group=sorted(points), tested=work)
        if limited:
            result["status"] = "unresolved"
        elif sample is None:
            result["status"] = "required_for_every_compatible_record"
        else:
            readings = [[i, sample[i]] for i in outside(audit, points)]
            assert all(sample[i] == x for i, x in audit.disclosed.items())
            verify_report(audit.archive, audit.targets, audit.labels, readings)
            result.update(
                status="can_be_omitted", compatible_record=sample, readings=readings
            )
        print(json.dumps(result, indent=2))
    except (IndexError, KeyError, TypeError, ValueError) as err:
        parser.exit(2, f"{err}\n")


if __name__ == "__main__":
    main()
