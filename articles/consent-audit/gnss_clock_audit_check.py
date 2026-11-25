"""Independently verify measured GPS time, L1 range and broadcast orbit samples."""

import argparse
from collections import Counter, defaultdict
from csv import DictReader, reader
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
from hashlib import sha256
import json
from math import atan2, cos, dist, isclose, radians, sin, sqrt
from pathlib import Path
from statistics import median

EPOCH = datetime(1980, 1, 6)
WEEK = 604800
LIGHT = 299792458
MU = 398600500000000.0
OMEGA_E = 0.000072921151467


def state_epochs(path):
    kept = defaultdict(dict)
    counts = Counter()
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        names = next(
            next(reader([line[2:]])) for line in f if line.startswith("# Raw,")
        )
        for line in DictReader(
            (x for x in f if x.startswith("Raw,")), fieldnames=names
        ):
            counts["all_raw"] += 1
            freq = Decimal(line["CarrierFrequencyHz"] or 0)
            if line["ConstellationType"] != "1" or not 1574420000 <= freq <= 1576420000:
                continue
            counts["gps_l1"] += 1
            flags = int(line["State"])
            if flags % 2 == 0 or not (flags // 8 % 2 or flags // 16384 % 2):
                counts["state_excluded"] += 1
                continue
            whole = Decimal(line["TimeNanos"]) - Decimal(line["FullBiasNanos"])
            offset = Decimal(line["TimeOffsetNanos"] or "0")
            gps = (whole + offset - Decimal(line["BiasNanos"] or "0")) / 10**9
            tx = Decimal(line["ReceivedSvTimeNanos"]) / 10**9
            week = int(whole // (WEEK * 10**9))
            tow = gps - week * WEEK
            travel = tow - tx
            if travel < -WEEK // 2:
                travel += WEEK
            elif travel > WEEK // 2:
                travel -= WEEK
            observed = LIGHT * travel
            if not 10000000 <= observed <= 60000000:
                counts["physical_excluded"] += 1
                continue
            counts["kept_nonzero_time_offsets"] += offset != 0
            stamp = (
                int(line["HardwareClockDiscontinuityCount"]),
                int(line["TimeNanos"]),
            )
            svid = int(line["Svid"])
            strength = Decimal(line["Cn0DbHz"])
            if svid in kept[stamp]:
                counts["duplicates"] += 1
            item = observed, int(line["utcTimeMillis"]), week, tow, strength
            if svid not in kept[stamp] or strength > kept[stamp][svid][4]:
                kept[stamp][svid] = item
    return kept, counts


def align_references(path, records):
    quality = Counter()
    solved = {}
    use = []
    for line in path.read_text(encoding="ascii").splitlines():
        if not line or line.startswith("%"):
            continue
        dt, tm, lat, lon, altitude, q, *_ = line.split()
        quality[q] += 1
        if q == "1":
            without_leaps = datetime.strptime(
                dt + " " + tm, "%Y/%m/%d %H:%M:%S.%f"
            ).replace(tzinfo=timezone.utc)
            stamp = round(1000 * (without_leaps - timedelta(seconds=18)).timestamp())
            solved[stamp] = list(map(float, (lat, lon, altitude)))
    for key, observations in records.items():
        items = list(observations.values())
        week = items[0][2]
        tow = median([i[3] for i in items])
        measured_ms = 315964800000 + 1000 * WEEK * week + round(1000 * tow) - 18000
        logger_ms = round(median([i[1] for i in items]))
        use.append((logger_ms, key, measured_ms))

    def nearest(field):
        chosen = {}
        counts = Counter()
        for logger, key, measured in sorted(use, key=lambda v: v[0]):
            t = measured if field == "measurement" else logger
            candidate = min(solved, key=lambda r: (abs(t - r), r))
            d = abs(candidate - t)
            if d > 250:
                counts["raw_no_fixed_within_250_ms"] += 1
                continue
            if candidate in chosen:
                counts["raw_duplicate_reference"] += 1
            if candidate not in chosen or d < chosen[candidate][0]:
                chosen[candidate] = (d, key, measured)
        return chosen, counts

    actual, drops = nearest("measurement")
    diagnostic, _ = nearest("logger")
    return (
        actual,
        solved,
        quality,
        drops,
        len(diagnostic),
        median([m - l for l, _, m in use]),
    )


def ephemerides(path):
    found = defaultdict(list)
    with path.open(encoding="ascii") as f:
        for line in f:
            if "END OF HEADER" in line:
                break
        for start in f:
            if not start.startswith("G"):
                continue
            year, month, day, hour, minute, second = map(int, start[4:23].split())
            toc = (
                datetime(year, month, day, hour, minute, second) - EPOCH
            ).total_seconds()

            def decode(row, pos, n):
                return [
                    float(row[pos + 19 * j : pos + 19 * (j + 1)].replace("D", "E"))
                    for j in range(n)
                ]

            clock = decode(start, 23, 3)
            values = [decode(next(f), 4, 4) for _ in range(6)]
            next(f)
            week = int(values[4][2])
            toe = week * WEEK + values[2][0]
            issue = int(values[0][0])
            found[int(start[1:3])].append((toe, toc, issue, clock, values))
    return found


def compute_orbit(record, transmit):
    toe, toc, _, clock, block = record
    tick = transmit - toe
    _, crs, n, m0 = block[0]
    cuc, eccentricity, cus, sqrt_a = block[1]
    toe_week, cic, omega0, cis = block[2]
    incline, crc, perigee, rotation = block[3]
    inclination_rate = block[4][0]
    a = sqrt_a**2
    mean = m0 + (sqrt(MU / (a**3)) + n) * tick
    anomaly = mean
    for _ in range(30):
        anomaly = mean + eccentricity * sin(anomaly)
    angle = (
        atan2(sqrt(1 - eccentricity**2) * sin(anomaly), cos(anomaly) - eccentricity)
        + perigee
    )
    phi = angle + cus * sin(2 * angle) + cuc * cos(2 * angle)
    radius = (
        a * (1 - eccentricity * cos(anomaly))
        + crs * sin(2 * angle)
        + crc * cos(2 * angle)
    )
    inclination = (
        incline + inclination_rate * tick + cis * sin(2 * angle) + cic * cos(2 * angle)
    )
    node = omega0 + rotation * tick - OMEGA_E * (toe_week + tick)
    first, second = radius * cos(phi), radius * sin(phi)
    pos = (
        first * cos(node) - second * cos(inclination) * sin(node),
        first * sin(node) + second * cos(inclination) * cos(node),
        second * sin(inclination),
    )
    dt = transmit - toc
    offset = (
        clock[0]
        + dt * (clock[1] + dt * clock[2])
        - 2 * sqrt(MU * a) * eccentricity * sin(anomaly) / (LIGHT * LIGHT)
    )
    return pos, offset, block[5][2]


def wgs84_xyz(lla):
    lat, lon = map(radians, lla[:2])
    alt = lla[2]
    a, b = 6378137.0, 6356752.314245179
    radius = a * a / sqrt((a * cos(lat)) ** 2 + (b * sin(lat)) ** 2)
    return (
        (radius + alt) * cos(lat) * cos(lon),
        (radius + alt) * cos(lat) * sin(lon),
        (radius * (b / a) ** 2 + alt) * sin(lat),
    )


def check(log, reference, nav, compressed, totals):
    raw, raw_counts = state_epochs(log)
    matches, solved, quality, drops, logger, delay = align_references(reference, raw)
    data = json.loads(gzip.decompress(compressed.read_bytes()))
    summary = json.loads(totals.read_bytes())
    info = data["inputs"]
    assert all(
        info["source_sha256"][p.name] == sha256(p.read_bytes()).hexdigest()
        for p in (log, reference, nav)
    )
    assert info["raw_counts"] == raw_counts and info["raw_epochs"] == len(raw)
    assert (
        info["reference_quality"] == quality and info["alignment_exclusions"] == drops
    )
    assert (
        info["logger_timestamp_matched"] == logger
        and info["median_measurement_minus_logger_ms"] == delay
    )
    records = data["cases"]
    assert len(records) == len(matches) == summary["aligned_fixed"]
    assert [row["reference"]["utc_ms"] for row in records] == sorted(matches)
    orbits = ephemerides(nav)
    pos_max, clock_max = 0.0, 0.0
    orbit_points, pseudoranges = 0, 0
    closed_failures = Counter()
    for seq, case in enumerate(records):
        epoch = case["epoch"]
        t = case["reference"]["utc_ms"]
        gap, key, measured = matches[t]
        assert gap == case["absolute_time_gap_ms"] and key == tuple(epoch["clock_key"])
        assert (
            case["reference"]["lla"] == solved[t]
            and epoch["measurement_utc_ms"] == measured
        )
        assert set(raw[key]) == {item["sat"] for item in epoch["items"]}
        receiver = wgs84_xyz(solved[t])
        for row, state in zip(epoch["items"], case["prediction"], strict=True):
            expected, _, week, _, _ = raw[key][row["sat"]]
            assert abs(row["pseudorange"] - float(expected)) < 1e-7
            pseudoranges += 1
            if state is None:
                continue
            sat = state["sat_ecef"]
            corrected = (
                dist(sat, receiver)
                + OMEGA_E * (sat[0] * receiver[1] - sat[1] * receiver[0]) / LIGHT
            )
            assert abs(corrected - state["geometric_range"]) < 2e-6
            modeled = (
                state["geometric_range"]
                - LIGHT * (state["sat_clock"] - state["tgd"])
                + state["iono"]
                + state["tropo"]
            )
            assert abs(modeled - state["nominal"]) < 1e-6
            assert (
                abs(epoch["tow"] - state["tx"] - state["geometric_range"] / LIGHT)
                < 1e-9
            )
            if seq % 20:
                continue
            received = week * WEEK + epoch["tow"]
            sent = week * WEEK + state["tx"]
            chosen = min(
                (x for x in orbits[row["sat"]] if x[2] == state["iode"]),
                key=lambda x: abs(x[0] - received),
            )
            assert abs(chosen[0] - received) <= 7201
            position, clock, tgd = compute_orbit(chosen, sent)
            pos_max = max(pos_max, dist(position, state["sat_ecef"]))
            clock_max = max(clock_max, abs(clock - state["sat_clock"]) * 1e9)
            assert isclose(tgd, state["tgd"], abs_tol=1e-14)
            orbit_points += 1
        if "unavailable" in case["point"]:
            token = case["point"]["unavailable"].split(" nv=", 1)[0].split(" ns=", 1)[0]
            closed_failures[token] += 1
    assert closed_failures == summary["native_failures"]
    assert summary["median_alignment_ms"] == median([x[0] for x in matches.values()])
    assert len(matches) - sum(closed_failures.values()) == summary["native_fixes"]
    assert orbit_points and pos_max < 0.005 and clock_max < 0.1
    return {
        "aligned_fixed_checked": len(matches),
        "pseudoranges_checked": pseudoranges,
        "independent_broadcast_satellites_checked": orbit_points,
        "max_ecef_difference_m": pos_max,
        "max_clock_difference_ns": clock_max,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("log", "reference", "navigation", "fixture", "results"):
        p.add_argument(arg, type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.log, a.reference, a.navigation, a.fixture, a.results)))
