"""Cross-check the sharp three-request frontier and the general release mechanism."""

import argparse
from fractions import Fraction as F
import gzip
from itertools import permutations
import json
from math import comb
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from multi_odds import (
    pair_cap_complete_cube,
    projected_probability,
    rounded_count,
    sample,
    window_bias_law,
)
from multi_odds_check import sample as read_archive, verify_negative, verify_policy
from multi_odds_inquiry import inspect, publish
from multi_odds_run import solve
from public_optimality_check import model
from slack_certificate_check import potential


def packed(policy):
    return [
        [str(p) for _, p in sorted(row.items())] for _, row in sorted(policy.items())
    ]


def permute(mask, order):
    return sum(1 << dest for i, dest in enumerate(order) if mask >> i & 1)


def frontier():
    selectors = [F(3), F(31, 10), F(13, 4), F(7, 2), F(4), F(10)]
    checked = []
    for bound in selectors:
        modes = list(range(8))
        optimal, policy = pair_cap_complete_cube(bound)
        pair = {w: bound for w in (3, 5, 6)}
        ratios = verify_policy(modes, packed(policy), optimal, pair)
        assert ratios[7] == optimal
        found = solve(modes, optimal, pair)
        assert found["status"] == "feasible"
        verify_policy(modes, found["rows"], optimal, pair)
        below = optimal - F(1, 1000)
        impossible = solve(modes, below, pair)
        assert impossible["status"] == "infeasible"
        verify_negative(modes, impossible["certificate"], below, pair)
        checked.append((str(bound), str(optimal)))
    assert pair_cap_complete_cube(F(3))[0] == F(5)
    optimal, policy = pair_cap_complete_cube(F(7, 2))
    assert optimal == F(32, 7)
    assert solve(list(range(8)), optimal - F(1, 1000), {})["status"] == "infeasible"
    policy[3] = {0: F(3, 10), 1: F(1, 5), 2: F(1, 5), 3: F(3, 10)}
    verify_policy(list(range(8)), packed(policy), F(5), {})
    orders = list(permutations(range(3)))
    sym = {
        state: {
            out: sum(
                policy[permute(state, order)][permute(out, order)] for order in orders
            )
            / 6
            for out in line
        }
        for state, line in policy.items()
    }
    assert sym != policy
    ratios = verify_policy(list(range(8)), packed(sym), F(5), {})
    assert all(
        sym[x][a] == sym[y][b]
        for x in sym
        for y in sym
        if x.bit_count() == y.bit_count()
        for a in sym[x]
        for b in sym[y]
        if a.bit_count() == b.bit_count()
    )
    assert ratios[7] <= F(5)
    return checked


def ratio_on_cube(n):
    q = {
        (t, h, a): projected_probability(t, h, a)
        for t in range(n + 1)
        for h in range(t + 1)
        for a in range(h + 1)
    }
    for t in range(n + 1):
        for h in range(t + 1):
            assert sum(comb(h, a) * q[t, h, a] for a in range(h + 1)) == 1
            if h:
                assert sum(
                    comb(h - 1, a - 1) * q[t, h, a] for a in range(1, h + 1)
                ) == F(1, 2)
            assert all(q[t, h, a] >= F(1, 2 ** (h + 1)) for a in range(h + 1))
            if h < t:
                assert all(
                    q[t, h, a] == q[t, h + 1, a] + q[t, h + 1, a + 1]
                    for a in range(h + 1)
                )
    largest = F(1)
    for size in range(1, n + 1):
        limits = [[None, None] for _ in range(size + 1)]
        for t in range(n + 1):
            for h in range(max(0, t - (n - size)), min(t, size) + 1):
                for a in range(h + 1):
                    p = q[t, h, a]
                    old, new = limits[a]
                    limits[a] = [
                        min(p, old) if old is not None else p,
                        max(p, new) if new is not None else p,
                    ]
        largest = max(largest, *(high / low for low, high in limits))
    assert F(3, 2) ** n / 2 <= largest <= 4 * F(3, 2) ** n
    return largest


