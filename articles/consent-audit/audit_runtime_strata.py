"""Exchangeable stratified scheduling within an already verified partition."""

from fractions import Fraction as F
from itertools import accumulate
from random import SystemRandom

from audit_runtime_partition import distribution, partition_indices, weighted_index


def power_of_two_blocks(blocks):
    partition_indices(blocks)
    result = []
    for block in blocks:
        todo = sorted(block)
        while todo:
            size = 1 << (len(todo).bit_length() - 1)
            result.append(todo[:size])
            todo = todo[size:]
    return result


def stratum_masses(weights, strata):
    """Each row describes a categorical draw conditioned on a uniform quantile stratum."""
    w = distribution(weights)
    if type(strata) is not int or strata < 1:
        raise ValueError("strata must be a positive integer")
    endpoints = (F(0), *accumulate(w))
    return tuple(
        tuple(
            strata * max(0, min(b, F(j + 1, strata)) - max(a, F(j, strata)))
            for a, b in zip(endpoints, endpoints[1:])
        )
        for j in range(strata)
    )


def draw_stratified(blocks, weights, independent_floor=F(1, 2), rng=None):
    """Assign mode indices. Weights are ordered by the configured floor."""
    groups = power_of_two_blocks(blocks)
    w = distribution(weights)
    floor = F(independent_floor)
    if not 0 <= floor <= 1:
        raise ValueError("expected an independent fraction in [0,1]")
    rng = SystemRandom() if rng is None else rng
    count = sum(map(len, groups))
    if rng.randrange(floor.denominator) < floor.numerator:
        return [weighted_index(w, rng) for _ in range(count)]
    assigned = [None] * count
    for block in groups:
        strata = min(4, len(block))
        draws = []
        for row in stratum_masses(w, strata):
            draws.extend([weighted_index(row, rng)] * (len(block) // strata))
        rng.shuffle(draws)
        for i, mode in zip(block, draws, strict=True):
            assigned[i] = mode
    return assigned


def balanced_strata(blocks, rng):
    """Enumerate eight balanced replay batches for the declared eight equal modes."""
    groups = power_of_two_blocks(blocks)
    n = sum(map(len, groups))
    aligned = [[None] * n for _ in range(8)]
    for block in groups:
        positions = rng.sample(block, len(block))
        s = min(4, len(block))
        inner = 8 // s
        repeat = len(block) // s
        compatible = []
        for shift in range(s):
            choices = [
                rng.sample(range(i * inner, (i + 1) * inner), inner) for i in range(s)
            ]
            for ordinal in range(inner):
                compatible.append(
                    [
                        choices[(j // repeat + shift) % s][ordinal]
                        for j in range(len(block))
                    ]
                )
        rng.shuffle(compatible)
        for row, selection in zip(aligned, compatible, strict=True):
            for i, mode in zip(positions, selection, strict=True):
                row[i] = mode
    return aligned
