"""Test three-read conditional certificates using a different day's route map."""

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from gnss_clock_audit import ecef, read_gps
from gnss_quality_verification import (
    ExactKeys,
    choose_weighted,
    edge_sets,
    evaluate,
    scale_for,
)
from gnss_route_verification import (
    GUARD,
    LABELS,
    compressed,
    geometry_cases,
    opposite,
    rank90,
    read_json,
    trimmed_squared,
)

STEM = "gnss-prefix-verification"
DOSES = (-20000, -10000, -5000, 5000, 10000, 20000)
PREFIX = "conditional"
METHODS = (
    PREFIX,
    "cert3",
    "cert4",
    "lts3",
    "lts4",
    "wlts3",
    "wlts4",
    "same_lts",
    "same_wlts",
)


def load_drive(root, manifest):
    items = [
        root / name
        for name in ("pixel5/device_gnss.csv", "pixel5/ground_truth.csv", "brdc.nav")
    ]
    for path in items:
        key = (
            "dataset_2023/train/" + root.name + "/" + path.relative_to(root).as_posix()
        )
        assert sha256(path.read_bytes()).hexdigest() == manifest[key]["sha256"]
    gnss, ref, nav = items
    with TemporaryDirectory() as directory:
        adapted = Path(directory) / "raw.txt"
        with (
            gnss.open(encoding="utf-8-sig", newline="") as source,
            adapted.open("w", encoding="utf-8", newline="") as target,
        ):
            head = source.readline()
            assert head.startswith("MessageType,")
            target.write("# Raw," + head.split(",", 1)[1])
            target.writelines(line for line in source if line.startswith("Raw,"))
        epochs, raw_counts = read_gps(adapted)
    with ref.open(encoding="utf-8-sig", newline="") as source:
        truth = {
            int(r["UnixTimeMillis"]): tuple(
                map(
                    float,
                    (r["LatitudeDegrees"], r["LongitudeDegrees"], r["AltitudeMeters"]),
                )
            )
            for r in csv.DictReader(source)
            if r["Provider"] == "GT"
            and all(
                r[k] for k in ("LatitudeDegrees", "LongitudeDegrees", "AltitudeMeters")
            )
        }
    return epochs, truth, nav, raw_counts


def assign(position, boundary):
    lat = Decimal(str(position[0]))
    return LABELS[lat > boundary], abs(lat - boundary)


def sample(epochs, indices):
    origin = epochs[0]["measurement_utc_ms"]
    buckets = defaultdict(list)
    for i in indices:
        t = epochs[i]["measurement_utc_ms"] - origin
        q, r = divmod(t, 10000)
        buckets[q].append((abs(r - 5000), t, i))
    return [min(buckets[k])[2] for k in sorted(buckets)]


