"""Independently reconstruct stored cases and verify costs, policies and refusal witnesses."""

from collections import Counter, defaultdict
from functools import cache
import gzip
from hashlib import sha256
from itertools import combinations
import json
from math import inf
from pathlib import Path
from random import Random
import sys

from interval_fault_cut_check import components
from interval_fault_delta_check import compatible, derived_reports, source


def ring_of(edges):
    allowed = {frozenset(e) for e in edges}
    neighbors = sorted({v for e in edges for v in e})

    def closed(origin, remainder, prefix, remaining):
        if remaining == 0:
            return prefix if frozenset((origin, prefix[-1])) in allowed else None
        for j, v in enumerate(remainder):
            if frozenset((prefix[-1], v)) in allowed:
                candidate = closed(
                    origin,
                    remainder[:j] + remainder[j + 1 :],
                    (*prefix, v),
                    remaining - 1,
                )
                if candidate:
                    return candidate
        return None

    for size in (6, 4):
        for i, first in enumerate(neighbors[: len(neighbors) - size + 1]):
            result = closed(first, neighbors[i + 1 :], (first,), size - 1)
            if result:
                return result
    return None


def prepared(weather, bart, transfer):
    for key, values, bands, reported, limit in source(weather, bart):
        if key.startswith("weather/"):
            targets = (
                [p for p in combinations(range(len(values)), 2) if p not in reported]
                if transfer
                else reported
            )
            yield key, 1, values, bands, reported, targets, limit, None
        else:
            ring = ring_of(reported)
            if ring:
                ix = dict(zip(ring, range(len(ring)), strict=True))
                cycle = [(i, ix[ring[(i + 1) % len(ring)]]) for i in range(len(ring))]
                if transfer:
                    existing = {frozenset(p) for p in cycle}
                    targets = [
                        (ix[u], ix[v])
                        for u, v in reported
                        if {u, v} <= ix.keys()
                        and frozenset((ix[u], ix[v])) not in existing
                    ]
                else:
                    targets = cycle
                yield (
                    key,
                    1,
                    [values[i] for i in ring],
                    [bands[i] for i in ring],
                    cycle,
                    targets,
                    limit,
                    list(ring),
                )
            else:
                yield key, 1, None, None, None, None, limit, "no_cycle"
        if not transfer:
            yield key, 2, values, bands, reported, reported, limit, None


def reports_for(key, budget, values, edges):
    if budget == 2:
        return derived_reports(key, values, edges)[0]
    weather = key.startswith("weather/")
    material = key.split("/", 1)[1] if weather else key + "/1"
    a, b, c, *_ = sha256(material.encode()).digest()
    if weather:
        offset = [1, 5, 15][c % 3] * [-1, 1][b % 2]
    else:
        offset = [60, 180, 300][b % 3] * [-1, 1][c % 2]
    return [
        (s, t, values[t] - values[s] + (offset if i == a % len(edges) else 0))
        for i, (s, t) in enumerate(edges)
    ]


def all_worlds(bands, reports, budget):
    for count in range(budget + 1):
        found, world = False, {}
        for removed in combinations(range(len(reports)), count):
            model = components(len(bands), None, reports, removed)
            if model is None:
                continue
            found = True
            if count == budget and compatible(model, bands) is not None:
                assert model[0] == [0] * len(bands)
                world[removed] = tuple(model[1])
        if found:
            return world, None if count == budget else f"graph_minimum_{count}"
    raise AssertionError("injected record must have a repair")


def inventory(key, budget, count, reports, transfer):
    projected = set(frozenset(e) for e in reports)
    out = []
    for u in range(count):
        for v in range(u + 1, count):
            p = (u, v)
            prefix = "/".join(map(str, (key, budget, "probe", u, v)))
            x, y, z = sha256(prefix.encode()).digest()[:3]
            offered = frozenset(p) in projected
            if (offered or x % 3 == 0) and (not transfer or z % 3 != 0):
                out.append((u, v, y % 4 + (1 if offered else 3)))
    return out


