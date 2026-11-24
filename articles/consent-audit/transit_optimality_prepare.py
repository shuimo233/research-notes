"""Build the preregistered same-station BART schedule windows."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import gzip
from hashlib import sha256
from io import TextIOWrapper
import json
from pathlib import Path
from zipfile import ZipFile


EXPECTED = "838bae35002f76c217aa7350ff65e137b5d89c312c28c0a1c43ec32ab1ed6170"
FEED = "https://www.bart.gov/dev/schedules/google_transit.zip"
DAYS = ("2026-08-19", "2026-08-22", "2026-08-23")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def key(parts):
    return sha256("\n".join(map(str, parts)).encode()).digest()


def rows(feed, name):
    with feed.open(name + ".txt") as content:
        yield from csv.DictReader(
            TextIOWrapper(content, encoding="utf-8-sig", newline="")
        )


def seconds(value):
    h, m, s = map(int, value.split(":"))
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError("invalid GTFS time")
    return (h * 60 + m) * 60 + s


def service(feed):
    days = defaultdict(set)
    for day in DAYS:
        stamp = day.replace("-", "")
        w = WEEKDAYS[date.fromisoformat(day).weekday()]
        for r in rows(feed, "calendar"):
            if r[w] == "1" and r["start_date"] <= stamp <= r["end_date"]:
                days[day].add(r["service_id"])
        for r in rows(feed, "calendar_dates"):
            if r["date"] != stamp:
                continue
            if r["exception_type"] == "1":
                days[day].add(r["service_id"])
            elif r["exception_type"] == "2":
                days[day].discard(r["service_id"])
            else:
                raise ValueError("invalid calendar exception")
    return days


def windows(feed):
    dates = service(feed)
    rail = {
        r["route_id"]
        for r in rows(feed, "routes")
        if r["route_type"] in {"0", "1", "2"}
    }
    trip = {
        r["trip_id"]: (r["route_id"], [d for d in DAYS if r["service_id"] in dates[d]])
        for r in rows(feed, "trips")
        if r["route_id"] in rail
    }
    root = {
        r["stop_id"]: r["parent_station"] or r["stop_id"] for r in rows(feed, "stops")
    }
    collected = defaultdict(lambda: defaultdict(list))
    for r in rows(feed, "stop_times"):
        t = r["trip_id"]
        if t not in trip:
            continue
        route, days = trip[t]
        if not days:
            continue
        stop = r["stop_id"]
        station = root[stop]
        seq = int(r["stop_sequence"])
        for role, field, permission in (
            ("arrival", "arrival_time", "drop_off_type"),
            ("departure", "departure_time", "pickup_type"),
        ):
            if not r[field] or r[permission] == "1":
                continue
            at = seconds(r[field])
            if not 6 * 3600 <= at < 24 * 3600:
                continue
            span = (at // 1200) * 1200
            for day in days:
                rank = key((day, station, role, t, stop, seq))
                collected[station, day, span][role].append(
                    (
                        rank,
                        dict(
                            role=role,
                            trip=t,
                            station=stop,
                            sequence=seq,
                            route=route,
                            second=at,
                        ),
                    )
                )
    return collected


def put(out, name, content, compressed=False):
    data = (
        json.dumps(
            content,
            separators=(",", ":") if compressed else None,
            indent=None if compressed else 2,
        )
        + "\n"
    ).encode()
    (out / name).write_bytes(gzip.compress(data, mtime=0) if compressed else data)
    return sha256(data).hexdigest()


def prepare(path, out):
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED:
        raise ValueError("source archive does not match the preregistered feed")
    with ZipFile(path) as f:
        assert f.testzip() is None
        info = list(rows(f, "feed_info"))[0]
        assert info["feed_version"] == "72"
        candidates = windows(f)
    counts = Counter()
    kept = []
    signatures = set()
    for station, day, span in sorted(candidates):
        sides = candidates[station, day, span]
        arrivals, departures = (
            [v for _, v in sorted(sides[role], key=lambda row: row[0])[:5]]
            for role in ("arrival", "departure")
        )
        pairs = [
            [u, v]
            for u, x in enumerate(arrivals, 1)
            for v, y in enumerate(departures, len(arrivals) + 1)
            if x["route"] != y["route"] and x["trip"] != y["trip"]
        ]
        events = arrivals + departures
        if len(pairs) < 6 or len({v["route"] for v in events}) < 2:
            counts["insufficient_relations"] += 1
            continue
        clock = [(v["role"], v["route"], v["second"]) for v in events]
        sig = (
            station,
            span,
            tuple(sorted(clock)),
            tuple(sorted((clock[u - 1], clock[v - 1]) for u, v in pairs)),
        )
        if sig in signatures:
            counts["duplicates"] += 1
            continue
        signatures.add(sig)
        kept.append(
            dict(station=station, date=day, start=span, events=events, pairs=pairs)
        )
    counts["eligible"] = len(kept)
    kept = sorted(kept, key=lambda r: key((r["station"], r["date"], r["start"])))[:500]
    counts["selected"] = len(kept)
    task = [
        dict(r, job=i, repo="BART", run=int(r["date"].replace("-", "")))
        for i, r in enumerate(kept, 1)
    ]
    out.mkdir(parents=True, exist_ok=False)
    normalized = put(out, "transit-optimality-fixtures.json.gz", task, compressed=True)
    put(
        out,
        "transit-optimality-source.json",
        dict(
            archive_sha256=digest,
            fixture_sha256=normalized,
            url=FEED,
            metadata=info,
            service_dates=DAYS,
            windows=len(candidates),
            **counts,
        ),
    )
    return counts


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("gtfs", type=Path)
    p.add_argument("destination", type=Path)
    a = p.parse_args()
    print(json.dumps(prepare(a.gtfs, a.destination)))
