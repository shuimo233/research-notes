"""Independently enumerate the measured UWB calibration and purchase claims."""

import argparse
from collections import Counter
from decimal import Decimal
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import isqrt
from pathlib import Path
from re import fullmatch

E = 600  # All contract intervals are in half-millimeter units.
PILOT = "12.21_4.95_1.32"


def middle(numbers):
    vals = sorted(numbers)
    k = len(vals) // 2
    return vals[k] if len(vals) % 2 else (vals[k - 1] + vals[k]) / 2


def geometry(anchor, tag):
    sum_sq = sum(
        (int(1000 * Decimal(a)) - int(1000 * Decimal(b))) ** 2
        for a, b in zip(anchor, tag, strict=True)
    )
    root = isqrt(sum_sq)
    return root + (4 * sum_sq > (2 * root + 1) ** 2)


def surviving(values, k):
    for omit in range(min(k, len(values)) + 1):
        yield from combinations(values, len(values) - omit)


def interval_low(sample, bound):
    return max([bound[0], *(lo for lo, _ in sample)])


def interval_high(sample, bound):
    return min([bound[1], *(hi for _, hi in sample)])


def overlaps(sample, bound):
    return interval_low(sample, bound) <= interval_high(sample, bound)


def one_offset(intervals, bound, failures, separate=False):
    if separate:
        return (
            sum(not overlaps([interval], bound) for interval in intervals) <= failures
        )
    return any(overlaps(left, bound) for left in surviving(tuple(intervals), failures))


def fit(values):
    intervals = []
    for keep in combinations(values, len(values) - 1):
        a, b = min(keep), max(keep)
        intervals.append((b - a, abs(a + b), a + b))
    width, _, center = min(intervals)
    return width, center


def observations(fixture, result, name):
    path = fixture["reference_path"]
    assert len(path) == len(set(path)) == fixture["path_size"]
    expected = set()
    for parity, side in ((0, "calibration"), (1, "heldout")):
        ordered = sorted(
            (sha256(f"uwb-offset-v1/{name}/{folder}".encode()).hexdigest(), i, folder)
            for i, folder in enumerate(path)
            if i // 5 % 2 == parity and not (name == "environment2" and folder == PILOT)
        )
        expected.update((i, folder, side) for _, i, folder in ordered[:20])
    assert expected == {(s["rank"], s["folder"], s["split"]) for s in fixture["sites"]}
    correct = (
        ("A1", "A2", "A3", "A4", "A5", "A7", "A8")
        if name == "environment2"
        else tuple(sorted(fixture["anchors_m"]))
    )
    assert tuple(result["anchors"]) == correct
    coordinates = fixture["anchors_m"]
    cases = {}
    omitted = 0
    for s in fixture["sites"]:
        source = s["anchors"]
        if any(a not in source or not source[a]["range_m"] for a in correct):
            omitted += 1
            continue
        assert tuple(map(Decimal, s["folder"].split("_"))) == tuple(
            map(Decimal, s["position_m"])
        )
        xx = int(1000 * Decimal(s["position_m"][0]))
        ref = {a: geometry(v, s["position_m"]) for a, v in coordinates.items()}
        observed = {
            a: round(middle([1000 * Fraction(v) for v in data["range_m"]]))
            for a, data in source.items()
            if data["range_m"]
        }
        delta = {a: observed[a] - ref[a] for a in observed}
        expect = result["positions"][s["folder"]]
        assert expect["residual_mm"] == delta and expect["split"] == s["split"]
        assert expect["rank"] == s["rank"]
        assert expect["all_los"] == all(source[a]["los"] == ["LOS"] for a in correct)
        raw = {}
        for field, references in (
            ("tag", {a: s["position_m"] for a in correct}),
            ("anchor", coordinates),
        ):
            raw[field] = sum(
                any(
                    tuple(map(Decimal, coordinate))
                    != tuple(map(Decimal, references[a]))
                    for coordinate in source[a][f"raw_{field}_m"]
                )
                for a in correct
            )
        assert expect["raw_tag_disagreements"] == raw["tag"]
        assert expect["raw_anchor_disagreements"] == raw["anchor"]
        for a, metadata in source.items():
            assert (
                metadata["member"]
                == f"data_set/raw_data/{name}/data/{s['folder']}/ch1_{a}.csv"
            )
            assert fullmatch("[0-9a-f]{8}", metadata["crc32"])
            assert fullmatch("[0-9a-f]{64}", metadata["sha256"])
        cases[s["folder"]] = (s["split"], xx, observed, ref, delta)
    assert len(cases) == len(result["positions"]) and omitted == result["data_excluded"]
    assert result["raw_path_size"] == len(path)
    return correct, cases


