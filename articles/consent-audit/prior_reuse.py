"""Certify reuse of an optimal independent-input query policy after a prior update."""

import argparse
from collections import deque
from fractions import Fraction as Q
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from block_query_plan import scopes
from frontier_plan import FrontierPlan, bits


def transport(old, new, cost):
    """Exact min-cost flow between excess and deficient masks."""
    if sum(old.values()) != sum(new.values()) or any(
        p < 0 for law in (old, new) for p in law.values()
    ):
        raise ValueError("transport requires nonnegative laws of equal mass")
    supply = []
    demand = []
    for mask in sorted(set(old) | set(new)):
        gap = old.get(mask, 0) - new.get(mask, 0)
        if gap > 0:
            supply.append((mask, gap))
        elif gap < 0:
            demand.append((mask, -gap))
    capacity = sum(p for _, p in supply)
    if not capacity:
        return Q(0)
    sink = len(supply) + len(demand) + 1
    arcs = [[] for _ in range(sink + 1)]

    def connect(a, b, cap, price):
        arcs[a].append([b, len(arcs[b]), cap, price])
        arcs[b].append([a, len(arcs[a]) - 1, Q(0), -price])

    for i, (a, p) in enumerate(supply, 1):
        connect(0, i, p, 0)
        for j, (b, _) in enumerate(demand, len(supply) + 1):
            connect(i, j, capacity, sum(cost[k] for k in bits(a ^ b)))
    for j, (_, p) in enumerate(demand, len(supply) + 1):
        connect(j, sink, p, 0)

    value = Q(0)
    while capacity:
        distance = [None] * (sink + 1)
        path = [None] * (sink + 1)
        distance[0] = 0
        queue = deque([0])
        queued = {0}
        while queue:
            u = queue.popleft()
            queued.remove(u)
            for k, (v, _, remaining, price) in enumerate(arcs[u]):
                if not remaining:
                    continue
                candidate = distance[u] + price
                if distance[v] is None or candidate < distance[v]:
                    distance[v] = candidate
                    path[v] = u, k
                    if v not in queued:
                        queue.append(v)
                        queued.add(v)
        if path[sink] is None:
            raise ValueError("transport masses differ")
        edges = []
        v = sink
        while v:
            u, k = path[v]
            edges.append((u, k))
            v = u
        amount = min(arcs[u][k][2] for u, k in edges)
        for u, k in edges:
            v, rev, _, _ = arcs[u][k]
            arcs[u][k][2] -= amount
            arcs[v][rev][2] += amount
        value += amount * distance[sink]
        capacity -= amount
    return value


def common_structure(old, new):
    if (old.names, old.neighbors, old.counts, old.cost) != (
        new.names,
        new.neighbors,
        new.counts,
        new.cost,
    ):
        raise ValueError("query graph and prices must match")
    if any(n != 1 for n in old.counts):
        raise ValueError("use one type per queried location")
    for a, b in zip(old.groups, new.groups, strict=True):
        if {m for m, _ in a} != {m for m, _ in b}:
            raise ValueError("trigger supports must match")


def _transport_bounds(old, new, live):
    active = {old.names[i]: 1 for i in bits(live)}
    edges = [
        (old.names[i], old.names[j])
        for i in bits(live)
        for j in bits(old.neighbors[i] & live)
        if i < j
    ]
    partition = scopes(active, edges)
    distance = Q(0)
    drift = Q(0)
    for u in active:
        i = old.indices[u]
        for scope in partition[u]:
            local = sum(1 << old.indices[v] for v in scope)
            a = dict(old.projections(i, local))
            b = dict(new.projections(i, local))
            distance += transport(a, b, old.cost)
        drift += sum(
            old.cost[j] * (new.rates[i][j] - p)
            for j, p in old.rates[i].items()
            if live >> j & 1
        )
    assert distance >= abs(drift)
    return (distance - drift) / 2, (distance + drift) / 2


def transfer_bound(old, new):
    """Return cost-decrease and cost-increase allowances from old to new."""
    common_structure(old, new)
    return _transport_bounds(old, new, (1 << len(old.names)) - 1)


def mandatory_first_regret_bound(old, new):
    """Ignore initial compulsory reads when bounding the loss of an optimal old policy."""
    common_structure(old, new)
    live = (1 << len(old.names)) - 1
    compulsory = old.obligations(old.counts, 0)
    return sum(_transport_bounds(old, new, live & ~compulsory))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    a = parser.parse_args()
    p, q = (FrontierPlan(**json.loads(path.read_bytes())) for path in (a.old, a.new))
    low, high = transfer_bound(p, q)
    print(
        json.dumps(
            dict(
                optimal_budget_change=[str(-low), str(high)],
                reused_policy_regret_at_most=str(low + high),
                regret_after_removing_mandatory_reads=str(
                    mandatory_first_regret_bound(p, q)
                ),
            ),
            indent=2,
        )
    )
