"""Replay source-aware grouped verification on frozen single-fault archives."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import inf
from pathlib import Path

from interval_fault_noisy import Offer, ambiguous_record
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, channels, path_worlds, single_reports
from interval_fault_source_bundle import source_disagreements, source_plan


STEM = "interval-fault-source-bundle"


def source_inventory(key, target_number, count, pairs):
    result = []
    for i in range(count):
        incident = [p for p in pairs if i in p]
        for slot in (0, 1):
            h = sha256(f"{key}/bundle/anchor/{i}/{slot}".encode()).digest()
            if slot and h[0] % 2:
                continue
            edges = (
                incident
                if not slot
                else [p for r, p in enumerate(incident) if h[r + 1] % 3]
            )
            if edges:
                cost = 2 + h[0] % 4 + (len(edges) - 1) // 2
                result.append((f"anchor-{i}-{slot}", cost, edges))
    eligible = [(a, b) for a, b in combinations(pairs, 2) if not set(a) & set(b)]
    n = len(result)
    if eligible:
        for slot in (0, 1):
            h = sha256(f"{key}/bundle/mixed/{target_number}/{slot}".encode()).digest()
            ix = int.from_bytes(h[:4], "big") % len(eligible)
            result.append((f"mixed-{slot}", 3 + h[4] % 5, list(eligible[ix])))
    return result, n


def vectors(coordinates, sources):
    return [
        Offer(cost, tuple(tuple(w[v] - w[u] for u, v in edges) for w in coordinates))
        for _, cost, edges in sources
    ]


def row_count_plan(offers, ref, rivals):
    """Research control that overcounts several readings from a single source."""
    start, goal = (0,) * len(rivals), (3,) * len(rivals)
    table = {start: (0, ())}
    for i, q in enumerate(offers):
        contribution = [
            sum(a != b for a, b in zip(q.values[ref], q.values[j], strict=True))
            for j in rivals
        ]
        if not any(contribution):
            continue
        extension = table.copy()
        for count, (price, old) in table.items():
            code = tuple(
                min(3, a + b) for a, b in zip(count, contribution, strict=True)
            )
            choice = (price + q.cost, (*old, i))
            if choice < extension.get(code, (inf, ())):
                extension[code] = choice
        table = extension
    return table.get(goal)


def record(plan):
    if plan.cost is None:
        return {"witness": plan.counterexample}
    return {"cost": plan.cost, "selected": plan.selected}


def target(key, number, path, coordinates, pairs, edge, limit):
    s, t = edge
    labels = [w[t] - w[s] >= limit for w in coordinates]
    if len(set(labels)) == 1:
        return {"known": labels[0]}
    approved = [p for p in pairs if p != tuple(sorted(edge))]
    sources, base_count = source_inventory(key, number, len(coordinates[0]), approved)
    offers = vectors(coordinates, sources)
    combined = source_plan(labels, offers, 1)
    base = source_plan(labels, offers[:base_count], 1)
    assert not base.exceptions
    for (_, _, original), mask in zip(sources, combined.differing, strict=True):
        assert (
            source_disagreements(path, original, combined.reference, combined.rivals)
            == mask
        )
    control = row_count_plan(offers, combined.reference, combined.rivals)
    counted = None
    if control is not None:
        cost, subset = control
        counted = {"cost": cost, "selected": subset}
        if combined.cost is None or cost < combined.cost:
            picked = [offers[i] for i in subset]
            weak = next(
                r
                for r in combined.rivals
                if sum(q.values[r] != q.values[combined.reference] for q in picked) < 3
            )
            counted["counterexample"] = ambiguous_record(
                picked, combined.reference, weak
            )
    return {
        "sources": sources,
        "reference": combined.reference,
        "rivals": combined.rivals,
        "exceptions": [(i, combined.differing[i]) for i in combined.exceptions],
        "flow_calls": combined.flow_calls,
        "only_anchors": record(base),
        "combined": record(combined),
        "rows_as_votes": counted,
    }


def run_case(key, values, bands, edges, limit, selection):
    if values is None:
        return {"id": key, "excluded": selection}
    path = compile_path(bands, single_reports(key, values, edges))
    states = path_worlds(path)
    coordinates = [w for _, w in states]
    pairs = [(u, v) for u, v, _ in channels(key, 1, len(values), edges, False)]
    assert tuple(x - values[0] for x in values) in coordinates
    return {
        "id": key,
        "repairs": [k[0] for k, _ in states],
        "targets": [
            target(key, i, path, coordinates, pairs, pair, limit)
            for i, pair in enumerate(edges)
        ],
    }


def summarize(ledger):
    by = defaultdict(Counter)
    for row in ledger:
        for k in (row["id"].split("/")[0], "all"):
            counters = by[k]
            if "excluded" in row:
                counters[row["excluded"]] += 1
                continue
            counters["archives"] += 1
            for out in row["targets"]:
                counters["targets"] += 1
                if "known" in out:
                    counters["known"] += 1
                    continue
                counters["ambiguous"] += 1
                fixed = out["combined"].get("cost")
                anchor = out["only_anchors"].get("cost")
                optimistic = out["rows_as_votes"]
                counters["source_feasible"] += fixed is not None
                counters["anchor_feasible"] += anchor is not None
                counters["mixed_only"] += fixed is not None and anchor is None
                if anchor is not None:
                    counters["combined_common_cost"] += fixed
                    counters["anchor_common_cost"] += anchor
                counters["optimistic_feasible"] += optimistic is not None
                counters["false_assurances"] += (
                    optimistic is not None and "counterexample" in optimistic
                )
                counters["source_models_with_exceptions"] += bool(out["exceptions"])
                counters["noncontiguous_offers"] += len(out["exceptions"])
                counters["flow_calls"] += out["flow_calls"]
    a = by["all"]
    return {
        "counts": dict(sorted(by.items())),
        "gates": {
            "provenance": a["source_feasible"] >= 50 and a["false_assurances"] >= 20,
            "mixed_gain": a["mixed_only"] >= 5
            or (
                bool(a["anchor_common_cost"])
                and 20 * a["combined_common_cost"] <= 19 * a["anchor_common_cost"]
            ),
        },
    }


def run(noaa, bart, out):
    ledger = [
        run_case(key, values, bands, edges, limit, selection)
        for key, budget, values, bands, edges, limit, selection, _ in cases(
            noaa, bart, False
        )
        if budget == 1
    ]
    report = summarize(ledger)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("noaa", "bart", "out"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    print(json.dumps(run(args.noaa, args.bart, args.out)))
