"""Independently verify fixed reads against two counterfactual copies of each archive."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
from statistics import median_low
import sys


ARCHIVE_PAIRS = ((1, 2), (1, 3), (1, 4), (1, 5), (2, 3), (4, 5))
PAIRS = tuple(combinations(range(1, 6), 2))
STATIONS = {
    "california": ("23234", "23230", "23293", "23232", "23213"),
    "new_york": ("14732", "94789", "14734", "94741", "13739"),
}


def observations(snapshot):
    months, daily = defaultdict(list), defaultdict(dict)
    with gzip.open(snapshot, "rt", encoding="ascii") as stream:
        for row in csv.DictReader(stream):
            station, date = row["station"], row["date"]
            value = int(row["tmax_tenths"])
            if date < "2018":
                months[station, date[5:7]].append(value)
            if date.startswith("2025-"):
                daily[date][station] = value
    medians = {k: median_low(v) for k, v in months.items()}
    for date, readings in daily.items():
        for region, members in STATIONS.items():
            stations = tuple("USW000" + u for u in members)
            if not set(stations) <= readings.keys():
                continue
            data = tuple(readings[u] for u in stations)
            base = tuple(medians[u, date[5:7]] for u in stations)
            low = [x - (x - m) % 20 for x, m in zip(data, base, strict=True)]
            yield (date, region), (0, *data), low


def shortest_paths(n, edges, source):
    distance = [float("inf")] * n
    distance[source] = 0
    for _ in range(n - 1):
        changed = False
        for u, v, w in edges:
            step = distance[u] + w
            if step < distance[v]:
                distance[v] = step
                changed = True
        if not changed:
            break
    assert all(distance[v] <= distance[u] + w for u, v, w in edges)
    return distance


def feasible(n, edges):
    # Implicit super-source of cost zero to each vertex.
    potential = [0] * n
    for _ in range(n):
        changed = False
        for u, v, w in edges:
            proposed = potential[u] + w
            if proposed < potential[v]:
                potential[v] = proposed
                changed = True
        if not changed:
            return True
    return False


def cross_cuts(dist, targets):
    return [
        (u, v, t)
        for u, v, cuts in targets
        for t in cuts
        if -dist[v][u] < t <= dist[u][v]
    ]


def coordinates(dist, represented):
    return {
        min(u for u, row in enumerate(dist) if row[v] == -dist[v][u])
        for v in represented
        if dist[0][v] != -dist[v][0]
    }


def most_needed(dist, targets):
    active = cross_cuts(dist, targets)
    return len(coordinates(dist, (p for u, v, _ in active for p in (u, v))))


def agree_on(n, edges, observed, crossings):
    # The left world has d < cut, the right world has d >= cut.
    shifted = [(u + n, v + n, w) for u, v, w in edges]
    equalities = [
        edge for u in (0, *observed) for edge in ((u, n + u, 0), (n + u, u, 0))
    ]
    both = edges + shifted + equalities
    return all(
        not feasible(2 * n, [*both, (u, v, t - 1), (v + n, u + n, -t)])
        for u, v, t in crossings
    )


def reveal(edges, i, value):
    return [*edges, (0, i, value), (i, 0, -value)]


def all_paths(n, edges):
    return [shortest_paths(n, edges, i) for i in range(n)]


def audit(row, truth, lows):
    count = len(truth)
    assert row["lows"] == lows
    cold = [arc for u, x in enumerate(lows, 1) for arc in ((0, u, x + 19), (u, 0, -x))]
    constraints = list(cold)
    old = []
    for u, v in ARCHIVE_PAIRS:
        t = truth[v] - truth[u]
        state = 0 if t <= -10 else 2 if t >= 10 else 1
        old.append(state)
        if state == 0:
            constraints.append((u, v, -10))
        elif state == 2:
            constraints.append((v, u, -10))
        else:
            constraints.extend(((u, v, 9), (v, u, 9)))
    assert row["archive"] == old
    tolerance = row["tolerance"]
    targets = [(u, v, (1 - tolerance, tolerance)) for u, v in PAIRS]
    raw = [bisect_right(cuts, truth[v] - truth[u]) for u, v, cuts in targets]
    assert row["labels"] == raw
    dist = all_paths(count, constraints)
    crossings = cross_cuts(dist, targets)
    paths = row["paths"]
    assert paths["all"] == list(range(1, count))
    cold_graph = all_paths(count, cold)
    cold_required = {p for u, v, _ in cross_cuts(cold_graph, targets) for p in (u, v)}
    assert paths["cold"] == sorted(cold_required)
    archived = dict(zip(ARCHIVE_PAIRS, old, strict=True))
    local_required = set()
    for u, v, cuts in targets:
        lo, hi = -cold_graph[v][u], cold_graph[u][v]
        category = archived.get((u, v))
        if category == 0:
            hi = min(hi, -10)
        elif category == 1:
            lo, hi = max(lo, -9), min(hi, 9)
        elif category == 2:
            lo = max(lo, 10)
        if any(lo < cut <= hi for cut in cuts):
            local_required.update((u, v))
    assert paths["local"] == sorted(local_required)
    known = {}

    def certifies(sequence):
        key = tuple(sorted(sequence))
        if key in known:
            return known[key]
        pinned = list(constraints)
        for i in key:
            pinned.extend(((0, i, truth[i]), (i, 0, -truth[i])))
        result = not cross_cuts(all_paths(count, pinned), targets)
        known[key] = result
        return result

    for path in paths.values():
        assert len(path) == len(set(path)) and all(1 <= i < count for i in path)
        assert certifies(path)
    fixed = paths["fixed"]
    assert agree_on(count, constraints, fixed, crossings)
    assert coordinates(dist, fixed) == set(fixed)
    for i in fixed:
        # All points outside this entire rigid component leave a disagreement.
        outside = [j for j in range(1, count) if dist[i][j] != -dist[j][i]]
        assert not agree_on(count, constraints, outside, crossings)
    oracle = paths["oracle"]
    for size in range(len(oracle)):
        assert not any(certifies(s) for s in combinations(range(1, count), size))
    choices = []
    if len(fixed) > 1:
        for i in sorted(coordinates(dist, range(1, count))):
            values = range(-dist[i][0], dist[0][i] + 1)
            budgets = (
                most_needed(all_paths(count, reveal(constraints, i, value)), targets)
                for value in values
            )
            choices.append((1 + max(budgets), i))
    budget, first = min(choices, default=(len(fixed), None))
    best = min(len(fixed), budget)
    assert best == row["budget"]
    probe = paths["probe"]
    if best < len(fixed):
        assert probe[0] == first
        assert len(probe) == 1 + most_needed(
            all_paths(count, reveal(constraints, first, truth[first])), targets
        )
    else:
        assert probe == fixed
    return len(fixed)


def synthetic():
    # The production routines are called only when checking against literal worlds.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conclusion_replay import closure, first_probe, interval, necessary, pin

    rng = Random(186773)
    cases, rigid_examples, branches = 0, 0, 0
    for _ in range(350):
        n = rng.randrange(2, 6)
        mins = [rng.randint(-4, 1) for _ in range(n)]
        ends = [lo + rng.randrange(4) for lo in mins]
        bands = tuple(zip(mins, ends, strict=True))
        truth = (0, *(rng.randint(lo, hi) for lo, hi in bands))
        pairs = tuple(combinations(range(n + 1), 2))
        facts = []
        for u, v in pairs:
            if rng.random() < 0.42:
                diff = truth[v] - truth[u]
                facts.append((u, v, diff - rng.randrange(3), diff + rng.randrange(3)))
        worlds = [
            (0, *values)
            for values in product(*(range(lo, hi + 1) for lo, hi in bands))
            if all(
                lo <= (0, *values)[v] - (0, *values)[u] <= hi for u, v, lo, hi in facts
            )
        ]
        targets = [
            (u, v, tuple(sorted(rng.sample(range(-5, 6), 2))))
            for u, v in pairs
            if rng.random() < 0.5
        ]
        matrix = closure(bands, facts)
        for u, v in pairs:
            vals = [w[v] - w[u] for w in worlds]
            assert interval(matrix, u, v) == (min(vals), max(vals))
            assert set(vals) == set(range(min(vals), max(vals) + 1))
            if u and max(vals) == min(vals) and len({w[u] for w in worlds}) > 1:
                rigid_examples += 1

        outputs = {
            w: tuple(bisect_right(cuts, w[v] - w[u]) for u, v, cuts in targets)
            for w in worlds
        }

        def sufficient(support, subset):
            signatures = {}
            for w in support:
                seen = tuple(w[i] for i in subset)
                if signatures.setdefault(seen, outputs[w]) != outputs[w]:
                    return False
            return True

        def minimum(support):
            return next(
                size
                for size in range(n + 1)
                if any(
                    sufficient(support, s) for s in combinations(range(1, n + 1), size)
                )
            )

        fixed = necessary(matrix, targets)
        assert sufficient(worlds, fixed) and len(fixed) == minimum(worlds)
        first, budget = first_probe(matrix, targets, fixed)
        expected = len(fixed)
        for i in range(1, n + 1):
            sub = []
            for value in {w[i] for w in worlds}:
                fiber = [w for w in worlds if w[i] == value]
                conditioned = pin(matrix, i, value)
                for u, v in pairs:
                    vals = [w[v] - w[u] for w in fiber]
                    assert interval(conditioned, u, v) == (min(vals), max(vals))
                continuation = necessary(conditioned, targets)
                need = minimum(fiber)
                assert len(continuation) == need and sufficient(fiber, continuation)
                sub.append(need)
                branches += 1
            expected = min(expected, 1 + max(sub))
        assert budget == expected and (first is not None) == (expected < len(fixed))
        cases += 1
    try:
        pin(closure([(-3, -1)]), 1, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("an infeasible exact read was accepted")
    try:
        closure([(0, 1), (0, 1)], [(1, 2, 2, 3)])
    except ValueError:
        pass
    else:
        raise AssertionError("an inconsistent archive was accepted")
    # A nontarget selector can reduce m necessary fixed reads to worst-case two.
    gap = {}
    for m in (3, 8, 24):
        archive = closure(
            [(0, m - 1), *([(0, m)] * m)], [(1, u, 0, 1) for u in range(2, m + 2)]
        )
        targets = [(0, u, (u - 1,)) for u in range(2, m + 2)]
        fixed = necessary(archive, targets)
        assert len(fixed) == m and 1 not in fixed
        assert first_probe(archive, targets, fixed) == (1, 2)
        gap[m] = 2
    return dict(
        synthetic=cases,
        rigid_pair_occurrences=rigid_examples,
        pin_branches=branches,
        selector_gap=gap,
    )


def check(snapshot, folder):
    days = {k: (truth, lows) for k, truth, lows in observations(snapshot)}
    roster = {(date, region, tol) for date, region in days for tol in (8, 12)}
    totals = defaultdict(Counter)
    with gzip.open(folder / "conclusion-replay-ledger.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            k = row["date"], row["region"], row["tolerance"]
            roster.remove(k)
            mandatory = audit(row, *days[k[:2]])
            for group in ("total", str(k[2]), f"{k[1]}/{k[2]}"):
                counts = totals[group]
                counts["reports"] += 1
                counts["labels"] += len(row["labels"])
                counts.update({mode: len(path) for mode, path in row["paths"].items()})
                counts["probe_worst_bound"] += row["budget"]
                counts["probe_strict_bound"] += row["budget"] < mandatory
                counts["fixed_zero"] += not mandatory
    assert not roster
    expected = json.loads((folder / "conclusion-replay-results.json").read_bytes())
    assert totals == expected["by_source"]
    counts = totals["total"]
    assert expected["distinct_region_dates"] == len(days)
    assert expected["gate"] == (
        len(days) >= 500 and 20 * (counts["local"] - counts["fixed"]) >= counts["local"]
    )
    return dict(counts, mandatory_components=counts["fixed"], **synthetic())


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("folder", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.snapshot, a.folder), indent=2))
