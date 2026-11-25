"""Optimize fixed source-vector checks whose disagreements mostly form intervals."""

from dataclasses import dataclass
from itertools import combinations
from math import inf

from interval_fault_noisy import _arc, _augment, _reference, ambiguous_record


@dataclass(frozen=True)
class SourcePlan:
    cost: int | None
    selected: tuple
    reference: int
    rivals: tuple
    differing: tuple
    exceptions: tuple
    flow_calls: int
    counterexample: tuple | None = None


def source_disagreements(path, pairs, reference, rivals):
    """Positions covered by the rotated spans of report-graph components."""
    neighbors = {}
    for u, v in pairs:
        neighbors.setdefault(u, []).append(v)
        neighbors.setdefault(v, []).append(u)
    cut = path.kept_positions[reference]
    cycle = len(path.rank) - 1
    rotation = [(path.kept_positions[i] - cut) % cycle for i in rivals]
    seen = set()
    spans = []
    for root in neighbors:
        if root in seen:
            continue
        pending = [root]
        seen.add(root)
        for u in pending:
            for v in neighbors[u]:
                if v not in seen:
                    pending.append(v)
                    seen.add(v)
        positions = [(path.position[u] - cut) % cycle for u in pending]
        spans.append((min(positions), max(positions)))
    return tuple(i for i, p in enumerate(rotation) if any(a < p <= b for a, b in spans))


def _interval_cover(size, indices, offers, differing, demands):
    source, sink = size + 1, size + 2
    graph = [[] for _ in range(size + 3)]
    for i in range(size):
        _arc(graph, i + 1, i, len(indices), 0)
    channels = []
    for i in indices:
        block = differing[i]
        channels.append(_arc(graph, block[0], block[-1] + 1, 1, offers[i].cost))
    required = 0
    for i, (a, b) in enumerate(zip((0, *demands), (*demands, 0), strict=True)):
        if b > a:
            required += b - a
            _arc(graph, source, i, b - a, 0)
        elif a > b:
            _arc(graph, i, sink, a - b, 0)
    _augment(graph, source, sink, required)
    return tuple(
        i for i, arc in zip(indices, channels, strict=True) if not arc.capacity
    )


def source_plan(labels, offers, errors):
    """Minimize paired-source distance cover when one label shares a signature.

    Noncontiguous disagreement sets are handled exactly by enumerating their
    choices and using an interval flow for the remaining, nonuniform demand.
    Every offer is one fault position, independently of its vector length.
    """
    if (
        not labels
        or errors < 0
        or any(q.cost <= 0 or len(q.values) != len(labels) for q in offers)
    ):
        raise ValueError(
            "nonempty aligned worlds, positive source prices and a nonnegative budget required"
        )
    ref = _reference(labels, offers)
    rotated = (*range(ref + 1, len(labels)), *range(ref))
    rivals = tuple(i for i in rotated if labels[i] != labels[ref])
    differing = tuple(
        tuple(j for j, i in enumerate(rivals) if q.values[ref] != q.values[i])
        for q in offers
    )
    demand = 2 * errors + 1
    order, exceptional = [], []
    counts = [0] * len(rivals)
    for i, hits in enumerate(differing):
        if not hits:
            continue
        for j in hits:
            counts[j] += 1
        (order if hits[-1] - hits[0] + 1 == len(hits) else exceptional).append(i)
    if not rivals:
        return SourcePlan(0, (), ref, rivals, differing, (), 0)
    weak = next((rivals[j] for j, count in enumerate(counts) if count < demand), None)
    if weak is not None:
        return SourcePlan(
            None,
            (),
            ref,
            rivals,
            differing,
            tuple(exceptional),
            0,
            ambiguous_record(offers, ref, weak),
        )
    support = [0] * len(rivals)
    for i in order:
        for j in differing[i]:
            support[j] += 1
    best, selected, calls = inf, (), 0
    for length in range(len(exceptional) + 1):
        for choice in combinations(exceptional, length):
            charge = sum(offers[i].cost for i in choice)
            if charge >= best:
                continue
            left = [demand] * len(rivals)
            for i in choice:
                for j in differing[i]:
                    left[j] = max(0, left[j] - 1)
            if any(x > c for x, c in zip(left, support, strict=True)):
                continue
            rest = _interval_cover(len(rivals), order, offers, differing, tuple(left))
            calls += 1
            cost = sum(offers[i].cost for i in rest) + charge
            if cost < best:
                best, selected = cost, tuple(sorted((*choice, *rest)))
    assert best < inf
    return SourcePlan(best, selected, ref, rivals, differing, tuple(exceptional), calls)
