"""Freeze GNSS rosters, then compare calibrated measurement budgets on S4."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

import numpy as np

from gnss_clock_audit import ecef
from gnss_quality_verification import (
    ExactKeys,
    cap_decision,
    choose_weighted,
    edge_sets,
    evaluate,
    ratio_pair,
    scale_for,
    witness,
)
from gnss_route_verification import (
    GUARD,
    LABELS,
    compressed,
    geometry_cases,
    opposite,
    rank90,
    read_json,
    state,
    trimmed_squared,
)

STEM = "gnss-budget-frontier"
BUDGETS = ("4", "5", "6")
PRIMARY = "minimum_reads"


def scope(data):
    cases = data["cases"]
    latitudes = [Decimal(str(r["reference"]["lla"][0])) for r in cases]
    cut = (min(latitudes) + max(latitudes)) / 2
    start = cases[0]["reference"]["utc_ms"]
    blocks = {}
    guard = 0
    for i, case in enumerate(cases):
        distance = abs(latitudes[i] - cut) * 111111
        if abs(latitudes[i] - cut) <= GUARD:
            guard += 1
            continue
        t = case["reference"]["utc_ms"] - start
        slot, phase = divmod(t, 5000)
        candidate = (abs(phase - 2500), t, i, distance)
        if slot not in blocks or candidate < blocks[slot]:
            blocks[slot] = candidate
    catalog = []
    for _, t, i, distance in (blocks[s] for s in sorted(blocks)):
        catalog.append(
            {
                "fixture_row": i,
                "ecef_m": ecef(cases[i]["reference"]["lla"]),
                "label": LABELS[latitudes[i] > cut],
                "block": t // 30000,
                "split": "heldout" if (t // 30000) % 2 else "calibration",
                "near": distance <= 60,
            }
        )
    return cut, catalog, guard, len(cases) - guard - len(catalog)


def plan_for(matrix, weights, left, right):
    codec = ExactKeys(weights)
    codes = codec.wrap(matrix[right] - matrix[left])
    rosters = {}
    for k in BUDGETS:
        indices, key, at, stats = choose_weighted(codes, len(weights), int(k))
        a, b = int(left[at]), int(right[at])
        bound = codec.unwrap(key)
        rosters[k] = {
            "indices": indices,
            "pair": [a, b],
            "radius2": ratio_pair(bound),
            "witness": witness(
                list(map(int, matrix[a, indices])),
                list(map(int, matrix[b, indices])),
                [weights[i] for i in indices],
                bound,
            ),
            "search": stats,
        }
    return rosters


def design(fixture_path, exe, nav, output):
    fixture = read_json(fixture_path)
    assert (
        fixture["inputs"]["source_sha256"][nav.name]
        == sha256(nav.read_bytes()).hexdigest()
    )
    cut, catalog, guard, thinned = scope(fixture)
    left, right = opposite(np.array([r["label"] for r in catalog]))
    plans, missing = [], []
    cases = fixture["cases"]
    for world, (svs, _, table) in enumerate(geometry_cases(cases, catalog, exe, nav)):
        if len(svs) < 6:
            missing.append(world)
            continue
        metadata = cases[catalog[world]["fixture_row"]]["epoch"]["items"]
        cn0 = {r["sat"]: r["cn0"] for r in metadata}
        weights = [scale_for(cn0[sat]) for sat in svs]
        plans.append(
            {
                "world": world,
                "satellites": svs,
                "weights": weights,
                "nominal_mm": table.tolist(),
                "rosters": plan_for(table, weights, left, right),
            }
        )
    record = {
        "fixture_sha256": sha256(fixture_path.read_bytes()).hexdigest(),
        "boundary_deg": str(cut),
        "guard_excluded": guard,
        "thinned": thinned,
        "catalog": catalog,
        "unavailable_worlds": missing,
        "plan": plans,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    compressed(output, record)
    return {"catalog": len(catalog), "planned": len(plans), "missing": len(missing)}


def observe(roster, plan, weights, labels, world, read):
    # The callback is called only for this roster. Replay invokes other rosters
    # independently for the baselines and the offline empirical diagnostics.
    take = roster["indices"]
    received = np.array([read(plan["satellites"][j]) for j in take], dtype=np.int64)
    residual = received - np.asarray(plan["nominal_mm"], dtype=np.int64)[:, take]
    codec = ExactKeys([weights[j] for j in take])
    _, edges = edge_sets(len(take), len(take), 1)
    support = evaluate(codec.wrap(residual, True), edges[0])
    ls = trimmed_squared(residual)
    return {
        "true_needed2": ratio_pair(codec.unwrap(support[world])),
        "labels_needed2": {
            label: ratio_pair(codec.unwrap(support[labels == label].min()))
            for label in LABELS
        },
        "radius2": roster["radius2"],
        "lts": {label: int(ls[labels == label].min() - ls.min()) for label in LABELS},
    }


def pick(rosters, cutoff):
    if cutoff is None:
        return None
    return next((k for k in BUDGETS if cutoff < Fraction(*rosters[k]["radius2"])), None)


def measurements(fixture, design_record, output, control):
    labels = np.array([r["label"] for r in design_record["catalog"]])
    rows = []
    for plan in design_record["plan"]:
        world = plan["world"]
        scene = design_record["catalog"][world]
        raw = fixture["cases"][scene["fixture_row"]]["epoch"]["items"]
        readings = {r["sat"]: r for r in raw}
        accesses = []

        def read(satellite):
            accesses.append(satellite)
            return round(readings[satellite]["pseudorange"] * 1000)

        def observe_budget(k):
            return observe(
                plan["rosters"][k], plan, plan["weights"], labels, world, read
            )

        row = {
            "world": world,
            "truth": scene["label"],
            "near": scene["near"],
            "block": scene["block"],
        }
        if control is None:
            row["budgets"] = {k: observe_budget(k) for k in BUDGETS}
        else:
            k = pick(plan["rosters"], control["joint"])
            selected = observe_budget(k) if k else None
            row["picked"] = k
            row["reads"] = accesses[:]
            # Baseline observations take place after the primary method's
            # measured access trace has been saved.
            row["budgets"] = {
                i: selected if i == k else observe_budget(i) for i in BUDGETS
            }
        rows.append(row)
    output.extend(rows)


def calibrate(rows):
    true_scores = [
        {k: Fraction(*r["budgets"][k]["true_needed2"]) for k in BUDGETS} for r in rows
    ]
    radii = [Fraction(*r["budgets"]["6"]["radius2"]) for r in rows]
    return {
        "joint": rank90([max(s.values()) for s in true_scores]),
        "fixed": {k: rank90([s[k] for s in true_scores]) for k in BUDGETS},
        "lts": {
            k: rank90([r["budgets"][k]["lts"][r["truth"]] for r in rows])
            for k in BUDGETS
        },
        "ratio6": rank90(
            [s["6"] / r if r else None for s, r in zip(true_scores, radii, strict=True)]
        ),
    }


def classify(row, cut):
    truth = row["truth"]
    k = row["picked"]
    labels = {
        i: {y: Fraction(*t) for y, t in b["labels_needed2"].items()}
        for i, b in row["budgets"].items()
    }
    radii = {i: Fraction(*b["radius2"]) for i, b in row["budgets"].items()}

    def below_radius(i, bound):
        return (
            state(labels[i], bound, truth)
            if bound is not None and bound < radii[i]
            else "abstain"
        )

    def lts(i):
        bound = cut["lts"][i]
        return (
            state(row["budgets"][i]["lts"], bound, truth)
            if bound is not None
            else "abstain"
        )

    ratio = cut["ratio6"]
    decisions = {
        PRIMARY: below_radius(k, cut["joint"]) if k else "abstain",
        "variable_lts": lts(k) if k else "abstain",
        "ratio6": below_radius("6", ratio * radii["6"])
        if ratio is not None and ratio < 1
        else "abstain",
    }
    for i in BUDGETS:
        decisions[f"absolute{i}"] = below_radius(i, cut["fixed"][i])
        decisions[f"lts{i}"] = lts(i)
        decisions[f"limit{i}"] = cap_decision(labels[i], radii[i], truth)
    row["decisions"] = decisions
    row["status"] = (
        "no_roster"
        if k is None
        else "incompatible"
        if decisions[PRIMARY] == "abstain"
        else decisions[PRIMARY]
    )


def totals(rows):
    methods = [
        PRIMARY,
        "variable_lts",
        "ratio6",
        *(f"{m}{k}" for m in ("absolute", "lts", "limit") for k in BUDGETS),
    ]
    return {
        m: {
            y: Counter(r["decisions"][m] for r in rows if r["truth"] == y)
            for y in LABELS
        }
        for m in methods
    }


def jointly_correct(rows, comparator):
    shared = [
        r
        for r in rows
        if r["decisions"][PRIMARY] == r["decisions"][f"lts{comparator}"] == "correct"
    ]
    return {
        "count": len(shared),
        "primary_reads": sum(len(r["reads"]) for r in shared),
        "baseline_reads": comparator * len(shared),
    }


def summarize(design_record, cal, heldout, cut):
    groups = totals(heldout)
    counts = Counter(r["truth"] for r in heldout)
    main = groups[PRIMARY]
    common = {str(k): jointly_correct(heldout, k) for k in (4, 5, 6)}
    six = common["6"]
    cheaper = next(
        (
            k
            for k in ("4", "5")
            if all(
                groups[f"lts{k}"][y]["correct"] >= groups["lts6"][y]["correct"]
                and groups[f"lts{k}"][y]["wrong"] == 0
                for y in LABELS
            )
        ),
        None,
    )
    gate = {
        "each_class_count": all(counts[y] >= 8 for y in LABELS),
        "each_class_80_correct": all(
            counts[y] and 5 * main[y]["correct"] >= 4 * counts[y] for y in LABELS
        ),
        "zero_wrong": all(main[y]["wrong"] == 0 for y in LABELS),
        "matches_lts6_by_class": all(
            main[y]["correct"] >= groups["lts6"][y]["correct"] for y in LABELS
        ),
        "matches_variable_lts_by_class": all(
            main[y]["correct"] >= groups["variable_lts"][y]["correct"] for y in LABELS
        ),
        "saves_one_per_common_correct_lts6": six["count"] > 0
        and six["baseline_reads"] - six["primary_reads"] >= six["count"],
        "saves_against_cheapest_matching_lts": cheaper is None
        or common[cheaper]["primary_reads"] < common[cheaper]["baseline_reads"],
    }
    return {
        "boundary_deg": design_record["boundary_deg"],
        "catalog": len(design_record["catalog"]),
        "guard_excluded": design_record["guard_excluded"],
        "thinned": design_record["thinned"],
        "unavailable": len(design_record["unavailable_worlds"]),
        "calibration": dict(Counter(r["truth"] for r in cal)),
        "heldout": dict(counts),
        "blocks": {
            "calibration": sorted({r["block"] for r in cal}),
            "heldout": sorted({r["block"] for r in heldout}),
        },
        "cutoffs": {
            "joint": ratio_pair(cut["joint"]),
            "fixed": {k: ratio_pair(v) for k, v in cut["fixed"].items()},
            "lts": cut["lts"],
            "ratio6": ratio_pair(cut["ratio6"]),
        },
        "by_method": groups,
        "near_boundary": totals([r for r in heldout if r["near"]]),
        "read_count_distribution": dict(Counter(str(len(r["reads"])) for r in heldout)),
        "primary_status": dict(Counter(r["status"] for r in heldout)),
        "common_correct": common,
        "cheapest_matching_lts": cheaper,
        "gate_inputs": gate,
        "gate": all(gate.values()),
    }


def replay(fixture_path, design_path, output):
    fixture, design_record = read_json(fixture_path), read_json(design_path)
    assert (
        design_record["fixture_sha256"] == sha256(fixture_path.read_bytes()).hexdigest()
    )
    catalog = design_record["catalog"]
    calibration, heldout = [], []
    cal_plan = {
        **design_record,
        "plan": [
            r
            for r in design_record["plan"]
            if catalog[r["world"]]["split"] == "calibration"
        ],
    }
    test_plan = {
        **design_record,
        "plan": [
            r
            for r in design_record["plan"]
            if catalog[r["world"]]["split"] == "heldout"
        ],
    }
    measurements(fixture, cal_plan, calibration, None)
    cutoffs = calibrate(calibration)
    measurements(fixture, test_plan, heldout, cutoffs)
    for row in heldout:
        classify(row, cutoffs)
    result = summarize(design_record, calibration, heldout, cutoffs)
    result["design_sha256"] = sha256(design_path.read_bytes()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    compressed(
        output / (STEM + "-rows.json.gz"),
        {"calibration": calibration, "heldout": heldout},
    )
    (output / (STEM + "-result.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command, names in (
        ("design", ("fixture", "exe", "nav", "output")),
        ("replay", ("fixture", "plan", "output")),
    ):
        q = sub.add_parser(command)
        for name in names:
            q.add_argument(name, type=Path)
    a = p.parse_args()
    result = (
        design(a.fixture, a.exe, a.nav, a.output)
        if a.command == "design"
        else replay(a.fixture, a.plan, a.output)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
