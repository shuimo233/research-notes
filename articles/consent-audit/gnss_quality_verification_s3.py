"""Prepare the independent Samsung route with adjacent fixed RTK interpolation."""

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path

from gnss_clock_audit import read_gps


def trace(path):
    records = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("%"):
            continue
        day, time, lat, lon, h, quality, *_ = line.split()
        gpst = datetime.fromisoformat(day.replace("/", "-") + "T" + time).replace(
            tzinfo=timezone.utc
        )
        utc = round(1000 * (gpst - timedelta(seconds=18)).timestamp())
        records.append(
            {
                "utc_ms": utc,
                "lla": list(map(float, (lat, lon, h))),
                "quality": int(quality),
            }
        )
    assert all(a["utc_ms"] < b["utc_ms"] for a, b in zip(records, records[1:]))
    return records


def pair(samples, records):
    times = [r["utc_ms"] for r in records]
    groups = []
    excluded = Counter()
    for sample in samples:
        t = sample["measurement_utc_ms"]
        i = bisect_left(times, t)
        if i < len(times) and times[i] == t:
            endpoints = [records[i]]
        elif 0 < i < len(times) and times[i] - times[i - 1] <= 1000:
            endpoints = records[i - 1 : i + 1]
        else:
            excluded["missing_adjacent_reference"] += 1
            continue
        if any(r["quality"] != 1 for r in endpoints):
            excluded["reference_not_fixed"] += 1
            continue
        lo, hi = endpoints[0], endpoints[-1]
        f = (
            (t - lo["utc_ms"]) / (hi["utc_ms"] - lo["utc_ms"])
            if hi["utc_ms"] > lo["utc_ms"]
            else 0
        )
        location = [a + f * (b - a) for a, b in zip(lo["lla"], hi["lla"], strict=True)]
        groups.append(
            {
                "epoch": sample,
                "reference": {"utc_ms": t, "lla": location, "fixed_bracket": endpoints},
            }
        )
    return sorted(groups, key=lambda row: row["reference"]["utc_ms"]), dict(excluded)


def run(log, reference, nav, out):
    epochs, raw_counts = read_gps(log)
    positions = trace(reference)
    cases, excluded = pair(epochs, positions)
    result = {
        "inputs": {
            "source_sha256": {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in (log, reference, nav)
            },
            "raw_counts": raw_counts,
            "raw_epochs": len(epochs),
            "aligned_fixed_interpolated": len(cases),
            "reference_quality": dict(Counter(row["quality"] for row in positions)),
            "excluded": excluded,
        },
        "cases": cases,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(
        gzip.compress(json.dumps(result, separators=(",", ":")).encode(), mtime=0)
    )
    return result["inputs"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("log", "reference", "nav", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.log, a.reference, a.nav, a.output)))
