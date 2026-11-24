"""Verify the station task census, range certificates and optimal values independently."""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from struct import Struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from station_query import STATIONS, EDGES, MODES


def data(snapshot, sources, raw):
    contents = gzip.decompress(snapshot.read_bytes())
    manifest = json.loads(sources.read_bytes())
    assert sha256(contents).hexdigest() == manifest["uncompressed_sha256"]
    samples = defaultdict(dict)
    for sid, stamp, value in csv.reader(contents.decode("ascii").splitlines()[1:]):
        assert stamp not in samples[sid] and "2000-01-01" <= stamp <= "2024-12-31"
        samples[sid][stamp] = int(value)
    assert {x["station"]: x["rows"] for x in manifest["sources"]} == {
        s: len(values) for s, values in samples.items()
    }
    if raw is not None:
        fields = Struct("11s4s2s4s" + "8s" * 31)
        for row in manifest["sources"]:
            sid = row["station"]
            blob = (raw / (sid + ".dly")).read_bytes()
            assert sha256(blob).hexdigest() == row["sha256"]
            recovered = {}
            for line in blob.splitlines():
                station, year, month, element, *days = fields.unpack(line)
                assert station.decode() == sid
                if b"2000" <= year <= b"2024" and element == b"TMAX":
                    for i, packed in enumerate(days, 1):
                        t = int(packed[:5])
                        if t != -9999 and packed[-2:-1] == b" ":
                            recovered[f"{year.decode()}-{month.decode()}-{i:02d}"] = t
            assert recovered == samples[sid]
    return samples


def category(d):
    return (d >= 10) - (d <= -10)


def certified(edges, ranges, known):
    result = []
    for a, b in edges:
        x, y = (known[a],) * 2 if a in known else ranges[a]
        u, v = (known[b],) * 2 if b in known else ranges[b]
        lower, upper = category(x - v), category(y - u)
        if lower != upper:
            return None
        result.append(lower)
    return result


def reference(ranges, weighted, edges):
    names = sorted(ranges)
    index = {v: i for i, v in enumerate(names)}
    law = [Counter() for _ in names]
    required = [0 for _ in names]
    for i, u in enumerate(names):
        for value in range(ranges[u][0], ranges[u][1] + 1):
            trigger = 0
            for a, b in edges:
                if u in (a, b) and certified([(a, b)], ranges, {u: value}) is None:
                    trigger |= 1 << index[b if a == u else a]
            law[i][trigger] += weighted[u][value]
    for a, b in edges:
        if certified([(a, b)], ranges, {}) is None:
            ia, ib = index[a], index[b]
            required[ia] |= 1 << ib
            required[ib] |= 1 << ia

    def minimum(groups):
        @lru_cache(None)
        def value(left, forced):
            active = [
                i
                for i in range(len(names))
                if left & (1 << i) and (forced & (1 << i) or required[i] & left)
            ]
            if not active:
                return Q(0)
            prices = []
            for i in active:
                rest = left ^ (1 << i)
                prices.append(
                    1
                    + sum(
                        p * value(rest, (forced | mask) & rest)
                        for mask, p in groups[i].items()
                    )
                )
            return min(prices)

        root = value((1 << len(names)) - 1, 0)
        value.cache_clear()
        return root

    marginals = [
        [sum(p for mask, p in g.items() if mask & (1 << j)) for j in range(len(names))]
        for g in law
    ]
    product_laws = []
    for probs in marginals:
        cells = {0: Q(1)}
        for i, p in enumerate(probs):
            cells = {
                **({m: q * (1 - p) for m, q in cells.items()} if p < 1 else {}),
                **({m | (1 << i): q * p for m, q in cells.items()} if p > 0 else {}),
            }
        product_laws.append(cells)
    return minimum(law), minimum(product_laws)


def check(snapshot, sources, results, raw):
    samples = data(snapshot, sources, raw)
    rows = {}
    with gzip.open(
        results / "station-query-ledger.jsonl.gz", "rt", encoding="ascii"
    ) as f:
        for line in f:
            r = json.loads(line)
            k = r["region"], r["date"]
            assert k not in rows
            rows[k] = r
    trained = defaultdict(list)
    for sid, entries in samples.items():
        for day, t in entries.items():
            if day < "2018":
                trained[sid, day[5:7]].append(t)
    trials = Counter()
    record = json.loads((results / "station-query-results.json").read_bytes())
    for group, codes in STATIONS.items():
        ids = {u: "USW000" + c for u, c in codes.items()}
        expected_days = {
            d
            for d in set.intersection(*(set(samples[s]) for s in ids.values()))
            if d >= "2018"
        }
        assert expected_days == {d for g, d in rows if g == group}
        total = Counter(tasks=len(expected_days))
        cache = {}
        for day in sorted(expected_days):
            r = rows[group, day]
            truth = {u: samples[s][day] for u, s in ids.items()}
            ranges = {}
            weights = {}
            for u, sid in ids.items():
                fit = sorted(trained[sid, day[5:7]])
                middle = fit[(len(fit) - 1) // 2]
                lo = truth[u] - ((truth[u] - middle) % 20)
                ranges[u] = (lo, lo + 19)
                empirical = Counter(fit)
                sums = sum(empirical[v] + 1 for v in range(lo, lo + 20))
                weights[u] = {v: Q(empirical[v] + 1, sums) for v in range(lo, lo + 20)}
            assert r["lows"] == [ranges[u][0] for u in "HABCD"]
            assert r["labels"] == [category(truth[a] - truth[b]) for a, b in EDGES]
            assert set(r["paths"]) == set(MODES)
            for policy, path in r["paths"].items():
                assert len(path) == len(set(path))
                assert (
                    certified(EDGES, ranges, {u: truth[u] for u in path}) == r["labels"]
                )
                total[policy] += len(path)
            for size in range(6):
                if any(
                    certified(EDGES, ranges, {u: truth[u] for u in sub}) is not None
                    for sub in combinations(truth, size)
                ):
                    break
            assert size == len(r["paths"]["oracle"])
            key = day[5:7], tuple(r["lows"])
            if key not in cache:
                cache[key] = reference(ranges, weights, EDGES)
            assert cache[key] == (Q(r["expected"]), Q(r["edge_forecast"]))
        assert total == record["by_region"][group]
        trials["groups"] += 1
        trials["daily_certificates"] += len(expected_days)
        trials["independent_planning_keys"] += len(cache)
    return trials


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "sources", "results"):
        p.add_argument(name, type=Path)
    p.add_argument("--raw-directory", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(check(a.snapshot, a.sources, a.results, a.raw_directory), indent=2)
    )
