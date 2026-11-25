"""Exact joint selection for ordered source signatures and up to two changes per source."""

from collections import Counter
from dataclasses import dataclass

from interval_fault_noisy import ambiguous_record


@dataclass(frozen=True)
class JointPlan:
    cost: int | None
    selected: tuple
    required: tuple
    covered_by: tuple
    witness: tuple | None = None


def after_anchor(model, anchor):
    """Order feasible repair indices immediately after the anchor boundary."""
    start = model.position[anchor] + 1
    full = len(model.rank) - 1
    return tuple(
        sorted(
            range(len(model.kept_positions)),
            key=lambda i: (model.kept_positions[i] - start) % full,
        )
    )


def minimum_pair_cover(costs, covers, demand):
    """Unit-capacity, weighted lower-degree edge cover, including singleton offers."""
    if (
        len(covers) != len(costs)
        or any(c <= 0 for c in costs)
        or any(d < 0 for d in demand)
    ):
        raise ValueError("aligned positive prices and nonnegative demand required")
    if any(
        len(row) > 2
        or len(set(row)) != len(row)
        or any(j not in range(len(demand)) for j in row)
        for row in covers
    ):
        raise ValueError("each source must cover at most two distinct valid boundaries")
    available = Counter(j for row in covers for j in row)
    slack = [available[j] - d for j, d in enumerate(demand)]
    if any(c < 0 for c in slack):
        return None
    if not any(demand):
        return ()

    import networkx as nx

    # An integer suffix specifies a unique omission set among equal-price optima.
    scale = 1 << len(costs)
    values = [cost * scale + (1 << i) for i, cost in enumerate(costs)]
    reserve = max(values) + 1
    graph = nx.Graph()
    for i, row in enumerate(covers):
        if not row:
            continue
        left, right = ("item", i, 0), ("item", i, 1)
        graph.add_edge(left, right, weight=2 * reserve)
        for duplicate in range(slack[row[0]]):
            graph.add_edge(
                left, ("slot", row[0], duplicate), weight=reserve + values[i]
            )
        if len(row) == 2:
            for duplicate in range(slack[row[1]]):
                graph.add_edge(right, ("slot", row[1], duplicate), weight=reserve)
        else:
            graph.add_edge(right, ("private", i), weight=reserve)
    matching = nx.max_weight_matching(graph)
    selected = []
    partners = {x: y for a, b in matching for x, y in ((a, b), (b, a))}
    for i, row in enumerate(covers):
        if not row:
            continue
        left, right = ("item", i, 0), ("item", i, 1)
        assert left in partners and right in partners
        if partners[left] == right:
            selected.append(i)
    return tuple(selected)


def joint_plan(labels, offers, errors):
    """Pick one fixed set of sources that certifies a whole decision vector.

    Supply an ordered list of feasible worlds. Within that order, each
    source's equality classes must be contiguous. Its signature may have at
    most two changes relevant to the requested labels.
    """
    if not labels or errors < 0 or any(len(q.values) != len(labels) for q in offers):
        raise ValueError(
            "aligned nonempty worlds and a nonnegative error budget required"
        )
    changes = tuple(i for i in range(len(labels) - 1) if labels[i] != labels[i + 1])
    d = 2 * errors + 1
    supports = []
    for q in offers:
        seen = {q.values[0]}
        for earlier, value in zip(q.values, q.values[1:]):
            if earlier != value:
                if value in seen:
                    raise ValueError(
                        "the source signature has noncontiguous equality classes"
                    )
                seen.add(value)
        supports.append(
            tuple(j for j, i in enumerate(changes) if q.values[i] != q.values[i + 1])
        )
    chosen = minimum_pair_cover([q.cost for q in offers], supports, (d,) * len(changes))
    if chosen is None:
        i = next(p for j, p in enumerate(changes) if sum(j in s for s in supports) < d)
        return JointPlan(
            None, (), changes, tuple(supports), ambiguous_record(offers, i, i + 1)
        )
    return JointPlan(
        sum(offers[i].cost for i in chosen), chosen, changes, tuple(supports)
    )
