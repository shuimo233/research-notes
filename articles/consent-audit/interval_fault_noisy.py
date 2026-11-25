"""Minimum-cost fixed noisy verification and an exact adaptive block policy."""

from dataclasses import dataclass
from math import inf


@dataclass(frozen=True)
class Offer:
    cost: int
    values: tuple


@dataclass(frozen=True)
class Cover:
    cost: int | None
    chosen: tuple
    reference: int
    rivals: tuple
    intervals: tuple
    potentials: tuple
    counterexample: tuple | None = None


@dataclass
class _Edge:
    head: int
    reverse: int
    capacity: int
    cost: int


def _arc(graph, u, v, capacity, cost):
    forward = _Edge(v, len(graph[v]), capacity, cost)
    graph[v].append(_Edge(u, len(graph[u]), 0, -cost))
    graph[u].append(forward)
    return forward


def _distances(graph, source=None):
    distances = [0 if source is None else inf] * len(graph)
    before = [None] * len(graph)
    if source is not None:
        distances[source] = 0
    for _ in range(len(graph) - 1):
        moved = False
        for u, row in enumerate(graph):
            for edge in row:
                nd = distances[u] + edge.cost
                if edge.capacity and nd < distances[edge.head]:
                    distances[edge.head] = nd
                    before[edge.head] = (u, edge)
                    moved = True
        if not moved:
            break
    return distances, before


def _augment(graph, source, sink, count):
    for _ in range(count):
        distance, before = _distances(graph, source)
        assert distance[sink] < inf
        v = sink
        while v != source:
            u, edge = before[v]
            edge.capacity -= 1
            graph[v][edge.reverse].capacity += 1
            v = u


def _minimum_flow(size, offers, intervals, demand):
    graph = [[] for _ in range(size + 1)]
    for i in range(size):
        _arc(graph, i + 1, i, len(offers), 0)
    channels = [
        None if span is None else _arc(graph, *span, 1, offer.cost)
        for offer, span in zip(offers, intervals, strict=True)
    ]
    _augment(graph, 0, size, demand)
    potentials, _ = _distances(graph)
    assert all(
        edge.cost + potentials[u] - potentials[edge.head] >= 0
        for u, row in enumerate(graph)
        for edge in row
        if edge.capacity
    )
    chosen = tuple(
        i for i, edge in enumerate(channels) if edge is not None and not edge.capacity
    )
    return chosen, tuple(potentials)


def _reference(labels, offers):
    for label in (False, True):
        group = [i for i, truth in enumerate(labels) if truth == label]
        if group and all(len({q.values[i] for i in group}) == 1 for q in offers):
            return group[0]
    raise ValueError("one label must share a single channel-answer signature")


def ambiguous_record(offers, reference, rival):
    observed = [q.values[reference] for q in offers]
    different = [i for i, q in enumerate(offers) if q.values[rival] != observed[i]]
    for i in different[: len(different) // 2]:
        observed[i] = offers[i].values[rival]
    return reference, rival, tuple(observed)


def cover_plan(labels, offers, errors):
    """Solve a fixed plan where each probe has a contiguous side in rank order."""
    if (
        not labels
        or errors < 0
        or any(q.cost <= 0 or len(q.values) != len(labels) for q in offers)
    ):
        raise ValueError(
            "nonempty worlds, positive aligned offers and nonnegative error budget required"
        )
    reference = _reference(labels, offers)
    turn = list(range(reference + 1, len(labels))) + list(range(reference))
    rivals = tuple(i for i in turn if labels[i] != labels[reference])
    intervals = []
    counts = [0] * len(rivals)
    for q in offers:
        positions = [
            j for j, i in enumerate(rivals) if q.values[i] != q.values[reference]
        ]
        if positions:
            low, high = positions[0], positions[-1] + 1
            if len(positions) != high - low:
                raise ValueError("the rotated probe disagreements must be contiguous")
            intervals.append((low, high))
            for j in positions:
                counts[j] += 1
        else:
            intervals.append(None)
    demand = 2 * errors + 1
    if not rivals:
        return Cover(0, (), reference, rivals, tuple(intervals), (0,))
    weakest = next(
        (rivals[j] for j, count in enumerate(counts) if count < demand), None
    )
    if weakest is not None:
        return Cover(
            None,
            (),
            reference,
            rivals,
            tuple(intervals),
            (),
            ambiguous_record(offers, reference, weakest),
        )
    selected, potentials = _minimum_flow(len(rivals), offers, intervals, demand)
    return Cover(
        sum(offers[i].cost for i in selected),
        selected,
        reference,
        rivals,
        tuple(intervals),
        potentials,
    )


def possible_labels(labels, selected_offers, observed, errors):
    if len(selected_offers) != len(observed):
        raise ValueError("one reply per selected channel is required")
    return {
        label
        for i, label in enumerate(labels)
        if sum(
            q.values[i] != reply
            for q, reply in zip(selected_offers, observed, strict=True)
        )
        <= errors
    }


def order_blocks(blocks, offers):
    """Accept one block of independent same-question sources per rival."""
    if not blocks or any(len(block) < 3 for block in blocks):
        raise ValueError("each rival needs at least three sources")
    triples = [tuple(sorted(b, key=lambda j: (offers[j].cost, j))[:3]) for b in blocks]
    return tuple(sorted(triples, key=lambda row: -offers[row[2]].cost))


def weighted_one_error_cost(ordered, offers):
    first = sum(offers[a].cost for a, _, _ in ordered)
    prefix, bound = 0, 0
    for _, b, c in ordered:
        prefix += offers[b].cost
        bound = max(bound, prefix + offers[c].cost)
    return first + bound


def adaptive_one_error(ordered, differs):
    """Ask binary readings normalized against the reference world. True means a rival."""
    hits = [row for row in ordered if differs(row[0])]
    if len(hits) > 1:
        return True
    if hits:
        _, b, c = hits[0]
        return differs(b) or differs(c)
    for _, b, c in ordered:
        if differs(b):
            return differs(c)
    return False
