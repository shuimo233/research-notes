"""Produce minimum private certificates and a separate public schedule packet file."""

import argparse
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import closure, interval, necessary
from slack_certificate import (
    Cover,
    claims,
    classifications,
    minimal_rows,
    reduced_slack,
    rows_for_claims,
    verify_report,
)
from transit_optimality_prepare import put


def packet_for(task):
    identity = {k: task[k] for k in ("repo", "run", "job")}
    truth = (0, *(v["second"] for v in task["events"]))
    bands = [(t - t % 300, t - t % 300 + 299) for t in truth[1:]]
    cold = closure(bands)
    bounds = []
    before = [(u, v, (0, 120, 300, 600)) for u, v in task["pairs"]]
    for (u, v, cuts), state in zip(before, classifications(before, truth), strict=True):
        lo, hi = interval(cold, u, v)
        if state:
            lo = max(lo, cuts[state - 1])
        if state < len(cuts):
            hi = min(hi, cuts[state] - 1)
        bounds.append((u, v, lo, hi))
    targets = [(u, v, (0, 180, 420, 720)) for u, v in task["pairs"]]
    labels = classifications(targets, truth)
    zone = closure(bands, bounds)
    slack = reduced_slack(zone, truth)
    clauses = minimal_rows(rows_for_claims(zone, slack, truth, claims(targets, labels)))
    solver = Cover(clauses, len(truth))
    optimum, lower, searched, done = solver.minimum((solver.greedy(),), 50_000)
    if not done:
        raise ArithmeticError("private minimum search hit its budget")
    disclosed = [[i, truth[i]] for i in optimum]
    verify_report(zone, targets, labels, disclosed)
    packet = dict(
        **identity,
        archive=dict(bands=bands, bounds=bounds, targets=targets),
        certificate=dict(labels=labels, disclosed=disclosed),
    )
    summary = dict(
        **identity,
        full=len(truth) - 1,
        targets=len(labels),
        fixed=len(necessary(zone, targets)),
        optimum=lower,
        search=searched,
    )
    return packet, summary


def export(src, output):
    population = json.loads(gzip.decompress(src.read_bytes()))
    packets, rows = zip(*(packet_for(row) for row in population), strict=True)
    output.mkdir(parents=True, exist_ok=False)
    put(output, "transit-optimality-packets.json.gz", packets, compressed=True)
    put(output, "transit-optimality-private-counts.json.gz", rows, compressed=True)
    return len(packets)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(dict(packets=export(a.fixtures, a.output))))