def exact_costs(labels, tests):
    """Solve with explicit subsets and a separate partition DP for fixed selections."""
    costs = [a for a, _ in tests]
    table = [b for _, b in tests]
    n = len(labels)

    @cache
    def optimal(state):
        if len({labels[i] for i in state}) <= 1:
            return 0
        best = inf
        for i, values in enumerate(table):
            partitions = defaultdict(list)
            for j in state:
                partitions[values[j]].append(j)
            if len(partitions) > 1:
                best = min(
                    best, costs[i] + max(optimal(tuple(p)) for p in partitions.values())
                )
        return best

    root = tuple(range(n))
    adaptive = optimal(root)
    if adaptive == inf:
        return None, None
    end = {(0,) * n: 0}
    fixed = inf
    for price, answers in tests:
        following = end.copy()
        for part, value in end.items():
            if value + price >= fixed:
                continue
            number = {}
            code = tuple(
                number.setdefault(pair, len(number))
                for pair in zip(part, answers, strict=True)
            )
            answers_for_code = {}
            for label, group in zip(labels, code, strict=True):
                if group in answers_for_code and answers_for_code[group] != label:
                    break
                answers_for_code[group] = label
            else:
                fixed = min(fixed, value + price)
                continue
            following[code] = min(following.get(code, inf), value + price)
        end = following
    if len(set(labels)) == 1:
        fixed = 0
    assert fixed != inf
    return adaptive, fixed


def verify_policy(target, labels, tests, actual):
    history_lookup = {}
    realized = []
    for w, path in enumerate(target["paths"]):
        path_history = ()
        alive = list(range(len(labels)))
        paid = 0
        for i in path:
            assert i in tests and len({labels[j] for j in alive}) > 1
            assert history_lookup.setdefault(path_history, (i, None)) == (i, None)
            cost, answers = tests[i]
            paid += cost
            assert len({answers[j] for j in alive}) > 1
            path_history += ((i, answers[w]),)
            alive = [j for j in alive if answers[w] == answers[j]]
        assert alive and w in alive and all(labels[j] == labels[w] for j in alive)
        leaf = (None, labels[w])
        assert history_lookup.setdefault(path_history, leaf) == leaf
        realized.append(paid)
    assert len(realized) == len(labels)
    assert (
        realized[actual] == target["actual_cost"] and max(realized) == target["worst"]
    )