def sampler():
    with patch("multi_odds.randbelow", side_effect=[0, 0, 1, 0]):
        assert sample(0b10101) == 0b10001
    with patch("multi_odds.randbelow", side_effect=[2, 1, 2, 0]):
        assert sample(0b10101) == 0b10000
    with (
        patch("multi_odds.randbelow", return_value=3),
        patch("multi_odds.SystemRandom") as rng,
    ):
        rng.return_value.sample.return_value = [2, 4]
        assert sample(0b10101) == 0b10100
        rng.return_value.sample.assert_called_once_with([0, 2, 4], 2)
    assert sum(v * p for v, p in rounded_count(4).items()) == F(8, 3)


def locked_pair_growth():
    values = []
    endpoint = {F(0): F(1, 5), F(1, 2): F(1, 2), F(5, 6): F(3, 10)}
    for cap, step in (
        (F(3), 0),
        (F(3), F(1, 1000)),
        (F(13, 4), F(1, 1000)),
        (F(7, 2), F(1, 1000)),
        (F(399, 100), F(1, 1000)),
        (F(4), F(1, 1000)),
    ):
        b = 4 / cap - F(1, 2) + step
        v = b / (1 + b)
        law = window_bias_law(cap, b) if step else endpoint
        assert min(law.values()) >= 0 and sum(law.values()) == 1
        assert sum(p * q for p, q in law.items()) == F(1, 2)
        if cap < 4:
            assert sum(p**2 * q for p, q in law.items()) == 1 / cap
        for k in (2, 4, 16, 64):
            ratios = [
                sum(q * p**a for p, q in law.items())
                / sum(q * p**a * (1 - p) ** (k - a) for p, q in law.items())
                for a in range(k + 1)
            ]
            if k == 2:
                assert max(ratios) <= cap
            if step:
                assert max(ratios) <= (1 + b) ** k / law[v]
            else:
                assert ratios[1] >= 2 ** (k - 1)
        values.append(str(1 + b))
    return values


def cache_replay(source, policies):
    rows = json.loads(gzip.decompress(policies.read_bytes()))
    index = next(
        i
        for i, r in enumerate(rows)
        if r["domain"] == "CI" and len(r.get("modes", [])) == 8
    )
    packet = list(read_archive(source, "CI"))[index]
    policy = rows[index]
    entry, status = inspect(packet, policy, "5", True)
    assert status["verdict"] == "feasible" and status["verified_odds"][7] == "5"
    n, _, _, _, base, _, _ = model(packet)
    raw = potential(n, [*base, *[(j, i, -c) for i, j, c in policy["labels"]]])
    actual = [value - raw[0] for value in raw]
    with TemporaryDirectory() as d:
        path = Path(d) / "one-release.json"
        with patch("multi_odds_inquiry.choose", return_value=0b101) as draw:
            left = publish(packet, policy, entry, actual, 0b011, path)
            right = publish(packet, policy, entry, actual, 0b110, path)
            whole = publish(packet, policy, entry, actual, 0b111, path)
            draw.assert_called_once()
        assert (left["policy"], right["policy"]) == (whole["policy"],) * 2
        assert left["replies"] == whole["replies"][:2]
        assert right["replies"] == whole["replies"][1:]
        assert [r["outcome"] for r in whole["replies"]] == [
            "comparison",
            "withheld",
            "comparison",
        ]
    return True


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public-ci", nargs=2, type=Path, metavar=("ARCHIVE", "POLICIES")
    )
    args = parser.parse_args()
    sampler()
    info = dict(
        frontier=frontier(),
        moment_constructions=locked_pair_growth(),
        mixed_release={
            n: dict(worst=str(r), independent=2**n, multiplier=float(r / 2**n))
            for n in (2, 3, 8, 16, 32, 64)
            if (r := ratio_on_cube(n))
        },
    )
    if args.public_ci:
        info["one_release_cache"] = cache_replay(*args.public_ci)
    print(json.dumps(info))
