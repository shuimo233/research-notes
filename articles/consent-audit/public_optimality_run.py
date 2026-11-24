"""Score public minimum-disclosure proofs using only the registered public packets."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit, candidate_records
from slack_certificate import (
    Cover,
    claims,
    minimal_rows,
    reduced_slack,
    rows_for_claims,
    verify_report,
)

LIMIT = 5_000


def shorter(audit):
    if not audit.disclosed:
        return None
    if len(audit.disclosed) <= 1 and audit.alternatives:
        return None
    necessary = list(claims(audit.targets, audit.labels))
    for truth in candidate_records(audit):
        rows = minimal_rows(
            rows_for_claims(
                audit.archive, reduced_slack(audit.archive, truth), truth, necessary
            )
        )
        solver = Cover(rows, len(truth))
        greedy = solver.greedy()
        if len(greedy) < len(audit.disclosed):
            selected = greedy
        else:
            selected, _, _, _ = solver.minimum((greedy,), limit=1_000)
        if len(selected) < len(audit.disclosed):
            cert = [[i, truth[i]] for i in selected]
            verify_report(audit.archive, audit.targets, audit.labels, cert)
            return dict(record=truth, disclosed=cert)
    return None


def assess(packet):
    zone, targets = parse(packet["archive"])
    audit = PublicAudit(zone, targets, packet["certificate"])
    single = audit.baseline(rigid=False)
    rigid = audit.baseline(rigid=True)
    groups, branches, capped = audit.pack(rigid, LIMIT)
    proofs = dict(single=single, rigid=rigid, groups=groups)
    readings = len(audit.disclosed)
    assert all(audit.check(p) <= readings for p in proofs.values())
    possible = shorter(audit) if len(groups) < readings else None
    if possible is not None:
        assert len(groups) <= len(possible["disclosed"])
    return dict(
        **{k: packet[k] for k in ("repo", "run", "job")},
        reads=readings,
        proofs=proofs,
        branches=branches,
        capped=capped,
        shorter=possible,
    )


def run(packets, output):
    source = json.loads(gzip.decompress(packets.read_bytes()))
    by_source = defaultdict(Counter)
    ledger = []
    for packet in source:
        row = assess(packet)
        ledger.append(row)
        for key in ("total", row["repo"]):
            count = by_source[key]
            reads = row["reads"]
            count["tasks"] += 1
            count["revealed"] += reads
            count["nonempty"] += bool(reads)
            count["capped"] += row["capped"]
            count["shorter_exists"] += row["shorter"] is not None
            count["branches"] += row["branches"]
            count["max_branches"] = max(count["max_branches"], row["branches"])
            improved = len(row["proofs"]["groups"]) > len(row["proofs"]["rigid"])
            count["stronger_than_rigid"] += improved
            for mode, proof in row["proofs"].items():
                count[mode + "_lower"] += len(proof)
                count[mode + "_complete_nonempty"] += bool(
                    reads and len(proof) == reads
                )
    total = by_source["total"]
    gates = dict(
        count=total["tasks"] >= 400,
        fully_public=10 * total["groups_complete_nonempty"] >= 9 * total["nonempty"],
        public_lower=100 * total["groups_lower"] >= 95 * total["revealed"],
    )
    result = dict(
        by_source=by_source, gates=gates, gate=all(gates.values()), budget=LIMIT
    )
    output.mkdir(parents=True, exist_ok=False)
    raw = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in ledger)
    (output / "public-optimality-ledger.jsonl.gz").write_bytes(
        gzip.compress(raw.encode(), mtime=0)
    )
    (output / "public-optimality-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("public_packets", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.public_packets, a.output), indent=2))