def audit(weather, bart, output, transfer):
    stem = "interval-fault-plan" + ("-transfer" if transfer else "")
    ledger = json.loads(
        gzip.decompress((output / f"{stem}-ledger.json.gz").read_bytes())
    )
    observed = defaultdict(Counter)
    strict_cases = []
    singleton, checked = 0, 0
    for saved, (key, budget, truth, bands, edges, targets, limit, ring) in zip(
        ledger, prepared(weather, bart, transfer), strict=True
    ):
        assert saved["id"] == key and saved["budget"] == budget
        source_id = key.split("/")[0]
        groups = (source_id + "-" + str(budget), str(budget), "all")
        if truth is None:
            reason = ring
        else:
            infos = [(s, t, truth[t] - truth[s]) for s, t in edges]
            tags, _, _ = components(len(truth), None, infos, ())
            if len(set(tags)) > 1:
                reason = "disconnected"
            else:
                reports = reports_for(key, budget, truth, edges)
                states, reason = all_worlds(bands, reports, budget)
        assert saved.get("excluded") == reason
        assert saved["cycle"] == (ring if isinstance(ring, list) else None)
        if reason:
            for group in groups:
                observed[group][reason] += 1
            continue
        for group in groups:
            row = observed[group]
            row["archives"] += 1
            if not targets:
                row["archives_no_targets"] += 1
            row["max_worlds"] = max(row["max_worlds"], len(states))
        keys = [tuple(e) for e in saved["repairs"]]
        assert len(keys) == len(states) and set(keys) == set(states)
        worlds = [states[f] for f in keys]
        actual = worlds.index(tuple(x - truth[0] for x in truth))
        probes = inventory(key, budget, len(truth), edges, transfer)
        tests = [(price, tuple(w[v] - w[u] for w in worlds)) for u, v, price in probes]
        for i, (entry, (s, t)) in enumerate(
            zip(saved["targets"], targets, strict=True)
        ):
            active = {
                j: test
                for j, test in enumerate(tests)
                if frozenset(probes[j][:2]) != frozenset((s, t))
            }
            labels = [x[t] - x[s] >= limit for x in worlds]
            cost, fixed = exact_costs(labels, list(active.values()))
            checked += 1
            local = Counter(targets=1)
            if cost is None:
                a, b = entry["counterexample"]
                assert labels[a] != labels[b]
                assert all(table[a] == table[b] for _, table in active.values())
                local["unsettled"] += 1
            else:
                assert (entry["worst"], entry["fixed"]) == (cost, fixed)
                verify_policy(entry, labels, active, actual)
                possible_in_one = any(
                    {v for v, yes in zip(table, labels, strict=True) if yes}.isdisjoint(
                        {v for v, yes in zip(table, labels, strict=True) if not yes}
                    )
                    for _, table in active.values()
                )
                assert entry["at_least_two"] == (bool(cost) and not possible_in_one)
                if not transfer and budget == 1:
                    assert (
                        sum(label != (reports[i][2] >= limit) for label in labels) <= 1
                    )
                    assert cost == fixed
                    singleton += bool(cost)
                if cost:
                    local.update(
                        {
                            "settleable": 1,
                            "worst": cost,
                            "fixed": fixed,
                            "realized": entry["actual_cost"],
                            "needs_multiple": not possible_in_one,
                            "strict": cost < fixed,
                        }
                    )
                    if cost < fixed:
                        strict_cases.append([key, budget, s, t, cost, fixed])
                else:
                    local["known"] += 1
            for group in groups:
                observed[group].update(local)
    archived = json.loads((output / f"{stem}-results.json").read_bytes())
    assert archived["counts"] == observed
    count = observed["all"]
    assert archived["utility_gate"] == (
        count["settleable"] >= 50 and (not transfer or count["unsettled"] >= 20)
    )
    assert archived["cost_gate"] == bool(
        count["fixed"] and count["worst"] * 20 <= count["fixed"] * 19
    )
    return {
        "archives": len(ledger),
        "targets": checked,
        "one_label_signature_cases": singleton,
        "strict_cases": strict_cases,
        "world_witnesses": count["unsettled"],
    }


