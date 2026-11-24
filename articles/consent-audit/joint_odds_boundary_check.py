"""Compare bounded transport with direct pairwise LPs and exercise sealed publication."""

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction as F
import gzip
from itertools import permutations
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from unittest.mock import patch

from denial_odds_boundary_check import witness
from joint_odds import diagnose, semantics
from joint_odds_check import read_source
from joint_odds_inquiry import inspect, once
from joint_odds_run import feasible
from selection_protection_inquiry import checked


def direct(worlds, floor, ratio):
    from scipy.optimize import linprog

    variables = [
        (x, i, j) for x, (left, right) in enumerate(worlds) for i in left for j in right
    ]
    n = len(variables)
    eq, rhs = [], []
    for x, (u, v) in enumerate(worlds):
        for i, p in u.items():
            eq.append([int(a == x and b == i) for a, b, _ in variables])
            rhs.append(float(p))
        for j, p in v.items():
            eq.append([int(a == x and c == j) for a, _, c in variables])
            rhs.append(float(p))
    rows = []
    for i, j in floor:
        allowed = [k for k, (_, b, c) in enumerate(variables) if (b, c) == (i, j)]
        for left, right in permutations(allowed, 2):
            row = [0] * n
            row[left], row[right] = 1, -float(ratio)
            rows.append(row)
    verdict = linprog(
        [0] * n,
        A_eq=eq,
        b_eq=rhs,
        A_ub=rows or None,
        b_ub=[0] * len(rows) if rows else None,
        bounds=[(float(floor[i, j]), 1) for _, i, j in variables],
        method="highs",
    )
    if verdict.status not in (0, 2):
        raise ArithmeticError(verdict.message)
    return verdict.success


def binary(p):
    return {-1: 1 - p, 0: p}


def boundaries():
    from scipy import __version__

    assert __version__ == "1.16.3"
    abstention = [({-1: F(1)}, {-1: F(1)}), (binary(F(1, 2)), binary(F(1, 2)))]
    floor, marginal, product = semantics(abstention)
    assert marginal == 2 and product == 4
    assert feasible(abstention, floor, F(8, 3))["status"] == "feasible"
    assert feasible(abstention, floor, F(799, 300))["status"] == "infeasible"
    assert diagnose(abstention, floor, F(799, 300))["kind"] == "cell"

    swapped = [
        ({-1: F(1, 4), 0: F(3, 4)}, {-1: F(3, 4), 0: F(1, 4)}),
        ({-1: F(3, 4), 1: F(1, 4)}, {-1: F(1, 4), 1: F(3, 4)}),
    ]
    _, marginal, product = semantics(swapped)
    assert (marginal, product) == (3, 1)

    irrational = [
        (binary(F(a, 4)), binary(F(b, 4))) for a, b in ((1, 1), (1, 2), (3, 2))
    ]
    half, _, product = semantics(irrational)
    floor = {key: 2 * value for key, value in half.items()}
    low, high = F(4645, 1000), F(4646, 1000)
    assert (low - 2) ** 2 < 7 < (high - 2) ** 2 and product == 6
    assert feasible(irrational, floor, low)["status"] == "infeasible"
    assert feasible(irrational, floor, high)["status"] == "feasible"

    rng = Random(241124)
    cases = [
        (abstention, semantics(abstention)[0], F(8, 3)),
        (irrational, floor, low),
        (irrational, floor, high),
    ]
    for _ in range(20):
        worlds = []
        for _ in range(rng.randint(2, 5)):
            axes = []
            for _ in range(2):
                labels = [-1, *rng.sample(range(3), rng.randint(0, 3))]
                raw = [rng.randint(1, 8) for _ in labels]
                axes.append(
                    {i: F(w, sum(raw)) for i, w in zip(labels, raw, strict=True)}
                )
            worlds.append(tuple(axes))
        floor, marginal, product = semantics(worlds)
        cases.extend(
            (worlds, floor, r) for r in (marginal, product, (marginal + product) / 2)
        )
    for worlds, m, ratio in cases:
        cert = feasible(worlds, m, ratio)
        assert direct(worlds, m, ratio) is (cert["status"] == "feasible")
    return len(cases)


def operational(source_path, results_path):
    source = read_source(source_path)
    results = json.loads(gzip.decompress(results_path.read_bytes()))
    index = next(i for i, r in enumerate(results) if r["job"] == 250)
    packet, result = source[index], results[index]
    rows, status = inspect(packet, result, "midpoint")
    assert status["verified_joint_ratio"] == "6"
    infeasible, verdict = inspect(packet, result, "marginal")
    assert infeasible is None and verdict["verdict"] == "infeasible"
    catalogue = packet["catalogue"]
    authority, labels = checked(catalogue)
    masks = [0, *packet["patterns"]]
    both = next(
        mask
        for mask in masks
        if all(any(mask >> j & 1 for j in axis["labels"]) for axis in result["views"])
    )
    record = witness(authority, labels, both)
    together = (record, packet, result, rows, "midpoint")
    with TemporaryDirectory() as folder:
        base = Path(folder)
        sealed = base / "sealed.json"
        with patch("denial_odds.randbelow", side_effect=lambda n: n - 1):
            left = once(*together, 0, sealed)
        with patch(
            "denial_odds.randbelow", side_effect=AssertionError("redrew cached pair")
        ):
            right = once(*together, 1, sealed)
            assert once(*together, 0, sealed) == left
        assert left["outcome"] == right["outcome"] == "comparison"
        assert left["event"] != right["event"]
        assert all("pair" not in row for row in (left, right))
        assert left["policy"] == right["policy"]
        cache = json.loads(sealed.read_bytes())
        assert len(cache["pair"]) == 2

        forced = (witness(authority, labels, 0), packet, result, rows, "midpoint")
        with patch("denial_odds.randbelow", return_value=0):
            for side in (0, 1):
                x = once(*forced, side, base / "forced.json")
                y = once(*together, side, base / "voluntary.json")
                assert (
                    x == y
                    and set(x) == {"policy", "event", "outcome"}
                    and x["outcome"] == "withheld"
                )

        destination = base / "parallel.json"
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(
                pool.map(lambda i: once(*together, i % 2, destination), range(16))
            )
        assert values[::2] == [values[0]] * 8 and values[1::2] == [values[1]] * 8
        assert sorted(p.name for p in base.iterdir()) == [
            "forced.json",
            "parallel.json",
            "sealed.json",
            "voluntary.json",
        ]


if __name__ == "__main__":
    import sys

    if not __debug__:
        raise RuntimeError("enable assertions")
    print(f"verified {boundaries()} direct LP targets")
    operational(*(Path(x) for x in sys.argv[1:]))
    print(
        "verified separate publication views, pooled cache, indistinguishable refusal, and retries"
    )
