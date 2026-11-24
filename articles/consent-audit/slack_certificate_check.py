"""Recompute reports and prove small disclosure by disjoint raw-constraint counterexamples."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys


def potential(n, edges, source=None):
    d = [0] * n if source is None else [float("inf")] * n
    if source is not None:
        d[source] = 0
    for _ in range(n):
        changed = False
        for u, v, weight in edges:
            trial = d[u] + weight
            if trial < d[v]:
                d[v] = trial
                changed = True
        if not changed:
            return d
    return None


def problem(row):
    times = [0]
    for _, start, end in row["steps"]:
        times.extend((start, end))
    n = len(times)
    graph = []
    for i, t in enumerate(times[1:], 1):
        lo = t - t % 60
        graph.extend(((0, i, lo + 59), (i, 0, -lo)))
    pairs = (
        [(1, n - 1)]
        + [(i, i + 1) for i in range(1, n - 1, 2)]
        + [(i, i + 1) for i in range(2, n - 1, 2)]
    )

    def old_cuts(i, u):
        if i == 0:
            return 0, 60, 600
        if u % 2:
            return 0, 1, 10, 60, 300
        return 0, 1, 10

    def new_cuts(i, u):
        if i == 0:
            return 30, 120, 300, 900
        if u % 2:
            return 1, 5, 30, 120
        return -1, 0, 2, 5

    labels, claims = [], []
    targets = []
    for i, (u, v) in enumerate(pairs):
        d = times[v] - times[u]
        old, new = old_cuts(i, u), new_cuts(i, u)
        for cuts, edges in ((old, graph), (new, claims)):
            below = [cut for cut in cuts if d < cut]
            above = [cut for cut in cuts if d >= cut]
            if below:
                edges.append((u, v, min(below) - 1))
            if above:
                edges.append((v, u, -max(above)))
        targets.append((u, v, new))
        labels.append(sum(d >= t for t in new))
    return times, graph, claims, labels, targets


def attach(edges, disclosed):
    return [*edges, *(edge for i, t in disclosed for edge in ((0, i, t), (i, 0, -t)))]


def missing(n, edges, claims):
    bound = {}
    for u, v, b in claims:
        if u not in bound:
            bound[u] = potential(n, edges, u)
            assert bound[u] is not None
        if bound[u][v] > b:
            yield u, v, b


def packing(times, archive, claims, selected):
    n = len(times)
    disclosed = set(selected)
    already = set()
    groups = []
    for i in selected:
        frozen = (disclosed - {i}) | already
        pinned = attach(archive, [(j, times[j]) for j in sorted(frozen)])
        beyond = next(missing(n, pinned, claims), None)
        if beyond is None:
            return groups
        u, v, b = beyond
        crossing = [*pinned, (v, u, -b - 1)]
        alt = potential(n, crossing)
        assert alt is not None
        for j in range(1, n):
            if j in frozen or j == i:
                continue
            proposal = attach(crossing, [(j, times[j])])
            witness = potential(n, proposal)
            if witness is not None:
                crossing, alt = proposal, witness
        reference = alt[0]
        alt = [x - reference for x in alt]
        support = {j for j in range(1, n) if alt[j] != times[j]}
        assert support & disclosed == {i} and support.isdisjoint(already)
        assert all(alt[v] - alt[u] <= w for u, v, w in archive)
        assert alt[v] - alt[u] > b
        groups.append(support)
        already.update(support)
    return groups


def replay(fixtures, folder):
    source = json.loads(gzip.decompress(fixtures.read_bytes()))
    with gzip.open(folder / "slack-certificate-ledger.jsonl.gz", "rt") as stream:
        ledger = list(map(json.loads, stream))
    groups = defaultdict(Counter)
    packing_checks = Counter()
    for f, row in zip(source, ledger, strict=True):
        assert (f["repo"], f["run"], f["job"]) == (row["repo"], row["run"], row["job"])
        times, archive, obligations, expected, targets = problem(f)
        assert expected == row["labels"] and len(times) - 1 == row["timepoints"]
        n = len(times)
        checked = set()
        for path in row["paths"].values():
            assert len(path) == len(set(path)) and all(0 < i < n for i in path)
            frozen = tuple(sorted(path))
            if frozen in checked:
                continue
            pinned = attach(archive, [(i, times[i]) for i in path])
            assert not list(missing(n, pinned, obligations))
            checked.add(frozen)
        fixed = row["paths"]["fixed"]
        assert row["paths"]["all"] == list(range(1, n))
        dist = [potential(n, archive, i) for i in range(n)]
        classes = [
            min(j for j in range(n) if dist[i][j] == -dist[j][i]) for i in range(n)
        ]
        pending_sites = {
            i
            for u, v, cuts in targets
            if any(-dist[v][u] < cut <= dist[u][v] for cut in cuts)
            for i in (classes[u], classes[v])
        }
        assert fixed == sorted(pending_sites - {0})
        selected = row["paths"]["optimum"]
        for shift in range(max(1, len(selected))):
            order = selected[shift:] + selected[:shift]
            disjoint = packing(times, archive, obligations, order)
            if len(disjoint) == len(selected):
                break
        assert sum(map(len, disjoint)) == len(set().union(*disjoint))
        lower = len(disjoint)
        size = len(row["paths"]["optimum"])
        assert lower == row["lower"] == size and row["solved"]
        packing_checks["singleton_witnesses"] += sum(len(w) == 1 for w in disjoint)
        packing_checks["shared_witnesses"] += sum(len(w) > 1 for w in disjoint)
        packing_checks["proof_groups"] += lower
        for name in (row["repo"], "total"):
            c = groups[name]
            c["jobs"] += 1
            c["labels"] += len(row["labels"])
            c["solved"] += row["solved"]
            for item in ("lower", "nodes", "raw_rows", "minimal_rows"):
                c[item] += row[item]
            for item, field in (
                ("max_timepoints", "timepoints"),
                ("max_rows", "minimal_rows"),
                ("max_nodes", "nodes"),
            ):
                c[item] = max(c[item], row[field])
            c.update({k: len(p) for k, p in row["paths"].items()})
            if row["solved"]:
                c["solved_greedy"] += len(row["paths"]["greedy"])
                c["solved_optimum"] += size
    result = json.loads((folder / "slack-certificate-results.json").read_bytes())
    assert groups == result["by_source"]
    counts = groups["total"]
    checks = {
        "count": counts["jobs"] >= 200,
        "greedy_fixed": counts["greedy"] / counts["fixed"] <= 0.9,
        "optimum_best": counts["optimum"] / min(counts["sequential"], counts["reverse"])
        <= 0.97,
        "solved": counts["solved"] / counts["jobs"] >= 0.99,
        "greedy_optimum": counts["solved_greedy"] / counts["solved_optimum"] <= 1.05,
    }
    assert checks == result["gates"] and result["gate"] == all(checks.values())
    return dict(jobs=len(source), labels=counts["labels"], **packing_checks)


def synthetic():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from conclusion_replay import closure
    from slack_certificate import (
        Cover,
        classifications,
        claims,
        counterfactual,
        minimal_rows,
        reduced_slack,
        rows_for_claims,
        visible,
    )

    rng = Random(347169)
    sums = Counter()
    for _ in range(450):
        count = rng.randint(2, 5)
        bands = [
            (lo, lo + rng.randrange(4))
            for lo in (rng.randint(-4, 1) for _ in range(count))
        ]
        truth = (0, *(rng.randint(lo, hi) for lo, hi in bands))
        pairs = list(combinations(range(count + 1), 2))
        facts, targets = [], []
        for u, v in pairs:
            d = truth[v] - truth[u]
            if rng.random() < 0.5:
                facts.append((u, v, d - rng.randrange(3), d + rng.randrange(3)))
            if rng.random() < 0.45:
                targets.append((u, v, tuple(sorted(rng.sample(range(-5, 6), 3)))))
        targets.extend((v, u, cuts) for u, v, cuts in targets[:] if rng.random() < 0.22)
        matrix = closure(bands, facts)
        slack = reduced_slack(matrix, truth)
        report = classifications(targets, truth)
        world = [
            value
            for value in (
                (0, *z) for z in product(*(range(lo, hi + 1) for lo, hi in bands))
            )
            if all(lo <= value[v] - value[u] <= hi for u, v, lo, hi in facts)
        ]

        def changed(x):
            return visible(
                i for i, (a, b) in enumerate(zip(x, truth, strict=True)) if a != b
            )

        bounds = list(claims(targets, report))
        compiled = rows_for_claims(matrix, slack, truth, bounds)
        for u, v, b in bounds:
            rows = rows_for_claims(matrix, slack, truth, [(u, v, b)])
            supports = {changed(x) for x in world if x[v] - x[u] > b}
            literal = {
                s for s in supports if not any(t != s and t & s == t for t in supports)
            }
            assert set(minimal_rows(rows)) == literal
            assert len(literal) <= count
            sums["bounds"] += 1
            for mask, (a, c, _, height, split) in rows.items():
                alt = counterfactual(slack, truth, a, c, height, split)
                assert (
                    alt in world and alt[c] - alt[a] == b + 1 and changed(alt) == mask
                )
                sums["explicit_worlds"] += 1
        bad = [changed(x) for x in world if classifications(targets, x) != report]
        exact = count
        for mask in range(0, 1 << (count + 1), 2):
            enough = all(mask & r for r in bad)
            assert enough == all(mask & r for r in compiled)
            if enough:
                exact = min(exact, mask.bit_count())
            sums["subsets"] += 1
        cover = Cover(minimal_rows(compiled), count + 1)
        optimum, lower, _, done = cover.minimum((cover.greedy(),), limit=10_000)
        assert done and len(optimum) == lower == exact
        sums["zones"] += 1

    # Binary reduction of set cover with one strict greedy gap.
    memberships = ({0, 1, 3, 4}, {0, 1, 2}, {3, 4, 5})
    count = 1 + len(memberships) + 6
    facts = [
        (1 + i, 4 + e, -1, 0) for i, members in enumerate(memberships) for e in members
    ]
    bands = [(0, 1)] * (count - 1)
    matrix = closure(bands, facts)
    truth = (0,) * count
    bounds = [(0, i, 0) for i in range(4, count)]
    compiled = rows_for_claims(matrix, reduced_slack(matrix, truth), truth, bounds)
    solver = Cover(minimal_rows(compiled), count)
    greedy = solver.greedy()
    assert len(greedy) == 3
    best, lower, _, done = solver.minimum((greedy,), limit=0)
    assert (best, lower, done) == (greedy, 2, False)
    best, lower, nodes, done = solver.minimum((greedy,), limit=100)
    assert best == (2, 3) and lower == 2 and done and nodes > 0

    # A huge integer span still has exactly n minimal counterfactual supports.
    for n in (2, 8, 32):
        t = [10**9 * i for i in range(n)]
        h = t[-1]
        matrix = closure(
            [(-h, h)] * n,
            [(i + 1, j + 1, 0, t[j] - t[i]) for i, j in combinations(range(n), 2)],
        )
        truth = (0,) * (n + 1)
        compiled = rows_for_claims(
            matrix, reduced_slack(matrix, truth), truth, [(1, n, h - 1)]
        )
        want = {(1 << (n + 1)) - 2 - (1 << i) for i in range(1, n + 1)}
        assert set(minimal_rows(compiled)) == want
    return dict(sums, greedy_gap=[3, 2], tight_rows=[2, 8, 32])


def source_check(fixtures, source, raw):
    manifest = json.loads(source.read_bytes())
    payload = gzip.decompress(fixtures.read_bytes())
    assert sha256(payload).hexdigest() == manifest["fixture_sha256"]
    assert len(json.loads(payload)) == manifest["records"]
    if raw is not None:
        for r in manifest["sources"]:
            repo = r["repo"].replace("/", "--")
            file = raw / f"{repo}--{r['id']}--{r['run_attempt']}.json"
            assert sha256(file.read_bytes()).hexdigest() == r["raw_sha256"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("fixtures", type=Path)
    p.add_argument("folder", type=Path)
    p.add_argument("source", type=Path)
    p.add_argument("--raw", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    source_check(a.fixtures, a.source, a.raw)
    print(
        json.dumps(
            dict(replay=replay(a.fixtures, a.folder), exhaustive=synthetic()), indent=2
        )
    )