def evaluate_fits(result, sites, anchors):
    calib = [delta for side, _, _, _, delta in sites.values() if side == "calibration"]
    intercepts = {a: round(middle([Fraction(r[a]) for r in calib])) for a in anchors}
    assert intercepts == result["calibrated_anchor_bias_mm"]
    offsets = result["offset_2mm"]
    assert offsets["A"] == [0, 0]
    for kind in ("H", "AH"):
        center = [
            fit([r[a] - (intercepts[a] if kind == "AH" else 0) for a in anchors])[1]
            for r in calib
        ]
        assert offsets[kind] == [min(center) - 100, max(center) + 100]
    checked, witnesses = 0, 0
    counts = Counter()
    for folder, (side, _, _, _, delta) in sites.items():
        for kind, bound in offsets.items():
            current = {
                a: delta[a] - (intercepts[a] if kind != "H" else 0) for a in anchors
            }
            residuals = {a: [2 * x - E, 2 * x + E] for a, x in current.items()}
            expected = result["positions"][folder]["metrics"][kind]
            good = one_offset(residuals.values(), bound, 1)
            assert good == expected["conforms"]
            assert fit(tuple(current.values()))[0] == expected["unbounded_required_2mm"]
            checked += 1
            counts[side, kind] += good
            if not good:
                local = expected["witness_intervals_2mm"]
                assert 2 <= len(local) <= 4
                assert all(interval == residuals[a] for a, interval in local.items())
                assert not one_offset(local.values(), bound, 1)
                witnesses += 1
    for side in ("calibration", "heldout"):
        sample = [row for row in result["positions"].values() if row["split"] == side]
        assert len(sample) == result["counts"][side]["positions"]
        assert (
            sum(row["all_los"] for row in sample) == result["counts"][side]["all_los"]
        )
        for kind in offsets:
            assert counts[side, kind] == result["counts"][side]["conforms"][kind]
        for kind in ("H", "AH"):
            widths = [
                Fraction(row["metrics"][kind]["unbounded_required_2mm"])
                for row in sample
            ]
            assert (
                middle(widths)
                == result["counts"][side]["unbounded_median_required_2mm"][kind]
            )
    assert result["heldout_gates"] == {k: counts["heldout", k] >= 18 for k in offsets}
    return intercepts, checked, witnesses