def create_plan(train_root, test_root, exe, manifest_path, target):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    train, train_truth, train_nav, train_counts = load_drive(train_root, manifest)
    test, _, test_nav, test_counts = load_drive(test_root, manifest)
    lats = [Decimal(str(p[0])) for p in train_truth.values()]
    cut = (min(lats) + max(lats)) / 2
    chosen = sample(
        train,
        [
            i
            for i, e in enumerate(train)
            if e["utc_ms"] in train_truth
            and assign(train_truth[e["utc_ms"]], cut)[1] > GUARD
        ],
    )
    catalog = [
        {
            "fixture_row": i,
            "ecef_m": ecef(train_truth[train[i]["utc_ms"]]),
            "label": assign(train_truth[train[i]["utc_ms"]], cut)[0],
        }
        for i in chosen
    ]
    left, right = opposite(np.array([r["label"] for r in catalog]))
    missing = {}
    records = {}
    for group, epochs, nav, selected in (
        ("calibration", train, train_nav, chosen),
        ("heldout", test, test_nav, sample(test, range(len(test)))),
    ):
        cases = [{"epoch": e} for e in epochs]
        queries = [{"fixture_row": i} for i in selected]
        geometry = geometry_cases(cases, catalog, exe, nav, queries=queries)
        records[group], missing[group] = [], []
        for i, (sats, _, matrix) in zip(selected, geometry, strict=True):
            if len(sats) < 4:
                missing[group].append(i)
                continue
            metadata = {r["sat"]: r["cn0"] for r in epochs[i]["items"]}
            weights = [scale_for(metadata[s]) for s in sats]
            order = ExactKeys(weights)
            codes = order.wrap(matrix[right] - matrix[left])
            take, key, at, search = choose_weighted(codes, len(sats), 4)
            radius = order.unwrap(key)
            records[group].append(
                {
                    "i": i,
                    "satellites": [sats[j] for j in take],
                    "weights": [weights[j] for j in take],
                    "nominal_mm": matrix[:, take].tolist(),
                    "all_satellites": sats,
                    "all_weights": weights,
                    "all_nominal_mm": matrix.tolist(),
                    "radius2": [radius.numerator, radius.denominator],
                    "indices": take,
                    "pair": [int(left[at]), int(right[at])],
                    "search": search,
                }
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    compressed(
        target,
        {
            "boundary": str(cut),
            "catalog": catalog,
            "missing": missing,
            "records": records,
            "counts": {"calibration": train_counts, "heldout": test_counts},
            "source_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        },
    )
    return {k: [len(records[k]), len(missing[k])] for k in records}


def weighted_loss(residual, weights):
    # C/N0 scales are proportional to standard deviations. Subtract a
    # common integer origin before evaluating the weighted sample variance.
    residual = residual - residual[:, :1]
    weight = 1 / (np.asarray(weights, dtype=float) ** 2)
    weighted = residual * weight
    a = weight.sum() - weight
    b = weighted.sum(axis=1, keepdims=True) - weighted
    squares = weighted * residual
    loss = squares.sum(axis=1, keepdims=True) - squares - b * b / a
    return np.maximum(loss.min(axis=1), 0).round(6)


def scores(plan, width, read, labels, world=None):
    observed = [read(s) for s in plan["satellites"][:width]]
    res = np.asarray(observed) - np.asarray(plan["nominal_mm"])[:, :width]
    weights = plan["weights"][:width]
    codec = ExactKeys(weights)
    _, spans = edge_sets(width, width, 1)
    needed = evaluate(codec.wrap(res, True), spans[0])
    lts = trimmed_squared(res)
    wlts = weighted_loss(res, weights)
    record = {
        "cert": {y: codec.unwrap(needed[labels == y].min()) for y in LABELS},
        "lts": {y: int(lts[labels == y].min() - lts.min()) for y in LABELS},
        "wlts": {
            y: round(float(wlts[labels == y].min() - wlts.min()), 6) for y in LABELS
        },
    }
    if world is not None:
        record["true_world"] = codec.unwrap(needed[world])
    return record


def choose(scores_by_label, cutoff):
    return tuple(
        y for y in LABELS if cutoff is not None and scores_by_label[y] <= cutoff
    )


def outcome(labels, truth):
    if len(labels) == 1:
        return "correct" if labels[0] == truth else "wrong"
    return "ambiguous" if labels else "empty"


def replay_one(plan, measured, labels, actual, q, cutoffs, injected=None):
    accesses = {}
    sat_to_index = {p: i for i, p in enumerate(plan["satellites"])}

    def read(prn):
        if prn not in accesses:
            i = sat_to_index[prn]
            delta = injected[1] if injected is not None and injected[0] == i else 0
            accesses[prn] = measured[prn] + delta
        return accesses[prn]

    first = scores(plan, 3, read, labels)
    prefix = choose(first["cert"], q)
    last = scores(plan, 4, read, labels) if len(prefix) == 2 else None
    chosen = choose(last["cert"], q) if last is not None else prefix
    num_reads = len(accesses)
    saved = sorted(accesses)
    if last is None:
        last = scores(plan, 4, read, labels)
    four = choose(last["cert"], q)
    assert set(four).issubset(prefix)
    report = {
        PREFIX: outcome(chosen, actual),
        "cert3": outcome(prefix, actual),
        "cert4": outcome(four, actual),
    }
    for k, summary in ((3, first), (4, last)):
        for method in ("lts", "wlts"):
            report[method + str(k)] = outcome(
                choose(summary[method], cutoffs[method][k]), actual
            )
    for method in ("lts", "wlts"):
        report["same_" + method] = report[method + str(num_reads)]
    return {
        "decisions": report,
        "read_prns": saved,
        "injected": injected,
        "full_compatible": actual in four,
        "prefix_compatible": actual in prefix,
    }


def calibrate(records, epochs, catalog, labels):
    index = {c["fixture_row"]: j for j, c in enumerate(catalog)}
    draws = {k: [] for k in (3, 4)}
    for p in records:
        i = p["i"]
        measured = {
            x["sat"]: round(1000 * x["pseudorange"]) for x in epochs[i]["items"]
        }
        for k in draws:
            world = index[i]
            r = scores(p, k, measured.__getitem__, labels, world)
            r["truth"] = labels[world]
            draws[k].append(r)
    q = rank90([r["true_world"] for r in draws[4]])
    cutoffs = {
        m: {k: rank90([r[m][r["truth"]] for r in draws[k]]) for k in draws}
        for m in ("lts", "wlts")
    }
    return q, cutoffs


def score_test(plans, epochs, reference, boundary, labels, q, cutoffs):
    cases, skipped = [], Counter()
    for p in plans:
        i = p["i"]
        epoch = epochs[i]
        position = reference.get(epoch["utc_ms"])
        if position is None:
            skipped["reference_missing"] += 1
            continue
        if abs(epoch["measurement_utc_ms"] - epoch["utc_ms"]) > 10:
            skipped["timestamp"] += 1
            continue
        truth, distance = assign(position, boundary)
        if distance <= GUARD:
            skipped["guard"] += 1
            continue
        measured = {x["sat"]: round(1000 * x["pseudorange"]) for x in epoch["items"]}
        clean = replay_one(p, measured, labels, truth, q, cutoffs)
        changed = [
            replay_one(p, measured, labels, truth, q, cutoffs, (j, v))
            for j in range(4)
            for v in DOSES
        ]
        cases.append(
            {
                "i": i,
                "truth": truth,
                "near": distance * 111111 <= 60,
                "clean": clean,
                "fault": changed,
            }
        )
    return cases, dict(skipped)


def tally(cases, mode, only_near=False):
    out = {m: {y: Counter() for y in LABELS} for m in METHODS}
    for r in cases:
        if only_near and not r["near"]:
            continue
        records = [r["clean"]] if mode == "clean" else r["fault"]
        for answer in records:
            assert not (
                answer["full_compatible"] and answer["decisions"][PREFIX] == "wrong"
            )
            for m, decision in answer["decisions"].items():
                out[m][r["truth"]][decision] += 1
    return out


def summarize(cases):
    clean, fault = (tally(cases, mode) for mode in ("clean", "fault"))
    counts = Counter(r["truth"] for r in cases)

    def correct(scores, m):
        return sum(scores[m][y]["correct"] for y in LABELS)

    def wrong(scores, m):
        return sum(scores[m][y]["wrong"] for y in LABELS)

    def read_count(result, method):
        if method.endswith("3"):
            return 3
        if method.endswith("4"):
            return 4
        return len(result["read_prns"])

    comparisons = ("lts3", "wlts3", "lts4", "wlts4", "same_lts", "same_wlts")
    cost = {}
    for method in comparisons:
        subset = [
            r["clean"]
            for r in cases
            if r["clean"]["decisions"][PREFIX]
            == r["clean"]["decisions"][method]
            == "correct"
        ]
        cost[method] = {
            "common_correct": len(subset),
            "primary_total": sum(len(z["read_prns"]) for z in subset),
            "baseline_total": sum(read_count(z, method) for z in subset),
        }
    best4 = max(("lts4", "wlts4"), key=lambda m: (correct(clean, m), -wrong(clean, m)))
    shared = cost[best4]
    same = min(
        ("same_lts", "same_wlts"), key=lambda m: (wrong(fault, m), -correct(fault, m))
    )
    num_same_wrong = wrong(fault, same)
    fault_epochs_wrong = sum(
        any(z["decisions"][same] == "wrong" for z in r["fault"]) for r in cases
    )
    num_fault = sum(len(r["fault"]) for r in cases)
    clean_coverage = sum(r["clean"]["full_compatible"] for r in cases)
    fault_coverage = sum(z["full_compatible"] for r in cases for z in r["fault"])
    dominating = [
        m
        for m in comparisons
        if cost[m]["common_correct"]
        and cost[m]["baseline_total"] <= cost[m]["primary_total"]
        and all(
            clean[m][y]["correct"] >= clean[PREFIX][y]["correct"]
            and fault[m][y]["correct"] >= fault[PREFIX][y]["correct"]
            and clean[m][y]["wrong"] <= clean[PREFIX][y]["wrong"]
            and fault[m][y]["wrong"] <= fault[PREFIX][y]["wrong"]
            for y in LABELS
        )
    ]
    gate = {
        "each_class_count": all(counts[y] >= 12 for y in LABELS),
        "clean_class_80_percent": all(
            counts[y] and 5 * clean[PREFIX][y]["correct"] >= 4 * counts[y]
            for y in LABELS
        ),
        "clean_zero_wrong": wrong(clean, PREFIX) == 0,
        "clean_90_percent_of_fixed_four": all(
            10 * clean[PREFIX][y]["correct"]
            >= 9 * max(clean[m][y]["correct"] for m in ("lts4", "wlts4"))
            for y in LABELS
        ),
        "half_read_saved": shared["common_correct"] > 0
        and 2 * (shared["baseline_total"] - shared["primary_total"])
        >= shared["common_correct"],
        "fault_wrong_control_10_events_5_epochs": num_same_wrong >= 10
        and fault_epochs_wrong >= 5,
        "fault_halves_errors": 2 * wrong(fault, PREFIX) <= num_same_wrong,
        "fault_at_most_2_percent_errors": num_fault > 0
        and 50 * wrong(fault, PREFIX) <= num_fault,
        "fault_class_75_percent": all(
            counts[y]
            and 4 * fault[PREFIX][y]["correct"] >= 3 * len(DOSES) * 4 * counts[y]
            for y in LABELS
        ),
        "no_dominating_baseline": not dominating,
    }
    return {
        "counts": counts,
        "clean": clean,
        "fault": fault,
        "near_clean": tally(cases, "clean", True),
        "near_fault": tally(cases, "fault", True),
        "cost": cost,
        "clean_full_compatible": clean_coverage,
        "fault_full_compatible": fault_coverage,
        "num_injected": num_fault,
        "best_same_roster_fault_baseline": same,
        "baseline_fault_wrong_epochs": fault_epochs_wrong,
        "best_clean_fixed4": best4,
        "dominating_baselines": dominating,
        "gate_inputs": gate,
        "gate": all(gate.values()),
    }


def replay(train_root, test_root, manifest_path, target, output):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = read_json(target)
    assert (
        plan["source_manifest_sha256"] == sha256(manifest_path.read_bytes()).hexdigest()
    )
    train, _, _, _ = load_drive(train_root, manifest)
    test, reference, _, _ = load_drive(test_root, manifest)
    catalog = plan["catalog"]
    labels = np.array([c["label"] for c in catalog])
    q, cutoffs = calibrate(plan["records"]["calibration"], train, catalog, labels)
    cases, skipped = score_test(
        plan["records"]["heldout"],
        test,
        reference,
        Decimal(plan["boundary"]),
        labels,
        q,
        cutoffs,
    )
    result = summarize(cases)
    result.update(
        {
            "scope_excluded": skipped,
            "insufficient": {k: len(v) for k, v in plan["missing"].items()},
            "train_map": len(catalog),
            "calibrated": len(plan["records"]["calibration"]),
            "cutoff_radius2": None if q is None else [q.numerator, q.denominator],
            "loss_cutoffs": cutoffs,
            "plan_sha256": sha256(target.read_bytes()).hexdigest(),
        }
    )
    output.mkdir(parents=True, exist_ok=True)
    compressed(output / (STEM + "-rows.json.gz"), cases)
    (output / (STEM + "-result.json")).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return {
        k: result[k]
        for k in ("gate", "scope_excluded", "calibrated", "counts", "gate_inputs")
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command, extra in (("design", ("exe", "plan")), ("replay", ("plan", "output"))):
        s = sub.add_parser(command)
        for name in ("train", "test", "manifest", *extra):
            s.add_argument(name, type=Path)
    a = p.parse_args()
    result = (
        create_plan(a.train, a.test, a.exe, a.manifest, a.plan)
        if a.command == "design"
        else replay(a.train, a.test, a.manifest, a.plan, a.output)
    )
    print(json.dumps(result))
