"""Complete public optimality on small timetable packets by exact finite search."""

import argparse
from collections import Counter
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import components
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from public_optimality_exact import possible
from slack_certificate import verify_report


def resolve(packet, event, limit=50_000):
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    proof = event["proofs"]["groups"]
    lower = audit.check(proof)
    size = len(audit.disclosed)
    if lower == size:
        return dict(status="proved_by_groups", sets=0, states=0)
    if event["shorter"] is not None:
        return dict(status="shorter", sets=0, states=0, **event["shorter"])
    sites = sorted(set(components(audit.archive)) - {0})
    classes = components(audit.archive)
    # Replacing one reading by another in its archive rigid class is exact.
    must_hit = [{classes[i] for i in group} for group, _ in proof]
    sets = states = 0
    for points in combinations(sites, min(len(sites), size - 1)):
        if any(not g.intersection(points) for g in must_hit):
            continue
        if sets >= limit:
            return dict(status="limited", sets=sets, states=states)
        sets += 1
        record, work, limited = possible(audit, points, limit - states)
        states += work
        if limited:
            return dict(status="limited", sets=sets, states=states)
        if record is not None:
            readings = [[i, record[i]] for i in points]
            verify_report(audit.archive, audit.targets, audit.labels, readings)
            return dict(
                status="shorter",
                sets=sets,
                states=states,
                record=record,
                disclosed=readings,
            )
    return dict(status="proved_by_search", sets=sets, states=states)


def run(packets, ledger):
    public = json.loads(gzip.decompress(packets.read_bytes()))
    rows = map(json.loads, gzip.decompress(ledger.read_bytes()).splitlines())
    followup = []
    for p, row in zip(public, rows, strict=True):
        assert p["job"] == row["job"] and p["run"] == row["run"]
        if row["reads"] != len(row["proofs"]["groups"]):
            followup.append(dict(job=p["job"], **resolve(p, row)))
    return dict(
        followup=followup,
        counts=Counter(r["status"] for r in followup),
        tested_sets=sum(r["sets"] for r in followup),
        disjunction_branches=sum(r["states"] for r in followup),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packets", type=Path)
    p.add_argument("ledger", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    result = run(a.packets, a.ledger)
    a.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps({k: v for k, v in result.items() if k != "followup"}))
