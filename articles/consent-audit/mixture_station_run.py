"""Run the registered 2025 mixture-prior comparison on held-out station records."""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction as Q
from functools import lru_cache
import gzip
import json
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_inquiry import RelationInquiry
from mixture_query import MixturePlan
from station_query import EDGES, STATIONS, label, load_snapshot

SIDE = (("A", "B"), ("C", "D"))


def cohort_ids():
    return {
        region: {u: "USW000" + code for u, code in codes.items()}
        for region, codes in STATIONS.items()
    }


def training(snapshot, bases):
    history = defaultdict(dict)
    with gzip.open(snapshot, "rt", encoding="ascii") as f:
        for r in csv.DictReader(f):
            if r["date"] < "2018":
                history[r["date"]][r["station"]] = int(r["tmax_tenths"])
    sizes = Counter()
    band_counts = Counter()
    value_counts = Counter()
    for date, all_values in sorted(history.items()):
        month = int(date[5:7])
        for region, ids in cohort_ids().items():
            if not all(v in all_values for v in ids.values()):
                continue
            values = {u: all_values[v] for u, v in ids.items()}
            offset = {u: values[u] - bases[v, month] for u, v in ids.items()}
            cls = int(sum(d >= 0 for d in offset.values()) >= 3)
            sizes[region, month, cls] += 1
            for u, t in values.items():
                band = offset[u] // 20
                if not -50 <= band < 50:
                    raise ValueError("training band outside registered support")
                band_counts[region, month, cls, u, band] += 1
                value_counts[region, month, cls, u, t] += 1
    return sizes, band_counts, value_counts


def conditional_laws(region, month, starts, ids, bases, fit, sufficient):
    sizes, band_counts, value_counts = sufficient
    bands = {u: (a - bases[ids[u], month]) // 20 for u, a in starts.items()}
    if any(not -50 <= b < 50 for b in bands.values()):
        raise ValueError("test band outside registered support")
    domains = {u: range(x, x + 20) for u, x in starts.items()}
    weighted = []
    conditional = {u: [] for u in starts}
    independent = {}
    for z in range(2):
        n = sizes[region, month, z]
        weighted.append(
            (n + 1)
            * prod(
                Q(band_counts[region, month, z, u, b] + 1, n + 100)
                for u, b in bands.items()
            )
        )
        for u, xs in domains.items():
            counts = {x: value_counts[region, month, z, u, x] + 1 for x in xs}
            total = sum(counts.values())
            conditional[u].append({x: Q(w, total) for x, w in counts.items()})
    mix = tuple(w / sum(weighted) for w in weighted)
    marginals = {}
    for u, xs in domains.items():
        marginals[u] = {
            x: sum(mix[z] * conditional[u][z][x] for z in range(2)) for x in xs
        }
        cnt = fit[ids[u], month]
        total = sum(cnt[x] + 1 for x in xs)
        independent[u] = {x: Q(cnt[x] + 1, total) for x in xs}
    return domains, mix, conditional, marginals, independent


def run(snapshot, out):
    fit, days, bases = load_snapshot(snapshot)
    sizes = training(snapshot, bases)
    records = []
    counts = defaultdict(Counter)
    forecast = defaultdict(Counter)
    losses = set()
    contexts = set()
    excluded = Counter()

    @lru_cache(32)
    def models(region, month, lows):
        ids = cohort_ids()[region]
        domains, mix, conditional, marginals, old = conditional_laws(
            region, month, dict(zip("HABCD", lows, strict=True)), ids, bases, fit, sizes
        )
        main = RelationInquiry(domains, EDGES, label, marginals)
        original = RelationInquiry(domains, EDGES, label, old)
        solver = MixturePlan(main, mix, conditional)
        best = solver.optimum(*solver.initial())[0]
        matched = solver.product_policy_cost(main.plan)
        assert matched >= best
        side = RelationInquiry(domains, SIDE, label, marginals)
        unit = dict.fromkeys(ids, 1)
        side_models = {
            "no_probe": MixturePlan(side, mix, conditional, disabled=("H",)),
            "unit_probe": MixturePlan(side, mix, conditional),
            "cheap_probe": MixturePlan(
                side, mix, conditional, costs={**unit, "H": Q(1, 10)}
            ),
        }
        side_expected = {
            name: p.optimum(*p.initial())[0] for name, p in side_models.items()
        }
        assert (
            side_expected["no_probe"]
            >= side_expected["unit_probe"]
            >= side_expected["cheap_probe"]
        )
        return solver, main.plan, original, side_models, best, matched, side_expected

    for date, readings in sorted(days.items()):
        if not date.startswith("2025-"):
            continue
        month = int(date[5:7])
        for region, ids in cohort_ids().items():
            if not all(s in readings for s in ids.values()):
                excluded[region] += 1
                continue
            truth = {u: readings[v] for u, v in ids.items()}
            lows = tuple(
                bases[v, month] + 20 * ((truth[u] - bases[v, month]) // 20)
                for u, v in ids.items()
            )
            key = region, month, lows
            solver, main, old, side_models, best, matched, side_exp = models(*key)
            contexts.add(key)
            if matched > best:
                losses.add(key)
            paths = {}
            answers = {e: label(truth[e[0]], truth[e[1]]) for e in EDGES}
            paths["mixture"], mix_result = solver.execute(truth.__getitem__)
            paths["matched"], same_result = solver.execute(
                truth.__getitem__, product=main
            )
            paths["old"], old_result, _ = old.execute(truth.__getitem__)
            assert mix_result == same_result == old_result == answers
            side_labels = {e: answers[e] for e in SIDE}
            side_paths = {}
            side_cost = {}
            for mode, p in side_models.items():
                path, result = p.execute(truth.__getitem__)
                assert result == side_labels
                side_paths[mode] = path
                side_cost[mode] = sum(p.cost[p.index[v]] for v in path)
            for bucket in (region, "total"):
                c = counts[bucket]
                c["tasks"] += 1
                c.update({k: len(v) for k, v in paths.items()})
                c.update(side_cost)
                for name in ("unit_probe", "cheap_probe"):
                    c[name + "_H_reads"] += "H" in side_paths[name]
                forecast[bucket].update(
                    mixture=float(best),
                    matched=float(matched),
                    **{k: float(v) for k, v in side_exp.items()},
                )
            records.append(
                dict(
                    region=region,
                    date=date,
                    lows=lows,
                    labels=[answers[e] for e in EDGES],
                    paths=paths,
                    side_paths=side_paths,
                    expected={
                        "mixture": str(best),
                        "matched": str(matched),
                        **{k: str(v) for k, v in side_exp.items()},
                    },
                )
            )
    results = dict(
        by_region=counts,
        excluded_incomplete=excluded,
        planning_contexts=len(contexts),
        positive_model_contexts=len(losses),
        fitted_costs={
            k: {name: round(v, 7) for name, v in terms.items()}
            for k, terms in forecast.items()
        },
    )
    total = counts["total"]
    results["primary_gate"] = (
        total["tasks"] >= 500
        and 200 * (total["matched"] - total["mixture"]) >= total["matched"]
    )
    results["mechanism_gate"] = len(losses) >= 10
    out.mkdir(parents=True, exist_ok=False)
    ledger = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records)
    (out / "mixture-station-ledger.jsonl.gz").write_bytes(
        gzip.compress(ledger.encode("ascii"), mtime=0)
    )
    (out / "mixture-station-results.json").write_bytes(
        (json.dumps(results, default=str, indent=2) + "\n").encode("ascii")
    )
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(args.snapshot, args.output), default=str, indent=2))
