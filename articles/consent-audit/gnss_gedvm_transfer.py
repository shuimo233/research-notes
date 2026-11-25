"""Replay frozen weighted GPS certificates on independent dates and phone models."""

import argparse
from collections import Counter
from fractions import Fraction
from itertools import chain
from hashlib import sha256
import json
from pathlib import Path

from gnss_gedvm_transfer_inputs import PIN
from gnss_quality_verification import MODES, build, cap_decision, observed_scores
from gnss_route_verification import LABELS, compressed, rank90, read_json, state


def freeze_design(fixture, executable, navigation, design):
    raw = read_json(fixture)
    assert raw["inputs"]["source_pin"] == PIN
    catalog = raw["catalog"]
    scope = {
        "catalog": catalog,
        "boundary_deg": raw["inputs"]["boundary_deg"],
        "guard_excluded": raw["inputs"]["alignment_exclusions"].get("guard", 0),
        "temporal_thinning": raw["inputs"]["thinned"],
    }
    nav = navigation / f"brdc{raw['inputs']['navigation_doy']}0.24n"
    return build(fixture, executable, nav, design, scope=scope)


def formula(scores):
    limits = {}
    for m in MODES:
        vals = [x["rosters"][m] for x in scores]
        limits[m] = rank90(
            [
                Fraction(*r["true_needed2"]) / Fraction(*r["radius2"])
                if Fraction(*r["radius2"])
                else None
                for r in vals
            ]
        )
    return limits, rank90([x["lts_x5"][x["truth"]] for x in scores])


def outcomes(row, limits, lts, diagnostics):
    truth = row["truth"]
    tagged = {}
    for key, r in row["rosters"].items():
        margin = Fraction(*r["radius2"])
        q = limits[key]
        seen = {y: Fraction(*d) for y, d in r["labels_needed2"].items()}
        tagged[key] = (
            state(seen, q * margin, truth)
            if q is not None and q < 1 and margin
            else "abstain"
        )
        if diagnostics:
            tagged[key + "_limit"] = cap_decision(seen, margin, truth)
    tagged["lts"] = state(row["lts_x5"], lts, truth) if lts is not None else "abstain"
    return tagged


def calibrate(rows, fixed):
    results, replay = {}, {}
    for session, test in rows.items():
        peers = sorted(
            key
            for key, other in rows.items()
            if other["drive"] != test["drive"] and other["model"] != test["model"]
        )
        assert len(peers) == 2 and len({rows[name]["drive"] for name in peers}) == 2
        calibration = list(chain.from_iterable(rows[key]["scores"] for key in peers))
        ratios, lts = formula(calibration)
        by_method = {
            m: {label: Counter() for label in LABELS}
            for m in (*MODES, *(m + "_limit" for m in MODES), "lts")
        }
        near = {m: {label: Counter() for label in LABELS} for m in by_method}
        transferred = {
            m: {label: Counter() for label in LABELS} for m in (*MODES, "lts")
        }
        groups = Counter()
        n_near = Counter()
        main_rows = []
        for row in test["scores"]:
            actual = row["truth"]
            near_boundary = test["catalog"][row["world"]]["distance_to_bound_m"] <= 60
            groups[actual] += 1
            n_near[actual] += near_boundary
            d = outcomes(row, ratios, lts, True)
            t = outcomes(row, *fixed, False)
            for name, value in d.items():
                by_method[name][actual][value] += 1
                if near_boundary:
                    near[name][actual][value] += 1
            for name, value in t.items():
                transferred[name][actual][value] += 1
            main_rows.append(
                {
                    **row,
                    "near_boundary": near_boundary,
                    "decision": d,
                    "hervanta_transfer": t,
                }
            )
        minimum = by_method["weighted"]
        check = {
            "both_classes_at_least_eight": all(groups[y] >= 8 for y in LABELS),
            "threshold_strictly_below_collision": ratios["weighted"] is not None
            and ratios["weighted"] < 1,
            "at_least_one_fewer_read_everywhere": bool(main_rows)
            and all(r["rosters"]["all"]["reads"] > 6 for r in main_rows),
            "each_class_80_correct": all(
                groups[y] and 5 * minimum[y]["correct"] >= 4 * groups[y] for y in LABELS
            ),
            "no_wrong": not any(minimum[y]["wrong"] for y in LABELS),
            "strongest_baseline_each_class": all(
                minimum[y]["correct"] >= by_method[m][y]["correct"]
                for m in ("geometry", "elevation", "strength", "lts")
                for y in LABELS
            ),
            "strictly_more_than_geometry": sum(minimum[y]["correct"] for y in LABELS)
            > sum(by_method["geometry"][y]["correct"] for y in LABELS),
        }
        results[session] = {
            "drive": test["drive"],
            "model": test["model"],
            "calibration_sessions": peers,
            "calibration_labels": dict(Counter(r["truth"] for r in calibration)),
            "calibration_ratios": {
                m: [q.numerator, q.denominator] if q is not None else None
                for m, q in ratios.items()
            },
            "lts_cutoff_x5": lts,
            "heldout_labels": dict(groups),
            "near_boundary_labels": dict(n_near),
            "by_method": by_method,
            "near_boundary_by_method": near,
            "hervanta_transfer": transferred,
            "metric_inputs": check,
            "gate": all(check.values()),
            "logical_reads_saved_over_full": sum(
                r["rosters"]["all"]["reads"] - 6 for r in main_rows
            ),
            "sha256": test["sha256"],
        }
        replay[session] = main_rows
    return results, replay


