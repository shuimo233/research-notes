"""Compile the minimum number of blocks for exact robust refusal parity."""

from collections import defaultdict
from fractions import Fraction as F
from itertools import zip_longest
from math import lcm
from random import SystemRandom


def signature(row):
    """Positive rate vectors are identified up to scalar multiplication."""
    return tuple(v / row[0] for v in row) if min(row) != max(row) else ()


def matching_partition(rates):
    """Return a partition and a matching optimality clique on request indices."""
    tables = tuple(tuple(tuple(map(F, row)) for row in world) for world in rates)
    if len(tables) != 2 or not tables[0] or len(tables[0]) != len(tables[1]):
        raise ValueError("expected two worlds over the same nonempty request list")
    modes = len(tables[0][0])
    if not modes or any(
        len(row) != modes or any(not 0 < a < 1 for a in row)
        for world in tables
        for row in world
    ):
        raise ValueError(
            "expected common mode labels and positive interior refusal rates"
        )

    static, left, right, aligned = [], [], [], []
    switched = defaultdict(lambda: ([], []))
    for i, (a, b) in enumerate(zip(*tables, strict=True)):
        a, b = signature(a), signature(b)
        if not a and not b:
            static.append(i)
        elif not a:
            right.append(i)
        elif not b:
            left.append(i)
        elif a == b:
            aligned.append(i)
        else:
            switched[tuple(sorted((a, b)))][int(a > b)].append(i)

    blocks, clique = [], []

    def add_paired(x, y):
        for pair in zip_longest(x, y):
            blocks.append([i for i in pair if i is not None])
        clique.extend(x if len(x) >= len(y) else y)

    add_paired(left, right)
    if aligned:
        blocks.append(aligned)
        clique.append(aligned[0])
    for key in sorted(switched):
        add_paired(*switched[key])
    if blocks:
        blocks[0].extend(static)
    else:
        blocks.append(static)
        clique.append(static[0])
    return {"blocks": [sorted(b) for b in blocks], "clique": sorted(clique)}


def partition_indices(blocks):
    if not blocks or any(not block for block in blocks):
        raise ValueError("expected a nonempty partition")
    actual = [i for block in blocks for i in block]
    if any(type(i) is not int for i in actual) or sorted(actual) != list(
        range(len(actual))
    ):
        raise ValueError("partition must cover each request index once")
    return len(actual)


def distribution(weights):
    w = tuple(map(F, weights))
    if not w or min(w) < 0 or sum(w) != 1:
        raise ValueError("expected a valid distribution of original mode labels")
    return w


def weighted_index(weights, rng):
    denominator = lcm(*(p.denominator for p in weights))
    n = rng.randrange(denominator)
    for i, p in enumerate(weights):
        n -= p.numerator * (denominator // p.denominator)
        if n < 0:
            return i
    raise ArithmeticError("categorical mass does not sum to one")


def draw_modes(blocks, weights, independent_floor=F(1, 2), rng=None):
    """Draw route indices. Neither the actual world nor prior outcomes are inputs."""
    width = partition_indices(blocks)
    w = distribution(weights)
    floor = F(independent_floor)
    if not 0 <= floor <= 1:
        raise ValueError("expected an independent floor in [0, 1]")
    rng = SystemRandom() if rng is None else rng
    if rng.randrange(floor.denominator) < floor.numerator:
        blocks = [[i] for i in range(width)]
    result = [None] * width
    for block in blocks:
        mode = weighted_index(w, rng)
        for i in block:
            result[i] = mode
    return result


def mean_distinct(draws, weights):
    if type(draws) is not int or draws < 1:
        raise ValueError("expected at least one draw")
    return sum(1 - (1 - p) ** draws for p in distribution(weights))


def main():
    import argparse
    import json
    from pathlib import Path

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("contract", type=Path)
    args = cli.parse_args()
    data = json.loads(args.contract.read_text(encoding="utf-8"))
    print(json.dumps(matching_partition(data["rates"])))


if __name__ == "__main__":
    main()
