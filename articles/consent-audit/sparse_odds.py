"""Exact directed windows and bounded-rank truthful release mechanisms."""

from fractions import Fraction as F
from itertools import combinations
from math import comb
from secrets import SystemRandom

from denial_odds import choose
from selection_odds import members

THREE = F(32, 7)
OVERLAP = F(93, 20)


def subsets(mask):
    answer = mask
    while answer:
        yield answer
        answer = (answer - 1) & mask
    yield 0


def project(row, window):
    out = {}
    for response, value in row.items():
        seen = response & window
        out[seen] = out.get(seen, 0) + value
    return out


def canonical_odds(rows):
    """Only the denominator truth set must be observed for each ordered comparison."""
    for truth, row in rows.items():
        if (
            type(truth) is not int
            or truth < 0
            or len(row) != 2 ** truth.bit_count()
            or any(
                type(a) is not int or a < 0 or a & ~truth or p <= 0
                for a, p in row.items()
            )
            or sum(row.values()) != 1
        ):
            raise ValueError(
                "each world needs a normalized, positive, truthful probability row"
            )
    if not rows:
        raise ValueError("at least one possible world is required")
    maximum = F(1)
    count = 0
    witness = None
    for denominator, mass in rows.items():
        for numerator, row in rows.items():
            if numerator == denominator:
                continue
            for reply, value in project(row, denominator).items():
                r = F(value) / mass[reply]
                count += 1
                if r > maximum:
                    maximum, witness = r, (numerator, denominator, reply)
    return maximum, count, witness


def has_overlap(modes):
    rank = [m for m in modes if m.bit_count() == 3]
    return any((a & b).bit_count() == 2 for a, b in combinations(rank, 2))


def catalogue_policy(modes):
    """Return a rational upper certificate for any rank-at-most-three family."""
    rank = max(m.bit_count() for m in modes)
    if rank > 3:
        raise ValueError("use the bounded-rank construction for higher rank")
    target = (F(1), F(2), F(3), THREE)[rank]
    diagonal = F(1, 3) if rank < 3 else F(2, 7)
    triple = [F(7, 32), F(7, 64), F(1, 16), F(17, 64)]
    if rank == 3 and has_overlap(modes):
        target = OVERLAP
        diagonal = F(1, 4)
        u, v, w = 1 / target, 1 / (2 * target), F(1, 2) - 2 / target
        triple = [u, v, w, F(1, 2) - v - 2 * w]
    levels = [[F(1)], [F(1, 2)] * 2, [diagonal, F(1, 2) - diagonal, diagonal], triple]
    return target, {
        s: {reply: levels[s.bit_count()][reply.bit_count()] for reply in subsets(s)}
        for s in modes
    }


def anchor_lower(modes):
    """Identify a proof using empty and projected singleton truth states."""
    if 0 not in modes:
        return {"lower": "1"}
    rank = max(m.bit_count() for m in modes)
    if rank < 2:
        return {"lower": str(2**rank)}
    projected = {
        s: {s & x: x for x in modes if (s & x).bit_count() == 1}
        for s in modes
        if s.bit_count() == rank
    }
    for left, anchors in projected.items():
        if rank != 3 or len(anchors) < 2:
            continue
        for right, other in projected.items():
            shared = left & right
            if shared.bit_count() == 2 and all(
                (1 << j) in anchors for j in members(shared)
            ):
                unique = right ^ shared
                if unique in other:
                    return {
                        "lower": "2+sqrt(7)",
                        "denominator": left,
                        "numerator": right,
                        "anchors": [anchors[1 << j] for j in members(shared)]
                        + [other[unique]],
                    }
    for s, anchors in projected.items():
        if len(anchors) >= (2 if rank == 3 else 1):
            return {
                "lower": "32/7" if rank == 3 else "3",
                "world": s,
                "anchors": [
                    v for _, v in sorted(anchors.items())[: 2 if rank == 3 else 1]
                ],
            }
    return {"lower": "16/5" if rank == 3 else "8/3"}


def transform(counts):
    d = len(counts) - 1
    return [sum(comb(j, a) * counts[j] for j in range(a, d + 1)) for a in range(d + 1)]


def bounded_rank_counts(d):
    """Return a rational d-slot law and its bound, independent of catalogue size."""
    if type(d) is not int or d < 0:
        raise ValueError("rank must be a nonnegative integer")
    if not d:
        return F(1), [F(1)]
    r = 24 * F(3, 2) ** d

    def resolve(initial):
        result = [F(0)] * (d + 1)
        for a in reversed(range(d + 1)):
            above = sum(comb(j, a) * result[j] for j in range(a + 1, d + 1))
            result[a] = (r * initial[a] + above) / (r - 1)
        return result

    fair = resolve([F(comb(d, j), 2 ** (d + 1)) for j in range(d + 1)])
    j = (7 * d + 11) // 12
    high = resolve([int(i == j) for i in range(d + 1)])
    total_high = sum(high)
    high = [p / total_high for p in high]
    left = 1 - sum(fair)
    deficit = F(d, 2) - sum(i * p for i, p in enumerate(fair))
    high_mass = deficit / sum(i * p for i, p in enumerate(high))
    table = [a + high_mass * b for a, b in zip(fair, high, strict=True)]
    table[0] += left - high_mass
    return r, table


def sample_bounded(eligible, counts):
    """Project one symmetric d-slot draw onto the true requests."""
    if type(eligible) is not int or eligible < 0 or eligible.bit_count() >= len(counts):
        raise ValueError("true requests exceed the declared active limit")
    size = choose(dict(enumerate(counts)))
    positions = set(SystemRandom().sample(range(len(counts) - 1), size))
    return sum(1 << j for i, j in enumerate(members(eligible)) if i in positions)
