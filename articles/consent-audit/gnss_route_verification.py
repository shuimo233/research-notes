"""Exact satellite selection and held-out GPS route-label verification."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import atan2, degrees, hypot, sin, sqrt
from pathlib import Path

import numpy as np

from gnss_clock_audit import ecef, point_solutions, predict

STEM = "gnss-route-verification"
LABELS = ("south", "north")
ROSTERS = ("margin_six", "elevation_six", "all")
GUARD = Decimal(15) / Decimal(111111)


def read_json(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def compressed(path, obj):
    path.write_bytes(
        gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), mtime=0)
    )


def own_scope(data):
    cases = data["cases"]
    vals = [Decimal(str(r["reference"]["lla"][0])) for r in cases]
    cut = (min(vals) + max(vals)) / 2
    time_zero = cases[0]["reference"]["utc_ms"]
    return cut, [
        {
            "fixture_row": i,
            "ecef_m": ecef(case["reference"]["lla"]),
            "label": LABELS[lat > cut],
            "split": "heldout"
            if ((case["reference"]["utc_ms"] - time_zero) // 30000) % 2
            else "calibration",
        }
        for i, (case, lat) in enumerate(zip(cases, vals, strict=True))
        if abs(lat - cut) > GUARD
    ]


def widths(gaps, faults):
    ranked = np.sort(gaps, axis=-1)
    start = ranked.shape[-1] - faults - 1
    return np.min(ranked[..., start:] - ranked[..., : faults + 1], axis=-1)


def opposite(label):
    south = np.flatnonzero(label == LABELS[0])
    north = np.flatnonzero(label == LABELS[1])
    return np.repeat(south, len(north)), np.tile(north, len(south))


def ceiling(gaps, take):
    scores = widths(gaps[:, take], 2)
    i = int(scores.argmin())
    return int(scores[i]), i


def exact_roster(gaps):
    n = gaps.shape[1]
    menu = list(combinations(range(n), 6))
    seed = widths(gaps, 2).argsort(kind="stable")[:16]
    possible = widths(gaps[seed][:, np.array(menu)], 2).min(axis=0)
    best, evaluated, bounded = (-1, (), -1), 0, 0
    for j in sorted(range(len(menu)), key=lambda i: (-int(possible[i]), menu[i])):
        take = menu[j]
        if int(possible[j]) < best[0] or (possible[j] == best[0] and take >= best[1]):
            bounded += 1
            continue
        e, witness = ceiling(gaps, take)
        evaluated += 1
        if e > best[0] or (e == best[0] and take < best[1]):
            best = (e, take, witness)
    return best, {"options": len(menu), "evaluated": evaluated, "bounded": bounded}


def collision(matrix, take, pair, radius):
    a, b = pair
    u, v = 4 * matrix[a, take], 4 * matrix[b, take]
    deltas = sorted(int(x) for x in v - u)
    window = len(deltas) - 2
    lo, hi = min(zip(deltas, deltas[window - 1 :]), key=lambda x: (x[1] - x[0], x[0]))
    assert hi - lo == 4 * radius
    clock = (lo + hi) // 2
    faults = [j for j, x in enumerate(v - u) if abs(x - clock) > 2 * radius]
    mask_a, mask_b = faults[:1], faults[1:]
    assert len(mask_b) <= 1
    reply = [
        int(
            y
            if j in mask_a
            else x + clock
            if j in mask_b
            else max(x + clock, y) - radius
        )
        for j, (x, y) in enumerate(zip(u, v, strict=True))
    ]
    return {
        "opposite_worlds": [int(a), int(b)],
        "clock_4mm": [clock, 0],
        "fault_indices": [mask_a, mask_b],
        "reply_4mm": reply,
    }


def geometry_cases(cases, catalog, exe, nav):
    points = [w["ecef_m"] for w in catalog]
    center = np.array(points).mean(axis=0).tolist()
    for start in range(0, len(catalog), 8):
        headers = [
            cases[item["fixture_row"]]["epoch"] for item in catalog[start : start + 8]
        ]
        svlists = [tuple(x["sat"] for x in h["items"]) for h in headers]
        tasks = [
            (head["week"], head["tow"], sv, pos)
            for head, satellites in zip(headers, svlists, strict=True)
            for sv in satellites
            for pos in (center, *points)
        ]
        out = predict(exe, nav, tasks)
        offset = 0
        for satellites in svlists:
            by_sat, kept, elevation = [], [], []
            for sv in satellites:
                cell = out[offset : offset + len(points) + 1]
                offset += len(cell)
                if any(p is None for p in cell) or cell[0]["elevation"] < 5.0:
                    continue
                kept.append(sv)
                elevation.append(cell[0]["elevation"])
                by_sat.append([round(r["nominal"] * 1000) for r in cell[1:]])
            yield kept, elevation, np.array(by_sat, dtype=np.int64).T
        assert len(out) == offset


def design(fixture, executable, nav, output):
    data = read_json(fixture)
    assert (
        data["inputs"]["source_sha256"][nav.name]
        == sha256(nav.read_bytes()).hexdigest()
    )
    cut, catalog = own_scope(data)
    lhs, rhs = opposite(np.array([w["label"] for w in catalog]))
    plan = []
    missing = []
    for index, (satellites, elevations, matrix) in enumerate(
        geometry_cases(data["cases"], catalog, executable, nav)
    ):
        if len(satellites) < 6:
            missing.append(index)
            continue
        gaps = matrix[rhs] - matrix[lhs]
        (optimum, best, argmin), proof = exact_roster(gaps)
        high = tuple(
            sorted(
                sorted(
                    range(len(satellites)),
                    key=lambda i: (-elevations[i], satellites[i]),
                )[:6]
            )
        )
        biggest = tuple(range(len(satellites)))
        rosters = {}
        for name, choose in zip(ROSTERS, (best, high, biggest), strict=True):
            threshold, row = (
                (optimum, argmin) if name == ROSTERS[0] else ceiling(gaps, choose)
            )
            pair = lhs[row], rhs[row]
            rosters[name] = {
                "indices": choose,
                "radius_4mm": threshold,
                "collision": collision(matrix, choose, pair, threshold),
            }
        plan.append(
            {
                "world": index,
                "satellites": satellites,
                "center_elevation_deg": elevations,
                "nominal_mm": matrix.tolist(),
                "rosters": rosters,
                "pruning": proof,
            }
        )
    output.mkdir(parents=True, exist_ok=True)
    record = {
        "fixture_sha256": sha256(fixture.read_bytes()).hexdigest(),
        "route_boundary_deg": str(cut),
        "guard_m": 15,
        "catalog": catalog,
        "excluded_within_guard": len(data["cases"]) - len(catalog),
        "unavailable_worlds": missing,
        "plan": plan,
    }
    compressed(output / (STEM + "-design.json.gz"), record)
    return {
        "catalog": len(catalog),
        "usable": len(plan),
        "unavailable": len(missing),
        "scope": dict(Counter(w["split"] + "/" + w["label"] for w in catalog)),
        "enumerated_options": sum(r["pruning"]["options"] for r in plan),
        "full_pair_evaluations": sum(r["pruning"]["evaluated"] for r in plan),
    }


def trimmed_squared(residual):
    # Center each row before squaring. Clock offsets remain free.
    shifted = residual - residual[:, :1]
    n = shifted.shape[1] - 1
    remain_sum = shifted.sum(axis=1, keepdims=True) - shifted
    squares = shifted * shifted
    remain_squares = squares.sum(axis=1, keepdims=True) - squares
    numerators = n * remain_squares - remain_sum**2
    return numerators.min(axis=1)


def rank90(values):
    k = (9 * (len(values) + 1) + 9) // 10
    if k > len(values):
        return None
    return sorted(values, key=lambda x: (x is None, x))[k - 1]


def state(label_scores, bound, truth):
    accepted = [label for label in LABELS if label_scores[label] <= bound]
    if len(accepted) != 1:
        return "abstain"
    return "correct" if accepted[0] == truth else "wrong"


def latitude_geodetic(position):
    x, y, z = position
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)
    p = hypot(x, y)
    lat = atan2(z, p)
    for _ in range(9):
        n = 6378137.0 / sqrt(1 - e2 * sin(lat) ** 2)
        lat = atan2(z + n * e2 * sin(lat), p)
    return Decimal(str(degrees(lat)))


def native_state(point, boundary, truth):
    if "position_ecef" not in point:
        return "abstain"
    lat = latitude_geodetic(point["position_ecef"])
    if abs(lat - boundary) <= GUARD:
        return "abstain"
    return "correct" if LABELS[lat > boundary] == truth else "wrong"


def split_cases(data, design_doc, exe, nav):
    predictions = design_doc["plan"]
    catalog = design_doc["catalog"]
    cases = [data["cases"][catalog[r["world"]]["fixture_row"]] for r in predictions]
    use_native = {name: [] for name in ROSTERS}
    details = []
    label_vec = np.array([w["label"] for w in catalog])
    for case, plan in zip(cases, predictions, strict=True):
        known = catalog[plan["world"]]
        available = {r["sat"]: r for r in case["epoch"]["items"]}
        rows = [available[i] for i in plan["satellites"]]
        observed = np.array(
            [round(r["pseudorange"] * 1000) for r in rows], dtype=np.int64
        )
        residual = observed - np.array(plan["nominal_mm"], dtype=np.int64)
        current = {
            "world": plan["world"],
            "truth": known["label"],
            "split": known["split"],
            "empirical": {},
        }
        for name, portfolio in plan["rosters"].items():
            take = portfolio["indices"]
            z = residual[:, take]
            needed = 2 * widths(z, 1)
            label_demand = {
                label: int(needed[label_vec == label].min()) for label in LABELS
            }
            current["empirical"][name] = {
                "needed_4mm": int(needed[plan["world"]]),
                "label_needed_4mm": label_demand,
                "radius_4mm": portfolio["radius_4mm"],
                "reads": len(take),
            }
            if name == ROSTERS[0]:
                ls = trimmed_squared(z)
                current["lts_scores_x5"] = {
                    label: int(ls[label_vec == label].min() - ls.min())
                    for label in LABELS
                }
            use_native[name].append(
                {**case, "epoch": {**case["epoch"], "items": [rows[i] for i in take]}}
            )
        details.append(current)
    native = {
        name: point_solutions(exe, nav, subset) for name, subset in use_native.items()
    }
    for i, row in enumerate(details):
        row["rtklib"] = {name: native[name][i] for name in ROSTERS}
    return details


def estimate_policy(details, boundary):
    calibration = [row for row in details if row["split"] == "calibration"]
    ratios = {}
    for name in ROSTERS:
        vals = [r["empirical"][name] for r in calibration]
        ratios[name] = rank90(
            [
                Fraction(x["needed_4mm"], x["radius_4mm"]) if x["radius_4mm"] else None
                for x in vals
            ]
        )
    lts = rank90([r["lts_scores_x5"][r["truth"]] for r in calibration])
    coverage = Counter()
    tagged = {
        name: {label: Counter() for label in LABELS}
        for name in (
            *ROSTERS,
            *(name + "_limit" for name in ROSTERS),
            *(name + "_rtklib" for name in ROSTERS),
            "lts",
        )
    }
    for current in details:
        truth = current["truth"]
        if current["split"] == "calibration":
            continue
        coverage[truth] += 1
        current["decisions"] = {}
        for name, info in current["empirical"].items():
            radius = info["radius_4mm"]
            q = ratios[name]
            answer = (
                state(info["label_needed_4mm"], int(q * radius), truth)
                if radius and q is not None and q < 1
                else "abstain"
            )
            diagnostics = state(info["label_needed_4mm"], radius - 1, truth)
            solved = native_state(current["rtklib"][name], boundary, truth)
            current["decisions"].update(
                {name: answer, name + "_limit": diagnostics, name + "_rtklib": solved}
            )
        current["decisions"]["lts"] = (
            state(current["lts_scores_x5"], lts, truth)
            if lts is not None
            else "abstain"
        )
        for mode, decision in current["decisions"].items():
            tagged[mode][truth][decision] += 1
    best = tagged[ROSTERS[0]]
    gate_inputs = {
        "threshold_below_collision": ratios[ROSTERS[0]] is not None
        and ratios[ROSTERS[0]] < 1,
        "six_cheaper_at_every_test": all(
            r["empirical"]["all"]["reads"] > 6
            for r in details
            if r["split"] == "heldout"
        ),
        "north_test_count": coverage[LABELS[1]] >= 8,
        "eighty_percent_correct_each": all(
            coverage[l] and 5 * best[l]["correct"] >= 4 * coverage[l] for l in LABELS
        ),
        "zero_wrong": not any(best[l]["wrong"] for l in LABELS),
        "matches_lts_each": all(
            best[l]["correct"] >= tagged["lts"][l]["correct"] for l in LABELS
        ),
    }
    return {
        "calibration_ratios": {
            name: [q.numerator, q.denominator] if q is not None else None
            for name, q in ratios.items()
        },
        "lts_cutoff_x5": lts,
        "heldout_labels": dict(coverage),
        "heldout_by_method": tagged,
        "gate_inputs": gate_inputs,
        "gate": all(gate_inputs.values()),
    }


def replay(fixture, design_file, exe, nav, output):
    data, design_doc = read_json(fixture), read_json(design_file)
    assert design_doc["fixture_sha256"] == sha256(fixture.read_bytes()).hexdigest()
    assert (
        data["inputs"]["source_sha256"][nav.name]
        == sha256(nav.read_bytes()).hexdigest()
    )
    detail = split_cases(data, design_doc, exe, nav)
    report = estimate_policy(detail, Decimal(design_doc["route_boundary_deg"]))
    report["design_sha256"] = sha256(design_file.read_bytes()).hexdigest()
    report["rollup"] = {
        name: {
            "reads": sorted(
                Counter(r["empirical"][name]["reads"] for r in detail).items()
            ),
            "median_heldout_radius_4mm": float(
                np.median(
                    [
                        r["empirical"][name]["radius_4mm"]
                        for r in detail
                        if r["split"] == "heldout"
                    ]
                )
            ),
            "calibration_needed_less_than_collision": sum(
                r["empirical"][name]["needed_4mm"] < r["empirical"][name]["radius_4mm"]
                for r in detail
                if r["split"] == "calibration"
            ),
        }
        for name in ROSTERS
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / (STEM + "-results.json")).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    compressed(output / (STEM + "-replay.json.gz"), detail)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="stage", required=True)
    for stage in ("design", "replay"):
        sub = subs.add_parser(stage)
        sub.add_argument("fixture", type=Path)
        if stage == "replay":
            sub.add_argument("design_file", type=Path)
        for name in ("executable", "navigation", "output"):
            sub.add_argument(name, type=Path)
    args = p.parse_args()
    f = (args.fixture, args.executable, args.navigation, args.output)
    print(
        json.dumps(
            design(*f)
            if args.stage == "design"
            else replay(args.fixture, args.design_file, *f[1:])
        )
    )
