"""Run the preregistered protected-attestation study."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted, ShorterWorlds
from conclusion_replay_inquiry import parse
from public_optimality import PublicAudit
from slack_certificate import reduced_slack
from unlocked_attestation import solve

PINS = {
    "attested-optimality-cases.json.gz": "2b631e71e9317d56b62362db820dc49b15770ed5",
    "attested-optimality-ledger.json.gz": "486596a4610c25133c26a4665c7d30a51d0e1486",
    "attested-optimality-results.json": "81631079304640a4770c938a39e0e7e19d332a14",
}
GRIDS = (1, 60, 300)


def read(directory, name):
    raw = (directory / name).read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PINS[name]:
        raise ValueError(f"preregistered source changed: {name}")
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def assess(case, previous):
    p = case["packet"]
    audit = PublicAudit(*parse(p["archive"]), p["certificate"])
    actual = case["actual"]
    reduced_slack(audit.fibre, actual)
    oracle = ShorterWorlds(audit, case["groups"])
    assert oracle.find() is not None
    scores = {}
    for grid in GRIDS:
        options = {}
        for label, strict in (("both", True), ("strongest", False)):
            try:
                options[label] = solve(oracle, actual, grid, preserve_strict=strict)
            except Exhausted:
                options[label] = dict(status="limited")
        legacy = previous["grids"][str(grid)]
        options["prior_preserves"] = (
            legacy["status"] == "proved" and not legacy["newly_exact"]
        )
        scores[str(grid)] = options
    return dict(
        source=case["source"],
        run=p["run"],
        job=p["job"],
        grids=scores,
        checks=oracle.checked,
    )


def summarize(c, row):
    c["tasks"] += 1
    c["checks"] += row["checks"]
    for grid, tests in row["grids"].items():
        c[grid + "_prior_preserves"] += tests["prior_preserves"]
        for method in ("both", "strongest"):
            r = tests[method]
            tag = f"{grid}_{method}_"
            c[tag + r["status"]] += 1
            c[tag + "rounds"] += r.get("rounds", 0)
            c[tag + "nodes"] += r.get("nodes", 0)
            if r["status"] == "proved":
                c[tag + "facts"] += len(r["attested"])
                c[tag + f"size_{len(r['attested'])}"] += 1
        if tests["both"]["status"] == "proved":
            c[grid + "_additional_over_prior"] += not tests["prior_preserves"]
            c[grid + "_additional_over_strongest"] += (
                tests["strongest"]["status"] != "proved"
            )


def run(directory, output):
    source = read(directory, "attested-optimality-cases.json.gz")
    old = read(directory, "attested-optimality-ledger.json.gz")
    read(directory, "attested-optimality-results.json")
    by_source = defaultdict(Counter)
    ledger, packets = [], []
    for case, previous in zip(source, old, strict=True):
        assert (previous["job"], previous["run"]) == (
            case["packet"]["job"],
            case["packet"]["run"],
        )
        row = assess(case, previous)
        ledger.append(row)
        for scope in ("total", case["source"]):
            summarize(by_source[scope], row)
        main = row["grids"]["60"]["both"]
        if main["status"] == "proved":
            packets.append(
                dict(
                    source=case["source"],
                    packet=case["packet"],
                    groups=case["groups"],
                    grid=60,
                    attested=main["attested"],
                    worlds=main["worlds"],
                )
            )
    total = by_source["total"]
    result = dict(
        by_source=by_source,
        gate=total["tasks"] == 35
        and total["60_both_proved"] >= 25
        and not any(
            total[f"{g}_{m}_limited"] for g in GRIDS for m in ("both", "strongest")
        ),
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "unlocked-attestation-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    for label, rows in (("ledger", ledger), ("packets", packets)):
        (output / f"unlocked-attestation-{label}.json.gz").write_bytes(
            gzip.compress(
                (json.dumps(rows, separators=(",", ":")) + "\n").encode(), mtime=0
            )
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    report = run(args.sources, args.output)
    print(
        json.dumps(
            dict(counts=report["by_source"]["total"], gate=report["gate"]), indent=2
        )
    )
