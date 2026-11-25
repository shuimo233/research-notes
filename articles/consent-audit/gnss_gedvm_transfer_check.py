"""Audit the pinned raw alignment, reported decisions, and group isolation."""

import argparse
from collections import Counter, defaultdict
from csv import DictReader, reader
from decimal import Decimal
from fractions import Fraction
from io import TextIOWrapper
import json
from math import atan2, cos, degrees, hypot, radians, sin, sqrt, tan
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from gnss_gedvm_transfer_inputs import PIN, digest, metadata
from gnss_quality_verification_check import (
    audit_case,
    choice,
    exact_fraction,
    population_rank,
    unpack,
)

LABELS = ("south", "north")
MODES = ("weighted", "geometry", "elevation", "strength", "all")
WEEK = 604800000000000


def proposed_latitude(xyz):
    """Bowring's ellipsoidal inverse, independent of iterative latitude."""
    x, y, z = map(float, xyz)
    a, b = 6378137.0, 6356752.314245179
    e, e_prime = 1 - (b / a) ** 2, (a / b) ** 2 - 1
    p = hypot(x, y)
    t = atan2(z * a, p * b)
    return degrees(atan2(z + e_prime * b * sin(t) ** 3, p - e * a * cos(t) ** 3))


def boundary_height(xyz, lat):
    """Find ECEF z on the prescribed geodetic latitude at fixed horizontal p."""
    a, e = 6378137.0, 0.0066943799901413165
    theta = radians(lat)
    return hypot(*xyz[:2]) * tan(theta) - a * e * sin(theta) / sqrt(
        1 - e * sin(theta) ** 2
    )


def route_data(path):
    ref = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in DictReader(f):
            stamp = int(
                Decimal(row["gps_week"]) * WEEK + Decimal(row["gps_sow_s"]) * 10**9
            )
            xy = tuple(Decimal(row[f"{p}_ecef_m"]) for p in "xyz")
            if all(v.is_finite() for v in xy):
                assert stamp not in ref
                ref[stamp] = xy, row["solution_quality_code"]
    return ref


