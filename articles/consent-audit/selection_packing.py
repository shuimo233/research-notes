"""Pack disjoint affine bases for a fixed public catalogue of release labels."""

from collections import deque
from math import gcd

from attested_optimality import Exhausted
from conclusion_replay import components, interval, pin
from lag_protection import decode, rational_table
from public_optimality import tighten


class Span:
    def __init__(self, coordinates):
        self.coordinates = coordinates
        self.rows = {}

    @staticmethod
    def scaled(row):
        factor = gcd(*row)
        return [x // factor for x in row] if factor > 1 else row

    def remainder(self, world):
        row = [1, *(world[i] for i in self.coordinates)]
        for pivot in sorted(self.rows):
            column = row[pivot]
            if column:
                saved = self.rows[pivot]
                row = self.scaled(
                    [
                        saved[pivot] * a - column * b
                        for a, b in zip(row, saved, strict=True)
                    ]
                )
        return row

    def can_add(self, world):
        return any(self.remainder(world))

    def add(self, world):
        row = self.remainder(world)
        index = next((i for i, value in enumerate(row) if value), None)
        if index is None:
            return False
        self.rows[index] = self.scaled(row)
        return True


def restrict(zone, site, lo, hi):
    zone = tighten(zone, 0, site, hi)
    return tighten(zone, site, 0, -lo) if zone is not None else None


def boxes(zone, axes, excluded, depth=0):
    if not excluded:
        yield zone
        return
    if depth == len(axes):
        return
    slot = axes[depth]
    lo, hi = interval(zone, 0, slot)
    children = {}
    for world in excluded:
        value = world[slot]
        if lo <= value <= hi:
            children.setdefault(value, []).append(world)
    lower = lo
    for value, child in sorted(children.items()):
        if lower < value:
            yield restrict(zone, slot, lower, value - 1)
        yield from boxes(pin(zone, slot, value), axes, child, depth + 1)
        lower = value + 1
    if lower <= hi:
        yield restrict(zone, slot, lower, hi)


def possible(zone, x):
    return all(
        x[v] - x[u] <= c for u, row in enumerate(zone) for v, c in enumerate(row)
    )


def extract(zone, axes, excluded, tally, limit):
    span = Span(axes)
    kept = []
    wanted = len(axes) + 1

    def sample(region):
        tally["cells"] += 1
        if tally["cells"] > limit:
            raise Exhausted("basis construction budget exceeded")
        for row in decode(rational_table(region, region)):
            world = tuple(row)
            if world not in excluded and span.add(world):
                kept.append(world)

    sample(zone)
    if len(kept) == wanted:
        return kept
    relevant = [w for w in sorted(excluded) if possible(zone, w)]
    for c in boxes(zone, axes, relevant):
        sample(c)
        if len(kept) == wanted:
            break
    return kept


def independent(rows, axes):
    span = Span(axes)
    return all(span.add(row) for row in rows)


def exchange(pools, axes):
    """Matroid intersection of a per-label affine matroid and a per-world partition."""
    rank = len(axes) + 1
    target = rank * len(pools)
    chosen = set()
    while len(chosen) < target:
        projection = [[] for _ in pools]
        owner = {}
        for i, w in sorted(chosen):
            projection[i].append(w)
            owner[w] = (i, w)
        queue = deque()
        parent = {}

        def reach(node, ancestor):
            if node not in parent:
                parent[node] = ancestor
                queue.append(node)

        for i, row in enumerate(pools):
            if len(projection[i]) == rank:
                continue
            span = Span(axes)
            assert all(span.add(w) for w in projection[i])
            for w in row:
                if (i, w) not in chosen and span.can_add(w):
                    reach((i, w), None)
        terminal = None
        while queue:
            node = queue.popleft()
            i, w = node
            if node not in chosen:
                paired = owner.get(w)
                if paired is None:
                    terminal = node
                    break
                reach(paired, node)
            else:
                span = Span(axes)
                assert all(span.add(x) for x in projection[i] if x != w)
                for x in pools[i]:
                    if (i, x) not in chosen and span.can_add(x):
                        reach((i, x), node)
        if terminal is None:
            break
        while terminal is not None:
            chosen.symmetric_difference_update((terminal,))
            terminal = parent[terminal]
    result = [sorted(w for j, w in chosen if j == i) for i in range(len(pools))]
    assert all(independent(row, axes) for row in result)
    assert len({x for row in result for x in row}) == len(chosen)
    return result


def packed(public, zones, budget=50_000):
    if not zones:
        return dict(status="empty")
    axes = tuple(sorted(set(components(public)) - {0}))
    rank = len(axes) + 1
    tally = dict(cells=0)
    chosen = []
    committed = set()
    try:
        for zone in zones:
            basis = extract(zone, axes, committed, tally, budget)
            if len(basis) != rank:
                break
            committed.update(basis)
            chosen.append(basis)
        else:
            return dict(
                status="proved", method="disjoint extraction", bases=chosen, **tally
            )

        pools = []
        size = rank * len(zones)
        for zone in zones:
            selected = set()
            for _ in range(size):
                basis = extract(zone, axes, selected, tally, budget)
                if not basis:
                    break
                selected.update(basis)
            pools.append(sorted(selected))
        solution = exchange(pools, axes)
        count = sum(map(len, solution))
        if count != size:
            return dict(
                status="impossible",
                independent_size=count,
                needed_size=size,
                kernel_sizes=[len(p) for p in pools],
                **tally,
            )
        return dict(
            status="proved",
            method="kernel and matroid intersection",
            bases=solution,
            kernel_sizes=[len(p) for p in pools],
            **tally,
        )
    except Exhausted:
        return dict(status="limited", **tally)
