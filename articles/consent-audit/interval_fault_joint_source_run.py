"""Replay one fixed source purchase for all non-anchor temperature or wait thresholds."""

import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

from interval_fault_joint_source import after_anchor, joint_plan
from interval_fault_noisy import Offer, possible_labels
from interval_fault_path import compile_path
from interval_fault_plan_run import cases, path_worlds, single_reports


STEM = "interval-fault-joint-source"


def source_inventory(key, anchor, size):
    other = [v for v in range(size) if v != anchor]
    sources = []
    for u in other:
        h = sha256(f"{key}/shared/{anchor}/one/{u}".encode()).digest()
        pair = tuple(sorted((anchor, u)))
        for j in range(1 + h[0] % 4):
            sources.append((2 + h[j + 1] % 6, (pair,)))
    for u, v in combinations(other, 2):
        h = sha256(f"{key}/shared/{anchor}/two/{u}/{v}".encode()).digest()
        if h[0] % 3:
            pairs = (tuple(sorted((anchor, u))), tuple(sorted((anchor, v))))
            for j in range(1 + h[1] % 2):
                sources.append((3 + h[j + 2] % 7, pairs))
    return sources


def compile_offers(coordinates, sources):
    return [
        Offer(cost, tuple(tuple(w[v] - w[u] for u, v in edges) for w in coordinates))
        for cost, edges in sources
    ]


def replay_anchor(key, path, states, truth, reported, threshold, anchor):
    order = after_anchor(path, anchor)
    targets = [(s, t) for s, t in reported if anchor not in (s, t)]
    coordinates = [states[i] for i in order]
    labels = [tuple(w[t] - w[s] >= threshold for s, t in targets) for w in coordinates]
    varying = [c for c in range(len(targets)) if len({v[c] for v in labels}) > 1]
    summary = {"anchor": anchor, "order": order, "ambiguous_targets": len(varying)}
    if not varying:
        summary["known"] = labels[0]
        return summary
    offers = compile_offers(coordinates, source_inventory(key, anchor, len(truth)))
    plan = joint_plan(labels, offers, 1)
    summary["boundaries"] = list(plan.required)
    if plan.cost is None:
        summary["witness"] = plan.witness
        return summary
    by_target = [joint_plan([v[i] for v in labels], offers, 1) for i in varying]
    assert all(x.cost is not None for x in by_target)
    union = {i for individual in by_target for i in individual.selected}
    price = sum(offers[i].cost for i in union)
    assert plan.cost <= price
    sold = [offers[i] for i in plan.selected]
    actual = coordinates.index(tuple(x - truth[0] for x in truth))
    collision = [x.values[actual] for x in sold]
    i = sha256(f"{key}/shared/{anchor}/noise".encode()).digest()[0] % len(sold)
    # An out-of-code vector represents arbitrary values from a wrong source.
    collision[i] = (max(row[0] for row in sold[i].values) + 1, *collision[i][1:])
    assert possible_labels(labels, sold, collision, 1) == {labels[actual]}
    summary.update(
        {
            "joint": plan.cost,
            "joint_selected": plan.selected,
            "individual": [x.selected for x in by_target],
            "union_price": price,
        }
    )
    return summary


def replay(key, values, bands, edges, limit, reason):
    if values is None:
        return {"id": key, "excluded": reason}
    path = compile_path(bands, single_reports(key, values, edges))
    candidates = path_worlds(path)
    states = [x for _, x in candidates]
    return {
        "id": key,
        "repairs": [r[0] for r, _ in candidates],
        "anchors": [
            replay_anchor(key, path, states, values, edges, limit, i)
            for i in range(len(values))
        ],
    }


def summarize(rows):
    counters = defaultdict(Counter)
    for r in rows:
        for tag in ("all", r["id"].split("/")[0]):
            c = counters[tag]
            if "excluded" in r:
                c[r["excluded"]] += 1
                continue
            c["archives"] += 1
            multi = False
            for a in r["anchors"]:
                c["anchor_profiles"] += 1
                if "known" in a:
                    c["known_profiles"] += 1
                    continue
                c["ambiguous_profiles"] += 1
                if "witness" in a:
                    c["unavailable_profiles"] += 1
                    continue
                c["safe_profiles"] += 1
                if a["ambiguous_targets"] >= 2:
                    multi = True
                    c["joint_multi_profiles"] += 1
                    c["joint_multi_cost"] += a["joint"]
                    c["independent_union_cost"] += a["union_price"]
                    c["strictly_better"] += a["joint"] < a["union_price"]
            c["distinct_joint_multi_archives"] += multi
    a = counters["all"]
    return {
        "counts": dict(sorted(counters.items())),
        "utility_gate": a["distinct_joint_multi_archives"] >= 20
        and 20 * a["joint_multi_cost"] <= 19 * a["independent_union_cost"],
    }


def run(noaa, bart, out):
    rows = [
        replay(key, values, bands, edges, limit, reason)
        for key, budget, values, bands, edges, limit, reason, _ in cases(
            noaa, bart, False
        )
        if budget == 1
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
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("noaa", "bart", "out"):
        p.add_argument(k, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.noaa, a.bart, a.out)))
