"""Create and verify a public minimum-disclosure proof from a public packet."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from public_optimality_exact import close_gap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("make", "check"))
    parser.add_argument("packet", type=Path)
    parser.add_argument("proof_file", type=Path, nargs="?")
    parser.add_argument(
        "--complete",
        action="store_true",
        help="exhaust the final one-read gap when applicable",
    )
    args = parser.parse_args()
    if (args.mode == "check") != (args.proof_file is not None):
        parser.error("provide the proof file in check mode")
    try:
        packet = json.loads(args.packet.read_bytes())
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        if args.mode == "make":
            proof, _, _ = audit.pack(audit.baseline(rigid=True))
        else:
            proof = json.loads(args.proof_file.read_bytes())["groups"]
        lower = audit.check(proof)
        proved = lower == len(audit.disclosed)
        result = dict(groups=proof, lower=lower, minimum_proved=proved)
        if args.complete and not proved:
            result["followup"] = detail = close_gap(audit, proof)
            if detail["status"] == "proven":
                result["minimum_proved"] = True
                result["lower"] = len(audit.disclosed)
        print(json.dumps(result, indent=2))
    except (IndexError, KeyError, TypeError, ValueError) as err:
        parser.exit(2, f"{err}\n")


if __name__ == "__main__":
    main()