def verify_purchase(result, sites, anchors, intercepts):
    target = result["procurement"]
    high_level = int(2 * middle([Fraction(x) for _, x, *_ in sites.values()]))
    assert target["threshold_2mm"] == high_level
    allowed = {
        k: data for k, data in sites.items() if abs(2 * data[1] - high_level) > 1000
    }
    truth = {k: 2 * r[1] > high_level for k, r in allowed.items()}
    if len(set(truth.values())) != 2:
        assert "skipped" in target
        return 0, 0
    assert target["candidates"] == len(allowed)
    bounds = result["offset_2mm"]["AH"]
    delta = bounds[0] - bounds[1], bounds[1] - bounds[0]
    columns = {
        k: [2 * (r[3][a] + intercepts[a]) for a in anchors] for k, r in allowed.items()
    }
    pairs = [
        {
            a: [x - y - 2 * E, x - y + 2 * E]
            for a, x, y in zip(anchors, columns[b], columns[c], strict=True)
        }
        for b, c in combinations(allowed, 2)
        if truth[b] != truth[c]
    ]
    portfolios, replay = 0, 0
    for method in ("shared", "marginal"):
        rec = target[method]
        marginal = method == "marginal"
        winners = []
        for size in range(len(anchors) + 1):
            for proposal in combinations(anchors, size):
                portfolios += 1
                if not any(
                    one_offset([row[a] for a in proposal], delta, 2, marginal)
                    for row in pairs
                ):
                    winners.append(proposal)
            if winners:
                break
        if not winners:
            assert rec["queries"] is None
            a, b, offsets, reply, fa, fb = rec["proof"]
            keys = list(allowed)
            assert truth[keys[a]] != truth[keys[b]]
            assert len(reply) == len(anchors) == len(offsets)
            if not marginal:
                assert len(set(map(tuple, offsets))) == 1
            failures = [0, 0]
            for i, ((v,), (x, y)) in enumerate(zip(reply, offsets, strict=True)):
                assert bounds[0] <= x <= bounds[1] and bounds[0] <= y <= bounds[1]
                for j, (world, offset) in enumerate(((a, x), (b, y))):
                    if abs(v - columns[keys[world]][i] - offset) > E:
                        failures[j] |= 1 << i
            assert failures == [fa, fb] and all(x.bit_count() <= 1 for x in failures)
            continue
        selected = tuple(rec["anchors"])
        assert selected in winners and rec["queries"] == len(selected)
        take = [anchors.index(a) for a in selected]
        total = Counter()
        assert rec["tests"].keys() == {
            key for key, row in allowed.items() if row[0] == "heldout"
        }
        for key, (side, _, read, _, _) in allowed.items():
            if side != "heldout":
                continue
            labels = set()
            for k, expected in columns.items():
                centered = [2 * read[anchors[i]] - expected[i] for i in take]
                intervals = [(v - E, v + E) for v in centered]
                if one_offset(intervals, bounds, 1, marginal):
                    labels.add(truth[k])
            assert rec["tests"][key]["labels"] == sorted(labels)
            state = (
                "correct"
                if labels == {truth[key]}
                else "wrong"
                if len(labels) == 1
                else "abstain"
            )
            assert rec["tests"][key]["state"] == state
            total[state] += 1
            replay += 1
        assert total == rec["replay"]
    shared, marginal = target["shared"], target["marginal"]
    assert target["gate"] == (
        result["heldout_gates"]["AH"]
        and shared["queries"] is not None
        and marginal["queries"] is not None
        and marginal["queries"] > shared["queries"]
        and shared["replay"].get("wrong", 0) == 0
        and shared["replay"].get("correct", 0) >= 12
    )
    return portfolios, replay


def audit(fixture, results):
    output = {}
    for name, source in fixture["environments"].items():
        result = results["results"][name]
        anchors, sites = observations(source, result, name)
        offsets, fits, witnesses = evaluate_fits(result, sites, anchors)
        if name == "environment2":
            raw = [
                abs(delta["A6"])
                for _, _, _, _, delta in sites.values()
                if "A6" in delta
            ]
            assert result["recorded_environment2_A6_fault"] == {
                "positions_with_data": len(raw),
                "absolute_median_mm": middle([Fraction(x) for x in raw]),
                "above_300mm": sum(x > 300 for x in raw),
            }
        portfolios, labels = verify_purchase(result, sites, anchors, offsets)
        output[name] = {
            "verified_position_contracts": fits,
            "verified_rejection_witnesses": witnesses,
            "verified_purchase_subsets": portfolios,
            "verified_observed_decisions": labels,
        }
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("observations", type=Path)
    p.add_argument("results", type=Path)
    args = p.parse_args()
    raw = args.observations.read_bytes()
    data = json.loads(gzip.decompress(raw))
    results = json.loads(args.results.read_bytes())
    assert results["observations_sha256"] == sha256(raw).hexdigest()
    print(json.dumps(audit(data, results)))
