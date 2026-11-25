"""Diagnose limited map support with denser historical and oracle positions."""

import argparse
import json
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from statistics import median
import numpy as np
from gnss_prefix_verification import load_drive, assign
from gnss_clock_audit import ecef, predict
from gnss_quality_verification_check import intersect, unpack
from gnss_route_verification import GUARD


def compare(args):
    dest = args.output
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    _, train_truth, _, _ = load_drive(args.train, manifest)
    epochs, truth, nav, _ = load_drive(args.test, manifest)
    exe = args.exe
    plan = unpack(args.plan)
    rows = unpack(dest / "gnss-prefix-verification-rows.json.gz")
    report = json.loads((dest / "gnss-prefix-verification-result.json").read_text())
    cut = Decimal(plan["boundary"])
    radius = Fraction(*report["cutoff_radius2"])
    maps = {
        y: [
            ecef(p)
            for p in train_truth.values()
            if assign(p, cut)[0] == y and assign(p, cut)[1] > GUARD
        ]
        for y in ("south", "north")
    }
    by_id = {p["i"]: p for p in plan["records"]["heldout"]}
    near = []
    counts = Counter()
    for row in rows:
        i = row["i"]
        e = epochs[i]
        p = by_id[i]
        y = row["truth"]
        position = ecef(truth[e["utc_ms"]])
        kept = np.array([x["ecef_m"] for x in plan["catalog"] if x["label"] == y])
        near.append(float(np.linalg.norm(kept - np.asarray(position), axis=-1).min()))
        measured = {r["sat"]: round(1000 * r["pseudorange"]) for r in e["items"]}
        req = [
            (e["week"], e["tow"], s, where)
            for where in (position, *maps[y])
            for s in p["satellites"]
        ]
        pred = predict(exe, nav, req)
        n = np.array(
            [round(r["nominal"] * 1000) if r is not None else None for r in pred],
            dtype=object,
        ).reshape((-1, 4))
        available = np.array([all(v is not None for v in r) for r in n])
        assert available[0]
        actual = np.asarray([measured[s] for s in p["satellites"]])
        possible = np.zeros(len(available), dtype=bool)
        possible[available] = intersect(
            2 * (actual - n[available].astype(np.int64)),
            np.array(p["weights"]),
            radius,
            1,
        )
        counts["historical_dense_map"] += bool(possible[1:].any())
        counts["true_coordinate_oracle"] += bool(possible[0])
        counts["published_sparse_map"] += row["clean"]["full_compatible"]
        counts["dense_matches_while_oracle_misses"] += bool(
            possible[1:].any() and not possible[0]
        )
        counts["oracle_matches_while_dense_misses"] += bool(
            possible[0] and not possible[1:].any()
        )
    summary = {
        "post_hoc": True,
        "tested_epochs": len(rows),
        "same_label_training_points": {y: len(a) for y, a in maps.items()},
        "true_label_compatible": dict(counts),
        "distance_to_nearest_same_label_original_map_point_m": {
            "minimum": min(near),
            "median": median(near),
            "maximum": max(near),
            "within_15_m": sum(x <= 15 for x in near),
        },
    }
    (dest / "pe1-compatibility-posthoc.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("train", "test", "manifest", "exe", "plan", "output"):
        cli.add_argument(name, type=Path)
    print(json.dumps(compare(cli.parse_args())))
