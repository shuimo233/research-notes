"""Score and export attestation repairs on the frozen information-gap cases."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted, ShorterWorlds, one_exact, repair
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from slack_certificate import reduced_slack

GRIDS = (1, 60, 300)


def ident(case):
    return dict(
        source=case["source"], job=case["packet"]["job"], run=case["packet"]["run"]
    )


def assess(case):
    packet = case["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    actual = case["actual"]
    reduced_slack(audit.fibre, actual)
    oracle = ShorterWorlds(audit, case["groups"])
    if oracle.find() is None:
        raise ValueError("an earlier information gap cannot be reproduced")
    choices = {}
    for grid in GRIDS:
        try:
            choices[str(grid)] = repair(oracle, actual, grid)
        except Exhausted:
            choices[str(grid)] = dict(status="limited")
    return dict(
        **ident(case),
        grids=choices,
        one_exact=one_exact(oracle, actual),
        queries=oracle.checked,
    )


def summarize(counts, row):
    counts["tasks"] += 1
    counts["one_exact"] += row["one_exact"] is not None
    counts["queries"] += row["queries"]
    for grid, result in row["grids"].items():
        state = result["status"]
        counts[grid + "_" + state] += 1
        if state == "proved":
            added = len(result["attested"])
            counts[f"{grid}_clauses_{added}"] += 1
            counts[f"{grid}_unary_single"] += result["single_unary"]
            counts[f"{grid}_pair_single"] += result["single_pair"]
            counts[f"{grid}_new_exact_values"] += len(result["newly_exact"])
            counts[f"{grid}_single_no_new_exact"] += (
                added == 1 and not result["newly_exact"]
            )
            counts[f"{grid}_single_no_raw_repair"] += (
                added == 1 and row["one_exact"] is None
            )


def run(cases, out):
    source = json.loads(gzip.decompress(cases.read_bytes()))
    group = defaultdict(Counter)
    rows, packets = [], []
    for case in source:
        row = assess(case)
        rows.append(row)
        for key in ("total", row["source"]):
            summarize(group[key], row)
        coarse = row["grids"]["60"]
        if coarse["status"] == "proved":
            packets.append(
                dict(
                    **ident(case),
                    packet=case["packet"],
                    groups=case["groups"],
                    grid=60,
                    attested=coarse["attested"],
                )
            )
    t = group["total"]
    result = dict(
        by_source=group,
        gate=t["tasks"] == 35
        and t["60_single_no_new_exact"] >= 21
        and all(not t[f"{g}_limited"] for g in GRIDS),
    )
    out.mkdir(parents=True, exist_ok=False)
    (out / "attested-optimality-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    for tag, value in (("ledger", rows), ("packets", packets)):
        (out / f"attested-optimality-{tag}.json.gz").write_bytes(
            gzip.compress(
                (json.dumps(value, separators=(",", ":")) + "\n").encode(), mtime=0
            )
        )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cases", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.cases, a.output), indent=2))
