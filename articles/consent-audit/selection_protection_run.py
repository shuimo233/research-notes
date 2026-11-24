"""Replay protocol selection on frozen public minimum-disclosure gaps."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha1
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import Exhausted
from conclusion_replay_inquiry import parse
from lag_protection import rational_table
from public_optimality import PublicAudit
from selection_packing import packed
from selection_protection import (
    catalogue,
    comparison,
    fibre_log,
    safe_order,
    selected_by_bases,
    true_indices,
)

PINS = {
    "attested-optimality-cases.json.gz": "2b631e71e9317d56b62362db820dc49b15770ed5",
    "lag-protection-ledger.json.gz": "146e4368ca45d1f05d639713cb415af19d95f1e0",
    "lag-protection-results.json": "1803c3849dbeed514a28c627a72a4f50213d96df",
}
GRID = 60


def source(folder, name):
    raw = (folder / name).read_bytes()
    if sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() != PINS[name]:
        raise ValueError(f"changed preregistered input: {name}")
    return json.loads(gzip.decompress(raw) if name.endswith(".gz") else raw)


def assess(case, prior):
    packet = case["packet"]
    audit = PublicAudit(*parse(packet["archive"]), packet["certificate"])
    actual = case["actual"]
    ident = dict(source=case["source"], job=packet["job"], run=packet["run"])
    try:
        atoms, checks = catalogue(audit, case["groups"], GRID)
    except Exhausted:
        return dict(**ident, status="limited"), None
    zones = [comparison(audit.fibre, q) for q in atoms]
    alternatives = true_indices(actual, atoms)
    first = fibre_log(audit.fibre, atoms, range(len(atoms)))
    overlaps = sum(
        comparison(zones[i], atoms[j]) is not None
        for i, j in combinations(range(len(atoms)), 2)
    )
    order = safe_order(audit.fibre, atoms)
    plan = packed(audit.fibre, zones)
    chosen = alternatives[0] if alternatives else None
    recovered = None
    if plan["status"] == "proved":
        recovered = selected_by_bases(actual, atoms, plan["bases"])
        assert recovered in alternatives if alternatives else recovered is None
    info = dict(
        **ident,
        status="scored",
        checks=checks,
        labels=len(atoms),
        true_labels=alternatives,
        selected_first=chosen,
        selected_by_bases=recovered,
        first_fibres=first,
        intersecting_supports=overlaps,
        priority=order,
        basis_plan=plan,
        prior_single=(
            prior["grids"]["60"]["both"]["status"] == "proved"
            and len(prior["grids"]["60"]["both"]["attested"]) == 1
        ),
    )
    assert bool(alternatives) == info["prior_single"]
    if not atoms:
        return info, None
    public = dict(
        **ident,
        packet=packet,
        groups=case["groups"],
        grid=GRID,
        entries=[
            dict(comparison=q, rational=rational_table(audit.fibre, z))
            for q, z in zip(atoms, zones, strict=True)
        ],
        priority=order,
        basis_plan=plan,
    )
    return info, public


def count(c, row):
    c["tasks"] += 1
    if row["status"] == "limited":
        c["limited_catalogue"] += 1
        return
    actual = row["selected_first"]
    c["labels"] += row["labels"]
    c["nonempty_catalogues"] += bool(row["labels"])
    c["public_queries"] += row["checks"]
    c["actual_eligible"] += actual is not None
    c["actual_first_new_exact"] += actual is not None and bool(
        row["first_fibres"][actual]["fixed"]
    )
    c["actual_first_narrowed"] += (
        actual is not None and row["first_fibres"][actual]["narrowed"] > 0
    )
    c["catalogues_overlapping"] += row["intersecting_supports"] > 0
    c["overlapping_pairs"] += row["intersecting_supports"]
    c["catalogues_first_new_exact"] += any(
        bool(c["fixed"]) for c in row["first_fibres"]
    )
    c["first_empty_outputs"] += sum(c["empty"] for c in row["first_fibres"])
    c["first_leaking_outputs"] += sum(bool(c["fixed"]) for c in row["first_fibres"])
    c["first_narrowed_outputs"] += sum(c["narrowed"] > 0 for c in row["first_fibres"])
    if row["labels"]:
        c["priority_" + row["priority"]["status"]] += 1
    plan = row["basis_plan"]
    c["bases_" + plan["status"]] += 1
    c["cells"] += plan.get("cells", 0)
    c["actual_basis_safe"] += row["selected_by_bases"] is not None
    c["basis_repairs_first_order"] += plan["status"] == "proved" and any(
        x["empty"] or x["fixed"] for x in row["first_fibres"]
    )
    c["basis_beyond_any_order"] += (
        plan["status"] == "proved" and row["priority"]["status"] == "impossible"
    )
    if plan["status"] == "proved":
        c["witness_worlds"] += sum(map(len, plan["bases"]))
        c["matroid_fallback"] += plan["method"] == "kernel and matroid intersection"


def run(folder, output):
    cases = source(folder, "attested-optimality-cases.json.gz")
    compared = source(folder, "lag-protection-ledger.json.gz")
    source(folder, "lag-protection-results.json")
    totals = defaultdict(Counter)
    output.mkdir(parents=True, exist_ok=False)
    ledger, packets = [], []
    for case, prior in zip(cases, compared, strict=True):
        row, packet = assess(case, prior)
        assert all(row[k] == prior[k] for k in ("source", "job", "run"))
        ledger.append(row)
        for name in ("total", row["source"]):
            count(totals[name], row)
        if packet is not None:
            packets.append(packet)
    c = totals["total"]
    summary = dict(
        by_source=totals,
        gate=c["tasks"] == 35
        and c["actual_basis_safe"] >= 18
        and not c["limited_catalogue"]
        and not c["bases_limited"],
    )
    (output / "selection-protection-results.json").write_bytes(
        (json.dumps(summary, indent=2) + "\n").encode()
    )
    for name, payload in (("ledger", ledger), ("packets", packets)):
        serialized = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        (output / f"selection-protection-{name}.json.gz").write_bytes(
            gzip.compress(serialized, mtime=0)
        )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    r = run(a.sources, a.output)
    print(json.dumps(dict(gate=r["gate"], counts=r["by_source"]["total"]), indent=2))
