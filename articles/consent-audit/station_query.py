"""Replay exact station comparisons with coarse temperature bands and paid reads."""

import argparse
import calendar
from collections import Counter, defaultdict
import csv
from datetime import date
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from hashlib import sha256
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_query_plan import compile_blocks, marginal_profiles
from frontier_information import actual_cost, with_rates
from frontier_inquiry import RelationInquiry

STATIONS = {
    "california": dict(
        zip("HABCD", ("23234", "23230", "23293", "23232", "23213"), strict=True)
    ),
    "new_york": dict(
        zip("HABCD", ("14732", "94789", "14734", "94741", "13739"), strict=True)
    ),
}
IDS = sorted("USW000" + v for region in STATIONS.values() for v in region.values())
EDGES = (("H", "A"), ("H", "B"), ("H", "C"), ("H", "D"), ("A", "B"), ("C", "D"))
MODES = ("all", "fixed", "greedy", "edge", "full", "block", "oracle")


def prepare(directory, snapshot, manifest):
    records = ["station,date,tmax_tenths"]
    sources = []
    for station in IDS:
        raw = (directory / (station + ".dly")).read_bytes()
        rows = {}
        for row in raw.decode("ascii").splitlines():
            if row[17:21] != "TMAX":
                continue
            assert row[:11] == station and len(row) == 269
            year, month = int(row[11:15]), int(row[15:17])
            if not 2000 <= year <= 2024:
                continue
            for day in range(1, calendar.monthrange(year, month)[1] + 1):
                start = 21 + (day - 1) * 8
                value = int(row[start : start + 5])
                if value != -9999 and row[start + 6] == " ":
                    stamp = date(year, month, day).isoformat()
                    if stamp in rows:
                        raise ValueError(f"duplicate station day {station} {stamp}")
                    rows[stamp] = value
        if not rows:
            raise ValueError(f"no measurements for {station}")
        records.extend(
            f"{station},{stamp},{value}" for stamp, value in sorted(rows.items())
        )
        sources.append(
            dict(station=station, sha256=sha256(raw).hexdigest(), rows=len(rows))
        )
    contents = ("\n".join(records) + "\n").encode("ascii")
    snapshot.write_bytes(gzip.compress(contents, mtime=0))
    manifest.write_text(
        json.dumps(
            dict(sources=sources, uncompressed_sha256=sha256(contents).hexdigest()),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def label(a, b):
    difference = a - b
    return -1 if difference <= -10 else 1 if difference >= 10 else 0


def load_snapshot(snapshot):
    fit = defaultdict(Counter)
    dates = defaultdict(dict)
    with gzip.open(snapshot, "rt", encoding="ascii") as f:
        for row in csv.DictReader(f):
            sid, stamp = row["station"], row["date"]
            v = int(row["tmax_tenths"])
            if stamp < "2018":
                fit[sid, int(stamp[5:7])][v] += 1
            else:
                if sid in dates[stamp]:
                    raise ValueError(f"duplicate snapshot row {sid} {stamp}")
                dates[stamp][sid] = v
    bases = {}
    for k, counts in fit.items():
        half = (sum(counts.values()) + 1) // 2
        for value, count in sorted(counts.items()):
            half -= count
            if half <= 0:
                bases[k] = value
                break
    return fit, dates, bases


def bootstrap(months, baseline):
    rng = Random(20261124)
    entries = [c[baseline] - c["full"] for _, c in sorted(months.items())]
    samples = sorted(sum(rng.choices(entries, k=len(entries))) for _ in range(2000))
    return [samples[49], samples[1949]]


def run(snapshot, out):
    fit, dates, bases = load_snapshot(snapshot)
    counts = defaultdict(Counter)
    years = defaultdict(Counter)
    months = defaultdict(Counter)
    exclusions = Counter()
    distinct = set()
    strictly_worse = set()
    cross_block_change = set()
    rows = []

    @lru_cache(96)
    def compile_key(region, month, lows):
        domains = {u: range(lo, lo + 20) for u, lo in zip("HABCD", lows, strict=True)}
        weights = {}
        for u, domain in domains.items():
            empirical = fit["USW000" + STATIONS[region][u], month]
            normalizer = sum(empirical[x] + 1 for x in domain)
            weights[u] = {x: Q(empirical[x] + 1, normalizer) for x in domain}
        svc = RelationInquiry(domains, EDGES, label, weights)
        full = svc.plan
        profiles = marginal_profiles(full)
        edge = with_rates(full, profiles, "independent")
        block = compile_blocks(**profiles)
        value = full.root_value()
        deployed = actual_cost(edge, full)
        assert deployed >= value and block.root_value() == value
        # An arbitrary cross-block coupling may change, but the local policy and cost are preserved.
        return (
            svc,
            edge,
            block,
            deployed,
            any(dict(a) != dict(b) for a, b in zip(full.groups, block.groups)),
        )

    for stamp, readings in sorted(dates.items()):
        month = int(stamp[5:7])
        for region, station_codes in STATIONS.items():
            station_ids = {u: "USW000" + code for u, code in station_codes.items()}
            if not all(s in readings for s in station_ids.values()):
                exclusions[region] += 1
                continue
            truth = {u: readings[s] for u, s in station_ids.items()}
            lows = tuple(
                bases[s, month] + 20 * ((truth[u] - bases[s, month]) // 20)
                for u, s in station_ids.items()
            )
            key = region, month, lows
            svc, edge, block, deployed, changed = compile_key(*key)
            expected = svc.plan.root_value()
            distinct.add(key)
            if deployed > expected:
                strictly_worse.add(key)
            if changed:
                cross_block_change.add(key)
            labels = {e: label(*(truth[u] for u in e)) for e in EDGES}
            paths = dict(all=list("HABCD"), oracle=svc.service.certificate(truth))
            for mode in ("fixed", "greedy", "edge", "full", "block"):
                planner = (
                    edge if mode == "edge" else block if mode == "block" else svc.plan
                )
                path, answers, fallback = svc.execute(
                    truth.__getitem__,
                    mode if mode in ("fixed", "greedy") else "optimal",
                    planner=planner,
                )
                assert answers == labels and not fallback
                paths[mode] = path
            assert paths["full"] == paths["block"]
            sizes = {mode: len(path) for mode, path in paths.items()}
            for aggregator in (
                counts[region],
                counts["total"],
                years[region, stamp[:4]],
                months[stamp[:7]],
            ):
                aggregator.update(sizes)
                aggregator["tasks"] += 1
            rows.append(
                dict(
                    region=region,
                    date=stamp,
                    lows=lows,
                    labels=[labels[e] for e in EDGES],
                    paths=paths,
                    expected=str(expected),
                    edge_forecast=str(edge.root_value()),
                    edge_cost_under_fitted_model=str(deployed),
                )
            )
    total = counts["total"]
    result = dict(
        by_region=counts,
        by_year={r: {y: v for (g, y), v in years.items() if g == r} for r in STATIONS},
        excluded_incomplete=exclusions,
        different_planning_keys=len(distinct),
        keys_edge_strict_expected_loss=len(strictly_worse),
        keys_altering_cross_block_coupling=len(cross_block_change),
        actual_edges_checked=len(rows) * len(EDGES) * 5,
        forecast_budgets={
            k: round(sum(float(Q(row[k])) for row in rows), 6)
            for k in ("expected", "edge_forecast", "edge_cost_under_fitted_model")
        },
        month_bootstrap_query_saving={
            v: bootstrap(months, v) for v in ("fixed", "greedy", "edge")
        },
        main_gate=total["tasks"] >= 2000
        and total["full"] < total["greedy"]
        and 200 * (total["fixed"] - total["full"]) >= total["fixed"],
        mechanism_gate=len(strictly_worse) >= 2,
    )
    out.mkdir(parents=True, exist_ok=False)
    data = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in rows
    ).encode("ascii")
    (out / "station-query-ledger.jsonl.gz").write_bytes(gzip.compress(data, mtime=0))
    (out / "station-query-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode("ascii")
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("prepare")
    for name in ("raw_directory", "snapshot", "manifest"):
        pr.add_argument(name, type=Path)
    r = sub.add_parser("run")
    for name in ("snapshot", "output"):
        r.add_argument(name, type=Path)
    a = p.parse_args()
    if a.command == "prepare":
        prepare(a.raw_directory, a.snapshot, a.manifest)
    else:
        print(json.dumps(run(a.snapshot, a.output), indent=2))
