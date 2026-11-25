"""Optimize unanchored joint verification of the fixed one- and two-error archives."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from interval_fault_delta import compile_two
from interval_fault_delta_run import injected
from interval_fault_noisy import Offer, possible_labels
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, path_worlds, single_reports
from interval_fault_world_tree import discriminate, world_plan


STEM = "interval-fault-world-tree"


def forest(size, pairs):
    groups = [{a} for a in range(size)]
    found = []
    for u, v in pairs:
        a = next(g for g in groups if u in g)
        b = next(g for g in groups if v in g)
        if a is not b:
            a.update(b)
            groups.remove(b)
            found.append((u, v))
    return found


def inventory(key, budget, size, edges):
    prefix = f"{key}/tree/{budget}/"
    parity = sha256((prefix + "targets").encode()).digest()[0] % 2
    targets = [p for i, p in enumerate(edges) if i % 2 == parity]
    banned = {tuple(sorted(p)) for p in targets}
    pool = [p for p in combinations(range(size), 2) if p not in banned]
    quotes = []
    if pool:
        for i in range(12):
            h = sha256((prefix + f"offer/{i}").encode()).digest()
            ranked = sorted(pool, key=lambda p: sha256(h + bytes(p)).digest())
            anchor = ranked[0][0]
            group = [p for p in ranked if anchor in p][: 1 + h[0] % 3]
            quotes.append((3 + h[1] % 8 + len(group) - 1, group))
    formation = forest(size, pool)
    opening = len(quotes)
    for i in range(3):
        b = sha256((prefix + f"full/{i}").encode()).digest()[0]
        quotes.append((7 + 2 * len(formation) + b % 7, formation))
    return targets, quotes, opening


def summarize_plan(plan):
    return {
        "tree": {
            "edges": plan.tree.edges,
            "agreement": plan.tree.agreement,
            "upper": plan.tree.possible,
        },
        "opposite_pairs": plan.opposite_pairs,
        "candidate_pairs": plan.candidate_pairs,
        "constraints": plan.constraints,
        "wide_sources": plan.wide_sources,
        "wide_types": plan.wide_types,
        "matching_calls": plan.matching_calls,
    }


def replay(key, budget, truth, bands, edges, limit, selection):
    row = {"id": key, "budget": budget}
    if truth is None:
        row["excluded"] = selection
        return row
    if budget == 1:
        model = compile_path(bands, single_reports(key, truth, edges))
        states = path_worlds(model)
    else:
        reports, _ = injected(key.split("/")[0], key, truth, edges)
        model = compile_two(bands, reports)
        if model.minimum != 2:
            row["excluded"] = f"graph_minimum_{model.minimum}"
            return row
        states = [(list(k), v) for k, v in sorted(model.repair_coordinates().items())]
    coords = [v for _, v in states]
    targets, quotes, opening = inventory(key, budget, len(truth), edges)
    labels = [tuple(x[v] - x[u] >= limit for u, v in targets) for x in coords]
    row["repairs"] = [d for d, _ in states]
    if len(set(labels)) <= 1:
        row["known"] = labels[0]
        return row
    offers = [
        Offer(cost, tuple(tuple(x[v] - x[u] for u, v in pairs) for x in coords))
        for cost, pairs in quotes
    ]
    baseline = offers[opening:]
    admissible = all(
        discriminate(baseline, i, j).bit_count() >= 3
        for i, j in combinations(range(len(coords)), 2)
        if labels[i] != labels[j]
    )
    row["full_price"] = sum(q.cost for q in baseline) if admissible else None
    plan = world_plan(labels, offers, 1)
    row.update(summarize_plan(plan))
    anchor = set(range(len(truth)))
    for q, (_, pairs) in zip(offers, quotes, strict=True):
        if len(set(q.values)) > 1:
            anchor &= {i for edge in pairs for i in edge}
    row["common_vertices"] = sorted(anchor)
    if plan.cost is None:
        assert row["full_price"] is None
        row["witness"] = plan.witness
        return row
    actual = coords.index(tuple(x - truth[0] for x in truth))
    ordered = [offers[i] for i in plan.selected]
    reply = [q.values[actual] for q in ordered]
    j = sha256(f"{key}/tree/{budget}/noise".encode()).digest()[0] % len(ordered)
    reply[j] = (max(x[0] for x in ordered[j].values) + 1, *reply[j][1:])
    assert possible_labels(labels, ordered, reply, 1) == {labels[actual]}
    row["price"] = plan.cost
    row["selected"] = plan.selected
    return row


def summarize(ledger):
    groups = defaultdict(Counter)
    matched = defaultdict(set)
    for row in ledger:
        origin = row["id"].split("/")[0]
        for group in ("all", origin, f"budget-{row['budget']}"):
            a = groups[group]
            if "excluded" in row:
                a[row["excluded"]] += 1
                continue
            a["profiles"] += 1
            if "known" in row:
                a["known"] += 1
                continue
            a["ambiguous"] += 1
            a["tree_recognized"] += row["tree"]["agreement"] == row["tree"]["upper"]
            a["full_pairs"] += row["opposite_pairs"]
            a["pairs_after_tree"] += row["candidate_pairs"]
            a["constraints"] += len(row["constraints"])
            a["max_wide_sources"] = max(a["max_wide_sources"], row["wide_sources"])
            a["max_wide_types"] = max(a["max_wide_types"], row["wide_types"])
            a["matching_calls"] += row["matching_calls"]
            if "witness" in row:
                a["unavailable"] += 1
                continue
            a["safe"] += 1
            if row["wide_sources"] == 0:
                a["pure_matching"] += 1
                a["pure_without_physical_anchor"] += not row["common_vertices"]
                a["pure_without_tree"] += (
                    row["tree"]["agreement"] != row["tree"]["upper"]
                )
            if row["full_price"] is not None:
                matched[group].add(row["id"])
                a["matched"] += 1
                a["baseline_price"] += row["full_price"]
                a["optimized_price"] += row["price"]
    for group, a in groups.items():
        a["matched_distinct_archives"] = len(matched[group])
    a = groups["all"]
    return {
        "counts": dict(sorted(groups.items())),
        "gates": {
            "practical": a["matched_distinct_archives"] >= 50
            and 10 * a["optimized_price"] <= 9 * a["baseline_price"],
            "structure": a["pure_without_physical_anchor"] >= 20,
        },
    }


def run(noaa, bart, out):
    ledger = [
        replay(key, budget, v, bands, edges, limit, selection)
        for key, budget, v, bands, edges, limit, selection, _ in cases(
            noaa, bart, False
        )
    ]
    result = summarize(ledger)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("noaa", "bart", "out"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.noaa, args.bart, args.out)))
