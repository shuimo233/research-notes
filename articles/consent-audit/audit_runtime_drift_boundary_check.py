"""Cross-check regular and boundary cases of the runtime drift compiler."""

from fractions import Fraction as F
from itertools import product
import json
from pathlib import Path
from random import Random

from audit_runtime_drift import plan
from audit_runtime_drift_check import inputs, proof, windows


def raw_atoms(rates, weights):
    """Construct exact original laws before computing all-refusal probabilities."""
    result = []
    for world in rates:
        w = len(world)
        independent = {}
        sharing = {}
        for atom in product((0, 1), repeat=w):
            same_mode = [F(1)] * len(weights)
            stand_alone = F(1)
            for i, value in enumerate(atom):
                p = world[i] if value else tuple(1 - x for x in world[i])
                same_mode = [a * b for a, b in zip(same_mode, p, strict=True)]
                stand_alone *= sum(a * b for a, b in zip(weights, p, strict=True))
            independent[atom] = stand_alone
            sharing[atom] = sum(a * b for a, b in zip(weights, same_mode, strict=True))
        assert sum(independent.values()) == sum(sharing.values()) == 1
        result.append((independent, sharing))
    return result


def check_feasible(rates, weights, share, cap):
    laws = raw_atoms(rates, weights)
    for subset in windows(len(rates[0])):
        odds = []
        for independent, sharing in laws:
            a, b = (
                sum(m for row, m in v.items() if all(row[i] for i in subset))
                for v in (independent, sharing)
            )
            odds.append(((1 - share) * a + share * b) / a)
        assert max(odds) <= cap * min(odds)


def examples():
    lo, hi = F(1, 20), F(19, 20)
    half, purity = F(1, 2), F(1, 20)
    paired = (((lo, hi),) * 2, ((half, half),) * 2)
    toy = plan(paired, drift=1, resolution=F(1, 100000))
    _, extreme, _, a, b = proof(paired, toy, drift=1)
    assert extreme == F(1, 2) and a <= F(19, 1620) <= b and b - a <= F(1, 100000)
    check_feasible(paired, (1 - purity, purity), F(19, 1620), F(21, 20))

    exclusive = ((hi,) * 5 + (lo,) * 3, (lo,) * 5 + (hi,) * 3)
    near_uniform = (exclusive, ((lo,) * 8,) * 2)
    out = plan(near_uniform, resolution=F(1, 10000000))
    nominal, extreme, _, a, b = proof(near_uniform, out)
    assert nominal == F(217, 3645) and extreme == F(25519, 433755)
    assert a == b == F(100, 1701) < F(147, 2500) < extreme
    check_feasible(near_uniform, (F(1, 10),) * 5 + (F(1, 6),) * 3, a, F(21, 20))


def replay_actual(ledger, archive, spec):
    data = json.loads(spec.read_bytes())
    cfg = tuple(tuple(tuple(map(F, row)) for row in world) for world in data["rates"])
    record = next((k, r) for k, r in inputs(ledger, archive) if k[0] == 1044)
    assert record[1] == cfg
    result = plan(**data)
    center, tips, _, lo, hi = proof(cfg, result)
    assert center == F(1, 2) and tips == F(25625, 56133) and lo == hi == F(29575, 70227)
    u = tuple(map(F, result["witness"]["contamination"]))
    assert u == (0, 0, 0, 0, 0, F(11, 16), F(5, 16), 0)
    deployed = tuple(F(3, 32) + p / 4 for p in u)
    check_feasible(cfg, deployed, lo, F(21, 20))


def random_profiles():
    rng = Random(1044)
    checked = 0
    choices = (F(1, 10), F(1, 6), F(2, 3), F(9, 10))
    for w, m in product((2, 3, 4), (2, 3, 4)):
        for mode in range(3):
            rates = tuple(
                tuple(
                    tuple(rng.choice(choices) for _ in range(m))
                    if (j + i + mode) % 3
                    else (rng.choice(choices),) * m
                    for i in range(w)
                )
                for j in range(2)
            )
            p = [1 + int(i >= mode) for i in range(m)]
            p0 = tuple(F(i, sum(p)) for i in p)
            drift = (F(0), F(3, 10), F(1))[mode]
            cap = (F(1), F(7, 6), F(3, 2))[mode]
            report = plan(rates, p0, drift, cap, F(3, 5), F(1, 200), 8)
            _, _, _, safe, high = proof(rates, report, drift, cap, F(3, 5), p0, 8)
            assert safe <= high
            for j in range(m):
                compliance = list(p0)
                if j:
                    compliance = [F(int(i in (0, j)), 2) for i in range(m)]
                weights = tuple(
                    (1 - drift) * a + drift * b
                    for a, b in zip(p0, compliance, strict=True)
                )
                check_feasible(rates, weights, safe, cap)
                checked += 1
    return checked


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("ledger", "archive", "spec"):
        cli.add_argument(key, type=Path)
    arg = cli.parse_args()
    examples()
    replay_actual(arg.ledger, arg.archive, arg.spec)
    print(
        json.dumps({"aligned_examples": 3, "ungrouped_atom_checks": random_profiles()})
    )
