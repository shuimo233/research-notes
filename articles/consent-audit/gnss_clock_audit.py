"""Prepare GPS L1 pseudoranges, verify timing, and run a native RTKLIB comparator."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import gzip
from hashlib import sha256
import json
from math import cos, isfinite, radians, sin, sqrt
from pathlib import Path
from statistics import median
import subprocess

C = 299_792_458
WEEK_NS = 604_800_000_000_000
STEM = "gnss-clock-audit"


def read_gps(log):
    counts = Counter()
    epochs = defaultdict(dict)
    with log.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
        header = next(
            next(csv.reader([r.removeprefix("# ").strip()]))
            for r in stream
            if r.startswith("# Raw,")
        )
        for row in csv.DictReader(
            (r for r in stream if r.startswith("Raw,")), fieldnames=header
        ):
            counts["all_raw"] += 1
            if (
                row["ConstellationType"] != "1"
                or abs(float(row["CarrierFrequencyHz"] or "0") - 1_575_420_000)
                > 1_000_000
            ):
                continue
            counts["gps_l1"] += 1
            state = int(row["State"])
            if not (state & 1 and state & (8 | 16384)):
                counts["state_excluded"] += 1
                continue
            try:
                hardware = int(row["TimeNanos"])
                full = int(row["FullBiasNanos"])
                tx = int(row["ReceivedSvTimeNanos"])
                utc = int(row["utcTimeMillis"])
                clock = int(row["HardwareClockDiscontinuityCount"])
                prn = int(row["Svid"])
                cn0 = float(row["Cn0DbHz"])
                offset = float(row["TimeOffsetNanos"] or "0")
                fractional = offset - float(row["BiasNanos"] or "0")
            except (TypeError, ValueError):
                counts["unknown_numeric"] += 1
                continue
            gps_epoch = hardware - full
            week, ns_week = divmod(gps_epoch, WEEK_NS)
            diff = (ns_week - tx + WEEK_NS // 2) % WEEK_NS - WEEK_NS // 2
            pseudorange = (diff + fractional) * C / 1e9
            if not (10_000_000 <= pseudorange <= 60_000_000 and isfinite(cn0)):
                counts["physical_excluded"] += 1
                continue
            counts["kept_nonzero_time_offsets"] += bool(offset)
            epoch = epochs[clock, hardware]
            item = {
                "sat": prn,
                "pseudorange": pseudorange,
                "cn0": cn0,
                "utc_ms": utc,
                "tow": (ns_week + fractional) / 1e9,
                "week": week,
            }
            if prn in epoch:
                counts["duplicates"] += 1
            if prn not in epoch or cn0 > epoch[prn]["cn0"]:
                epoch[prn] = item
    assert counts["gps_l1"] == sum(
        counts[k]
        for k in (
            "state_excluded",
            "unknown_numeric",
            "physical_excluded",
            "duplicates",
        )
    ) + sum(map(len, epochs.values()))
    groups = []
    for key, group in epochs.items():
        items = sorted(group.values(), key=lambda r: r["sat"])
        weeks = {r["week"] for r in items}
        if len(weeks) != 1:
            raise ValueError("GPS week must agree within the raw epoch")
        week = next(iter(weeks))
        tow = median([r["tow"] for r in items])
        groups.append(
            {
                "clock_key": key,
                "week": week,
                "tow": tow,
                "utc_ms": round(median([r["utc_ms"] for r in items])),
                "measurement_utc_ms": 315_964_800_000
                + week * 604_800_000
                + round(tow * 1000)
                - 18_000,
                "items": items,
            }
        )
    return sorted(groups, key=lambda x: x["utc_ms"]), dict(counts)


def read_reference(path):
    result = []
    qualities = Counter()
    for line in path.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("%"):
            continue
        date, time, lat, lon, h, quality, number, sdn, sde, sdu, *_ = line.split()
        stamp = datetime.fromisoformat(date.replace("/", "-") + "T" + time)
        utc = stamp.replace(tzinfo=timezone.utc) - timedelta(seconds=18)
        qualities[quality] += 1
        if quality == "1":
            result.append(
                {
                    "utc_ms": round(1000 * utc.timestamp()),
                    "lla": list(map(float, (lat, lon, h))),
                    "reference_sd_neu": list(map(float, (sdn, sde, sdu))),
                    "satellites": int(number),
                }
            )
    return result, dict(qualities)


def align(epochs, reference, key="measurement_utc_ms"):
    time = [r["utc_ms"] for r in reference]
    linked = {}
    excluded = Counter()
    for epoch in epochs:
        i = bisect_left(time, epoch[key])
        nearby = [r for r in (i - 1, i) if 0 <= r < len(time)]
        selected = min(nearby, key=lambda j: (abs(time[j] - epoch[key]), j))
        gap = abs(time[selected] - epoch[key])
        if gap > 250:
            excluded["raw_no_fixed_within_250_ms"] += 1
            continue
        if selected in linked:
            excluded["raw_duplicate_reference"] += 1
        if selected not in linked or gap < linked[selected][0]:
            linked[selected] = gap, epoch
    cases = [
        {
            "epoch": linked[i][1],
            "reference": reference[i],
            "absolute_time_gap_ms": linked[i][0],
        }
        for i in sorted(linked)
    ]
    return cases, dict(excluded)


def ecef(lla):
    latitude, longitude, height = lla
    t, p = radians(latitude), radians(longitude)
    semimajor, flattening = 6378137.0, 1 / 298.257223563
    e2 = flattening * (2 - flattening)
    n = semimajor / sqrt(1 - e2 * sin(t) ** 2)
    return (
        (n + height) * cos(t) * cos(p),
        (n + height) * cos(t) * sin(p),
        (n * (1 - e2) + height) * sin(t),
    )


def horizontal(ref_lla, calculated):
    dx, dy, dz = (x - y for x, y in zip(calculated, ecef(ref_lla), strict=True))
    lat, lon = map(radians, ref_lla[:2])
    east = -sin(lon) * dx + cos(lon) * dy
    north = -sin(lat) * (cos(lon) * dx + sin(lon) * dy) + cos(lat) * dz
    return sqrt(east * east + north * north)


def native(exe, nav, mode, requests):
    args = [str(exe.resolve()), mode, str(nav.resolve())]
    text = "\n".join(" ".join(map(str, row)) for row in requests) + "\n"
    result = subprocess.run(
        args, input=text, text=True, check=True, capture_output=True, timeout=100
    )
    return [row.split() for row in result.stdout.splitlines()]


def predict(exe, nav, tasks):
    requests = [
        (i, week, tow, prn, *position)
        for i, (week, tow, prn, position) in enumerate(tasks)
    ]
    outputs = native(exe, nav, "predict", requests)
    assert len(outputs) == len(tasks)
    predicted = []
    for i, (key, value, *extra) in enumerate(outputs):
        assert i == int(key)
        if value == "unavailable":
            predicted.append(None)
            continue
        elevation, tx, issue, x, y, z, clock, tgd, geom, ion, trop = extra
        predicted.append(
            {
                "nominal": float(value),
                "elevation": float(elevation),
                "tx": float(tx),
                "iode": int(issue),
                "sat_ecef": list(map(float, (x, y, z))),
                "sat_clock": float(clock),
                "tgd": float(tgd),
                "geometric_range": float(geom),
                "iono": float(ion),
                "tropo": float(trop),
            }
        )
    return predicted


def point_solutions(exe, nav, metrics):
    requests = []
    for i, case in enumerate(metrics):
        epoch = case["epoch"]
        items = epoch["items"]
        requests.append((i, epoch["week"], epoch["tow"], len(items)))
        requests.extend((r["sat"], r["pseudorange"], r["cn0"]) for r in items)
    raw = native(exe, nav, "point", requests)
    assert len(raw) == len(metrics)
    points = []
    for i, (key, value, *extra) in enumerate(raw):
        assert i == int(key)
        if value == "unavailable":
            points.append({"unavailable": " ".join(extra)})
            continue
        x, y, z = map(float, (value, *extra[:2]))
        points.append(
            {
                "position_ecef": (x, y, z),
                "receiver_clock_s": float(extra[2]),
                "satellites": int(extra[3]),
                "status": int(extra[4]),
                "horizontal_error_m": horizontal(
                    metrics[i]["reference"]["lla"], (x, y, z)
                ),
            }
        )
    return points


def order_stat(values, numerator, denominator):
    if not values:
        return None
    return sorted(values)[
        (numerator * len(values) + denominator - 1) // denominator - 1
    ]


def summarize(cases, inputs):
    errors = [
        e["point"]["horizontal_error_m"]
        for e in cases
        if "horizontal_error_m" in e["point"]
    ]
    useful = []
    unavailable = Counter()
    prediction_counts = Counter()
    for case in cases:
        if "unavailable" in case["point"]:
            message = (
                case["point"]["unavailable"].split(" nv=", 1)[0].split(" ns=", 1)[0]
            )
            unavailable[message] += 1
        raw = case["epoch"]["items"]
        aligned = [
            (r, p)
            for r, p in zip(raw, case["prediction"], strict=True)
            if p is not None and p["elevation"] >= 5
        ]
        prediction_counts["no_ephemeris_or_unhealthy"] += sum(
            p is None for p in case["prediction"]
        )
        prediction_counts["below_five_degrees"] += sum(
            p is not None and p["elevation"] < 5 for p in case["prediction"]
        )
        if len(aligned) >= 6:
            residual = sorted(r["pseudorange"] - p["nominal"] for r, p in aligned)
            useful.append(
                min(residual[-2] - residual[0], residual[-1] - residual[1]) / 2
            )
    return {
        **inputs,
        "aligned_fixed": len(cases),
        "median_alignment_ms": median([case["absolute_time_gap_ms"] for case in cases]),
        "native_fixes": len(errors),
        "native_failures": dict(unavailable),
        "native_error_m": {
            "median": median(errors) if errors else None,
            "p90": order_stat(errors, 9, 10),
        },
        "median_reference_horizontal_sd_m": median(
            [
                sqrt(
                    case["reference"]["reference_sd_neu"][0] ** 2
                    + case["reference"]["reference_sd_neu"][1] ** 2
                )
                for case in cases
            ]
        ),
        "predictions": dict(prediction_counts),
        "epochs_with_six_healthy_elevated": len(useful),
        "unbounded_clock_one_fault_radius_m": {
            "median": median(useful) if useful else None,
            "p90": order_stat(useful, 9, 10),
        },
    }


def run(log, ref, nav, exe, out):
    epochs, raw = read_gps(log)
    reference, quality = read_reference(ref)
    cases, dropped = align(epochs, reference)
    logger, _ = align(epochs, reference, "utc_ms")
    tasks = [
        (
            case["epoch"]["week"],
            case["epoch"]["tow"],
            item["sat"],
            ecef(case["reference"]["lla"]),
        )
        for case in cases
        for item in case["epoch"]["items"]
    ]
    all_predictions = iter(predict(exe, nav, tasks))
    for case, point in zip(cases, point_solutions(exe, nav, cases), strict=True):
        case["prediction"] = [next(all_predictions) for _ in case["epoch"]["items"]]
        case["point"] = point
    assert next(all_predictions, None) is None
    inputs = {
        "source_sha256": {
            p.name: sha256(p.read_bytes()).hexdigest() for p in (log, ref, nav)
        },
        "raw_counts": raw,
        "reference_quality": quality,
        "raw_epochs": len(epochs),
        "alignment_exclusions": dropped,
        "logger_timestamp_matched": len(logger),
        "median_measurement_minus_logger_ms": median(
            [x["measurement_utc_ms"] - x["utc_ms"] for x in epochs]
        ),
        "rtklib_source_commit": "180043ee24b6d2b168f98b64be15f69d50046b1a",
    }
    result = summarize(cases, inputs)
    out.mkdir(parents=True, exist_ok=True)
    (out / (STEM + "-fixture.json.gz")).write_bytes(
        gzip.compress(
            json.dumps(
                {"inputs": inputs, "cases": cases}, separators=(",", ":")
            ).encode(),
            mtime=0,
        )
    )
    (out / (STEM + "-results.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("log", "reference", "navigation", "rtklib_adapter", "output"):
        p.add_argument(arg, type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.log, a.reference, a.navigation, a.rtklib_adapter, a.output)))
