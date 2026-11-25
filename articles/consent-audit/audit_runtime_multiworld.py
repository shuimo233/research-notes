"""Compile exact parity groups across multiple possible worlds."""

from collections import defaultdict, deque
from fractions import Fraction as F
from functools import cache
from itertools import combinations, zip_longest

from audit_runtime_partition import signature


def tables_from(rates):
    data = tuple(tuple(tuple(map(F, row)) for row in world) for world in rates)
    if len(data) < 2 or not data[0] or any(len(q) != len(data[0]) for q in data):
        raise ValueError(
            "expected at least two worlds over the same nonempty request list"
        )
    modes = len(data[0][0])
    if not modes or any(
        len(r) != modes or any(not 0 < x < 1 for x in r) for a in data for r in a
    ):
        raise ValueError("expected a common mode inventory and interior refusal rates")
    return data


def activity(tables):
    return [
        sum(1 << j for j, row in enumerate(q) if min(row) < max(row))
        for q in zip(*tables, strict=True)
    ]


def global_groups(profiles):
    coherent = []
    solo = []
    pairings = defaultdict(lambda: ([], []))
    all_active = (1 << len(profiles[0][1])) - 1 if profiles else 0
    for i, s in profiles:
        kinds = tuple(sorted(set(s)))
        if len(kinds) == 1:
            coherent.append(i)
        elif len(kinds) == 2:
            side = sum(1 << w for w, tag in enumerate(s) if tag == kinds[1])
            key = (kinds, min(side, side ^ all_active))
            pairings[key][int(side != key[1])].append(i)
        else:
            solo.append(i)
    parts = [[i] for i in solo]
    clique = solo[:]
    if coherent:
        parts.append(coherent)
        clique.append(coherent[0])
    for key in sorted(pairings):
        a, b = pairings[key]
        parts.extend([v for v in q if v is not None] for q in zip_longest(a, b))
        clique.extend(a if len(a) >= len(b) else b)
    return parts, clique


def matching_core(core, edges):
    pairs = []
    barrier = []
    if edges:
        import networkx as nx

        g = nx.Graph()
        g.add_nodes_from(core)
        g.add_edges_from(edges)

        def matching(graph):
            return nx.max_weight_matching(graph, maxcardinality=True)

        m = matching(g)
        pairs = sorted(sorted(edge) for edge in m)
        exposed = {
            i
            for i in core
            if len(matching(g.subgraph([v for v in core if v != i]))) == len(m)
        }
        barrier = sorted({v for i in exposed for v in g[i]} - exposed)
    consumed = {i for pair in pairs for i in pair}
    blocks = [pair[:] for pair in pairs] + [[i] for i in core if i not in consumed]
    return blocks, {"kind": "matching", "pairs": pairs, "barrier": barrier}


def counted_core(core, masks):
    types = sorted({masks[i] for i in core})
    pools = [deque(i for i in core if masks[i] == mask) for mask in types]
    # A block uses at most one request of a type, and disjoint types.
    groups = [[] for _ in types]

    def generate(start, used, chosen):
        for j in range(start, len(types)):
            if not used & types[j]:
                block = (*chosen, j)
                groups[block[0]].append(block)
                generate(j + 1, used | types[j], block)

    generate(0, 0, ())
    sizes = tuple(map(len, pools))
    choice = {}

    @cache
    def optimum(state):
        start = next((i for i, n in enumerate(state) if n), None)
        if start is None:
            return 0
        best = sum(state) + 1
        for block in groups[start]:
            if all(state[i] for i in block):
                following = tuple(n - int(i in block) for i, n in enumerate(state))
                value = 1 + optimum(following)
                if value < best:
                    best = value
                    choice[state] = block
        return best

    v = optimum(sizes)
    rows = []
    while sizes in choice:
        b = choice[sizes]
        rows.append([pools[i].popleft() for i in b])
        sizes = tuple(n - int(i in b) for i, n in enumerate(sizes))
    assert len(rows) == v
    return rows, {"kind": "counts", "core_colors": v}


def partition_masks(masks, worlds):
    """Optimize disjoint activity-mask blocks with an exact core proof."""
    core = [i for i in sorted(masks) if masks[i].bit_count() >= 2]
    types = sorted({masks[i] for i in core})
    triples = any(a & b == a & c == b & c == 0 for a, b, c in combinations(types, 3))
    if triples:
        parts, cert = counted_core(core, masks)
    else:
        edges = [(i, j) for i, j in combinations(core, 2) if not masks[i] & masks[j]]
        parts, cert = matching_core(core, edges)
    peak = max(
        sum(bool(mask & (1 << j)) for mask in masks.values()) for j in range(worlds)
    )
    parts.extend([] for _ in range(peak - len(parts)))
    for j in range(worlds):
        bit = 1 << j
        available = (b for b in parts if all(not masks[i] & bit for i in b))
        for i in sorted(i for i, mask in masks.items() if mask == bit):
            next(available).append(i)
    return parts, cert


def compile_partition(rates):
    tables = tables_from(rates)
    worlds = len(tables)
    masks = activity(tables)
    full = (1 << worlds) - 1
    universal = [
        (i, tuple(signature(row[i]) for row in tables))
        for i, a in enumerate(masks)
        if a == full
    ]
    total, clique = global_groups(universal)
    partial, certificate = partition_masks(
        {i: a for i, a in enumerate(masks) if a and a != full}, worlds
    )
    total.extend(partial)
    always = [i for i, mask in enumerate(masks) if not mask]
    if total:
        total[0].extend(always)
    else:
        total = [always]
    return {
        "blocks": [sorted(a) for a in total],
        "global_clique": sorted(clique),
        "partial_core": certificate,
    }


def conservative_partition(rates):
    data = tables_from(rates)
    groups, proof = partition_masks(
        {i: m for i, m in enumerate(activity(data)) if m}, len(data)
    )
    fixed = [i for i, m in enumerate(activity(data)) if not m]
    if groups:
        groups[0].extend(fixed)
    else:
        groups = [fixed]
    return {"blocks": [sorted(a) for a in groups], "core": proof}


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("contract", type=Path)
    a = cli.parse_args()
    print(json.dumps(compile_partition(json.loads(a.contract.read_bytes())["rates"])))
