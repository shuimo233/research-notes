"""Recompute minimum protected attestations for all lags in the fixed cases."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha1
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted, ShorterWorlds, impose
from conclusion_replay_inquiry import parse
from lag_protection import LagCycles, exact_lags
from public_optimality import PublicAudit
from slack_certificate import reduced_slack
from unlocked_attestation import solve


SOURCES = {
    "attested-optimality-cases.json.gz": "2b631e71e9317d56b62362db820dc49b15770ed5",
    "unlocked-attestation-ledger.json.gz": "c19fbf973729b7ef0c25905cf65f631b51c0c907",
    "unlocked-attestation-results.json": "5c359ca79e00670d812dcb504d8096b753c6aa67",
}
GRIDS = (1, 60, 300)


def verify_source(folder, name):
    body = (folder / name).read_bytes()
    if sha1(f"blob {len(body)}\0".encode() + body).hexdigest() != SOURCES[name]:
        raise ValueError(f"source blob does not match the registration: {name}")
    return json.loads(gzip.decompress(body) if name.endswith(".gz") else body)


def evaluate(case, previous):
    packet = case["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    truth = case["actual"]
    reduced_slack(audit.fibre, truth)
    oracle = ShorterWorlds(audit, case["groups"])
    assert oracle.find() is not None
    outcomes = {}
    for grid in GRIDS:
        r = {}
        for label, keep in (("both", True), ("strongest", False)):
            try:
                r[label] = solve(
                    oracle, truth, grid, preserve_strict=keep, graph_type=LagCycles
                )
            except Exhausted:
                r[label] = dict(status="limited")
        prior = previous["grids"][str(grid)]["both"]
        r["prior_absolute"] = prior["status"] == "proved"
        r["prior_exact_lags"] = (
            exact_lags(audit.fibre, impose(audit.fibre, prior["attested"]))
            if r["prior_absolute"]
            else []
        )
        outcomes[str(grid)] = r
    return dict(
        source=case["source"],
        job=packet["job"],
        run=packet["run"],
        checks=oracle.checked,
        grids=outcomes,
    )


def collect(c, row):
    c["tasks"] += 1
    c["checks"] += row["checks"]
    for g, scores in row["grids"].items():
        prior = scores["prior_absolute"]
        loss = scores["prior_exact_lags"]
        c[f"{g}_prior_absolute"] += prior
        c[f"{g}_prior_lag_preserved"] += prior and not loss
        c[f"{g}_prior_leaked_instances"] += bool(loss)
        c[f"{g}_prior_leaked_pairs"] += len(loss)
        for label in ("both", "strongest"):
            r = scores[label]
            k = f"{g}_{label}_"
            c[k + r["status"]] += 1
            c[k + "nodes"] += r.get("nodes", 0)
            if r["status"] == "proved":
                proof = r["rational"]
                c[k + "facts"] += len(r["attested"])
                c[k + "classes"] += proof["denominator"]
                c[k + "compressed_values"] += len(proof["numerators"]) + 1
                c[k + "expanded_values"] += proof["denominator"] * len(
                    proof["numerators"]
                )
                if label == "both":
                    c[f"{g}_recovered"] += bool(loss)
                    c[f"{g}_over_strongest"] += (
                        scores["strongest"]["status"] != "proved"
                    )


def run(folder, output):
    previous = verify_source(folder, "unlocked-attestation-ledger.json.gz")
    cases = verify_source(folder, "attested-optimality-cases.json.gz")
    verify_source(folder, "unlocked-attestation-results.json")
    by_source = defaultdict(Counter)
    ledger, public = [], []
    for case, earlier in zip(cases, previous, strict=True):
        row = evaluate(case, earlier)
        assert (row["job"], row["run"], row["source"]) == (
            earlier["job"],
            earlier["run"],
            earlier["source"],
        )
        ledger.append(row)
        for scope in ("total", case["source"]):
            collect(by_source[scope], row)
        score = row["grids"]["60"]["both"]
        if score["status"] == "proved":
            public.append(
                dict(
                    source=case["source"],
                    packet=case["packet"],
                    groups=case["groups"],
                    grid=60,
                    attested=score["attested"],
                    rational=score["rational"],
                )
            )
    total = by_source["total"]
    report = dict(
        by_source=by_source,
        gate=total["tasks"] == 35
        and total["60_both_proved"] >= 18
        and not any(
            total[f"{g}_{m}_limited"] for g in GRIDS for m in ("both", "strongest")
        ),
    )
    output.mkdir(parents=True, exist_ok=False)
    for label, payload in (("ledger", ledger), ("packets", public)):
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        (output / f"lag-protection-{label}.json.gz").write_bytes(
            gzip.compress(data, mtime=0)
        )
    (output / "lag-protection-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    report = run(a.sources, a.output)
    print(
        json.dumps(
            dict(gate=report["gate"], counts=report["by_source"]["total"]), indent=2
        )
    )
