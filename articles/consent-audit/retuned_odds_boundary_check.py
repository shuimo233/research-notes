"""Test direct pairwise LP agreement, sharp product bounds, and practical release."""

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction as F
import gzip
from itertools import permutations
import json
from pathlib import Path
from random import Random
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from denial_odds import ratio_of
from denial_odds_boundary_check import witness
from joint_odds import semantics
from joint_odds_check import read_source
from joint_odds_inquiry import once
from retuned_odds import refusal_budget
from retuned_odds_check import read_published, reconstruct
from retuned_odds_inquiry import inspect
from retuned_odds_run import solve
from selection_odds_check import independent_patterns
from selection_protection_inquiry import checked


def direct(worlds, caps, thresholds, floors, ratio):
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix

    columns = [dict() for _ in worlds]
    variable_bounds = [(0, 1)]
    inequalities, limits = [], []
    equalities = []
    measures = [{}, {}, {}]

    def append(form, bound):
        inequalities.append(form)
        limits.append(float(bound))

    for mode, (left, right) in enumerate(worlds):
        coords = columns[mode]
        for i in left:
            for j in right:
                k = len(variable_bounds)
                coords[i, j] = k
                variable_bounds.append((float(floors[i, j]), 1))
                measures[2].setdefault((i, j), []).append({k: 1})
        equalities.append(dict.fromkeys(coords.values(), 1))
        for side, axis in enumerate((left, right)):
            for label, old in axis.items():
                indices = [k for cell, k in coords.items() if cell[side] == label]
                positive = dict.fromkeys(indices, 1)
                negative = dict.fromkeys(indices, -1)
                measures[side].setdefault(label, []).append(positive)
                append(positive | {0: -1}, old)
                append(negative | {0: -1}, -old)
                if label >= 0:
                    append(negative, -thresholds[side])
                elif len(axis) > 1:
                    append(positive, F(1, 2))

    for window, cap in zip(measures, (*caps, ratio), strict=True):
        for sightings in window.values():
            for x, y in permutations(sightings, 2):
                append(x | {j: -cap for j in y}, 0)

    def sparse(rows):
        first, second, values = [], [], []
        for i, row in enumerate(rows):
            for j, p in row.items():
                first.append(i)
                second.append(j)
                values.append(float(p))
        return coo_matrix(
            (values, (first, second)), shape=(len(rows), len(variable_bounds))
        ).tocsr()

    result = linprog(
        [1] + [0] * (len(variable_bounds) - 1),
        A_ub=sparse(inequalities),
        b_ub=limits,
        A_eq=sparse(equalities),
        b_eq=[1] * len(worlds),
        bounds=variable_bounds,
        method="highs",
    )
    if result.status == 2:
        return None
    if not result.success:
        raise ArithmeticError(result.message)
    return result.fun


def marginal(mask, n):
    ids = [i for i in range(n) if mask >> i & 1]
    if not ids:
        return {-1: F(1)}
    if len(ids) == 1:
        return {-1: F(1, 2), ids[0]: F(1, 2)}
    return {-1: F(2, len(ids) + 2), **{i: F(1, len(ids) + 2) for i in ids}}


def product_case(left, right):
    count = left + right
    pairs = [{"comparison": [0, i, 1]} for i in range(1, count + 1)]
    edges = [(0, i, 1) for i in range(1, count + 1)] + [
        (i, 0, 0) for i in range(1, count + 1)
    ]
    patterns = independent_patterns(count + 1, edges, pairs)
    assert patterns == list(range(1 << count))
    worlds = [
        (marginal(mask & ((1 << left) - 1), left), marginal(mask >> left, right))
        for mask in patterns
    ]
    floors, _, independent = semantics(worlds)
    caps = [ratio_of([row[side] for row in worlds]) for side in (0, 1)]
    expected = F((left + 2) * (right + 2), 4)
    assert independent == caps[0] * caps[1] == expected
    return worlds, caps, [F(1, 2 * left), F(1, 2 * right)], floors, expected


