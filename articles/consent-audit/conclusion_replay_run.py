"""Replay exact new NOAA reports using only bands and archived categories."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conclusion_replay import (
    closure,
    first_probe,
    interval,
    necessary,
    pin,
    replay,
    shortest,
)
from station_query import EDGES, STATIONS, load_snapshot


SITE_ORDER = "HABCD"
ORIGINAL = tuple((SITE_ORDER.index(u) + 1, SITE_ORDER.index(v) + 1) for u, v in EDGES)
CURRENT = tuple(combinations(range(1, len(SITE_ORDER) + 1), 2))
OLD_CUTS = (-9, 10)
MARGINS = (8, 12)


def old_bounds(bands, archive):
    cold = closure(bands)
    bounds = []
    for (u, v), state in zip(ORIGINAL, archive, strict=True):
        lo, hi = interval(cold, u, v)
        if state:
            lo = max(lo, OLD_CUTS[state - 1])
        if state < len(OLD_CUTS):
            hi = min(hi, OLD_CUTS[state] - 1)
        bounds.append((u, v, lo, hi))
    return cold, bounds


def edgewise(cold, bounds, targets):
    local = {(u, v): (lo, hi) for u, v, lo, hi in bounds}
    needed = set()
    for u, v, cuts in targets:
        lo, hi = local.get((u, v), interval(cold, u, v))
        if bisect_right(cuts, lo) != bisect_right(cuts, hi):
            needed.update((u, v))
    return tuple(i for i in sorted(needed) if cold[0][i] + cold[i][0] > 0)


def datum(snapshot):
    _, dates, bases = load_snapshot(snapshot)
    for date, day in sorted(dates.items()):
        if not date.startswith("2025-"):
            continue
        month = int(date[5:7])
        for region, group in STATIONS.items():
            ids = ["USW000" + group[u] for u in SITE_ORDER]
            if any(u not in day for u in ids):
                continue
            truth = (0, *(day[u] for u in ids))
            lows = []
            for name, actual in zip(ids, truth[1:], strict=True):
                base = bases[name, month]
                lows.append(base + 20 * ((actual - base) // 20))
            archive = [bisect_right(OLD_CUTS, truth[v] - truth[u]) for u, v in ORIGINAL]
            yield date, region, truth, lows, archive


def record(date, region, truth, lows, archive, tolerance, cold, bounds, zone):
    cuts = (1 - tolerance, tolerance)
    targets = [(u, v, cuts) for u, v in CURRENT]
    expected = [bisect_right(cuts, truth[v] - truth[u]) for u, v in CURRENT]
    static = necessary(zone, targets)
    probe, budget = first_probe(zone, targets, static)
    active = (
        static
        if probe is None
        else (probe, *necessary(pin(zone, probe, truth[probe]), targets))
    )
    paths = {
        "all": tuple(range(1, len(truth))),
        "cold": necessary(cold, targets),
        "local": edgewise(cold, bounds, targets),
        "fixed": static,
        "probe": active,
        "oracle": shortest(zone, targets, truth),
    }
    for path in paths.values():
        assert replay(zone, targets, path, truth.__getitem__) == expected
    assert len(paths["oracle"]) <= len(active) <= budget <= len(static)
    assert len(static) <= len(paths["local"]) <= len(paths["cold"])
    return dict(
        date=date,
        region=region,
        tolerance=tolerance,
        lows=lows,
        archive=archive,
        labels=expected,
        paths=paths,
        budget=budget,
    )


def run(snapshot, out):
    source = defaultdict(Counter)
    ledger = []
    for date, region, truth, lows, archive in datum(snapshot):
        cold, bounds = old_bounds([(lo, lo + 19) for lo in lows], archive)
        zone = closure([(lo, lo + 19) for lo in lows], bounds)
        for t in MARGINS:
            row = record(date, region, truth, lows, archive, t, cold, bounds, zone)
            ledger.append(row)
            paths = row["paths"]
            for name in ("total", str(t), f"{region}/{t}"):
                c = source[name]
                c["reports"] += 1
                c["labels"] += len(row["labels"])
                c.update({mode: len(path) for mode, path in paths.items()})
                c["probe_worst_bound"] += row["budget"]
                c["probe_strict_bound"] += row["budget"] < len(paths["fixed"])
                c["fixed_zero"] += not paths["fixed"]
    total = source["total"]
    result = dict(
        distinct_region_dates=total["reports"] // len(MARGINS),
        by_source=source,
        gate=total["reports"] >= 500 * len(MARGINS)
        and total["local"] > 0
        and 20 * (total["local"] - total["fixed"]) >= total["local"],
    )
    out.mkdir(parents=True, exist_ok=False)
    data = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in ledger)
    (out / "conclusion-replay-ledger.jsonl.gz").write_bytes(
        gzip.compress(data.encode(), mtime=0)
    )
    (out / "conclusion-replay-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.snapshot, a.output), indent=2))
