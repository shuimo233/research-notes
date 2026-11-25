"""Independent deletion, component and joint-projection check for the two-fault replay."""

from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from math import comb
from pathlib import Path
from random import Random
import sys

from interval_fault_cut_check import components, source_days


NOAA_EDGES = ((0, 1), (0, 2), (0, 3), (0, 4), (1, 2), (3, 4))
BART_HASH = "a915f1052755d1ae96c785852f9d9ae40f676324403c1ff2f6112e7656048a0f"


def source(noaa, bart):
    for panel, stamp, values, bands in source_days(noaa):
        yield f"weather/{panel}/{stamp}", values, bands, NOAA_EDGES, 10
    raw = bart.read_bytes()
    assert sha256(raw).hexdigest() == BART_HASH
    for row in json.loads(gzip.decompress(raw)):
        times = tuple(x["second"] for x in row["events"])
        bands = tuple((300 * (x // 300), 300 * (x // 300) + 299) for x in times)
        pairs = [(a - 1, b - 1) for a, b in row["pairs"]]
        key = "/".join(map(str, ("bart", row["station"], row["date"], row["start"])))
        yield key, times, bands, pairs, 180


def derived_reports(key, values, edges):
    a, b, c, d, e, f, *_ = sha256(key.encode()).digest()
    if key.startswith("weather/"):
        first, second = [0, 1, 4][a % 3], [2, 3, 5][b % 3]
        levels = [1, 5, 15]
    else:
        first = a % len(edges)
        second = b % (len(edges) - 1)
        second += second >= first
        levels = [60, 180, 300]
    changes = {
        first: levels[c % 3] * [-1, 1][e % 2],
        second: levels[d % 3] * [-1, 1][f % 2],
    }
    return [
        (s, t, values[t] - values[s] + changes.get(i, 0))
        for i, (s, t) in enumerate(edges)
    ], sorted([k, v] for k, v in changes.items())


def compatible(model, bands):
    tags, offsets, limits = model
    lower = [float("-inf")] * len(limits)
    upper = [float("inf")] * len(limits)
    for i, (lo, hi) in enumerate(bands):
        g = tags[i]
        lower[g] = max(lower[g], lo - offsets[i])
        upper[g] = min(upper[g], hi - offsets[i])
    if any(a > b for a, b in zip(lower, upper, strict=True)):
        return None
    return tags, offsets, lower, upper


def oracle(size, reports, bands):
    minimum = 3
    graph, bounded = {}, {}
    for k in range(3):
        for dropped in combinations(range(len(reports)), k):
            model = components(size, None, reports, dropped)
            if model is None:
                continue
            minimum = min(minimum, k)
            if k == 2:
                graph[dropped] = model
                banded = compatible(model, bands)
                if banded is not None:
                    bounded[dropped] = banded
    return minimum, graph, bounded


def constraint(model, s, t, limit):
    tags, base, lower, upper = model
    a, b = tags[s], tags[t]
    cap = limit - (base[t] - base[s])
    if a == b:
        return None if cap < 0 else (a, b, cap, lower, upper)
    lower, upper = lower[:], upper[:]
    lower[a] = max(lower[a], lower[b] - cap)
    upper[b] = min(upper[b], upper[a] + cap)
    if lower[a] > upper[a] or lower[b] > upper[b]:
        return None
    return a, b, cap, lower, upper


def projection(model, condition, u, v):
    tags, base, _, _ = model
    a, b, cap, lower, upper = condition
    p, q = tags[u], tags[v]
    h = base[v] - base[u]
    if p == q:
        return [h, h]
    lo, hi = lower[q] - upper[p], upper[q] - lower[p]
    if (p, q) == (a, b):
        hi = min(hi, cap)
    if (p, q) == (b, a):
        lo = max(lo, -cap)
    return [h + lo, h + hi]


def normalized(ranges):
    points = Counter()
    for a, b in ranges:
        assert a <= b
        points[a] += 1
        points[b + 1] -= 1
    count, start, result = 0, None, []
    for p in sorted(points):
        after = count + points[p]
        if not count and after:
            start = p
        if count and not after:
            result.append([start, p - 1])
        count = after
    return result


def sides(model_rows, s, t, limit, probes):
    labels = []
    for direction in ((s, t, limit - 1), (t, s, -limit)):
        active = [
            (m, c) for m in model_rows if (c := constraint(m, *direction)) is not None
        ]
        labels.append(
            (
                bool(active),
                [
                    normalized(projection(m, c, u, v) for m, c in active)
                    for u, v in probes
                ],
            )
        )
    return [x[0] for x in labels], list(zip(labels[0][1], labels[1][1], strict=True))


def tight_metrics(saved, graph, banded, reports, pairs):
    for tags, _, _ in graph.values():
        assert tags == [0] * len(tags)
    assert saved["distinct_banded_repairs"] == len(banded)
    first, second = saved["reference_faults"]
    reference = banded[first, second][1]
    residuals = [
        reports[i][2] - (reference[reports[i][1]] - reference[reports[i][0]])
        for i in (first, second)
    ]
    assert all(residuals)
    envelope = {
        a * residuals[0] + b * residuals[1] for a, b in product((-1, 0, 1), repeat=2)
    }
    maximum, diagnoses = 0, set()
    for u, v in pairs:
        values = {offset[v] - offset[u] for _, offset, _ in graph.values()}
        baseline = reference[v] - reference[u]
        assert all(value - baseline in envelope for value in values)
        maximum = max(maximum, len(values))
        if len({m[1][v] - m[1][u] for m in banded.values()}) == len(banded):
            diagnoses.add((u, v))
    assert saved["maximum_value_support"] == maximum
    return diagnoses


def verify_cycle(claimed, reports):
    assert len(claimed) == len(set(claimed))
    origin, target, measured = reports[claimed[0]]
    walk, visited, inferred = origin, {origin}, 0
    for i in claimed[1:]:
        u, v, delta = reports[i]
        assert walk in (u, v)
        if walk == u:
            walk, inferred = v, inferred + delta
        else:
            walk, inferred = u, inferred - delta
        assert walk not in visited
        visited.add(walk)
    assert walk == target and inferred != measured


def audit(noaa, bart, out):
    records = json.loads(
        gzip.decompress((out / "interval-fault-delta-ledger.json.gz").read_bytes())
    )
    all_counts = defaultdict(Counter)
    joint_probes, audited = 0, 0
    data_maximal_candidates = 0
    for saved, (key, truth, bands, edges, limit) in zip(
        records, source(noaa, bart), strict=True
    ):
        assert key == saved["id"]
        original = [(s, t, truth[t] - truth[s]) for s, t in edges]
        tags, _, _ = components(len(truth), None, original, ())
        origin = key.split("/")[0]
        if len(set(tags)) > 1:
            assert saved == {"id": key, "excluded": True}
            all_counts[origin]["disconnected"] += 1
            continue
        reports, errors = derived_reports(key, truth, edges)
        assert errors == saved["errors"]
        minimum, graph, banded = oracle(len(truth), reports, bands)
        assert minimum == saved["minimum"]
        assert banded
        cycle = saved["cycle"]
        if minimum:
            verify_cycle(cycle, reports)
        else:
            assert not cycle
        candidates = 1 + len(reports) + comb(len(reports), 2)
        assert saved["pairs_enumerated_by_oracle"] == candidates
        data_maximal_candidates += candidates
        pairs = list(combinations(range(len(truth)), 2))
        tight = minimum == 2
        if tight:
            assert saved["graph_branches"] == sum(
                any(i in e for e in graph) for i in cycle
            )
            assert saved["branches"] == sum(any(i in e for e in banded) for i in cycle)
            diagnoses = tight_metrics(saved, graph, banded, reports, pairs)
        else:
            assert not saved["graph_branches"] and not saved["branches"]
            assert all(
                saved[k] is None
                for k in (
                    "maximum_value_support",
                    "distinct_banded_repairs",
                    "reference_faults",
                )
            )
        metrics = Counter()
        for row, (s, t) in zip(saved["targets"], edges, strict=True):
            probes = [p for p in pairs if p != tuple(sorted((s, t)))]
            flags, options = sides(list(banded.values()), s, t, limit, probes)
            relative_values = set()
            for tags, offset, _ in graph.values():
                if tags[s] != tags[t]:
                    relative_values |= {False, True}
                else:
                    relative_values.add(offset[t] - offset[s] >= limit)
            relative = [flag in relative_values for flag in (False, True)]
            query = (
                next(
                    (
                        i
                        for i, (left, right) in enumerate(options)
                        if all(b < c or d < a for a, b in left for c, d in right)
                    ),
                    None,
                )
                if all(flags)
                else None
            )
            identifies = any(p in diagnoses for p in probes) if tight else None
            raw = json.dumps(options, separators=(",", ":")).encode()
            assert row == [flags, relative, query, identifies, sha256(raw).hexdigest()]
            actual = truth[t] - truth[s] >= limit
            assert flags[actual]
            if query is not None:
                u, v = probes[query]
                answer = truth[v] - truth[u]
                observed = [
                    any(a <= answer <= b for a, b in arm) for arm in options[query]
                ]
                assert observed == [not actual, actual]
            audited += 1
            joint_probes += len(probes)
            metrics.update(
                {
                    "tasks": 1,
                    "graph_decided": sum(relative) == 1,
                    "joint_decided": sum(flags) == 1,
                    "ambiguous": all(flags),
                    "guaranteed_query": query is not None,
                    "guaranteed_without_identifying": query is not None
                    and identifies is False,
                }
            )
        mode = "tight" if tight else "loose"
        for group in (origin, origin + "-" + mode, mode):
            c = all_counts[group]
            c.update(metrics)
            c.update(
                {
                    "archives": 1,
                    "graph_cycle_branches": len(cycle),
                    "band_feasible_branches": saved["branches"],
                    "oracle_deletion_sets": candidates,
                }
            )
            c["largest_cycle"] = max(c["largest_cycle"], len(cycle))
            c["maximum_value_support"] = max(
                c["maximum_value_support"], saved["maximum_value_support"] or 0
            )
    summary = json.loads((out / "interval-fault-delta-results.json").read_bytes())
    assert summary["groups"] == all_counts
    q = all_counts["tight"]
    assert summary["utility_gate"] == (
        q["archives"] >= 300
        and q["ambiguous"] >= 50
        and 10 * q["guaranteed_query"] >= q["ambiguous"]
    )
    assert summary["maximum_value_support"] == max(
        c["maximum_value_support"] for c in all_counts.values()
    )
    assert summary["largest_cycle"] == max(
        c["largest_cycle"] for c in all_counts.values()
    )
    return {
        "archives": len(records),
        "target_checks": audited,
        "probe_checks": joint_probes,
        "oracle_deletion_sets": data_maximal_candidates,
    }


def constructions():
    from interval_fault_cut import branches, inquire
    from interval_fault_delta import compile_two

    family = []
    for k in range(1, 9):
        reports = [
            edge
            for i in range(k)
            for edge in ((i, k + 1 + i, 0), (k + 1 + i, i + 1, 0), (i, i + 1, 1 << i))
        ]
        found = set()
        for choices in product((0, 2), repeat=k):
            removed = {3 * i + j for i, j in enumerate(choices)}
            tags, values, _ = components(2 * k + 1, None, reports, removed)
            assert tags == [0] * (2 * k + 1)
            found.add(values[k] - values[0])
        assert found == set(range(1 << k))
        family.append(len(found))
    widths = (13, 101, 10001)
    reports = [(0, 1, 0), (1, 2, 0), (0, 2, 1), (0, 3, 0)]
    for width in widths:
        bands = [(0, 0)] * 3 + [(1, width)]
        assert compile_two(bands, reports).minimum == 1
        valid = list(branches(4, bands, reports, 2))
        no, yes = inquire(valid, 0, 3, 1, [(0, 3)])
        assert no[0] is None and yes[1] == [[[1, width]]]
    return {"chain": family, "loose_support": widths}


def stress():
    from interval_fault_delta import compile_two

    rng = Random(86745)
    seen = Counter()
    for _ in range(160):
        n = rng.randrange(3, 8)
        edges = [(i, (i + 1) % n) for i in range(n)]
        existing = {tuple(sorted(e)) for e in edges}
        edges.extend(
            e
            for e in combinations(range(n), 2)
            if e not in existing and rng.randrange(2)
        )
        truth = [rng.randint(-4, 4) for _ in range(n)]
        fault_indices = rng.sample(range(len(edges)), rng.randrange(4))
        reports = [
            (
                u,
                v,
                truth[v]
                - truth[u]
                + (rng.choice([-6, -2, 3, 8]) if i in fault_indices else 0),
            )
            for i, (u, v) in enumerate(edges)
        ]
        bands = [(x - rng.randrange(3), x + rng.randrange(3)) for x in truth]
        minimum, graph, banded = oracle(n, reports, bands)
        packed = compile_two(bands, reports)
        assert packed.minimum == minimum
        if minimum == 2:
            assert packed.repair_coordinates() == {
                f: tuple(m[1]) for f, m in banded.items()
            }
            for s, t in combinations(range(n), 2):
                assert packed.values(s, t, ignore_intervals=True) == {
                    b[t] - b[s] for _, b, _ in graph.values()
                }
        seen[minimum] += 1
    return seen


def graph_repair_values(n, reports, limit):
    pairs = list(combinations(range(n), 2))
    for cost in range(limit + 1):
        values = [set() for _ in pairs]
        for removed in combinations(range(len(reports)), cost):
            state = components(n, None, reports, removed)
            if state is None:
                continue
            tags, coordinates, _ = state
            assert tags == [0] * n
            for (s, t), collected in zip(pairs, values, strict=True):
                collected.add(coordinates[t] - coordinates[s])
        if any(values):
            return cost, max(map(len, values))
    raise AssertionError("the reference repair must be in budget")


def sharp():
    summary = {"equal": Counter(), "unequal": Counter()}
    graphs = 0
    for n in (4, 5):
        pairs = list(combinations(range(n), 2))
        for m in range(n + 1, len(pairs) + 1):
            for edges in combinations(pairs, m):
                reports = [(a, b, 0) for a, b in edges]
                groups, _, _ = components(n, None, reports, ())
                if len(set(groups)) != 1:
                    continue
                graphs += 1
                for i, j in combinations(range(m), 2):
                    u, v = edges[i]
                    a, b = edges[j]
                    for residual in (1, -1, 2, -2):
                        reports[i], reports[j] = (u, v, 1), (a, b, residual)
                        mode = "equal" if abs(residual) == 1 else "unequal"
                        cost, count = graph_repair_values(n, reports, 2)
                        c = summary[mode]
                        c["cases"] += 1
                        c["tight"] += cost == 2
                        if cost == 2:
                            assert count <= 4
                            c["achieves_four"] += count == 4
                            c["maximum"] = max(c["maximum"], count)
                    reports[i], reports[j] = (u, v, 0), (a, b, 0)
    assert all(row["maximum"] == 4 for row in summary.values())
    rng = Random(795034)
    dissociated = defaultdict(Counter)
    for case in range(80):
        k = 1 + case % 4
        n = rng.randint(5, 8)
        tree = [(i, i + 1) for i in range(n - 1)]
        extra = [e for e in combinations(range(n), 2) if e not in tree]
        chosen = rng.sample(extra, rng.randint(k, min(k + 2, len(extra))))
        reports = [(u, v, 0) for u, v in tree + chosen[k:]]
        reports.extend(
            (u, v, rng.choice((-1, 1)) * (1 << i))
            for i, (u, v) in enumerate(chosen[:k])
        )
        cost, got = graph_repair_values(n, reports, k)
        assert cost == k and got <= (1 << k)
        dissociated[k]["cases"] += 1
        dissociated[k]["maximum"] = max(dissociated[k]["maximum"], got)
    return {"simple_graphs": graphs, "two_fault": summary, "dissociated": dissociated}


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "data": audit(*map(Path, sys.argv[1:])),
                "constructions": constructions(),
                "stress": stress(),
                "sharp": sharp(),
                "verified": True,
            }
        )
    )