def boundaries():
    from scipy import __version__

    assert __version__ == "1.16.3"
    cases = []
    for left, right in ((2, 2), (2, 3), (3, 3), (3, 4)):
        worlds, caps, labels, floor, r = product_case(left, right)
        assert refusal_budget(worlds, caps, labels, floor, r) is None
        assert refusal_budget(worlds, caps, labels, floor, r - F(1, 100)) is not None
        yes, no = (
            solve(worlds, caps, labels, floor, r),
            solve(worlds, caps, labels, floor, r - F(1, 100)),
        )
        assert yes["drift"] == "0" and no["status"] == "infeasible"
        if left + right <= 6:
            cases.extend(
                [
                    (worlds, caps, labels, floor, r),
                    (worlds, caps, labels, floor, r - F(1, 100)),
                ]
            )
    rng = Random(241126)
    for n in range(18):
        supports = {(0, 0)}
        supports.update((rng.randrange(4), rng.randrange(4)) for _ in range(n % 8 + 2))
        worlds = [(marginal(x, 2), marginal(y, 2)) for x, y in sorted(supports)]
        floors, marginal_ratio, independent = semantics(worlds)
        caps = [ratio_of([world[axis] for world in worlds]) for axis in (0, 1)]
        cases.extend(
            [
                (worlds, caps, [F(1, 4)] * 2, floors, r)
                for r in {marginal_ratio, (marginal_ratio + independent) / 2}
            ]
        )
    for trial in cases:
        certified = solve(*trial)
        direct_value = direct(*trial)
        if certified["status"] == "infeasible":
            assert direct_value is None
        else:
            assert (
                direct_value is not None
                and abs(direct_value - float(F(certified["drift"]))) < 1e-8
            )
    return len(cases)


def operational(source, joint, policies):
    original = read_source(source)
    paired = read_published(joint)
    rows = json.loads(gzip.decompress(policies.read_bytes()))
    i = next(i for i, v in enumerate(rows) if v["job"] == 293)
    packet, prior, revised = original[i], paired[i], rows[i]
    accepted, status = inspect(packet, prior, revised, "midpoint")
    assert F(status["minimum_drift"]) == F(141, 2240)
    assert F(status["joint_ratio"]) == F(27, 7) < 4
    rejected, verdict = inspect(packet, prior, revised, "marginal")
    assert rejected is None and verdict["refusal_budget"]
    axes, caps, label_floor, pair_floor = reconstruct(prior)
    value = direct(axes, caps, label_floor, pair_floor, F(prior["midpoint"]))
    assert abs(value - float(F(status["minimum_drift"]))) < 1e-8
    authority, labels = checked(packet["catalogue"])
    mask = next(
        m
        for m in packet["patterns"]
        if all(any(m >> j & 1 for j in axis["labels"]) for axis in prior["views"])
    )
    record = witness(authority, labels, mask)
    operator = (record, packet, dict(prior, retuned=revised), accepted, "midpoint")
    with TemporaryDirectory() as directory:
        sealed = Path(directory) / "private.json"
        with patch("denial_odds.randbelow", side_effect=lambda n: n - 1):
            left = once(*operator, 0, sealed)
        with patch("denial_odds.randbelow", side_effect=AssertionError("new draw")):
            right = once(*operator, 1, sealed)
        assert left["outcome"] == right["outcome"] == "comparison"
        assert left["event"] != right["event"] and left["policy"] == right["policy"]
        assert "pair" not in left and "pair" not in right
        with ThreadPoolExecutor(max_workers=4) as pool:
            answers = list(
                pool.map(lambda side: once(*operator, side, sealed), [0, 1] * 4)
            )
        assert answers == [left, right] * 4


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(f"verified {boundaries()} direct LP targets and four sharp product families")
    operational(*map(Path, sys.argv[1:]))
    print("verified calibrated job 293 by direct LP and sealed publication")
