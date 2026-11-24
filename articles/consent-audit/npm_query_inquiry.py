"""Resolve declared npm dependency ranges from a blinded candidate table."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from npm_query import VersionInquiry


LABELS = {"0": "undeclared", "1": "accepted", "2": "rejected"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument(
        "--ask", action="store_true", help="read requested versions interactively"
    )
    args = parser.parse_args()
    data = json.loads(args.instance.read_bytes())
    paths = {vertex["id"]: vertex["path"] for vertex in data["vertices"]}
    inquiry = VersionInquiry(data)
    expected = 0
    if inquiry.planner is not None:
        expected = inquiry.batch.optimum(inquiry.batch.counts, inquiry.initial_forced)[
            0
        ]
    print(f"Expected exact reads under the model: {expected}", file=sys.stderr)
    if not args.ask:
        return

    observed = {}

    def observe(u):
        versions = inquiry.raw[u]
        options = ", ".join(f"{i}={v}" for i, v in enumerate(versions, 1))
        print(f"{paths[u]} [{options}]", file=sys.stderr, flush=True)
        try:
            selected = int(sys.stdin.readline())
        except ValueError:
            parser.exit(2, "Enter a candidate number for each requested position.\n")
        if not 1 <= selected <= len(versions):
            parser.exit(2, "Candidate number is outside the displayed range.\n")
        observed[u] = versions[selected - 1]
        return observed[u]

    trace, labels = inquiry.replay(observe)
    result = {
        "reads": [{"path": paths[u], "version": observed[u]} for u in trace],
        "declarations": [
            {"from": paths[u], "to": paths[v], "label": LABELS[code]}
            for u, v, code in labels
        ],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
