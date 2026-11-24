"""Create or check a CI rule-change certificate using separate private and public inputs."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from slack_certificate import (
    Cover,
    claims,
    classifications,
    minimal_rows,
    reduced_slack,
    rows_for_claims,
    verify_report,
)


def make(dist, targets, truth):
    if not isinstance(truth, list) or any(type(x) is not int for x in truth):
        raise ValueError("the timepoints must be integer readings, starting at zero")
    result = classifications(targets, truth)
    slack = reduced_slack(dist, truth)
    rows = minimal_rows(rows_for_claims(dist, slack, truth, claims(targets, result)))
    cover = Cover(rows, len(truth))
    picked, lower, _, solved = cover.minimum((cover.greedy(),), limit=50_000)
    public = dict(labels=result, disclosed=[[i, truth[i]] for i in picked])
    check(dist, targets, public)
    print(
        f"Disclosed {len(picked)} exact values; lower bound {lower}; optimum proved: {solved}",
        file=sys.stderr,
    )
    return public


def check(dist, targets, proof):
    labels, values = proof["labels"], proof["disclosed"]
    if any(type(k) is not int for k in labels):
        raise ValueError("report labels must be integers")
    seen = set()
    for i, x in values:
        if (
            type(i) is not int
            or type(x) is not int
            or i in seen
            or not 0 < i < len(dist)
        ):
            raise ValueError("invalid disclosed reading")
        seen.add(i)
    return dict(
        valid=True,
        labels=labels,
        intervals=verify_report(dist, targets, labels, values),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("make", "check"))
    p.add_argument("archive", type=Path)
    p.add_argument("record_or_proof", type=Path)
    a = p.parse_args()
    try:
        dist, targets = parse(json.loads(a.archive.read_bytes()))
        record = json.loads(a.record_or_proof.read_bytes())
        result = (
            make(dist, targets, record)
            if a.mode == "make"
            else check(dist, targets, record)
        )
    except (IndexError, KeyError, TypeError, ValueError) as err:
        p.exit(2, f"{err}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
