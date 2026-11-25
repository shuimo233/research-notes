"""Check optimality by enumeration and full probability tables on varied inputs."""

from fractions import Fraction as F
from itertools import combinations, product
import json
from math import prod
from random import Random

from audit_runtime_partition import matching_partition
from audit_runtime_partition_check import check_partition, compatible


def set_partitions(n):
    if n == 0:
        yield ()
        return
    for a in set_partitions(n - 1):
        yield (*a, (n - 1,))
        for i, b in enumerate(a):
            yield (*a[:i], (*b, n - 1), *a[i + 1 :])


def atom_law(world, weights, blocks):
    result = {}
    for out in product((0, 1), repeat=len(world)):
        cells = []
        for block in blocks:
            cells.append(
                sum(
                    p * prod(world[i][j] if out[i] else 1 - world[i][j] for i in block)
                    for j, p in enumerate(weights)
                )
            )
        result[out] = prod(cells)
    assert sum(result.values()) == 1
    return result


def verify_parity(rates, weights, blocks):
    n = len(rates[0])
    singles = [(j,) for j in range(n)]
    laws = []
    for world in rates:
        baseline = atom_law(world, weights, singles)
        sharing = atom_law(world, weights, blocks)
        mixture = {atom: (baseline[atom] + sharing[atom]) / 2 for atom in baseline}
        assert sum(mixture.values()) == 1 and all(
            p >= baseline[k] / 2 for k, p in mixture.items()
        )
        laws.append((baseline, mixture))
    windows = 0
    for depth in range(1, n + 1):
        for subset in combinations(range(n), depth):
            lifts = []
            for pair in laws:
                a, b = [
                    sum(p for k, p in table.items() if all(k[j] for j in subset))
                    for table in pair
                ]
                if depth == 1:
                    assert a == b
                lifts.append(b / a)
            assert lifts[0] == lifts[1]
            windows += 1
    return windows


def tests():
    random = Random(1260)
    levels = tuple(map(F, ("1/10", "1/4", "2/5", "7/10", "9/10")))
    a = tuple(map(F, ("1/4", "1/8", "1/2")))
    b = tuple(map(F, ("1/10", "2/5", "3/5")))
    c = (F(1, 10),) * 3
    examples = [
        (
            (
                (a, b, c),
                (
                    tuple(x / 2 for x in b),
                    tuple(x * F(3, 2) for x in a),
                    tuple(x * 3 for x in c),
                ),
            ),
            1,
        ),
        (((a, b, c, a, b), (b, a, c, b, a)), 2),
        (((a, a, c, c, a, b), (c, c, a, b, a, b)), 3),
        ((((F(1, 2),),) * 4, ((F(1, 3),),) * 4), 1),
    ]
    for width, modes in product((2, 3, 4, 5, 6), (2, 3, 4)):
        for _ in range(8):
            rows = []
            for j in range(2):
                world = []
                for i in range(width):
                    if random.randrange(3) == 0:
                        v = (random.choice(levels),) * modes
                    elif j and random.randrange(4) == 0:
                        v = rows[0][i]
                    else:
                        v = tuple(random.choice(levels) for _ in range(modes))
                    world.append(v)
                rows.append(tuple(world))
            examples.append((tuple(rows), None))
    comparisons = 0
    for rates, known in examples:
        cert = matching_partition(rates)
        check_partition(rates, cert)
        width = len(rates[0])
        m = len(rates[0][0])
        forbidden = {
            (i, j)
            for i, j in combinations(range(width), 2)
            if not compatible(rates[0][i], rates[0][j], rates[1][i], rates[1][j])
        }
        lower = min(
            len(parts)
            for parts in set_partitions(width)
            if all(
                tuple(pair) not in forbidden
                for block in parts
                for pair in combinations(block, 2)
            )
        )
        assert len(cert["blocks"]) == lower
        if known is not None:
            assert lower == known
        for point in (
            tuple(F(1, m) for _ in range(m)),
            tuple(F(2 * (i + 1), m * (m + 1)) for i in range(m)),
        ):
            comparisons += verify_parity(rates, point, cert["blocks"])
    return {"enumerated_profiles": len(examples), "raw_window_checks": comparisons}


if __name__ == "__main__":
    print(json.dumps(tests()))