def run(fixtures, design_dir, prior, output):
    data = read_json(prior) if prior.suffix == ".gz" else json.loads(prior.read_bytes())
    fixed = (
        {m: Fraction(*r) if r is not None else None for m, r in data["ratios"].items()},
        data["lts_cutoff_x5"],
    )
    outline = {}
    for file in sorted(fixtures.glob("*-fixture.json.gz")):
        raw = read_json(file)
        session = raw["inputs"]["session"]
        plan = design_dir / (session + "-design.json.gz")
        frozen = read_json(plan)
        assert frozen["fixture_sha256"] == sha256(file.read_bytes()).hexdigest()
        outline[session] = {
            "drive": raw["inputs"]["drive"],
            "model": raw["inputs"]["model"],
            "catalog": frozen["catalog"],
            "scores": observed_scores(raw, frozen, None),
            "sha256": {
                "fixture": frozen["fixture_sha256"],
                "design": sha256(plan.read_bytes()).hexdigest(),
            },
        }
    assert len(outline) == 6 and len({r["drive"] for r in outline.values()}) == 3
    result, diagnostics = calibrate(outline, fixed)
    report = {
        "sessions": result,
        "gate": all(s["gate"] for s in result.values()),
        "calgary_source_commit": PIN,
        "hervanta_source_sha256": sha256(prior.read_bytes()).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    compressed(output.with_suffix(".json.gz"), diagnostics)
    return {
        "overall_gate": report["gate"],
        "sessions": {
            k: {
                "n": sum(v["heldout_labels"].values()),
                "weighted": v["by_method"]["weighted"],
                "same_lts": v["by_method"]["lts"],
                "gate": v["gate"],
            }
            for k, v in result.items()
        },
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="stage", required=True)
    d = sub.add_parser("design")
    for k in ("fixture", "executable", "navigation", "output"):
        d.add_argument(k, type=Path)
    s = sub.add_parser("replay")
    for k in ("fixtures", "designs", "prior", "output"):
        s.add_argument(k, type=Path)
    a = p.parse_args()
    r = (
        freeze_design(a.fixture, a.executable, a.navigation, a.output)
        if a.stage == "design"
        else run(a.fixtures, a.designs, a.prior, a.output)
    )
    print(json.dumps(r))
