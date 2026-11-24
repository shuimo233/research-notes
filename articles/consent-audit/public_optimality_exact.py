"""Close a one-reading proof gap by exhausting compatible substitute certificates."""

import argparse
from collections import Counter
import gzip
from itertools import combinations, product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import components
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit, tighten
from slack_certificate import verify_report


def group_choices(archive, proof):
    equivalent = components(archive)
    return [
        tuple({equivalent[i]: i for i in reversed(sorted(group))}.values())
        for group, _ in proof
    ]


def possible(audit, reading_set, max_nodes):
    """Return one public-compatible record, or prove this reading set cannot suffice."""
    sites = (0, *reading_set)
    groups = set()
    for u, v, b in audit.alternatives:
        alternative = tighten(audit.archive, v, u, -b - 1)
        alternatives = set()
        certain = False
        for a, c in combinations(sites, 2):
            for left, right in ((a, c), (c, a)):
                threshold = alternative[left][right] + 1
                if -audit.fibre[right][left] >= threshold:
                    certain = True
                    break
                if audit.fibre[left][right] >= threshold:
                    alternatives.add((left, right, threshold))
            if certain:
                break
        if certain:
            continue
        if not alternatives:
            return None, 0, False
        groups.add(tuple(sorted(alternatives)))
    clauses = sorted(groups, key=lambda row: (len(row), row))
    states = 0

    def satisfy(i, d):
        nonlocal states
        if i == len(clauses):
            return d[0]
        for a, c, h in clauses[i]:
            if states >= max_nodes:
                return ()
            states += 1
            changed = tighten(d, c, a, -h)
            if changed is not None:
                record = satisfy(i + 1, changed)
                if record is not None:
                    return record
        return None

    record = satisfy(0, audit.fibre)
    return record or None, states, record == ()


def close_gap(audit, proof, budget=50_000):
    low = audit.check(proof)
    gap = len(audit.disclosed) - low
    if gap != 1:
        return dict(status="proven" if not gap else "gap_exceeds_one", sets=0, states=0)
    sets = states = 0
    for points in product(*group_choices(audit.archive, proof)):
        if sets >= budget:
            return dict(status="limited", sets=sets, states=states)
        sets += 1
        record, work, limited = possible(audit, points, budget - states)
        states += work
        if limited:
            return dict(status="limited", sets=sets, states=states)
        if record is not None:
            public = [[i, record[i]] for i in points]
            audit.check(proof)
            verify_report(audit.archive, audit.targets, audit.labels, public)
            return dict(
                status="shorter",
                sets=sets,
                states=states,
                record=record,
                disclosed=public,
            )
    return dict(status="proven", sets=sets, states=states)


def run(packets, ledger):
    cases = json.loads(gzip.decompress(packets.read_bytes()))
    rows = map(json.loads, gzip.decompress(ledger.read_bytes()).splitlines())
    results = []
    for packet, row in zip(cases, rows, strict=True):
        if row["reads"] == len(row["proofs"]["groups"]):
            continue
        key = {k: packet[k] for k in ("repo", "run", "job")}
        assert all(row[k] == v for k, v in key.items())
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        result = close_gap(audit, row["proofs"]["groups"])
        results.append(dict(**key, **result))
    return dict(cases=results, totals=Counter(r["status"] for r in results))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("public_packets", type=Path)
    p.add_argument("packing_ledger", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    result = run(a.public_packets, a.packing_ledger)
    a.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(
        json.dumps(
            dict(
                totals=result["totals"],
                sets=sum(r["sets"] for r in result["cases"]),
                states=sum(r["states"] for r in result["cases"]),
            )
        )
    )