def exercise():
    from interval_fault_path import compile_path
    from interval_fault_plan import Probe, fixed_cost, interval_plan

    rng = Random(881709)
    counts = Counter()
    for case in range(600):
        n = rng.randint(2, 11)
        left, right = sorted(rng.sample(range(n + 1), 2))
        labels = [left <= i < right for i in range(n)]
        intervals = list(combinations(range(n + 1), 2))
        selected = rng.sample(intervals, rng.randint(1, min(12, len(intervals))))
        if case % 5 == 0 and len(set(labels)) == 2:
            a, b = labels.index(True), labels.index(False)
            selected = [(z, w) for z, w in selected if (z <= a < w) == (z <= b < w)]
        probes = [
            Probe(rng.randint(1, 8), tuple(a <= i < b for i in range(n)), (a, b))
            for a, b in selected
        ]
        want = exact_costs(labels, [(p.cost, p.answers) for p in probes])
        got = interval_plan(labels, probes)
        assert (got.cost, fixed_cost(labels, probes)) == want
        if got.cost is None:
            a, b = got.counterexample
            assert labels[a] != labels[b] and all(
                q.answers[a] == q.answers[b] for q in probes
            )
        else:
            walks = [got.walk(i) for i in range(n)]
            assert max(x[1] for x in walks) == got.cost
            assert [x[0] for x in walks] == labels
        counts["fixed_exceeds_adaptive"] += want[0] is not None and want[0] < want[1]
        counts["impossible"] += got.cost is None
    chain = {}
    for n in (16, 32, 64, 128):
        intervals = {(i, i + 1) for i in range(n - 1)} | {(0, i) for i in range(1, n)}
        labels = [False] * (n - 1) + [True]
        probes = [
            Probe(1, tuple(a <= i < b for i in range(n)), (a, b))
            for a, b in sorted(intervals)
        ]
        root = interval_plan(labels, probes)
        assert root.cost == 1
        chain[n] = {
            "structured_states": root.visited,
            "unpruned_ambiguous_states": (1 << (n - 1)) - 1,
        }
    packed = compile_path(
        [(0, 2)] * 4, [(0, 1, 0), (1, 2, 0), (2, 3, 0), (0, 3, 1)], reference_edge=3
    )
    q = [(1, 3), (0, 3), (1, 2)]
    vals = [
        tuple(packed.value_at(u, v, edge) for edge in packed.repair_edges) for u, v in q
    ]
    probes = [
        Probe(1, table, packed.partition(u, v)[2:])
        for table, (u, v) in zip(vals, q, strict=True)
    ]
    labels = [packed.value_at(0, 2, edge) >= 1 for edge in packed.repair_edges]
    policy = interval_plan(labels, probes)
    assert labels == [False, True, True, False]
    assert (policy.cost, fixed_cost(labels, probes)) == (2, 3)
    cursor = policy.start()
    cursor.next_probe()
    try:
        cursor.observe(99)
    except ValueError:
        assert cursor.charges == 0 and cursor.state == policy.root
    else:
        raise AssertionError("an impossible reply was accepted")
    return {
        "cases": 600,
        "counts": counts,
        "chain": chain,
        "four_cycle": {"adaptive": 2, "fixed": 3, "labels": labels, "reply_rows": vals},
    }


def ring_gap():
    from interval_fault_path import compile_path
    from interval_fault_plan import Probe, interval_plan

    result = {}
    for h in (*range(2, 10), 16, 32, 64):
        n = 2 * h
        reports = [(i, i + 1, 0) for i in range(n - 1)] + [(0, n - 1, 1)]
        bands = [(0, 1)] * n
        model = compile_path(bands, reports, reference_edge=n - 1)
        independent, reason = all_worlds(bands, reports, 1)
        assert reason is None and len(independent) == n
        assert model.repair_edges == (n - 1, *range(n - 1))
        worlds = [independent[e,] for e in model.repair_edges]
        labels = [x[-1] - x[h - 1] >= 1 for x in worlds]
        assert labels == [False] * h + [True] * h
        paired = [(h - j - 1, h + j - 1) for j in range(1, h)]
        singles = [(i - 1, i) if i else (0, n - 1) for i in range(h)]
        probes = [
            Probe(1, tuple(x[v] - x[u] for x in worlds), model.partition(u, v)[2:])
            for u, v in paired + singles
        ]
        for i in range(h):
            left = i
            right = n - 1 - i
            distinguished = [
                j for j, q in enumerate(probes) if q.answers[left] != q.answers[right]
            ]
            assert distinguished == [h - 1 + i]
        assert (
            len({tuple(q.answers[i] for q in probes[h - 1 :]) for i in range(h, n)})
            == 1
        )
        assert not any(
            all(q.answers[i] == q.answers[-1] for q in probes[h - 1 :])
            for i in range(h)
        )
        best = interval_plan(labels, probes)
        formula = 1 + (h - 1).bit_length()
        assert best.cost == formula
        traces = [best.walk(i) for i in range(n)]
        assert [x[0] for x in traces] == labels and max(x[1] for x in traces) == formula
        if h < 10:
            assert exact_costs(labels, [(q.cost, q.answers) for q in probes]) == (
                formula,
                h,
            )
        result[h] = {"fixed": h, "adaptive": formula, "crossing_states": best.visited}
    return result


if __name__ == "__main__":
    noaa, bart, out = map(Path, sys.argv[1:])
    print(
        json.dumps(
            {
                "main": audit(noaa, bart, out, False),
                "transfer": audit(noaa, bart, out, True),
                "synthetic": exercise(),
                "ring_gap": ring_gap(),
                "verified": True,
            }
        )
    )
