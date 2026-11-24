"""Read a rule-change audit from a JSON instance without loading exact records."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import closure, first_probe, interval, labels, necessary, pin


def parse(instance):
    # Keep the inputs integer and the reference node at index zero.
    bands = instance["bands"]
    if any(len(band) != 2 or any(type(x) is not int for x in band) for band in bands):
        raise ValueError("band endpoints must be integers")
    facts, targets = instance["bounds"], instance["targets"]
    for u, v, lo, hi in facts:
        if not all(type(x) is int for x in (u, v, lo, hi)):
            raise ValueError("constraint endpoints and bounds must be integers")
        if not (0 <= u <= len(bands) and 0 <= v <= len(bands) and lo <= hi):
            raise ValueError("invalid constraint")
    for u, v, cuts in targets:
        if not all(type(x) is int for x in (u, v, *cuts)):
            raise ValueError("target positions and cuts must be integers")
        if not (
            0 <= u <= len(bands) and 0 <= v <= len(bands) and sorted(set(cuts)) == cuts
        ):
            raise ValueError("invalid target")
    return closure(bands, facts), targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="evaluate a guaranteed one-read improvement",
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help="complete the report by reading the requested values",
    )
    args = parser.parse_args()
    try:
        zone, targets = parse(json.loads(args.instance.read_bytes()))
        static = necessary(zone, targets)
        first, budget = (
            first_probe(zone, targets, static) if args.probe else (None, len(static))
        )
        answer = dict(fixed=list(static), first=first, worst_case_reads=budget)
        if args.ask:
            observations = []

            def read(d, i):
                lo, hi = interval(d, 0, i)
                print(f"Position {i} [{lo}, {hi}]", file=sys.stderr, flush=True)
                value = int(sys.stdin.readline())
                after = pin(d, i, value)
                observations.append([i, value])
                return after

            if first is not None:
                zone = read(zone, first)
                static = necessary(zone, targets)
            for i in static:
                zone = read(zone, i)
            answer.update(
                reads=observations,
                labels=[
                    {
                        "from": u,
                        "to": v,
                        "label": label,
                        "difference": list(interval(zone, u, v)),
                    }
                    for (u, v, _), label in zip(
                        targets, labels(zone, targets), strict=True
                    )
                ],
            )
        print(json.dumps(answer, indent=2))
    except (KeyError, TypeError, ValueError) as err:
        parser.exit(2, f"{err}\n")


if __name__ == "__main__":
    main()
