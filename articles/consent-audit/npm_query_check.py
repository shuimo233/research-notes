"""Independently check raw lock relation certificates and fitting metrics."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
import gzip
from itertools import combinations, product
import json
from math import prod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_theory_check import raw_optimum


def cost_check(task):
    ids = [u["id"] for u in task["vertices"]]
    domains = {u["id"]: u["versions"] for u in task["vertices"]}
    involved = set()
    for edge in task["relations"]:
        if len(set("".join(edge["grid"]))) > 1:
            involved.update((edge["from"], edge["to"]))
    names = [u for u in ids if u in involved]
    sizes = [len(domains[u]) for u in names]
    if not names or len(names) > 6 or prod(n + 1 for n in sizes) > 12000:
        return None
    index = {u: i for i, u in enumerate(names)}
    grids = {}
    for edge in task["relations"]:
        u, v = edge["from"], edge["to"]
        if u not in index or v not in index:
            continue
        rows = edge["grid"]
        if index[u] > index[v]:
            u, v = v, u
            rows = list(zip(*rows))
        e = index[u], index[v]
        if e in grids:
            rows = [
                [x + y for x, y in zip(old, new, strict=True)]
                for old, new in zip(grids[e], rows, strict=True)
            ]
        grids[e] = rows
    return raw_optimum([[Q(1, n)] * n for n in sizes], grids, [1] * len(sizes))


def reference(task):
    """Build a second Bellman recurrence from literal rows, without grouping candidates."""
    vertices = {u["id"]: u["versions"] for u in task["vertices"]}
    ids = list(vertices)
    index = {u: i for i, u in enumerate(ids)}
    n = len(ids)
    adjacent = [0] * n
    supports = [[0] * len(vertices[u]) for u in ids]
    forced = 0
    for e in task["relations"]:
        a, b = index[e["from"]], index[e["to"]]
        grid = e["grid"]
        rows = [len(set(row)) > 1 for row in grid]
        columns = [len(set(col)) > 1 for col in zip(*grid)]
        if not any(rows):
            if any(columns):
                forced |= 1 << a
            continue
        if not any(columns):
            forced |= 1 << b
            continue
        adjacent[a] |= 1 << b
        adjacent[b] |= 1 << a
        for j, t in enumerate(rows):
            if t:
                supports[a][j] |= 1 << b
        for j, t in enumerate(columns):
            if t:
                supports[b][j] |= 1 << a
    masks = [Counter(row) for row in supports]
    for i, row in enumerate(masks):
        for j in range(n):
            if (adjacent[i] >> j & 1) and all(m >> j & 1 for m in row):
                forced |= 1 << j

    @lru_cache(None)
    def rec(live, need):
        if need:
            actions = [need.bit_length() - 1]
        else:
            actions = [i for i in range(n) if (live >> i & 1) and adjacent[i] & live]
        if not actions:
            return Q(0)
        prices = []
        for u in actions:
            rest = live ^ 1 << u
            prices.append(
                1
                + sum(
                    Q(mult, len(supports[u])) * rec(rest, (need | mask) & rest)
                    for mask, mult in masks[u].items()
                )
            )
        return min(prices)

    value = rec((1 << n) - 1, forced)
    rec.cache_clear()
    return value


def independent_certificate(task, row):
    vertices = {v["id"]: v for v in task["vertices"]}
    actual = {u: v["versions"].index(v["actual"]) for u, v in vertices.items()}
    ids = {u: i for i, u in enumerate(vertices)}
    prepared = []
    signatures = {u: [[] for x in v["versions"]] for u, v in vertices.items()}
    labels = []
    for edge in task["relations"]:
        u, v = edge["from"], edge["to"]
        a, b = actual[u], actual[v]
        cells = edge["grid"]
        true = cells[a][b]
        labels.append([u, v, true])
        shape = 1 << ids[u], 1 << ids[v]
        possible = tuple(
            all(
                cells[i][j] == true
                for i, j in product(
                    [a] if mask & 1 else range(len(cells)),
                    [b] if mask & 2 else range(len(cells[0])),
                )
            )
            for mask in range(4)
        )
        prepared.append((shape, possible))
        for i, line in enumerate(cells):
            signatures[u][i].extend(line)
        for j, column in enumerate(zip(*cells)):
            signatures[v][j].extend(column)
    assert sorted(labels) == row["labels"]
    assert row["equivalence_classes"] == sum(
        len(set(map(tuple, rows))) for rows in signatures.values()
    )

    def certifies(ids_set):
        mask = sum(1 << ids[u] for u in ids_set)
        return all(
            choices[bool(mask & a) + 2 * bool(mask & b)] for (a, b), choices in prepared
        )

    tested = 0
    if row.get("paths"):
        for path in row["paths"].values():
            assert len(set(path)) == len(path) and certifies(path)
            tested += 1
        assert certifies(row["oracle"])
        for size in range(len(vertices) + 1):
            if any(certifies(subset) for subset in combinations(vertices, size)):
                break
        assert size == len(row["oracle"])
    else:
        assert certifies([])
    return tested


def check(fixtures, results):
    cases = json.loads(gzip.decompress(fixtures.read_bytes()))
    with gzip.open(results / "npm-query-ledger.jsonl.gz", "rt", encoding="utf-8") as f:
        ledger = {(r["repo"], r["center"]): r for r in map(json.loads, f)}
    records = Counter()
    for task in cases:
        row = ledger.pop((task["repo"], task["center"]))
        records["nonempty_paths_verified"] += independent_certificate(task, row)
        records["tasks"] += 1
        if row["variable_relations"]:
            records["minimum_certificates_checked"] += 1
            assert reference(task) == Q(row["expected"])
            records["independent_mask_roots"] += 1
            cost = cost_check(task)
            if cost is not None:
                assert cost == Q(row["expected"])
                records["literal_cost_roots"] += 1
    assert not ledger
    return records


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("folder", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.fixtures, a.folder), indent=2))
