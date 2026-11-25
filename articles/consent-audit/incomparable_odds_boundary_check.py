"""Verify that each ambiguous window can carry the only large compatible-evidence ratio."""

from fractions import Fraction as F
from itertools import permutations, product
import json
from math import comb, prod
from pathlib import Path
from random import Random
import subprocess
import sys
from tempfile import TemporaryDirectory

from incomparable_odds import WindowAudit, windows_for


def parity_world(n, window, nested, left):
    local = {0: F(1, 2), 2: F(1, 2)}
    if left:
        local = (
            {0: F(1, 2), 1: F(1, 4), 2: F(1, 4)} if nested else {0: F(1, 2), 1: F(1, 2)}
        )
    inside = [i for i in range(n) if window >> i & 1]
    outside = [i for i in range(n) if not window >> i & 1]
    row = {}
    for y in product(local, repeat=n):
        base = prod(local[v] for v in y)
        inner = prod(local[y[i]] for i in inside)
        parity = sum(y[i] != 0 for i in inside) % 2
        coupled = 0
        for u, p in local.items():
            if all(y[i] == u for i in outside):
                even = left and (u == 1 or not outside)
                coupled += 2 * p * inner * (parity != even)
        row[y] = (base + coupled) / 2
    assert sum(row.values()) == 1
    assert all(row[y] >= prod(local[v] for v in y) / 2 for y in row)
    for i in range(n):
        assert {a: sum(p for y, p in row.items() if y[i] == a) for a in local} == local
    return row


def independent_ratio(left, right, w):
    def aggregate(row):
        totals = {}
        for a, p in row.items():
            message = tuple(x for i, x in enumerate(a) if w >> i & 1)
            totals[message] = totals.get(message, 0) + p
        return totals

    p, q = aggregate(left), aggregate(right)
    return max([F(1), *(v / q[a] for a, v in p.items() if a in q)])


def parity_limits():
    total = 0
    for nested in (False, True):
        for n in range(2, 6):
            for hidden in range(1, 1 << n):
                if hidden.bit_count() < 2:
                    continue
                pair = [parity_world(n, hidden, nested, left) for left in (True, False)]
                audit = WindowAudit(pair)
                permitted = tuple(windows_for(*audit.support))
                assert len(permitted) == 2**n
                found, _, end = audit.directed(0, 1)
                expected = (
                    F(3) if hidden == (1 << n) - 1 else F(3, 2) if nested else F(2)
                )
                assert found == expected and end[0] == hidden
                for w in range(1 << n):
                    benchmark = independent_ratio(*pair, w)
                    assert benchmark == (expected if w == hidden else 1)
                    if not nested:
                        assert independent_ratio(*reversed(pair), w) == 1
                total += 1
    return total


def directed_capacity():
    cases = 0
    for w in (2, 3, 4, 6):
        x = F(1, 2 * (w - 1))
        mean = F(w, 2) / (1 - x)
        lo = mean.numerator // mean.denominator
        counts = {lo: 1 + lo - mean, lo + 1: mean - lo}
        for n in (w, w + 1):
            for gamma in (F(1, 3), F(1, 2), F(3, 4)):
                rows = []
                for left in (True, False):
                    out = {}
                    for values in product((0, 1), repeat=n):
                        j = sum(values[:w])
                        if left:
                            primary = (
                                (1 - x) * counts.get(j, 0) / comb(w, j) if j else x
                            )
                            probability_zero = 1 / (2 * (1 - x)) if j else F(0)
                        else:
                            primary = x if j == 1 else (1 - w * x if j == w else F(0))
                            probability_zero = 1 / (2 * w * x) if j == 1 else F(0)
                        if n > w:
                            primary *= (
                                (1 - probability_zero)
                                if values[-1]
                                else probability_zero
                            )
                        labels = values if left else tuple(2 * v for v in values)
                        out[labels] = gamma * F(1, 2**n) + (1 - gamma) * primary
                    assert sum(out.values()) == 1
                    assert all(p >= gamma / 2**n for p in out.values())
                    assert all(
                        sum(p for a, p in out.items() if a[i]) == F(1, 2)
                        for i in range(n)
                    )
                    rows.append(out)
                target = (1 << w) - 1
                ratio = 1 + (1 - gamma) / gamma * F(2 ** (w - 1), w - 1)
                assert all(
                    independent_ratio(*rows, M) == (ratio if M == target else 1)
                    for M in range(1 << n)
                )
                assert WindowAudit(rows).directed(0, 1)[0] == ratio
                cases += 1
    return cases


def randomized():
    rng = Random(20261125)
    local = [(0,), (1,), (0, 1), (0, 2), (0, 1, 2), (2, 3)]
    for _ in range(32):
        rows = []
        for _ in range(3):
            support = [rng.choice(local) for _ in range(4)]
            rows.append({s: rng.randint(1, 18) for s in product(*support)})
        audit = WindowAudit(rows)
        for i, j in permutations(range(3), 2):
            true = max(
                independent_ratio(
                    *[
                        {k: F(v, sum(rows[x].values())) for k, v in rows[x].items()}
                        for x in (i, j)
                    ],
                    w,
                )
                for w in range(16)
            )
            assert audit.directed(i, j)[0] == true
    malformed = ({(0, 0): F(1, 2), (1, 1): F(1, 2)},)
    try:
        WindowAudit(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError("expected a rejection of linked support")
    return 192


def cli():
    cases = [parity_world(3, 3, False, left) for left in (True, False)]
    serialized = {
        "worlds": [
            {
                "id": f"world-{i}",
                "outcomes": [{"labels": a, "weight": str(p)} for a, p in row.items()],
            }
            for i, row in enumerate(cases)
        ]
    }
    with TemporaryDirectory() as tmp:
        src = Path(tmp) / "example.json"
        src.write_text(json.dumps(serialized), encoding="utf-8")
        tool = str(Path(__file__).with_name("incomparable_odds.py"))
        args = [sys.executable, "-B", tool, str(src), "--limit", "3/2"]
        verdict = json.loads(subprocess.check_output(args))
        assert verdict["ratio"] == "2" and verdict["within_limit"] is False
        assert verdict["witness"] == {
            "numerator": "world-0",
            "denominator": "world-1",
            "positions": [0, 1],
            "labels": [0, 0],
        }
        backward = json.loads(
            subprocess.check_output(
                [
                    *args,
                    "--ordered-pair",
                    "world-1",
                    "world-0",
                ]
            )
        )
        assert backward["ratio"] == "1" and backward["within_limit"] is True
    return True


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(
                hidden_peak_examples=parity_limits(),
                arbitrary_pairs=randomized(),
                directed_sharp_examples=directed_capacity(),
                command_line=cli(),
            )
        )
    )
