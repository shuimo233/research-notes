"""Independent interval and pair-loss replay of the locked PE1 experiment."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
from itertools import combinations
import json
from math import comb
from pathlib import Path

import numpy as np

from gnss_prefix_verification import load_drive
from gnss_quality_verification_check import intersect, unpack, wgs84_xyz, winner_upper

LABELS = ("south", "north")
DOSES = (-20000, -10000, -5000, 5000, 10000, 20000)


def closest_keep(residual, weights):
    candidates = [
        max(
            Fraction(
                2 * abs(int(residual[a]) - int(residual[b])), weights[a] + weights[b]
            )
            for a, b in combinations(keep, 2)
        )
        for keep in combinations(range(len(weights)), len(weights) - 1)
    ]
    return min(candidates)


def rank(sample):
    ordered = sorted(sample)
    idx = (9 * len(ordered) + 18) // 10 - 1
    return ordered[idx] if idx < len(ordered) else None


def losses(residual, weights, label):
    subsets = list(combinations(range(residual.shape[1]), residual.shape[1] - 1))
    # The centered SSE multiplied by the survivor count equals pair scatter.
    plain = np.minimum.reduce(
        [
            sum(
                (residual[:, a] - residual[:, b]) ** 2 for a, b in combinations(keep, 2)
            )
            for keep in subsets
        ]
    )
    effective = [1.0 / (int(w) ** 2) for w in weights]
    weighted = np.minimum.reduce(
        [
            sum(
                (residual[:, a] - residual[:, b]).astype(float) ** 2
                * effective[a]
                * effective[b]
                for a, b in combinations(keep, 2)
            )
            / sum(effective[j] for j in keep)
            for keep in subsets
        ]
    ).round(6)
    return [
        {y: round(float(out[label == y].min() - out.min()), 6) for y in LABELS}
        for out in (plain, weighted)
    ]


def measured_residual(source, record):
    observed = {r["sat"]: round(1000 * r["pseudorange"]) for r in source["items"]}
    return np.array([observed[s] for s in record["satellites"]]) - np.asarray(
        record["nominal_mm"]
    )


def ten_second_choice(epochs, permit):
    first_time = epochs[0]["measurement_utc_ms"]
    bins = defaultdict(list)
    for i, item in enumerate(epochs):
        if permit(item["utc_ms"]):
            t = item["measurement_utc_ms"] - first_time
            bucket, offset = divmod(t, 10000)
            bins[bucket].append((abs(offset - 5000), t, i))
    return [min(bins[k])[2] for k in sorted(bins)]


def check_plan(plan, epochs_by_group, labels):
    lo = np.flatnonzero(labels == "south")
    hi = np.flatnonzero(labels == "north")
    a, b = np.repeat(lo, len(hi)), np.tile(hi, len(lo))
    certs = 0
    for group, entries in plan["records"].items():
        for p in entries:
            metadata = {
                r["sat"]: r["cn0"] for r in epochs_by_group[group][p["i"]]["items"]
            }
            sats, take = p["all_satellites"], p["indices"]
            assert sorted(set(sats)) == sats
            weights = np.asarray(
                [
                    round(1024 * 10 ** ((40 - sorted((15, metadata[s], 50))[1]) / 20))
                    for s in sats
                ],
                dtype=np.int64,
            )
            assert weights.tolist() == p["all_weights"]
            assert [sats[i] for i in take] == p["satellites"] and weights[
                take
            ].tolist() == p["weights"]
            table = np.asarray(p["all_nominal_mm"], dtype=np.int64)
            assert table[:, take].tolist() == p["nominal_mm"]
            diffs = table[b] - table[a]
            pair = np.flatnonzero((a == p["pair"][0]) & (b == p["pair"][1])).item()
            threshold = Fraction(*p["radius2"])
            assert intersect(
                diffs[pair : pair + 1, take], weights[take], threshold, 2
            ).item()
            assert not intersect(
                diffs[:, take], weights[take], threshold, 2, True
            ).any()
            checked = winner_upper(diffs, weights, tuple(take), pair, threshold)
            assert checked == comb(len(sats), 4) == p["search"]["options"]
            certs += checked
    return certs


def score(labels, truth):
    return (
        "ambiguous"
        if len(labels) > 1
        else "empty"
        if not labels
        else "correct"
        if labels[0] == truth
        else "wrong"
    )


def replay(case, test, plan, labels, q, cutoffs):
    res = measured_residual(test, plan)
    truth = case["truth"]
    assert case["fault"] and [tuple(r["injected"]) for r in case["fault"]] == [
        (j, d) for j in range(4) for d in DOSES
    ]
    assert case["clean"]["injected"] is None
    for r in (case["clean"], *case["fault"]):
        snapshot = res.copy()
        if r["injected"]:
            i, d = r["injected"]
            snapshot[:, i] += d
        verdict, fits = {}, {}
        for k in (3, 4):
            block = snapshot[:, :k]
            weight = np.asarray(plan["weights"][:k], dtype=np.int64)
            mask = intersect(2 * block, weight, q, 1)
            fits[k] = [y for y in LABELS if np.any(mask & (labels == y))]
            verdict[f"cert{k}"] = score(fits[k], truth)
            for tag, values in zip(
                ("lts", "wlts"), losses(block, weight, labels), strict=True
            ):
                chosen = [
                    y
                    for y in LABELS
                    if cutoffs[tag][str(k)] is not None
                    and values[y] <= cutoffs[tag][str(k)]
                ]
                verdict[tag + str(k)] = score(chosen, truth)
        assert set(fits[4]).issubset(fits[3])
        k = 4 if len(fits[3]) == 2 else 3
        assert r["read_prns"] == plan["satellites"][:k]
        verdict.update(
            {
                "conditional": verdict[f"cert{k}"],
                "same_lts": verdict[f"lts{k}"],
                "same_wlts": verdict[f"wlts{k}"],
            }
        )
        assert verdict == r["decisions"]
        assert r["full_compatible"] == (truth in fits[4])
        assert r["prefix_compatible"] == (truth in fits[3])


def verify(trainpath, testpath, manifest_path, design, ledger, result):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan, cases = map(unpack, (design, ledger))
    report = json.loads(result.read_text(encoding="utf-8"))
    assert (
        plan["source_manifest_sha256"] == sha256(manifest_path.read_bytes()).hexdigest()
    )
    assert report["plan_sha256"] == sha256(design.read_bytes()).hexdigest()
    train, train_truth, _, _ = load_drive(trainpath, manifest)
    test, truths, _, _ = load_drive(testpath, manifest)
    plan_labels = np.array([r["label"] for r in plan["catalog"]])
    n_rosters = check_plan(plan, {"calibration": train, "heldout": test}, plan_labels)
    row_by_id = {r["fixture_row"]: i for i, r in enumerate(plan["catalog"])}
    bounds, errs = [], defaultdict(list)
    for p in plan["records"]["calibration"]:
        i = row_by_id[p["i"]]
        res = measured_residual(train[p["i"]], p)
        bounds.append(closest_keep(res[i], p["weights"]))
        for k in (3, 4):
            pairs = losses(res[:, :k], p["weights"][:k], plan_labels)
            for m, vals in zip(("lts", "wlts"), pairs, strict=True):
                errs[m, str(k)].append(vals[plan_labels[i]])
    q = rank(bounds)
    assert q == Fraction(*report["cutoff_radius2"])
    cuts = report["loss_cutoffs"]
    assert all(rank(v) == cuts[m][k] for (m, k), v in errs.items())
    mapping = {p["i"]: p for p in plan["records"]["heldout"]}
    assert len(mapping) == len(cases) + sum(report["scope_excluded"].values())
    boundary = Decimal(plan["boundary"])
    assert (
        boundary
        == (
            min(Decimal(str(p[0])) for p in train_truth.values())
            + max(Decimal(str(p[0])) for p in train_truth.values())
        )
        / 2
    )
    floor = Decimal(15) / 111111
    near = Decimal(60) / 111111
    calibration_ids = ten_second_choice(
        train,
        lambda t: (
            t in train_truth and abs(Decimal(str(train_truth[t][0])) - boundary) > floor
        ),
    )
    assert [r["fixture_row"] for r in plan["catalog"]] == calibration_ids
    for map_row in plan["catalog"]:
        reference = train_truth[train[map_row["fixture_row"]]["utc_ms"]]
        assert map_row["label"] == LABELS[Decimal(str(reference[0])) > boundary]
        assert np.allclose(wgs84_xyz(reference), map_row["ecef_m"], rtol=0, atol=1e-7)
    assert sorted([*mapping, *plan["missing"]["heldout"]]) == ten_second_choice(
        test, lambda _: True
    )
    assert (
        sorted(
            [p["i"] for p in plan["records"]["calibration"]]
            + plan["missing"]["calibration"]
        )
        == calibration_ids
    )
    skipped = Counter()
    included = []
    for i in mapping:
        item = test[i]
        t = item["utc_ms"]
        if t not in truths:
            skipped["reference_missing"] += 1
        elif abs(item["measurement_utc_ms"] - t) > 10:
            skipped["timestamp"] += 1
        elif abs(Decimal(str(truths[t][0])) - boundary) <= floor:
            skipped["guard"] += 1
        else:
            included.append(i)
    assert included == [r["i"] for r in cases] and skipped == report["scope_excluded"]
    counts = Counter()
    all_results = defaultdict(Counter)
    compatibility = Counter()
    for r in cases:
        epoch = test[r["i"]]
        p = truths[epoch["utc_ms"]]
        lat = Decimal(str(p[0]))
        assert abs(lat - boundary) > floor
        assert (
            r["near"] == (abs(lat - boundary) <= near)
            and r["truth"] == LABELS[lat > boundary]
        )
        replay(r, epoch, mapping[r["i"]], plan_labels, q, cuts)
        counts[r["truth"]] += 1
        for mode, rs in (("clean", [r["clean"]]), ("fault", r["fault"])):
            for t in rs:
                compatibility[mode] += t["full_compatible"]
                for m, s in t["decisions"].items():
                    all_results[mode, m, r["truth"]][s] += 1
                    if r["near"]:
                        all_results["near_" + mode, m, r["truth"]][s] += 1
    assert counts == report["counts"]
    assert compatibility["clean"] == report["clean_full_compatible"]
    assert compatibility["fault"] == report["fault_full_compatible"]
    for m in ("clean", "fault", "near_clean", "near_fault"):
        for k, by_label in report[m].items():
            assert all(by_label[y] == all_results[m, k, y] for y in LABELS)
    assert report["gate"] == all(report["gate_inputs"].values())
    return {
        "verified_rosters": n_rosters,
        "reconstructed_cutoffs": q is not None,
        "clean": len(cases),
        "injected": sum(len(r["fault"]) for r in cases),
        "full_contract_clean": compatibility["clean"],
        "full_contract_injected": compatibility["fault"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("train", "test", "manifest", "design", "ledger", "result"):
        parser.add_argument(name, type=Path)
    print(json.dumps(verify(*vars(parser.parse_args()).values()), indent=2))
