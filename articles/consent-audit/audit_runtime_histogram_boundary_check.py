"""Check width counts, worst-case work, and balanced matching by enumeration."""

from collections import Counter
from fractions import Fraction as F
from itertools import permutations
import json
from random import Random

from audit_runtime_histogram import (
    absence,
    draw_histogram,
    histogram_choices,
    optimize,
    profile,
    replay_histograms,
    shape_list,
)
from audit_runtime_histogram_check import avoided, proof


def check_math():
    rng = Random(7559)
    checks = 0
    extremes = 0
    for n in (1, 2, 3, 4, 5, 8):
        for _ in range(12):
            active = (n + 1) // 2
            h = tuple(int(i < active) * (1 + int(i < n - active)) for i in range(8))
            assert sum(h) == n
            floors = shape_list(h)
            lengths = tuple(rng.randrange(15, 50) for _ in range(n))
            all_placements = [
                tuple(max(a, b) for a, b in zip(lengths, z, strict=True))
                for z in sorted(set(permutations(floors)))
            ]
            targets = tuple(sorted(set(lengths) | set(floors)))
            maxima, missing = profile(lengths, (h,), targets)
            want = tuple(
                max(sum(v**p for v in row) for row in all_placements) for p in (1, 2)
            )
            assert maxima == want
            for v, t in zip(missing, targets, strict=True):
                actual = F(
                    sum(t not in row for row in all_placements), len(all_placements)
                )
                assert (
                    actual == v == absence(lengths, h, t) == avoided(lengths, floors, t)
                )
                checks += 1
            extremes += 2
    return checks, extremes


def check_runtime():
    base = ((16,) * 8,) * 3
    groups = [[0, 1, 2, 3, 4, 5, 6, 7]]
    p = optimize(base, groups)
    proof(base, groups, p)
    assert p["caps"] == [568, 54784] * 3
    assert F(p["residual_mean_widths"]) == F(7, 2)
    r = Random(597)
    checked = 0
    for layout in (
        [[0, 1, 2, 3, 4, 5, 6, 7]],
        [[0, 1, 2, 3], [4, 5], [6], [7]],
        [[0, 1], [2, 3], [4, 5], [6, 7]],
    ):
        for i in range(20):
            blocks = [
                {
                    "items": b,
                    "histograms": histogram_choices(len(b))[
                        i % len(histogram_choices(len(b)))
                    ],
                }
                for b in layout
            ]
            plan = {"blocks": blocks}
            z = replay_histograms(plan, r)
            assert all(set(a) == set(range(8)) for a in zip(*z, strict=True))
            for block in blocks:
                reference = Counter({h: 0 for h in block["histograms"]})
                for h in block["histograms"]:
                    reference[h] += 8 // len(block["histograms"])
                observed = Counter(
                    tuple(sum(row[j] == k for j in block["items"]) for k in range(8))
                    for row in z
                )
                assert reference == observed
                checked += 1
    for w in ((F(1, 3), F(2, 3)), (F(1),), (F(0), F(1))):
        for floor in (0, F(1, 2), 1):
            values = draw_histogram(p, w, floor, r)
            assert len(values) == 8 and all(w[i] > 0 for i in values)
    return checked, p


if __name__ == "__main__":
    a, b = check_math()
    c, d = check_runtime()
    print(
        json.dumps(
            {
                "absence_checks": a,
                "maxima_checks": b,
                "balanced_blocks": c,
                "example_residual_mean": d["residual_mean_widths"],
            }
        )
    )