def collect(path, day):
    counter = Counter()
    rows = defaultdict(dict)
    sec = 10**9
    first = 2331 * WEEK / float(sec) + (day - 252) * 86400
    with ZipFile(path) as archive:
        names = [
            n
            for n in archive.namelist()
            if n.lower().endswith(".txt") and not n.startswith("__MACOSX/")
        ]
        assert len(names) == 1 and archive.testzip() is None
        with TextIOWrapper(
            archive.open(names[0]), encoding="utf-8-sig", newline=""
        ) as f:
            schema = next(
                next(reader([line[2:]])) for line in f if line.startswith("# Raw,")
            )
            for rec in DictReader(
                (line for line in f if line.startswith("Raw,")), fieldnames=schema
            ):
                counter["raw_lines"] += 1
                freq = Decimal(rec["CarrierFrequencyHz"] or 0)
                if (
                    rec["ConstellationType"] != "1"
                    or not 1574420000 <= freq <= 1576420000
                ):
                    continue
                counter["gps_l1"] += 1
                flag = int(rec["State"])
                if flag % 2 == 0 or not (flag // 8 % 2 or flag // 16384 % 2):
                    counter["locking_excluded"] += 1
                    continue
                try:
                    t = int(rec["TimeNanos"])
                    absolute = (
                        Decimal(t)
                        - Decimal(rec["FullBiasNanos"])
                        - Decimal(rec["BiasNanos"] or 0)
                        + Decimal(rec["TimeOffsetNanos"] or 0)
                    )
                    week = (t - int(rec["FullBiasNanos"])) // WEEK
                    lag = absolute - week * WEEK - Decimal(rec["ReceivedSvTimeNanos"])
                    if lag < -WEEK // 2:
                        lag += WEEK
                    if lag >= WEEK // 2:
                        lag -= WEEK
                    value = lag * Decimal(299792458) / sec
                    power = Decimal(rec["Cn0DbHz"])
                    stamp = (t, int(rec["HardwareClockDiscontinuityCount"]))
                    sv = int(rec["Svid"])
                    if not all(x.is_finite() for x in (absolute, value, power)):
                        raise ValueError
                except (ValueError, ArithmeticError):
                    counter["invalid_numeric"] += 1
                    continue
                if not int(first) * sec <= absolute < (int(first) + 86400) * sec:
                    counter["out_of_declared_day"] += 1
                    continue
                if not 10000000 <= value <= 60000000:
                    counter["implausible_pseudorange"] += 1
                    continue
                if sv in rows[stamp]:
                    counter["duplicate_sv"] += 1
                if sv not in rows[stamp] or power > rows[stamp][sv][2]:
                    rows[stamp][sv] = absolute, value, power
    return rows, counter


def interpolation(t, ref, times):
    k = int(np.searchsorted(times, t, side="left"))
    if k < len(times) and int(times[k]) == t:
        chosen = [t]
    elif 0 < k < len(times) and int(times[k]) - int(times[k - 1]) <= 1050000000:
        chosen = list(map(int, times[k - 1 : k + 1]))
    else:
        return None, None
    a, b = chosen[0], chosen[-1]
    prop = Fraction(t - a, b - a) if b > a else 0
    value = [
        float(Fraction(x) + prop * (Fraction(y) - Fraction(x)))
        for x, y in zip(ref[a][0], ref[b][0], strict=True)
    ]
    return value, chosen


def audit_fixture(files, navigation, memo, ref, all_refs, fixture):
    day = int(Decimal(memo["raw_start_sow_s"]) // 86400) + 252
    nav = navigation / f"brdc{day}0.24n"
    raw_path, ref_path = files / memo["raw_archive"], files / memo["reference_csv"]
    source = fixture["inputs"]
    assert source["navigation_doy"] == day
    assert source["source_sha256"] == {
        memo["raw_archive"]: digest(raw_path),
        memo["reference_csv"]: digest(ref_path),
        nav.name: digest(nav),
    }
    assert (source["session"], source["drive"], source["model"]) == (
        memo["session_id"],
        memo["drive_id"],
        memo["model"],
    )
    values, c = collect(raw_path, day)
    assert source["raw_counts"] == c and source["raw_epochs"] == len(values)
    assert (
        len(ref) == source["reference_points"]
        and Counter(q for _, q in ref.values()) == source["reference_quality"]
    )
    origin = min(min(r) for r in all_refs)
    assert origin == source["origin_gps_ns"]
    center = float(source["boundary_deg"])
    lat = [
        proposed_latitude(coords)
        for catalogue in all_refs
        for coords, _ in catalogue.values()
    ]
    assert abs(center - (min(lat) + max(lat)) / 2) < 1e-9
    times = np.array(sorted(ref))
    selected = {}
    losses = Counter()
    for key, rows in values.items():
        ordered = sorted(k[0] for k in rows.values())
        j = len(ordered) // 2
        t = round(ordered[j] if len(ordered) % 2 else (ordered[j - 1] + ordered[j]) / 2)
        pos, brackets = interpolation(t, ref, times)
        if pos is None:
            losses["reference_gap"] += 1
            continue
        if (
            boundary_height(pos, center - 15 / 111111)
            <= pos[2]
            <= boundary_height(pos, center + 15 / 111111)
        ):
            losses["guard"] += 1
            continue
        cell = int((t - origin) // 60000000000)
        target = origin + cell * 60000000000 + 30000000000
        priority = (abs(t - target), t, *key)
        if cell not in selected or priority < selected[cell][0]:
            selected[cell] = priority, pos, brackets, rows
    assert (
        losses == source["alignment_exclusions"]
        and len(values) - sum(losses.values()) - len(selected) == source["thinned"]
    )
    assert len(selected) == len(fixture["cases"]) == len(fixture["catalog"])
    n = 0
    for i, ((cell, (priority, pos, brackets, raw)), actual, index) in enumerate(
        zip(sorted(selected.items()), fixture["cases"], fixture["catalog"], strict=True)
    ):
        _, t, hardware, clock = priority
        epoch = actual["epoch"]
        ref_doc = actual["reference"]
        assert (
            ref_doc["gps_ns"] == t
            and index["time_block"] == cell
            and index["fixture_row"] == i
        )
        assert (epoch["hardware_nanos"], epoch["discontinuity"]) == (hardware, clock)
        assert (
            epoch["week"] == t // WEEK and abs(epoch["tow"] - (t % WEEK) / 10**9) < 1e-9
        )
        assert (
            max(abs(a - b) for a, b in zip(ref_doc["ecef_m"], pos, strict=True)) < 1e-8
        )
        assert ref_doc["ecef_m"] == index["ecef_m"]
        assert ref_doc["brackets"] == [
            {"gps_ns": x, "ecef_m": [str(v) for v in ref[x][0]], "quality": ref[x][1]}
            for x in brackets
        ]
        assert index["label"] == LABELS[pos[2] > boundary_height(pos, center)]
        assert (
            abs(
                index["distance_to_bound_m"]
                - abs(proposed_latitude(pos) - center) * 111111
            )
            < 0.0002
        )
        assert [s["sat"] for s in epoch["items"]] == sorted(raw)
        for cell in epoch["items"]:
            _, d, w = raw[cell["sat"]]
            assert abs(cell["pseudorange"] - float(d)) < 1e-7 and cell["cn0"] == float(
                w
            )
            n += 1
    return n


def check_fold(sid, replay, result, fixed, frames, labels):
    test = frames[sid]
    eligible = [
        k
        for k, r in frames.items()
        if r["day"] != test["day"] and r["model"] != test["model"]
    ]
    assert sorted(eligible) == result["calibration_sessions"] and len(eligible) == 2
    train = [r for k in eligible for r in replay[k]]
    thresholds = {}
    for form in MODES:
        values = []
        for s in train:
            sample = s["rosters"][form]
            q, r = (exact_fraction(sample[k]) for k in ("true_needed2", "radius2"))
            values.append(q / r if r else None)
        thresholds[form] = population_rank(values)
    assert {
        m: exact_fraction(x) for m, x in result["calibration_ratios"].items()
    } == thresholds
    cutoff = population_rank([x["lts_x5"][x["truth"]] for x in train])
    assert cutoff == result["lts_cutoff_x5"]
    assert result["calibration_labels"] == Counter(v["truth"] for v in train)
    outer, near, transfer = [
        {m: {y: Counter() for y in LABELS} for m in result[k]}
        for k in ("by_method", "near_boundary_by_method", "hervanta_transfer")
    ]
    actual, close = Counter(), Counter()
    for row in replay[sid]:
        y = row["truth"]
        flag = labels[row["world"]]["distance_to_bound_m"] <= 60
        assert flag == row["near_boundary"]
        actual[y] += 1
        close[y] += flag
        d, old = {}, {}
        for name, m in row["rosters"].items():
            e = exact_fraction(m["radius2"])
            q = thresholds[name]
            before = exact_fraction(fixed["ratios"][name])
            score = {k: exact_fraction(s) for k, s in m["labels_needed2"].items()}
            d[name] = choice(score, q * e if q is not None and q < 1 and e else None, y)
            d[name + "_limit"] = choice(score, e, y, True)
            old[name] = choice(
                score,
                before * e if before is not None and before < 1 and e else None,
                y,
            )
        d["lts"] = choice(row["lts_x5"], cutoff, y)
        old["lts"] = choice(row["lts_x5"], fixed["lts_cutoff_x5"], y)
        assert row["decision"] == d and row["hervanta_transfer"] == old
        for name, status in d.items():
            outer[name][y][status] += 1
            if flag:
                near[name][y][status] += 1
        for name, status in old.items():
            transfer[name][y][status] += 1
    assert (
        outer == result["by_method"]
        and near == result["near_boundary_by_method"]
        and transfer == result["hervanta_transfer"]
    )
    assert (
        result["heldout_labels"] == actual and result["near_boundary_labels"] == close
    )
    weighted = outer["weighted"]
    gate = {
        "both_classes_at_least_eight": min(actual[y] for y in LABELS) >= 8,
        "threshold_strictly_below_collision": thresholds["weighted"] is not None
        and thresholds["weighted"] < 1,
        "at_least_one_fewer_read_everywhere": bool(replay[sid])
        and min(x["rosters"]["all"]["reads"] for x in replay[sid]) >= 7,
        "each_class_80_correct": all(
            actual[y] and Fraction(weighted[y]["correct"], actual[y]) >= Fraction(4, 5)
            for y in LABELS
        ),
        "no_wrong": sum(weighted[y]["wrong"] for y in LABELS) == 0,
        "strongest_baseline_each_class": all(
            weighted[y]["correct"] >= outer[m][y]["correct"]
            for y in LABELS
            for m in ("geometry", "elevation", "strength", "lts")
        ),
        "strictly_more_than_geometry": sum(weighted[y]["correct"] for y in LABELS)
        > sum(outer["geometry"][y]["correct"] for y in LABELS),
    }
    assert gate == result["metric_inputs"] and result["gate"] == all(gate.values())
    assert result["logical_reads_saved_over_full"] == sum(
        x["rosters"]["all"]["reads"] - 6 for x in replay[sid]
    )


def audit(source, files, nav, fixtures, designs, hervanta, report):
    index, sha = metadata(source)
    summary = json.loads(report.read_bytes())
    replay = unpack(report.with_suffix(".json.gz"))
    fixed = json.loads(hervanta.read_bytes())
    assert summary["calgary_source_commit"] == PIN and summary[
        "hervanta_source_sha256"
    ] == digest(hervanta)
    info = {m["session_id"]: m for m in index}
    assert set(summary["sessions"]) == set(replay) == set(info)
    frames = {
        sid: {"day": m["drive_id"], "model": m["model"]} for sid, m in info.items()
    }
    geo = {s: route_data(files / m["reference_csv"]) for s, m in info.items()}
    evidence = {}
    for sid, memo in info.items():
        for feature in ("raw_archive", "reference_csv"):
            assert digest(files / memo[feature]) == sha[memo[feature]]
        base = fixtures / (sid + "-fixture.json.gz")
        selection = designs / (sid + "-design.json.gz")
        fixture, plan = map(unpack, (base, selection))
        result = summary["sessions"][sid]
        assert result["sha256"] == {
            "fixture": digest(base),
            "design": digest(selection),
        }
        assert (
            plan["fixture_sha256"] == digest(base) and plan["geometry_sha256"] is None
        )
        checked_ranges = audit_fixture(
            files,
            nav,
            memo,
            geo[sid],
            [g for key, g in geo.items() if frames[key]["day"] == frames[sid]["day"]],
            fixture,
        )
        catalog = fixture["catalog"]
        assert plan["catalog"] == catalog
        labels = np.array([a["label"] for a in catalog])
        left, right = (
            np.flatnonzero(labels == "south"),
            np.flatnonzero(labels == "north"),
        )
        pairs = np.repeat(left, len(right)), np.tile(right, len(left))
        assert sorted(
            [r["world"] for r in plan["plan"]] + plan["unavailable_worlds"]
        ) == list(range(len(catalog)))
        options = 0
        for episode, row in zip(plan["plan"], replay[sid], strict=True):
            case = fixture["cases"][catalog[episode["world"]]["fixture_row"]]
            options += audit_case(case, episode, row, None, *pairs, labels)
        check_fold(sid, replay, result, fixed, frames, catalog)
        evidence[sid] = {
            "range_rows": checked_ranges,
            "six_star_options": options,
            "collision_witnesses": 5 * len(replay[sid]),
            "test_points": len(replay[sid]),
        }
    assert summary["gate"] == all(x["gate"] for x in summary["sessions"].values())
    return evidence


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in (
        "source",
        "files",
        "navigation",
        "fixtures",
        "designs",
        "hervanta",
        "report",
    ):
        p.add_argument(k, type=Path)
    a = p.parse_args()
    print(
        json.dumps(
            audit(
                a.source,
                a.files,
                a.navigation,
                a.fixtures,
                a.designs,
                a.hervanta,
                a.report,
            )
        )
    )
