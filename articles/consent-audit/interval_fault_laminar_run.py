"""Replay identical offers under flat, nested, and separated fault budgets."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from interval_fault_delta import compile_two
from interval_fault_delta_run import injected
from interval_fault_laminar import Quota, common_reply, normalize, quota_plan, separated
from interval_fault_noisy import Offer
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, path_worlds, single_reports
from interval_fault_world_tree import discriminate, world_plan
from interval_fault_world_tree_run import inventory


STEM = "interval-fault-laminar"


def market(key, budget, size, edges):
    targets, quotes, start = inventory(key, budget, size, edges)
    route = quotes[start][1]
    old_prefix = f"{key}/tree/{budget}/full/"
    for i in range(3, 7):
        h = sha256((old_prefix + str(i)).encode()).digest()
        quotes.append((7 + 2 * len(route) + h[0] % 7, route))
    prefix = f"{key}/quota/{budget}/"
    rotation = sha256((prefix + "rotation").encode()).digest()[0] % 3
    domain = [
        sha256((prefix + f"domain/{i}").encode()).digest()[0] % 3 for i in range(start)
    ]
    domain.extend((i + rotation) % 3 for i in range(7))
    return targets, quotes, domain


def encode(plan):
    if plan.cost is None:
        return {"witness": plan.witness}
    return {"cost": plan.cost, "selected": plan.selected}


def replay(key, budget, truth, bands, edges, theta, selection):
    row = {"id": key, "budget": budget}
    if truth is None:
        row["excluded"] = selection
        return row
    if budget == 1:
        model = compile_path(bands, single_reports(key, truth, edges))
        states = path_worlds(model)
    else:
        reported, _ = injected(key.split("/")[0], key, truth, edges)
        model = compile_two(bands, reported)
        if model.minimum != 2:
            row["excluded"] = f"graph_minimum_{model.minimum}"
            return row
        states = [(list(k), v) for k, v in sorted(model.repair_coordinates().items())]
    coords = [p for _, p in states]
    row["repairs"] = [i for i, _ in states]
    assert tuple(x - truth[0] for x in truth) in coords
    targets, quotes, which = market(key, budget, len(truth), edges)
    labels = [tuple(x[v] - x[u] >= theta for u, v in targets) for x in coords]
    if len(set(labels)) == 1:
        row["known"] = labels[0]
        return row
    offers = [
        Offer(p, tuple(tuple(x[v] - x[u] for u, v in pairs) for x in coords))
        for p, pairs in quotes
    ]
    root = Quota((1 << len(quotes)) - 1, 2)
    sub = tuple(
        Quota(sum((which[i] == g) << i for i in range(len(which))), 1) for g in range(3)
    )
    quotas = normalize((root, *sub), len(quotes))
    nested, separated_only = (
        quota_plan(labels, offers, quotas),
        quota_plan(labels, offers, sub),
    )
    uniform, one = world_plan(labels, offers, 2), world_plan(labels, offers, 1)
    row.update(
        {
            "nested": encode(nested),
            "domains": encode(separated_only),
            "flat_two": encode(uniform),
            "flat_one": encode(one),
            "calls": nested.calls,
            "matching_calls": nested.matching_calls,
        }
    )
    if one.cost is not None:
        used = sum(1 << i for i in one.selected)
        for a, b in combinations(range(len(labels)), 2):
            if labels[a] != labels[b] and not separated(
                discriminate(offers, a, b) & used, quotas
            ):
                row["flat_one_insufficient"] = common_reply(
                    offers, a, b, one.selected, quotas
                )
                break
    return row


def summarize(ledger):
    groups, examples = defaultdict(Counter), defaultdict(set)
    for row in ledger:
        origin = row["id"].split("/")[0]
        for label in ("all", origin, f"budget-{row['budget']}"):
            c = groups[label]
            if "excluded" in row:
                c[row["excluded"]] += 1
                continue
            c["profiles"] += 1
            if "known" in row:
                c["known"] += 1
                continue
            c["ambiguous"] += 1
            c["nested_safe"] += "cost" in row["nested"]
            c["flat_two_safe"] += "cost" in row["flat_two"]
            c["domains_safe"] += "cost" in row["domains"]
            c["old_flat_one_insufficient"] += "flat_one_insufficient" in row
            c["calls"] += row["calls"]
            c["matching_calls"] += row["matching_calls"]
            if "cost" in row["flat_two"]:
                n, f = row["nested"]["cost"], row["flat_two"]["cost"]
                c["matched"] += 1
                c["nested_matched"] += n
                c["flat_two_matched"] += f
                c["nested_saves"] += n < f
                examples[label].add(row["id"])
            if "cost" in row["domains"]:
                c["domain_matched_profiles"] += 1
                c["domain_matched_price"] += row["domains"]["cost"]
                c["nested_domain_matched_price"] += row["nested"]["cost"]
                c["global_quota_saves"] += (
                    row["nested"]["cost"] < row["domains"]["cost"]
                )
    for group, counts in groups.items():
        counts["unique_matched"] = len(examples[group])
    c = groups["all"]
    return {
        "counts": dict(sorted(groups.items())),
        "utility_gate": (
            c["unique_matched"] >= 100
            and 10 * c["nested_matched"] <= 9 * c["flat_two_matched"]
        ),
    }


def run(noaa, bart, output):
    ledger = [
        replay(key, budget, values, bands, edges, limit, selection)
        for key, budget, values, bands, edges, limit, selection, _ in cases(
            noaa, bart, False
        )
    ]
    result = summarize(ledger)
    output.mkdir(parents=True, exist_ok=True)
    (output / (STEM + "-ledger.json.gz")).write_bytes(
        gzip.compress(json.dumps(ledger, separators=(",", ":")).encode(), mtime=0)
    )
    (output / (STEM + "-results.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("weather", "bart", "out"):
        p.add_argument(field, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.weather, a.bart, a.out)))
