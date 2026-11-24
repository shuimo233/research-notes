"""Minimum exact-reading certificates under old integer difference bounds."""

from bisect import bisect_right
from collections import defaultdict

from conclusion_replay import interval, pin


def sites(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def visible(indices):
    return sum(1 << i for i in set(indices))


def classifications(targets, truth):
    return [bisect_right(cuts, truth[v] - truth[u]) for u, v, cuts in targets]


def claims(targets, labels):
    for (u, v, cuts), level in zip(targets, labels, strict=True):
        if not 0 <= level <= len(cuts):
            raise ValueError("invalid report category")
        if level:
            yield v, u, -cuts[level - 1]
        if level < len(cuts):
            yield u, v, cuts[level] - 1


def reduced_slack(dist, truth):
    if len(dist) != len(truth) or truth[0] != 0:
        raise ValueError("the exact readings must start with the reference zero")
    slack = tuple(
        tuple(bound + truth[u] - truth[v] for v, bound in enumerate(row))
        for u, row in enumerate(dist)
    )
    if any(c < 0 for row in slack for c in row):
        raise ValueError("original readings disagree with the archive")
    return slack


def bound_rows(slack, u, v, height):
    """Yield (changed-site mask, split) for achievable boundary counterexamples."""
    lo = max(0, height - slack[0][v])
    hi = min(height, slack[u][0])
    if lo > hi:
        raise ArithmeticError("a purported non-implied bound is already known")
    # An integer split is a counterexample separator. A point retains its
    # reading exactly throughout one interval of split values.
    events = defaultdict(int, {lo: 0})
    mask = (1 << len(slack)) - 2
    for i in range(1, len(slack)):
        start = max(lo, height - slack[i][v])
        stop = min(hi, slack[u][i])
        if start <= stop:
            events[start] ^= 1 << i
            if stop < hi:
                events[stop + 1] ^= 1 << i
    for split, change in sorted(events.items()):
        mask ^= change
        if not mask:
            raise ArithmeticError(
                "an unobserved report bound was false in the exact record"
            )
        yield mask, split


def counterfactual(slack, truth, u, v, height, split):
    """Clamp zero perturbation between difference-feasible lower/upper potentials."""
    return tuple(
        x + min(0, slack[u][i] - split) + max(0, height - split - slack[i][v])
        for i, x in enumerate(truth)
    )


def rows_for_claims(dist, slack, truth, bounds):
    rows = {}
    for u, v, b in bounds:
        if dist[u][v] <= b:
            continue
        height = b + 1 - (truth[v] - truth[u])
        for mask, split in bound_rows(slack, u, v, height):
            rows.setdefault(mask, (u, v, b, height, split))
    return rows


def minimal_rows(rows):
    kept = []
    for mask in sorted(rows, key=lambda r: (r.bit_count(), r)):
        if not any(mask & prev == prev for prev in kept):
            kept.append(mask)
    return tuple(kept)


def sequential(groups, count):
    selected = 0
    full = (1 << count) - 2
    for rows in groups:
        remaining = [s for s in rows if not s & selected]
        if not remaining:
            continue

        def intersection(uncovered):
            common = full
            for r in uncovered:
                common &= r
            return common

        solo = intersection(remaining)
        if solo:
            selected |= solo & -solo
            continue
        for i in range(1, count):
            bit = 1 << i
            if bit & selected:
                continue
            after = [s for s in remaining if not s & bit]
            candidates = intersection(after) & -(bit << 1)
            if candidates:
                selected |= bit | (candidates & -candidates)
                break
        else:
            raise ArithmeticError("a single difference label needs more than two reads")
    return tuple(sites(selected))


def reverse_delete(rows, initial):
    selected = visible(initial)
    for i in reversed(initial):
        after = selected ^ (1 << i)
        if all(r & after for r in rows):
            selected = after
    return tuple(sites(selected))


class Cover:
    def __init__(self, rows, count):
        self.rows = tuple(rows)
        by_site = [0] * count
        for k, row in enumerate(self.rows):
            for i in sites(row):
                by_site[i] |= 1 << k
        self.by_site = tuple(by_site)
        self.initial = (1 << len(self.rows)) - 1

    def greedy(self):
        remaining = self.initial
        reads = []
        while remaining:
            i = max(
                range(1, len(self.by_site)),
                key=lambda i: (self.by_site[i] & remaining).bit_count(),
            )
            reads.append(i)
            remaining &= ~self.by_site[i]
        return tuple(sorted(reads))

    def lower(self, remaining):
        if not remaining:
            return 0
        # Every pairwise-disjoint set of rows requires one reading per row.
        packed = 0
        used = 0
        for k in sites(remaining):
            row = self.rows[k]
            if not row & used:
                used |= row
                packed += 1
        capacity = max((r & remaining).bit_count() for r in self.by_site)
        return max(packed, (remaining.bit_count() + capacity - 1) // capacity)

    def minimum(self, start, limit):
        best = min(start, key=lambda s: (len(s), s))
        root_lower = self.lower(self.initial)
        seen_depth = {}
        nodes = 0
        exhausted = True

        def visit(remaining, chosen):
            nonlocal best, nodes, exhausted
            if not remaining:
                if len(chosen) < len(best):
                    best = tuple(sorted(chosen))
                return
            depth = len(chosen)
            if depth >= seen_depth.get(remaining, len(best)):
                return
            if depth + self.lower(remaining) >= len(best):
                return
            if nodes >= limit:
                exhausted = False
                return
            nodes += 1
            seen_depth[remaining] = depth
            row = self.rows[(remaining & -remaining).bit_length() - 1]
            options = sorted(
                sites(row),
                key=lambda i: (-(self.by_site[i] & remaining).bit_count(), i),
            )
            for i in options:
                visit(remaining & ~self.by_site[i], (*chosen, i))
                if not exhausted:
                    break

        visit(self.initial, ())
        return best, len(best) if exhausted else root_lower, nodes, exhausted


def verify_report(dist, targets, claimed, disclosed):
    for site, value in disclosed:
        dist = pin(dist, site, value)
    for u, v, b in claims(targets, claimed):
        if dist[u][v] > b:
            raise ValueError("the disclosed readings do not determine the report")
    return [list(interval(dist, u, v)) for u, v, _ in targets]
