"""Optimize exchangeable width histograms with exact normal-load caps."""

from fractions import Fraction as F
from functools import cache
from itertools import product
from math import comb, prod
from random import SystemRandom

from audit_runtime_latency_check import MODES
from audit_runtime_latency_load import quantile, work_distribution
from audit_runtime_partition import distribution, partition_indices, weighted_index
from audit_runtime_strata import power_of_two_blocks, stratum_masses

WEIGHTS = tuple((mode, F(1, 8)) for mode in MODES)


@cache
def histogram_choices(n):
    if n == 1:
        return (tuple(tuple(int(i == j) for i in range(8)) for j in range(8)),)
    if n == 2:
        return (tuple(tuple(int(i in (j, 7 - j)) for i in range(8)) for j in range(4)),)
    if n not in (4, 8):
        raise ValueError("unsupported group width")
    total = n // 4
    output = []
    for h in product(range(total + 1), repeat=8):
        if sum(h) == n:
            other = tuple(total - v for v in h)
            if h <= other:
                output.append((h, other))
    return tuple(output)


def shape_list(hist):
    return tuple(w for w, k in zip(MODES, hist, strict=True) for _ in range(k))


def absence(lengths, hist, t):
    b = lengths.count(t)
    c = sum(x > t for x in lengths)
    e = sum(h for w, h in zip(MODES, hist, strict=True) if w == t)
    h = sum(v for w, v in zip(MODES, hist, strict=True) if w > t)
    n = len(lengths)
    if b > h or e > c:
        return F(0)
    return F(comb(h, b), comb(n, b)) * F(comb(c, e), comb(n - b, e))


@cache
def profile(lengths, choices, targets):
    bounds = [0, 0]
    fixed = sorted(lengths)
    for h in choices:
        widest = tuple(
            max(x, y) for x, y in zip(fixed, reversed(shape_list(h)), strict=True)
        )
        bounds = [max(bounds[p - 1], sum(w**p for w in widest)) for p in (1, 2)]
    missing = tuple(
        sum(absence(lengths, h, t) for h in choices) / len(choices) for t in targets
    )
    return tuple(bounds), missing


def optimize(world_lengths, blocks):
    groups = power_of_two_blocks(blocks)
    n = partition_indices(groups)
    if n != 8 or len(world_lengths) != 3 or any(len(w) != n for w in world_lengths):
        raise ValueError(
            "this optimizer expects eight requests in three declared worlds"
        )
    solo = tuple((i,) for i in range(n))
    caps = tuple(
        quantile(work_distribution(lengths, solo, WEIGHTS, p), F(9, 10))
        for lengths in world_lengths
        for p in (1, 2)
    )
    targets = tuple(
        tuple(sorted(set(lengths) | set(MODES))) for lengths in world_lengths
    )
    candidates = []
    for b in groups:
        options = []
        for h in histogram_choices(len(b)):
            records = tuple(
                profile(tuple(v[i] for i in b), h, t)
                for v, t in zip(world_lengths, targets, strict=True)
            )
            limits = tuple(z for q, _ in records for z in q)
            options.append((h, limits, tuple(m for _, m in records)))
        candidates.append(options)
    best = None
    for row in product(*candidates):
        loads = tuple(sum(r[1][j] for r in row) for j in range(len(caps)))
        if any(x > budget for x, budget in zip(loads, caps, strict=True)):
            continue
        cost = sum(
            1 - prod(r[2][w][j] for r in row)
            for w in range(len(world_lengths))
            for j in range(len(targets[w]))
        ) / len(world_lengths)
        choices = tuple(r[0] for r in row)
        item = cost, choices, loads
        if best is None or item < best:
            best = item
    if best is None:
        return {
            "caps": list(caps),
            "maxima": None,
            "residual_mean_widths": None,
            "blocks": [],
        }
    cost, choices, loads = best
    return {
        "caps": list(caps),
        "maxima": list(loads),
        "residual_mean_widths": str(cost),
        "blocks": [
            {"items": b, "histograms": [list(h) for h in g]}
            for b, g in zip(groups, choices, strict=True)
        ],
    }


def draw_histogram(plan, weights, independent_floor=F(1, 2), rng=None):
    """Draw physical modes from an already verified eight-request plan."""
    rng = SystemRandom() if rng is None else rng
    w = distribution(weights)
    floor = F(independent_floor)
    if not 0 <= floor <= 1:
        raise ValueError("expected independent probability in [0,1]")
    if not plan["blocks"] or rng.randrange(floor.denominator) < floor.numerator:
        return [weighted_index(w, rng) for _ in range(8)]
    strata = stratum_masses(w, 8)
    values = [None] * 8
    for block in plan["blocks"]:
        group = block["items"]
        h = rng.choice(block["histograms"])
        modes = []
        for rank, count in enumerate(h):
            if count:
                modes.extend([weighted_index(strata[rank], rng)] * count)
        rng.shuffle(modes)
        for i, m in zip(group, modes, strict=True):
            values[i] = m
    return values


def perfect_match(remaining, rng):
    """A perfect matching from each eight-round regular residual multigraph."""
    matched = {}
    order = [rng.sample(range(8), 8) for _ in range(8)]

    def add(batch, seen):
        for mode in order[batch]:
            if remaining[batch][mode] > 0 and mode not in seen:
                seen.add(mode)
                if mode not in matched or add(matched[mode], seen):
                    matched[mode] = batch
                    return True
        return False

    for batch in rng.sample(range(8), 8):
        if not add(batch, set()):
            raise ArithmeticError("no matching in a regular bipartite graph")
    return {batch: mode for mode, batch in matched.items()}


def replay_histograms(plan, rng):
    if not plan["blocks"]:
        return list(
            map(list, zip(*(rng.sample(range(8), 8) for _ in range(8)), strict=True))
        )
    result = [[None] * 8 for _ in range(8)]
    for block in plan["blocks"]:
        hs = block["histograms"]
        remaining = [list(h) for h in hs for _ in range(8 // len(hs))]
        rng.shuffle(remaining)
        for i in rng.sample(block["items"], len(block["items"])):
            assigned = perfect_match(remaining, rng)
            for batch, mode in assigned.items():
                result[batch][i] = mode
                remaining[batch][mode] -= 1
        assert not any(any(h) for h in remaining)
    return result
