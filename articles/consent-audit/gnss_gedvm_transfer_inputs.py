"""Fetch pinned GEDVM data and extract time-aligned finite checkpoint catalogues."""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader, reader
from datetime import date, timedelta
from decimal import Decimal
import gzip
from hashlib import sha256
from io import TextIOWrapper
import json
from pathlib import Path
from re import search
from statistics import median
import subprocess
from zipfile import ZipFile

from gnss_route_verification import latitude_geodetic

PIN = "e2966fb40f89f009a4cc6c5282f2decdb1fe7035"
WEEK_NS = 604800000000000
LIGHT = 299792458
BAND = Decimal(15) / Decimal(111111)
DRIVES = ("drive01", "drive02", "drive03")
NAV_SHA256 = {
    254: "edbae3b894b863393335cb1aff46a4d7c85804a676b3a4dd5e14c152a3f7b7fc",
    255: "282a9257ad4dbc6bad8e23c36cf84239dbb446a9cf1b26689402e7048789ff3f",
    256: "06761354edaa4864643a99e379fc07f03ecf919a108bc1d1e0481a7ed3ea9f92",
}


def digest(file):
    with file.open("rb") as content:
        result = sha256()
        for chunk in iter(lambda: content.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


def metadata(source):
    version = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if version != PIN:
        raise ValueError("Use the pinned GEDVM release")
    checksum = {}
    for line in (source / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        value, filename = line.split(maxsplit=1)
        checksum[filename] = value
    index = source / "metadata/sessions.csv"
    assert digest(index) == checksum["metadata/sessions.csv"]
    with index.open(encoding="utf-8", newline="") as f:
        sessions = list(DictReader(f))
    assert len(sessions) == 6 and all(
        {s["model"] for s in sessions if s["drive_id"] == d}
        == {"Pixel 5", "Pixel 7 Pro"}
        for d in DRIVES
    )
    return sessions, checksum


def fetch(source, destination, workers):
    sessions, hashes = metadata(source)
    filenames = sorted(
        {s[key] for s in sessions for key in ("raw_archive", "reference_csv")}
    )

    def transfer(filename):
        out = destination / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.is_file() or digest(out) != hashes[filename]:
            temp = out.with_suffix(out.suffix + ".partial")
            endpoint = f"https://api.github.com/repos/YangRiverJiang/gedvm_dataset/contents/{filename}?ref={PIN}&download=1"
            common = [
                "curl",
                "--http1.1",
                "-fsSL",
                "-H",
                "Accept: application/vnd.github.raw+json",
            ]
            if not temp.is_file():
                subprocess.run(
                    [
                        *common,
                        "--max-time",
                        "65",
                        "--max-filesize",
                        "100000000",
                        "-o",
                        str(temp),
                        endpoint,
                    ],
                    capture_output=True,
                )
            blocked = 0
            while not temp.is_file() or digest(temp) != hashes[filename]:
                start = temp.stat().st_size if temp.is_file() else 0
                partial = temp.with_suffix(".segment")
                header = temp.with_suffix(".headers")
                partial.unlink(missing_ok=True)
                header.unlink(missing_ok=True)
                attempt = subprocess.run(
                    [
                        *common,
                        "--max-time",
                        "45",
                        "--max-filesize",
                        "2097152",
                        "--range",
                        f"{start}-{start + 2097151}",
                        "--dump-header",
                        str(header),
                        "--output",
                        str(partial),
                        endpoint + f"&segment={start}-{blocked}",
                    ],
                    capture_output=True,
                    text=True,
                )
                response = (
                    search(
                        r"(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)",
                        header.read_text(encoding="latin1"),
                    )
                    if header.is_file()
                    else None
                )
                nbytes = partial.stat().st_size if partial.is_file() else 0
                if (
                    response
                    and int(response[1]) == start
                    and 0 < nbytes <= int(response[2]) - start + 1
                ):
                    with temp.open("ab") as output:
                        output.write(partial.read_bytes())
                    if (
                        temp.stat().st_size == int(response[3])
                        and digest(temp) != hashes[filename]
                    ):
                        raise RuntimeError(f"Source SHA-256 mismatch: {filename}")
                    blocked = 0
                elif blocked < 4 and attempt.returncode in (0, 18, 22, 28, 35, 52, 56):
                    blocked += 1
                else:
                    raise RuntimeError(
                        f"Download incomplete: {filename}: {attempt.stderr.strip()}"
                    )
            temp.replace(out)
        return [filename, out.stat().st_size]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for filename, nbytes in pool.map(transfer, filenames):
            print(
                json.dumps({"verified_download": filename, "bytes": nbytes}), flush=True
            )


def references(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        records = []
        for row in DictReader(f):
            t = int(
                Decimal(row["gps_week"]) * WEEK_NS + Decimal(row["gps_sow_s"]) * 10**9
            )
            xyz = [Decimal(row[f"{component}_ecef_m"]) for component in "xyz"]
            if all(v.is_finite() for v in xyz):
                records.append((t, xyz, row["solution_quality_code"]))
    assert all(a[0] < b[0] for a, b in zip(records, records[1:]))
    return records


def reference_position(instant, ref, times):
    k = bisect_left(times, instant)
    if k < len(ref) and times[k] == instant:
        ends = [ref[k]]
    elif 0 < k < len(ref) and times[k] - times[k - 1] <= 1_050_000_000:
        ends = ref[k - 1 : k + 1]
    else:
        return None
    a, b = ends[0], ends[-1]
    ratio = Decimal(instant - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0
    xyz = tuple(float(x + ratio * (y - x)) for x, y in zip(a[1], b[1], strict=True))
    return {
        "gps_ns": instant,
        "ecef_m": xyz,
        "brackets": [
            {"gps_ns": t, "ecef_m": [str(v) for v in p], "quality": q}
            for t, p, q in ends
        ],
    }


def navigation_day(session):
    first = int(Decimal(session["raw_start_sow_s"]) // 86400)
    last = int(Decimal(session["raw_end_sow_s"]) // 86400)
    week = int(session["gps_week"])
    if week != 2331 or first != last:
        raise ValueError("the frozen release requires one navigation day per session")
    return (date(1980, 1, 6) + timedelta(days=week * 7 + first)).timetuple().tm_yday


def read_phone(archive, day):
    keep = defaultdict(dict)
    counts = Counter()
    # Allow the reference interval to decide usability after checking the
    # declared GPS date. The week/day check also catches Android sentinels.
    lower = 2331 * WEEK_NS + (day - 252) * 86400 * 10**9
    upper = lower + 86400 * 10**9
    with ZipFile(archive) as z:
        members = [
            n
            for n in z.namelist()
            if n.lower().endswith(".txt") and not n.startswith("__MACOSX/")
        ]
        if len(members) != 1:
            raise ValueError(
                f"Expected a single phone log in {archive.name}: {members}"
            )
        with TextIOWrapper(
            z.open(members[0]), encoding="utf-8-sig", errors="strict", newline=""
        ) as fd:
            cols = next(
                next(reader([line.strip().lstrip("# ")]))
                for line in fd
                if line.startswith("# Raw,")
            )
            for row in DictReader(
                (x for x in fd if x.startswith("Raw,")), fieldnames=cols
            ):
                counts["raw_lines"] += 1
                if (
                    row["ConstellationType"] != "1"
                    or abs(float(row["CarrierFrequencyHz"] or 0) - 1575420000) > 1000000
                ):
                    continue
                counts["gps_l1"] += 1
                flags = int(row["State"])
                if not (flags & 1 and flags & (8 | 16384)):
                    counts["locking_excluded"] += 1
                    continue
                try:
                    hardware = int(row["TimeNanos"])
                    whole = hardware - int(row["FullBiasNanos"])
                    fractional = Decimal(row["TimeOffsetNanos"] or "0") - Decimal(
                        row["BiasNanos"] or "0"
                    )
                    travel = (
                        whole % WEEK_NS - int(row["ReceivedSvTimeNanos"]) + WEEK_NS // 2
                    ) % WEEK_NS - WEEK_NS // 2
                    absolute = Decimal(whole) + fractional
                    pr = Decimal(LIGHT) * (travel + fractional) / 10**9
                    clock, sv = (
                        int(row["HardwareClockDiscontinuityCount"]),
                        int(row["Svid"]),
                    )
                    cn0 = Decimal(row["Cn0DbHz"])
                    if not all(x.is_finite() for x in (absolute, pr, cn0)):
                        raise ValueError
                except (ValueError, ArithmeticError):
                    counts["invalid_numeric"] += 1
                    continue
                if not lower <= absolute < upper:
                    counts["out_of_declared_day"] += 1
                    continue
                if not 10_000_000 <= pr <= 60_000_000:
                    counts["implausible_pseudorange"] += 1
                    continue
                # Keep individual record offsets as Decimal until epoch grouping.
                value = (absolute, pr, cn0)
                group = keep[hardware, clock]
                if sv in group:
                    counts["duplicate_sv"] += 1
                if sv not in group or group[sv][2] < cn0:
                    group[sv] = value
    return keep, dict(counts)


def make_session(session, files, reference, cutoff, origin, nav, hashes):
    day = navigation_day(session)
    raw, counts = read_phone(files / session["raw_archive"], day)
    times = [p[0] for p in reference]
    chosen = {}
    excludes = Counter()
    for (hardware, clock), group in raw.items():
        t = round(median([value[0] for value in group.values()]))
        gt = reference_position(t, reference, times)
        if gt is None:
            excludes["reference_gap"] += 1
            continue
        latitude = latitude_geodetic(gt["ecef_m"])
        if abs(latitude - cutoff) <= BAND:
            excludes["guard"] += 1
            continue
        week, offset = divmod(t, WEEK_NS)
        values = [
            {"sat": sv, "pseudorange": float(r), "cn0": float(s)}
            for sv, (_, r, s) in sorted(group.items())
        ]
        row = {
            "reference": gt,
            "epoch": {
                "week": week,
                "tow": offset / 10**9,
                "items": values,
                "hardware_nanos": hardware,
                "discontinuity": clock,
            },
        }
        cell, position = divmod(t - origin, 60 * 10**9)
        metric = (abs(position - 30 * 10**9), t, hardware, clock)
        if cell not in chosen or metric < chosen[cell][0]:
            chosen[cell] = metric, row, latitude
    cases, catalog = [], []
    for cell, (_, row, latitude) in sorted(chosen.items()):
        catalog.append(
            {
                "fixture_row": len(cases),
                "label": "north" if latitude > cutoff else "south",
                "split": "leave_day_and_model",
                "ecef_m": row["reference"]["ecef_m"],
                "distance_to_bound_m": float(abs(latitude - cutoff) * 111111),
                "time_block": cell,
            }
        )
        cases.append(row)
    return {
        "inputs": {
            "source_sha256": {
                session[k]: hashes[session[k]] for k in ("raw_archive", "reference_csv")
            }
            | {nav.name: digest(nav)},
            "session": session["session_id"],
            "drive": session["drive_id"],
            "model": session["model"],
            "source_pin": PIN,
            "navigation_doy": day,
            "raw_counts": counts,
            "raw_epochs": len(raw),
            "alignment_exclusions": dict(excludes),
            "thinned": len(raw) - sum(excludes.values()) - len(cases),
            "reference_points": len(reference),
            "reference_quality": dict(Counter(q for _, _, q in reference)),
            "boundary_deg": str(cutoff),
            "origin_gps_ns": origin,
        },
        "cases": cases,
        "catalog": catalog,
    }


def prepare(source, files, nav_dir, output):
    sessions, hashes = metadata(source)
    for s in sessions:
        for k in ("raw_archive", "reference_csv"):
            path = files / s[k]
            assert digest(path) == hashes[s[k]], path
    output.mkdir(parents=True, exist_ok=True)
    for day in DRIVES:
        together = [s for s in sessions if s["drive_id"] == day]
        ref = [references(files / s["reference_csv"]) for s in together]
        all_lat = [
            latitude_geodetic(list(map(float, xyz)))
            for group in ref
            for _, xyz, _ in group
        ]
        cut = (min(all_lat) + max(all_lat)) / 2
        origin = min(seq[0][0] for seq in ref)
        for s, truth in zip(together, ref, strict=True):
            num = navigation_day(s)
            nav = nav_dir / f"brdc{num}0.24n"
            assert digest(nav) == NAV_SHA256[num], nav
            fixture = make_session(s, files, truth, cut, origin, nav, hashes)
            destination = output / (s["session_id"] + "-fixture.json.gz")
            destination.write_bytes(
                gzip.compress(
                    json.dumps(fixture, separators=(",", ":")).encode(), mtime=0
                )
            )
            print(
                json.dumps(
                    {
                        "session": s["session_id"],
                        "catalogue": dict(
                            Counter(z["label"] for z in fixture["catalog"])
                        ),
                        "raw_epochs": fixture["inputs"]["raw_epochs"],
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("source", type=Path)
    f.add_argument("destination", type=Path)
    f.add_argument("--workers", type=int, default=4)
    b = sub.add_parser("prepare")
    for name in ("source", "files", "navigation", "output"):
        b.add_argument(name, type=Path)
    a = p.parse_args()
    if a.mode == "fetch":
        fetch(a.source, a.destination, a.workers)
    else:
        prepare(a.source, a.files, a.navigation, a.output)
