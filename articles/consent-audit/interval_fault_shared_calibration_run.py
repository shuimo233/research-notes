"""Apply shared and projected calibration contracts to the frozen archive portfolios."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from interval_fault_asymmetric_quota_run import caps_for
from interval_fault_delta import compile_two
from interval_fault_delta_run import injected
from interval_fault_laminar_run import market
from interval_fault_noisy import Offer
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, path_worlds, single_reports
from interval_fault_shared_calibration import plan

STEM = "interval-fault-shared-calibration"
MODES = ("shared", "marginal", "zero")
INVENTORIES = ("original", "references")


def replay(key, budget, truth, bands, edges, theta, reason):
    row = {"id": key, "budget": budget}
    if truth is None:
        return {**row, "excluded": reason}
    if budget == 1:
        states = path_worlds(compile_path(bands, single_reports(key, truth, edges)))
    else:
        reports, _ = injected(key.split("/")[0], key, truth, edges)
        model = compile_two(bands, reports)
        if model.minimum != 2:
            return {**row, "excluded": f"graph_minimum_{model.minimum}"}
        states = sorted(model.repair_coordinates().items())
    repairs, coords = zip(*states, strict=True)
    row["repairs"] = repairs
    targets, quotes, categories = market(key, budget, len(truth), edges)
    labels = [tuple(x[v] - x[u] >= theta for u, v in targets) for x in coords]
    if len(set(labels)) == 1:
        return {**row, "known": labels[0]}
    offers = [
        Offer(price, tuple(tuple(x[v] - x[u] for u, v in pairs) for x in coords))
        for price, pairs in quotes
    ]
    radius = 6 if key.startswith("weather/") else 90
    offsets = [(-radius, radius)] * len(labels)
    for inventory in INVENTORIES:
        slots, current = categories[:], offers[:]
        if inventory == "references":
            slots.extend(range(3))
            current.extend(Offer(4 + i, ((0,),) * len(labels)) for i in range(3))
        _, limits = caps_for(key, budget, repairs, slots)
        root = (1 << len(slots)) - 1
        groups = tuple(g for g in limits[0] if g != root)
        error = [1] * len(slots)
        row[inventory] = {}
        for mode in MODES:
            result = plan(labels, current, groups, limits, offsets, error, mode)
            record = {"cost": result.cost, "selected": result.selected}
            if result.proof is not None:
                record["proof"] = result.proof
            row[inventory][mode] = record
    return row


def summarize(rows):
    count, ambiguous, shared_marginal = (
        defaultdict(Counter),
        defaultdict(set),
        defaultdict(set),
    )
    for row in rows:
        family = row["id"].split("/")[0]
        for inventory in INVENTORIES:
            for tag in ("all", family, f"budget-{row['budget']}"):
                scope = inventory, tag
                counters = count[scope]
                if "excluded" in row:
                    counters[row["excluded"]] += 1
                    continue
                counters["profiles"] += 1
                if "known" in row:
                    counters["known"] += 1
                    continue
                counters["ambiguous"] += 1
                ambiguous[scope].add(row["id"])
                m = row[inventory]
                for mode in MODES:
                    counters[mode + "_safe"] += m[mode]["cost"] is not None
                s, c, z = (m[key]["cost"] for key in MODES)
                counters["shared_new"] += s is not None and c is None
                if c is not None:
                    assert z <= s <= c
                    counters["shared_matched_price"] += s
                    counters["marginal_matched_price"] += c
                    counters["shared_cheaper"] += s < c
                    shared_marginal[scope].add(row["id"])
                if s is not None:
                    assert z <= s
                    counters["shared_zero_matched_price"] += s
                    counters["zero_matched_price"] += z
    results = {inv: {} for inv in INVENTORIES}
    for scope, c in count.items():
        inv, tag = scope
        c["ambiguous_unique"] = len(ambiguous[scope])
        c["matched_unique"] = len(shared_marginal[scope])
        results[inv][tag] = dict(c)
    main = count["original", "all"]
    gates = {
        "matched_price": main["matched_unique"] >= 60
        and 10 * main["shared_matched_price"] <= 9 * main["marginal_matched_price"],
        "coverage": main["ambiguous_unique"] >= 150
        and 10 * main["shared_new"] >= main["ambiguous"],
    }
    return {"counts": results, "original_gates": gates}


def run(weather, bart, out):
    rows = [
        replay(key, budget, truth, bands, edges, theta, reason)
        for key, budget, truth, bands, edges, theta, reason, _ in cases(
            weather, bart, False
        )
    ]
    summary = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0)
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("weather", "bart", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.weather, args.bart, args.out)))
