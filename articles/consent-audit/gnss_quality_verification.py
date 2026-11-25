"""Select exact six-satellite rosters under a measured quality scale."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from functools import cache
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np

from gnss_clock_audit import ecef
from gnss_route_verification import (
    GUARD,
    LABELS,
    compressed,
    exact_roster,
    geometry_cases,
    opposite,
    rank90,
    read_json,
    state,
    trimmed_squared,
)

MODES = ("weighted", "geometry", "elevation", "strength", "all")


def scale_for(strength):
    return max(1, round(1024 * 10 ** ((40 - min(50, max(15, strength))) / 20)))


def ratio_pair(value):
    return [value.numerator, value.denominator] if value is not None else None


@cache
def edge_sets(n, width, failures):
    """For each roster, collect the edge indices of its legal survivor sets."""
    edges = {p: i for i, p in enumerate(combinations(range(n), 2))}
    menu = list(combinations(range(n), width))
    index = np.array(
        [
            [
                [edges[pair] for pair in combinations(keep, 2)]
                for keep in combinations(roster, width - failures)
            ]
            for roster in menu
        ],
        dtype=np.int64,
    )
    return menu, index


class ExactKeys:
    """Integer order keys for all rational edge radii of one epoch."""

    def __init__(self, weights):
        self.edges = np.array(list(combinations(range(len(weights)), 2)))
        self.denominators = np.array(
            [weights[i] + weights[j] for i, j in self.edges], dtype=np.int64
        )
        self.scale = int(self.denominators.max()) ** 2 + 1

    def wrap(self, value_rows, true_score=False):
        distances = np.abs(
            value_rows[:, self.edges[:, 0]] - value_rows[:, self.edges[:, 1]]
        )
        maximum = int(distances.max()) * (2 if true_score else 1)
        if maximum * self.scale > np.iinfo(np.int64).max:
            raise OverflowError("exact order keys exceed int64")
        return distances * (2 if true_score else 1) * self.scale // self.denominators

    def unwrap(self, key):
        identity = int(key)
        # A denominator with a valid integer numerator suffices. Any two
        # candidates admitted to this slot are the same rational value.
        for d in set(map(int, self.denominators)):
            numerator = (identity * d + self.scale - 1) // self.scale
            if numerator * self.scale // d == identity:
                return Fraction(numerator, d)
        raise ValueError("key must have originated from a legal pair")


def evaluate(codes, kept_edges):
    return codes[:, kept_edges].max(axis=-1).min(axis=-1)


def choose_weighted(codes, n, budget=6):
    menu, kept = edge_sets(n, budget, 2)
    _, all_edges = edge_sets(n, n, 2)
    worst = evaluate(codes, all_edges[0])
    seeds = worst.argsort(kind="stable")[:16]
    upper = evaluate(codes[seeds], kept).min(axis=0)
    best, index, boundary, assessed = -1, 0, 0, 0
    for j in sorted(range(len(menu)), key=lambda i: (-int(upper[i]), i)):
        if upper[j] < best or (upper[j] == best and j >= index):
            continue
        values = evaluate(codes, kept[j])
        place = int(values.argmin())
        score = int(values[place])
        assessed += 1
        if score > best or (score == best and j < index):
            best, index, boundary = score, j, place
    return menu[index], best, boundary, {"options": len(menu), "assessed": assessed}


def fix_radius(codes, n, picked):
    menu, kept = edge_sets(n, len(picked), 2)
    loc = menu.index(picked)
    values = evaluate(codes, kept[loc])
    place = int(values.argmin())
    return int(values[place]), place


def witness(a, b, weights, threshold):
    diffs = [y - x for x, y in zip(a, b, strict=True)]
    errors = [threshold * w / 2 for w in weights]
    span = [
        (d - threshold * w, d + threshold * w)
        for d, w in zip(diffs, weights, strict=True)
    ]
    for group in combinations(span, len(span) - 2):
        lo = max(k[0] for k in group)
        hi = min(k[1] for k in group)
        if lo <= hi:
            break
    else:
        raise AssertionError("claimed boundary has no common reply")
    exceptional = [i for i, (l, u) in enumerate(span) if not l <= lo <= u]
    bad_a, bad_b = exceptional[:1], exceptional[1:]
    assert len(bad_b) <= 1
    reply = []
    for i, (u, v) in enumerate(zip(a, b, strict=True)):
        reply.append(
            Fraction(v)
            if i in bad_a
            else u + lo
            if i in bad_b
            else max(u + lo, v) - errors[i]
        )
    return {
        "clocks_mm": [ratio_pair(lo), [0, 1]],
        "reply_mm": [ratio_pair(r) for r in reply],
        "faults": [bad_a, bad_b],
    }


def s3_scope(fixture):
    rows = fixture["cases"]
    lat = [Decimal(str(r["reference"]["lla"][0])) for r in rows]
    center = (min(lat) + max(lat)) / 2
    start = rows[0]["reference"]["utc_ms"]
    available = {}
    removed = 0
    for i, case in enumerate(rows):
        if abs(lat[i] - center) <= GUARD:
            removed += 1
            continue
        block, t = divmod(case["reference"]["utc_ms"] - start, 60000)
        which = int(t >= 30000)
        offset = abs(t - (15000 + 30000 * which))
        tag = block, which
        if tag not in available or (offset, i) < available[tag]:
            available[tag] = offset, i
    ordered = sorted((i, g[0]) for g, (_, i) in available.items())
    return {
        "boundary_deg": str(center),
        "guard_excluded": removed,
        "temporal_thinning": len(rows) - removed - len(ordered),
        "catalog": [
            {
                "fixture_row": i,
                "ecef_m": ecef(rows[i]["reference"]["lla"]),
                "label": LABELS[lat[i] > center],
                "split": "heldout" if block % 2 else "calibration",
            }
            for i, block in ordered
        ],
    }


def s3_geometry(fixture, exe, nav, scope=None):
    result = dict(scope) if scope is not None else s3_scope(fixture)
    plans, unavailable = [], []
    for i, (svs, elevation, table) in enumerate(
        geometry_cases(fixture["cases"], result["catalog"], exe, nav)
    ):
        if len(svs) < 6:
            unavailable.append(i)
        else:
            plans.append(
                {
                    "world": i,
                    "satellites": svs,
                    "center_elevation_deg": elevation,
                    "nominal_mm": table.tolist(),
                }
            )
    result.update(plan=plans, unavailable_worlds=unavailable)
    return result


def build(fixture_file, exe, nav, output, old_geometry=None, scope=None):
    inputs = read_json(fixture_file)
    source = sha256(fixture_file.read_bytes()).hexdigest()
    assert (
        inputs["inputs"]["source_sha256"][nav.name]
        == sha256(nav.read_bytes()).hexdigest()
    )
    if old_geometry:
        geometry = read_json(old_geometry)
        assert geometry["fixture_sha256"] == source
        origin = sha256(old_geometry.read_bytes()).hexdigest()
        scope = {key: geometry[key] for key in ("catalog", "unavailable_worlds")}
        scope.update(
            guard_excluded=geometry["excluded_within_guard"], temporal_thinning=0
        )
    else:
        geometry = s3_geometry(inputs, exe, nav, scope)
        scope = {key: value for key, value in geometry.items() if key != "plan"}
        origin = None
    catalog = geometry["catalog"]
    left, right = opposite(np.array([x["label"] for x in catalog]))
    isolated = []
    for plan in geometry["plan"]:
        world = plan["world"]
        epoch = inputs["cases"][catalog[world]["fixture_row"]]["epoch"]
        svs = plan["satellites"]
        cn0 = {q["sat"]: q["cn0"] for q in epoch["items"]}
        weights = [scale_for(cn0[i]) for i in svs]
        codec = ExactKeys(weights)
        matrix = np.array(plan["nominal_mm"], dtype=np.int64)
        gaps = matrix[right] - matrix[left]
        keys = codec.wrap(gaps)
        best, val, point, stats = choose_weighted(keys, len(svs))
        if old_geometry:
            geo = tuple(plan["rosters"]["margin_six"]["indices"])
            el = tuple(plan["rosters"]["elevation_six"]["indices"])
        else:
            (_, geo, _), _ = exact_roster(gaps)
            el = tuple(
                sorted(
                    sorted(
                        range(len(svs)),
                        key=lambda k: (-plan["center_elevation_deg"][k], svs[k]),
                    )[:6]
                )
            )
        signal = tuple(
            sorted(sorted(range(len(svs)), key=lambda k: (-cn0[svs[k]], svs[k]))[:6])
        )
        menus = {}
        for name, take in zip(
            MODES, (best, geo, el, signal, tuple(range(len(svs)))), strict=True
        ):
            key, pair = (
                (val, point) if name == "weighted" else fix_radius(keys, len(svs), take)
            )
            radius = codec.unwrap(key)
            a, b = int(left[pair]), int(right[pair])
            example = witness(
                list(map(int, matrix[a, take])),
                list(map(int, matrix[b, take])),
                [weights[j] for j in take],
                radius,
            )
            menus[name] = {
                "indices": take,
                "radius2": ratio_pair(radius),
                "pair": [a, b],
                "witness": example,
            }
        row = {
            "world": world,
            "weights": weights,
            "rosters": menus,
            "optimization": stats,
        }
        if not old_geometry:
            row.update({k: v for k, v in plan.items() if k != "world"})
        isolated.append(row)
    scope.update(fixture_sha256=source, geometry_sha256=origin, plan=isolated)
    output.parent.mkdir(parents=True, exist_ok=True)
    compressed(output, scope)
    return {
        "cases": len(isolated),
        "catalog": len(catalog),
        "north": sum(p["label"] == "north" for p in catalog),
        "options": sum(x["optimization"]["options"] for x in isolated),
        "full_evaluations": sum(x["optimization"]["assessed"] for x in isolated),
        "unavailable": len(scope["unavailable_worlds"]),
    }


def observed_scores(fixture, design, geometry):
    labels = np.array([x["label"] for x in design["catalog"]])
    combined = {r["world"]: r for r in geometry["plan"]} if geometry else {}
    data = []
    for plan in design["plan"]:
        world = plan["world"]
        scene = design["catalog"][world]
        raw = fixture["cases"][scene["fixture_row"]]["epoch"]
        table = combined[world] if geometry else plan
        observed = {i["sat"]: round(i["pseudorange"] * 1000) for i in raw["items"]}
        residual = np.array([observed[i] for i in table["satellites"]]) - np.array(
            table["nominal_mm"], dtype=np.int64
        )
        codec = ExactKeys(plan["weights"])
        code = codec.wrap(residual, True)
        result = {
            "world": world,
            "truth": scene["label"],
            "split": scene["split"],
            "rosters": {},
        }
        for name, roster in plan["rosters"].items():
            take = tuple(roster["indices"])
            menu, edges = edge_sets(len(plan["weights"]), len(take), 1)
            support = evaluate(code, edges[menu.index(take)])
            result["rosters"][name] = {
                "true_needed2": ratio_pair(codec.unwrap(int(support[world]))),
                "labels_needed2": {
                    label: ratio_pair(codec.unwrap(int(support[labels == label].min())))
                    for label in LABELS
                },
                "radius2": roster["radius2"],
                "reads": len(take),
            }
            if name == "weighted":
                ls = trimmed_squared(residual[:, take])
                result["lts_x5"] = {
                    label: int(ls[labels == label].min() - ls.min()) for label in LABELS
                }
        data.append(result)
    return data


def cap_decision(metric, rad, truth):
    accepted = {label for label, s in metric.items() if s < rad}
    return (
        "correct"
        if accepted == {truth}
        else "wrong"
        if len(accepted) == 1
        else "abstain"
    )


def assess(data, external):
    calibration = [r for r in data if r["split"] == "calibration"]
    heldout = [r for r in data if r["split"] == "heldout"]
    q = {}
    coverage = {}
    for mode in MODES:
        subset = [r["rosters"][mode] for r in calibration]
        values = [
            Fraction(*s["true_needed2"]) / Fraction(*s["radius2"])
            if Fraction(*s["radius2"])
            else None
            for s in subset
        ]
        q[mode] = rank90(values)
        coverage[mode] = sum(x is not None and x < 1 for x in values)
    lts = rank90([r["lts_x5"][r["truth"]] for r in calibration])
    tagged = {
        m: {y: Counter() for y in LABELS}
        for m in (*MODES, *(m + "_limit" for m in MODES), "lts")
    }
    for r in heldout:
        truth = r["truth"]
        d = {}
        for name, plan in r["rosters"].items():
            radius = Fraction(*plan["radius2"])
            values = {y: Fraction(*n) for y, n in plan["labels_needed2"].items()}
            allowed = q[name]
            d[name] = (
                state(values, allowed * radius, truth)
                if radius and allowed is not None and allowed < 1
                else "abstain"
            )
            d[name + "_limit"] = cap_decision(values, radius, truth)
        d["lts"] = state(r["lts_x5"], lts, truth) if lts is not None else "abstain"
        r["decision"] = d
        for m, value in d.items():
            tagged[m][truth][value] += 1
    counts = Counter(r["truth"] for r in heldout)
    primal = tagged["weighted"]
    gate = {
        "external_dataset": external,
        "each_class_count": min(counts[y] for y in LABELS) >= 8,
        "saves_one_everywhere": bool(heldout)
        and all(x["rosters"]["all"]["reads"] > 6 for x in heldout),
        "below_collision": q["weighted"] is not None and q["weighted"] < 1,
        "each_class_80_correct": all(
            counts[y] > 0 and 5 * primal[y]["correct"] >= 4 * counts[y] for y in LABELS
        ),
        "zero_wrong": sum(primal[y]["wrong"] for y in LABELS) == 0,
        "beats_or_matches_each_baseline": all(
            primal[y]["correct"] >= tagged[m][y]["correct"]
            for y in LABELS
            for m in ("geometry", "elevation", "strength", "lts")
        ),
        "strictly_beats_geometry_total": sum(primal[y]["correct"] for y in LABELS)
        > sum(tagged["geometry"][y]["correct"] for y in LABELS),
    }
    return {
        "ratios": {m: ratio_pair(v) for m, v in q.items()},
        "calibration_inside": coverage,
        "heldout_counts": dict(counts),
        "calibration_counts": dict(Counter(r["truth"] for r in calibration)),
        "by_method": tagged,
        "lts_cutoff_x5": lts,
        "gate_inputs": gate,
        "gate": all(gate.values()),
    }


def replay(fixture, design_file, output, old_geometry):
    design = read_json(design_file)
    assert design["fixture_sha256"] == sha256(fixture.read_bytes()).hexdigest()
    if old_geometry:
        assert (
            design["geometry_sha256"] == sha256(old_geometry.read_bytes()).hexdigest()
        )
    else:
        assert design["geometry_sha256"] is None
    data = observed_scores(
        read_json(fixture), design, read_json(old_geometry) if old_geometry else None
    )
    summary = assess(data, old_geometry is None)
    summary["design_sha256"] = sha256(design_file.read_bytes()).hexdigest()
    compressed(output.with_suffix(".json.gz"), data)
    output.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="stage", required=True)
    design = subs.add_parser("design")
    score = subs.add_parser("replay")
    for sub in (design, score):
        sub.add_argument("fixture", type=Path)
        sub.add_argument("--geometry", type=Path)
        sub.add_argument("output", type=Path)
    design.add_argument("executable", type=Path)
    design.add_argument("navigation", type=Path)
    score.add_argument("design_file", type=Path)
    a = p.parse_args()
    result = (
        build(a.fixture, a.executable, a.navigation, a.output, a.geometry)
        if a.stage == "design"
        else replay(a.fixture, a.design_file, a.output, a.geometry)
    )
    print(json.dumps(result))
