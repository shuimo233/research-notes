"""Measure extra disjoint proofs when the violated timetable bound may vary."""

import argparse
from collections import Counter
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from public_optimality_check import model
from slack_certificate import sites, visible
from transit_optimality_check import can_use_readings
from universal_witness import refutable


def enumerate_groups(audit, per_task):
    free = sorted(set(range(1, len(audit.archive))) - audit.disclosed.keys())
    retained = []
    for s in audit.disclosed:
        groups = []
        for size in range(len(free) + 1):
            for shell in combinations(free, size):
                g = frozenset((s, *shell))
                mask = visible(g)
                if any(mask & previous == previous for previous, _ in groups):
                    continue
                fixed = any(
                    all(mask & r for r in edges)
                    for edges in audit.alternatives.values()
                )
                if fixed:
                    groups.append((mask, False))
                    continue
                witness, _, limited = refutable(
                    audit, g, "pairs" if size else "providers", 5_000
                )
                per_task["queries"] += 1
                per_task["capped"] += limited
                if not limited and witness is None:
                    groups.append((mask, True))
        retained.append(groups)
    return retained


def pack(candidates):
    ordered = sorted(candidates, key=len)

    def choose(k, used):
        if k == len(ordered):
            return []
        for m, mixed in ordered[k]:
            if used & m:
                continue
            rest = choose(k + 1, used | m)
            if rest is not None:
                return [[list(sites(m)), mixed], *rest]
        return None

    return choose(0, 0)


def check_group(packet, per_task, proof, extras):
    n, _, _, _, pub_edges, f, possible = model(packet)
    packed = set()
    groups = {tuple(g): mixed for g, mixed in extras}
    on_proof = 0
    if proof is not None:
        assert len(proof) == len(packet["certificate"]["disclosed"])
        for g, mixed in proof:
            assert not packed.intersection(g)
            packed.update(g)
            if mixed:
                assert groups[tuple(g)] is True
                on_proof += 1
            outside = tuple(i for i in range(1, n) if i not in g)
            assert not can_use_readings(n, pub_edges, f, possible, outside)
        assert on_proof > 0
    for g, _ in extras:
        outside = (0, *(i for i in range(1, n) if i not in g))
        for alt in possible.values():
            assert any(f[i][j] > alt[i][j] for i in outside for j in outside)
        assert not can_use_readings(n, pub_edges, f, possible, outside[1:])
    per_task["verified_mixed_groups"] = len(extras)


def run(packets, exact):
    selected = {
        r["job"]
        for r in json.loads(exact.read_bytes())["followup"]
        if r["status"] == "proved_by_search"
    }
    exports = []
    totals = Counter()
    for packet in json.loads(gzip.decompress(packets.read_bytes())):
        job = packet["job"]
        if job not in selected:
            continue
        audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
        counts = Counter()
        groups = enumerate_groups(audit, counts)
        disjoint = pack(groups)
        extras = [[list(sites(m)), True] for row in groups for m, tag in row if tag]
        check_group(packet, counts, disjoint, extras)
        counts["checked_jobs"] = 1
        counts["with_extra_groups"] = bool(extras)
        counts["extra_groups"] = len(extras)
        counts["new_full_proofs"] = disjoint is not None
        totals.update(counts)
        exports.append(
            dict(job=job, counts=counts, proof=disjoint, mixed_candidates=extras)
        )
    assert totals["checked_jobs"] == len(selected)
    return dict(counts=totals, cases=exports)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packets", type=Path)
    p.add_argument("exact", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    result = run(args.packets, args.exact)
    args.output.write_bytes((json.dumps(result, separators=(",", ":")) + "\n").encode())
    print(json.dumps(result["counts"]))
