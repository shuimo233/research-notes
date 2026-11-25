"""Replay independent review offers around the fixed single-error graph archives."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path

from interval_fault_noisy import (
    Offer,
    cover_plan,
    order_blocks,
    possible_labels,
    weighted_one_error_cost,
)
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, channels, path_worlds, single_reports


STEM = "interval-fault-noisy"


def reviews(key, size, edges, coordinates):
    archived = {tuple(sorted(edge)) for edge in edges}
    result = []
    for u, v, base in channels(key, 1, size, edges, False):
        data = sha256(f"{key}/protected/{u}/{v}".encode()).digest()
        values = tuple(w[v] - w[u] for w in coordinates)
        offers = [Offer(base + data[i + 1] % 5, values) for i in range(1 + data[0] % 4)]
        result.append(((u, v), (u, v) in archived, offers))
    return result


def quorum_cost(groups, labels, r):
    k = 2 * r + 1
    grouped = [
        Offer(sum(sorted(q.cost for q in offer)[:k]), offer[0].values)
        for _, _, offer in groups
        if len(offer) >= k
    ]
    return cover_plan(labels, grouped, 0).cost


def packed_plan(plan):
    if plan.cost is None:
        a, b, observed = plan.counterexample
        return {"witness": [a, b, list(observed)]}
    return {
        "cost": plan.cost,
        "selected": list(plan.chosen),
        "potentials": list(plan.potentials),
    }


def blocks_for(groups, reference, rivals):
    rival_lookup = {i: j for j, i in enumerate(rivals)}
    blocks = [[] for _ in rivals]
    for i, (archived, q) in enumerate(groups):
        if not archived:
            continue
        differing = [r for r in rivals if q.values[r] != q.values[reference]]
        assert len(differing) <= 1
        if differing:
            blocks[rival_lookup[differing[0]]].append(i)
    return blocks


def replay(key, values, bands, edges, limit, selection):
    if values is None:
        return {"id": key, "excluded": selection}
    packed = compile_path(bands, single_reports(key, values, edges))
    states = path_worlds(packed)
    coordinates = [c for _, c in states]
    actual = coordinates.index(tuple(x - values[0] for x in values))
    inventory = reviews(key, len(values), edges, coordinates)
    results = []
    for step, (s, t) in enumerate(edges):
        labels = [c[t] - c[s] >= limit for c in coordinates]
        if len(set(labels)) == 1:
            results.append({"known": labels[0]})
            continue
        groups = [item for item in inventory if item[0] != tuple(sorted((s, t)))]
        active = [(archived, q) for _, archived, options in groups for q in options]
        offers = [q for _, q in active]
        none = cover_plan(labels, offers, 0)
        main = cover_plan(labels, offers, 1)
        sens = cover_plan(labels, offers, 2)
        blocks = blocks_for(active, main.reference, main.rivals)
        adaptive = None
        if all(len(b) >= 3 for b in blocks):
            ordered = order_blocks(blocks, offers)
            adaptive = {
                "rivals": len(blocks),
                "order": [list(b) for b in ordered],
                "fixed": sum(offers[i].cost for b in ordered for i in b),
                "adaptive": weighted_one_error_cost(ordered, offers),
            }
        if main.cost is not None:
            picked = [offers[i] for i in main.chosen]
            observed = [q.values[actual] for q in picked]
            h = sha256(f"{key}/after/{step}".encode()).digest()
            k = h[0] % len(picked)
            observed[k] = max(picked[k].values) + 1
            assert possible_labels(labels, picked, observed, 1) == {labels[actual]}
        results.append(
            {
                "reference": main.reference,
                "rivals": list(main.rivals),
                "no_error_cost": none.cost,
                "one_error": packed_plan(main),
                "two_errors": packed_plan(sens),
                "one_quorum": quorum_cost(groups, labels, 1),
                "two_quorum": quorum_cost(groups, labels, 2),
                "adaptive": adaptive,
            }
        )
    return {"id": key, "repairs": [i for (i,), _ in states], "targets": results}


def summarize(ledger):
    groups = defaultdict(Counter)
    for row in ledger:
        name = row["id"].split("/")[0]
        for k in (name, "all"):
            c = groups[k]
            if "excluded" in row:
                c[row["excluded"]] += 1
                continue
            c["archives"] += 1
            for t in row["targets"]:
                c["targets"] += 1
                if "known" in t:
                    c["known"] += 1
                    continue
                c["ambiguous"] += 1
                c["no_error_cost"] += t["no_error_cost"]
                for name, field, base in (
                    ("one", "one_error", "one_quorum"),
                    ("two", "two_errors", "two_quorum"),
                ):
                    cost, quorum = t[field].get("cost"), t[base]
                    c[f"{name}_robust"] += cost is not None
                    c[f"{name}_quorum"] += quorum is not None
                    c[f"{name}_rescue"] += cost is not None and quorum is None
                    if quorum is not None:
                        assert cost is not None and cost <= quorum
                        c[f"{name}_matched_cost"] += cost
                        c[f"{name}_matched_quorum_cost"] += quorum
                if t["adaptive"] is not None:
                    a = t["adaptive"]
                    c["adaptive_archives_targets"] += 1
                    c["adaptive_multiple_rivals"] += a["rivals"] >= 2
                    c["adaptive_cost"] += a["adaptive"]
                    c["adaptive_fixed_cost"] += a["fixed"]
    row = groups["all"]
    return {
        "counts": dict(sorted(groups.items())),
        "gates": {
            "fixed_verified_sample": row["one_robust"] >= 50,
            "mixing_gain": row["one_rescue"] >= 10
            or (
                row["one_matched_quorum_cost"] > 0
                and 20 * row["one_matched_cost"] <= 19 * row["one_matched_quorum_cost"]
            ),
            "adaptive_gain": row["adaptive_multiple_rivals"] >= 25
            and (
                row["adaptive_fixed_cost"] > 0
                and 20 * row["adaptive_cost"] <= 19 * row["adaptive_fixed_cost"]
            ),
        },
    }


def run(noaa, bart, out):
    ledger = [
        replay(key, values, bands, edges, limit, sel)
        for key, budget, values, bands, edges, limit, sel, _ in cases(noaa, bart, False)
        if budget == 1
    ]
    summary = summarize(ledger)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("noaa", "bart", "out"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.noaa, args.bart, args.out)))
