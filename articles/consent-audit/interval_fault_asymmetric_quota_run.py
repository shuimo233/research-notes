"""Run asymmetric quota purchases and two exact conservative comparators."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from interval_fault_asymmetric_quota import hierarchy, plan_asymmetric
from interval_fault_delta import compile_two
from interval_fault_delta_run import injected
from interval_fault_laminar import Quota, quota_cover, quota_plan
from interval_fault_laminar_run import market
from interval_fault_noisy import Offer
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, path_worlds, single_reports
from interval_fault_world_tree import discriminate


STEM = "interval-fault-asymmetric-quota"


def caps_for(key, budget, chosen, domains):
    root = (1 << len(domains)) - 1
    groups = tuple(sum((d == j) << i for i, d in enumerate(domains)) for j in range(3))
    tree = hierarchy(len(domains), (root, *groups))
    raw = []
    for omitted in chosen:
        raw_key = f"{key}/asymmetric/{budget}/repair/{min(omitted)}"
        home = sha256(raw_key.encode()).digest()[0] % 3
        limits = {g: (2 - (i - home) % 3) for i, g in enumerate(groups)}
        limits[root] = 2
        raw.append(limits)
    return tree, raw


def summed(labels, offers, raw):
    clauses = set()
    for a, b in combinations(range(len(labels)), 2):
        if labels[a] == labels[b]:
            continue
        different = discriminate(offers, a, b)
        quorum = [(different & g, cap + raw[b][g] + 1) for g, cap in raw[a].items()]
        possible = tuple(
            sorted((m, size) for m, size in quorum if m.bit_count() >= size)
        )
        if not possible:
            return {"unavailable": [a, b]}
        clauses.add(possible)
    cost, selected, _, _ = quota_cover([q.cost for q in offers], sorted(clauses))
    return {"cost": cost, "selected": selected}


def replay(key, budget, truth, bands, edges, theta, reason):
    row = {"id": key, "budget": budget}
    if truth is None:
        row["excluded"] = reason
        return row
    if budget == 1:
        parsed = compile_path(bands, single_reports(key, truth, edges))
        states = path_worlds(parsed)
    else:
        reported, _ = injected(key.split("/")[0], key, truth, edges)
        parsed = compile_two(bands, reported)
        if parsed.minimum != 2:
            row["excluded"] = f"graph_minimum_{parsed.minimum}"
            return row
        states = [(list(k), v) for k, v in sorted(parsed.repair_coordinates().items())]
    repairs = [d for d, _ in states]
    coords = [c for _, c in states]
    assert tuple(t - truth[0] for t in truth) in coords
    targets, quotes, domains = market(key, budget, len(truth), edges)
    labels = [
        tuple(world[v] - world[u] >= theta for u, v in targets) for world in coords
    ]
    row["repairs"] = repairs
    if len(set(labels)) == 1:
        row["known"] = labels[0]
        return row
    offers = [
        Offer(cost, tuple(tuple(x[v] - x[u] for u, v in pairs) for x in coords))
        for cost, pairs in quotes
    ]
    tree, raw = caps_for(key, budget, repairs, domains)
    main = plan_asymmetric(labels, offers, tree, [tree.capacities(c) for c in raw])
    widest = tuple(Quota(group, max(c[group] for c in raw)) for group in raw[0])
    envelope = quota_plan(labels, offers, widest)
    row["exact"] = {
        "cost": main.cost,
        "selected": main.selected,
        "cuts": main.cuts,
        "witness": main.witness,
    }
    row["summed"] = summed(labels, offers, raw)
    row["envelope"] = (
        {"cost": envelope.cost, "selected": envelope.selected}
        if envelope.cost is not None
        else {"witness": envelope.witness}
    )
    return row


def summarize(ledger):
    count, unique = defaultdict(Counter), defaultdict(set)
    for case in ledger:
        for tag in ("all", case["id"].split("/")[0], f"budget-{case['budget']}"):
            c = count[tag]
            if "excluded" in case:
                c[case["excluded"]] += 1
                continue
            c["profiles"] += 1
            if "known" in case:
                c["known"] += 1
                continue
            c["ambiguous"] += 1
            main = case["exact"]["cost"]
            simple = case["summed"].get("cost")
            general = case["envelope"].get("cost")
            c["exact_safe"] += main is not None
            c["summed_safe"] += simple is not None
            c["envelope_safe"] += general is not None
            c["cuts"] += len(case["exact"]["cuts"])
            c["max_cuts"] = max(c["max_cuts"], len(case["exact"]["cuts"]))
            if general is not None:
                assert main <= general
                c.update(
                    {
                        "exact_envelope_price": main,
                        "envelope_price": general,
                        "exact_less_than_envelope": main < general,
                    }
                )
                unique[tag].add(case["id"])
            if simple is not None:
                assert main <= simple
                c.update(
                    {
                        "exact_summed_price": main,
                        "summed_price": simple,
                        "exact_less_than_summed": main < simple,
                    }
                )
    for tag in count:
        count[tag]["matched_unique"] = len(unique[tag])
    a = count["all"]
    return {
        "counts": dict(sorted(count.items())),
        "gates": {
            "over_envelope": a["matched_unique"] >= 100
            and 10 * a["exact_envelope_price"] <= 9 * a["envelope_price"],
            "over_summed": bool(a["summed_price"])
            and 20 * a["exact_summed_price"] <= 19 * a["summed_price"],
        },
    }


def run(noaa, bart, out):
    ledger = [
        replay(key, budget, values, bands, edges, limit, reason)
        for key, budget, values, bands, edges, limit, reason, _ in cases(
            noaa, bart, False
        )
    ]
    results = summarize(ledger)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("noaa", "bart", "out"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.noaa, args.bart, args.out)))
