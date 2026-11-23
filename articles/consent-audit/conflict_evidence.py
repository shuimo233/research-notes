"""Exact signed relevance and nearest departures for two monotone families of finite evidence sets.

Evidence sets are represented by nonnegative integer bit masks. 'depart' is true precisely when
a proposal has support and none of its blockers has support. Other states retain the fallback.
"""

from functools import lru_cache
from operator import or_
from functools import reduce


def union(masks):
    return reduce(or_, masks, 0)


def bits(mask):
    while mask:
        bit = mask & -mask
        yield bit
        mask ^= bit


def minimal(masks):
    unique = set(masks)
    if any(type(m) is not int or m < 0 for m in unique):
        raise ValueError("evidence masks must be nonnegative integers")
    kept = []
    for m in sorted(unique, key=lambda v: (v.bit_count(), v)):
        if not any(k & m == k for k in kept):
            kept.append(m)
    return tuple(kept)


def present(paths, world):
    return any(p & world == p for p in paths)


def depart(proposals, blockers, world):
    return present(proposals, world) and not present(blockers, world)


def smallest_cut(residual):
    """Minimum hitting set for a fixed surviving proposal; no residual set may be empty."""

    @lru_cache(None)
    def solve(family):
        if not family:
            return 0
        return min(
            (e | solve(tuple(q for q in family if not e & q)) for e in bits(family[0])),
            key=lambda m: (m.bit_count(), m),
        )

    return solve(residual)


def analyze(proposals, blockers):
    proposals, blockers = minimal(proposals), minimal(blockers)
    up, down = {}, {}
    best = None
    for p in proposals:
        if present(blockers, p):
            continue
        for edge in bits(p):
            up.setdefault(edge, p ^ edge)
        residual = minimal(q & ~p for q in blockers)
        for tail in residual:
            for edge in bits(tail):
                down.setdefault(edge, (p | tail) ^ edge)
        cut = smallest_cut(residual)
        if best is None or (cut.bit_count(), cut) < (best.bit_count(), best):
            best = cut
    needed = union([*up, *down])
    naive = union(proposals)
    disagreement = None
    for edge in bits(needed & ~naive):
        low = up[edge] if edge in up else down[edge]
        for w in (low, low | edge):
            if depart(proposals, blockers, w) != depart(proposals, blockers, w & naive):
                disagreement = w
                break
        if disagreement is not None:
            break
    return {
        "rising": up,
        "falling": down,
        "needed": needed,
        "minimum_deletions": best,
        "proposal_only_counterexample": disagreement,
    }
