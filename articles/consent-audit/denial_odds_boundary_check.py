"""Cross-check the optimum with raw per-pattern probability variables and exercise publication."""

from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import gzip
from itertools import permutations
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from unittest.mock import patch

from denial_odds import choose
from denial_odds_inquiry import inspect, once
from denial_odds_run import compare, solve
from selection_protection_inquiry import once as prior_once
from slack_certificate_check import potential


def direct_feasible(k, masks, service, ratio):
    from scipy.optimize import linprog

    outputs = {m: [-1, *(j for j in range(k) if m >> j & 1)] for m in [0, *masks]}
    variables = [(m, j) for m in outputs for j in outputs[m]]
    indices = {x: i for i, x in enumerate(variables)}
    width = len(variables)
    bounds = [
        (0, float(1 - service))
        if j == -1 and m
        else (1, 1)
        if j == -1
        else (float(Fraction(1, 2 * k)), 1)
        for m, j in variables
    ]
    equalities = [[int(m == candidate) for candidate, _ in variables] for m in outputs]
    inequalities = []
    for j in range(-1, k):
        supported = [m for m in outputs if (m, j) in indices]
        for left, right in permutations(supported, 2):
            row = [0] * width
            row[indices[left, j]] = 1
            row[indices[right, j]] = -float(ratio)
            inequalities.append(row)
    result = linprog(
        [0] * width,
        A_eq=equalities,
        b_eq=[1] * len(equalities),
        A_ub=inequalities,
        b_ub=[0] * len(inequalities),
        bounds=bounds,
        method="highs",
    )
    if result.status not in (0, 2):
        raise ArithmeticError(result.message)
    return result.success


def direct_suite():
    from scipy import __version__

    assert __version__ == "1.16.3"
    rng = Random(241124)
    sets = [(4, [1, 3, 4, 12]), (3, list(range(1, 8)))]
    for k in (2, 3, 4):
        for _ in range(8):
            masks = {1 << j for j in range(k)}
            masks.update(rng.sample(range(1, 1 << k), rng.randint(1, (1 << k) - 1)))
            sets.append((k, sorted(masks)))

    count = 0
    for k, masks in sets:
        for service in map(Fraction, ("1/4", "1/2", "3/4")):
            result = solve(k, masks, service)
            ratio = Fraction(result["ratio"])
            assert direct_feasible(k, masks, service, ratio)
            assert not direct_feasible(k, masks, service, ratio - Fraction(1, 10000))
            delta = max(m.bit_count() for m in masks)
            if all(1 << j in masks for j in range(k)):
                assert ratio == max(
                    1 / (1 - service),
                    1 / (1 - Fraction(delta, 2 * k)),
                    1 + delta * service,
                )
            count += 1

    service = Fraction(1, 4)
    k, masks = 4, [1, 3, 4, 12]
    result = solve(k, masks, service)
    baseline = compare(k, masks, service, result)
    assert Fraction(result["ratio"]) == Fraction(10, 7)
    assert Fraction(baseline["fixed_at_minimum"]["ratio"]) == 2
    assert baseline["constant_match"]["can_match"] is False
    # At constant rate c, the content ratio is c/(c-1/8).
    # At their unique crossing, c**2=1/8, between 0.3535 and 0.3536.
    low, high = Fraction(3535, 10000), Fraction(3536, 10000)
    assert low**2 < Fraction(1, 8) < high**2
    assert Fraction(1546, 1000) < 1 / (1 - low) < 1 / (1 - high) < Fraction(1548, 1000)

    service = Fraction(1, 2)
    k, masks = 3, list(range(1, 8))
    result = solve(k, masks, service)
    assert Fraction(result["ratio"]) == Fraction(5, 2)
    assert compare(k, masks, service, result)["fixed_at_minimum"]["ratio"] == "3"
    return count


def witness(authority, labels, mask):
    truth = [
        (v, u, -c) if mask >> j & 1 else (u, v, c - 1)
        for j, (u, v, c) in enumerate(labels)
    ]
    row = potential(authority.n, [*authority.original, *truth])
    return [x - row[0] for x in row]


def publication_suite(policies):
    source = json.loads(gzip.decompress(policies.read_bytes()))
    service = Fraction(1, 2)
    entry = source[0]
    authority, labels, weights, _ = inspect(entry, service)
    forced = witness(authority, labels, 0)
    released = witness(authority, labels, entry["patterns"][0])
    args = (entry["catalogue"], authority, labels, weights, service)
    exact = {-1: Fraction(1, 3), 0: Fraction(1, 2), 1: Fraction(1, 6)}
    for cursor, expected in enumerate((-1, -1, 0, 0, 0, 1)):
        with patch("denial_odds.randbelow", return_value=cursor) as sampler:
            assert choose(exact) == expected
            sampler.assert_called_once_with(6)

    with TemporaryDirectory() as folder:
        base = Path(folder)
        with patch("denial_odds.randbelow", return_value=0):
            a = once(forced, *args, base / "forced.json")
            b = once(released, *args, base / "voluntary.json")
            assert (
                a == b
                and set(a) == {"outcome", "policy"}
                and a["outcome"] == "withheld"
            )
            assert (base / "forced.json").read_bytes() == (
                base / "voluntary.json"
            ).read_bytes()
        with patch("denial_odds.randbelow", side_effect=lambda upper: upper - 1):
            successful = once(released, *args, base / "success.json")
            assert successful["outcome"] == "comparison"
        with patch("denial_odds.randbelow", side_effect=AssertionError("drew twice")):
            assert once(released, *args, base / "voluntary.json") == b
            assert once(released, *args, base / "success.json") == successful

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(once, released, *args, base / "concurrent.json")
                for _ in range(16)
            ]
            first, *rest = [task.result() for task in futures]
            assert all(row == first for row in rest)
        prior_args = (
            released,
            entry["catalogue"],
            authority,
            labels,
            "weighted",
            base / "old.json",
            weights,
        )
        assert prior_once(*prior_args) == prior_once(*prior_args)
        assert sorted(path.name for path in base.iterdir()) == [
            "concurrent.json",
            "forced.json",
            "old.json",
            "success.json",
            "voluntary.json",
        ]


if __name__ == "__main__":
    import sys

    if not __debug__:
        raise RuntimeError("enable assertions")
    print(f"verified {direct_suite()} direct LP boundaries")
    publication_suite(Path(sys.argv[1]))
    print(
        "verified exact sampler, indistinguishable refusal bytes, concurrent cache, and prior cache"
    )
