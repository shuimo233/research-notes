"""Enumerate the implemented random draws and full probability tables exactly."""

from collections import defaultdict
from fractions import Fraction as F
from itertools import combinations, product
import json
from math import factorial, prod

from audit_runtime_multiworld_check import is_compatible
from audit_runtime_strata import draw_stratified, power_of_two_blocks, stratum_masses


class NeedChoice(Exception):
    pass


class ExactTape:
    """Replace uniform integer choices by a finite tape for enumeration."""

    def __init__(self, choices):
        self.choices = iter(choices)

    def randrange(self, n):
        a = next(self.choices, None)
        if a is None:
            raise NeedChoice(n)
        assert 0 <= a < n
        return a

    def shuffle(self, items):
        choice = self.randrange(factorial(len(items)))
        pending = list(items)
        for i in range(len(items)):
            index, choice = divmod(choice, factorial(len(pending) - 1))
            items[i] = pending.pop(index)


def assignment_law(blocks, weights, floor):
    result = defaultdict(F)
    live = [((), F(1))]
    while live:
        tape, p = live.pop()
        try:
            z = draw_stratified(blocks, weights, floor, ExactTape(tape))
        except NeedChoice as err:
            ways = err.args[0]
            live.extend((tape + (i,), p / ways) for i in range(ways))
        else:
            result[tuple(z)] += p
    assert sum(result.values()) == 1
    return dict(result)


def full_probability_law(route, rates):
    full = {}
    for event in product((0, 1), repeat=len(rates)):
        full[event] = sum(
            p
            * prod(
                rates[i][d] if f else 1 - rates[i][d]
                for i, (d, f) in enumerate(zip(modes, event, strict=True))
            )
            for modes, p in route.items()
        )
    assert sum(full.values()) == 1
    return full


def normalize(full, marginals, window):
    return sum(p for event, p in full.items() if all(event[i] for i in window)) / prod(
        marginals[i] for i in window
    )


def test(blocks, rates, weights, floor):
    for b in blocks:
        assert all(is_compatible(rates, i, j) for i, j in combinations(b, 2))
    for k in range(1, 5):
        prob = stratum_masses(weights, k)
        assert all(sum(q) == 1 for q in prob)
        assert tuple(sum(col) / k for col in zip(*prob, strict=True)) == weights
    law = assignment_law(blocks, weights, floor)
    width = len(rates[0])
    for i in range(width):
        assert (
            tuple(
                sum(p for x, p in law.items() if x[i] == j) for j in range(len(weights))
            )
            == weights
        )
    for b in power_of_two_blocks(blocks):
        for i, j in combinations(b, 2):
            for z, q in law.items():
                actual = list(z)
                actual[i], actual[j] = actual[j], actual[i]
                assert law[tuple(actual)] == q
    full = [full_probability_law(law, table) for table in rates]
    marginals = [
        tuple(sum(x * y for x, y in zip(row, weights, strict=True)) for row in table)
        for table in rates
    ]
    for f, r in zip(full, marginals, strict=True):
        for atom, p in f.items():
            assert p >= floor * prod(
                x if bit else 1 - x for bit, x in zip(atom, r, strict=True)
            )
    for depth in range(1, width + 1):
        for window in combinations(range(width), depth):
            obs = [
                normalize(f, r, window) for f, r in zip(full, marginals, strict=True)
            ]
            assert len(set(obs)) == 1
    return len(law), 2**width - 1


def tests():
    a = tuple(map(F, ("1/5", "4/5", "2/5")))
    b = tuple(map(F, ("1/2", "1/3", "3/4")))
    constant = (F(2, 5),) * 3
    weights = tuple(map(F, ("1/3", "1/6", "1/2")))
    ratios = ((a, b), (b, a), (tuple(x / 2 for x in a), b))
    scenarios = [
        ([[0, 1]], ratios, weights, F(1, 2)),
        (
            [[0, 1, 2, 3]],
            (
                (a, constant, constant, constant),
                (constant, b, constant, constant),
                (constant, constant, a, constant),
            ),
            weights,
            F(1, 2),
        ),
        (
            [[0, 1], [2, 3]],
            ((a, b, a, constant), (b, a, constant, b), (a, b, a, constant)),
            weights,
            F(1, 2),
        ),
        (
            [[0, 1, 2, 3, 4]],
            ((a, b, a, b, constant), (a, b, a, b, constant)),
            tuple(map(F, ("0", "1/2", "1/2"))),
            F(1, 2),
        ),
        ([[0, 1]], ratios, weights, F(0)),
    ]
    supported = 0
    checked = 0
    for fixture in scenarios:
        n, k = test(*fixture)
        supported += n
        checked += k
    # Equal mode marginals without exchangeability do not suffice for swapped profiles.
    cyclic = {(0, 1): F(1, 3), (1, 2): F(1, 3), (2, 0): F(1, 3)}
    uniform = (F(1, 3),) * 3
    base = [sum(row) / 3 for row in (a, b)]
    for i in range(2):
        assert (
            tuple(sum(v for z, v in cyclic.items() if z[i] == j) for j in range(3))
            == uniform
        )
    assert is_compatible(ratios, 0, 1)
    p = normalize(full_probability_law(cyclic, (a, b)), base, (0, 1))
    q = normalize(full_probability_law(cyclic, (b, a)), base, (0, 1))
    assert p != q
    return {
        "scenario_count": len(scenarios),
        "exact_joint_supports": supported,
        "windows_checked": checked,
        "asymmetric_coupling_lifts": [str(p), str(q)],
    }


if __name__ == "__main__":
    print(json.dumps(tests()))
