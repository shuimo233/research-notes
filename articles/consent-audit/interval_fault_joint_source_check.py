"""Independent all-pairs certification, best ties, and matching/hardness checks."""

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

from interval_fault_plan_check import all_worlds, prepared, reports_for
from interval_fault_source_bundle_check import connected_ring


def inventory(key, anchor, size):
    available = [i for i in range(size) if i != anchor]
    out = []
    for leaf in available:
        b = sha256(
            "/".join(map(str, (key, "shared", anchor, "one", leaf))).encode()
        ).digest()
        edge = tuple(sorted((anchor, leaf)))
        out.extend((2 + x % 6, (edge,)) for x in b[1 : 2 + b[0] % 4])
    for l, r in combinations(available, 2):
        b = sha256(
            "/".join(map(str, (key, "shared", anchor, "two", l, r))).encode()
        ).digest()
        if b[0] % 3 == 0:
            continue
        pairs = tuple(tuple(sorted((anchor, i))) for i in (l, r))
        out.extend((3 + x % 7, pairs) for x in b[2 : 3 + b[1] % 2])
    return out


def tables(coordinates, sources):
    return [
        tuple(tuple(w[v] - w[u] for u, v in pairs) for w in coordinates)
        for _, pairs in sources
    ]


def requirements(labels, answers):
    return {
        frozenset(i for i, col in enumerate(answers) if col[a] != col[b])
        for a, b in combinations(range(len(labels)), 2)
        if labels[a] != labels[b]
    }


def covers_all(chosen, coverage, demand=3):
    return all(len(chosen & requirement) >= demand for requirement in coverage)


def optimum(prices, requirement_set, demand=3, enumerate_ties=False):
    groups = tuple(
        r for r in requirement_set if not any(q < r for q in requirement_set)
    )
    n = len(prices)
    initial = (demand,) * len(groups)
    coverage = [tuple(j for j, r in enumerate(groups) if i in r) for i in range(n)]
    available = [[0] * len(groups) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row = available[i + 1][:]
        for j in coverage[i]:
            row[j] += 1
        available[i] = row

    def use(i, remain):
        row = list(remain)
        for j in coverage[i]:
            if row[j]:
                row[j] -= 1
        return tuple(row)

    @cache
    def value(i, remaining):
        if not any(remaining):
            return 0
        if any(r > c for r, c in zip(remaining, available[i], strict=True)):
            return inf
        keep = value(i + 1, remaining)
        next_state = use(i, remaining)
        return (
            min(keep, prices[i] + value(i + 1, next_state))
            if next_state != remaining
            else keep
        )

    def gather(i, remaining):
        cost = value(i, remaining)
        if not cost:
            yield 0
            return
        if value(i + 1, remaining) == cost:
            yield from gather(i + 1, remaining)
        afterward = use(i, remaining)
        if afterward != remaining and prices[i] + value(i + 1, afterward) == cost:
            for rest in gather(i + 1, afterward):
                yield rest | (1 << i)

    cost = value(0, initial)
    if cost == inf:
        return None, ()
    return cost, tuple(gather(0, initial)) if enumerate_ties else ()


def charge(mask, prices):
    return sum(p for i, p in enumerate(prices) if mask & (1 << i))


def union_of_ties(optimal_catalogs, prices):
    candidates = {0}
    for options in optimal_catalogs:
        candidates = {old | added for old in candidates for added in options}
    selected = min(candidates, key=lambda u: (charge(u, prices), u))
    for options in optimal_catalogs:
        assert any(s & selected == s for s in options)
    return charge(selected, prices), selected


def check_through_replies(labels, answers):
    from interval_fault_noisy import Offer, possible_labels

    count = 0
    wrap = [Offer(1, col) for col in answers]
    for i, label in enumerate(labels):
        normal = tuple(col[i] for col in answers)
        assert possible_labels(labels, wrap, normal, 1) == {label}
        count += 1
        for j, col in enumerate(answers):
            outsider = (max(row[0] for row in col) + 1, *normal[j][1:])
            for wrong in (set(col) | {outsider}) - {normal[j]}:
                transcript = (*normal[:j], wrong, *normal[j + 1 :])
                assert possible_labels(labels, wrap, transcript, 1) == {label}
                decoded = {
                    truth
                    for k, truth in enumerate(labels)
                    if sum(x[k] != s for x, s in zip(answers, transcript, strict=True))
                    <= 1
                }
                assert decoded == {label}
                count += 1
    return count


def verify(noaa, bart, out):
    ledger = json.loads(
        gzip.decompress(
            (out / "interval-fault-joint-source-ledger.json.gz").read_bytes()
        )
    )
    cases = [x for x in prepared(noaa, bart, False) if x[1] == 1]
    counters, tie = defaultdict(Counter), defaultdict(Counter)
    example, total_transcripts, witnesses = None, 0, 0
    for row, (key, _, values, bands, edges, _, limit, reason) in zip(
        ledger, cases, strict=True
    ):
        assert key == row["id"]
        src = key.split("/")[0]
        scores, bids = Counter(), Counter()
        if values is None:
            assert row["excluded"] == reason
            scores[reason] += 1
        else:
            graph = reports_for(key, 1, values, edges)
            solutions, refused = all_worlds(bands, graph, 1)
            assert refused is None
            states = [solutions[i,] for i in row["repairs"]]
            assert {i for (i,) in solutions} == set(row["repairs"]) and len(
                solutions
            ) == len(states)
            assert tuple(v - values[0] for v in values) in states
            scores["archives"] = 1
            multi = False
            for anchor, profile in zip(range(len(values)), row["anchors"], strict=True):
                assert profile["anchor"] == anchor
                order = profile["order"]
                assert sorted(order) == list(range(len(states)))
                coords = [states[i] for i in order]
                targets = [(u, v) for u, v in edges if anchor not in (u, v)]
                labels = [
                    tuple(w[v] - w[u] >= limit for u, v in targets) for w in coords
                ]
                active = [
                    j
                    for j in range(len(targets))
                    if len({flags[j] for flags in labels}) > 1
                ]
                assert profile["ambiguous_targets"] == len(active)
                scores["anchor_profiles"] += 1
                if not active:
                    assert profile["known"] == list(labels[0])
                    scores["known_profiles"] += 1
                    continue
                scores["ambiguous_profiles"] += 1
                offers = inventory(key, anchor, len(values))
                assert all(
                    set(pair) not in [set(t) for t in targets]
                    for _, pairs in offers
                    for pair in pairs
                )
                prices = [c for c, _ in offers]
                answers = tables(coords, offers)
                all_pairs = requirements(labels, answers)
                want, _ = optimum(prices, all_pairs)
                adjacent = [
                    i for i in range(len(labels) - 1) if labels[i] != labels[i + 1]
                ]
                assert profile["boundaries"] == adjacent
                if want is None:
                    a, b, record = profile["witness"]
                    assert labels[a] != labels[b]
                    assert all(
                        sum(
                            col[w] != tuple(z)
                            for col, z in zip(answers, record, strict=True)
                        )
                        <= 1
                        for w in (a, b)
                    )
                    witnesses += 1
                    scores["unavailable_profiles"] += 1
                    continue
                scores["safe_profiles"] += 1
                got = set(profile["joint_selected"])
                assert len(got) == len(profile["joint_selected"])
                assert profile["joint"] == want == sum(prices[i] for i in got)
                assert covers_all(got, all_pairs)
                total_transcripts += check_through_replies(
                    labels, [answers[i] for i in sorted(got)]
                )
                union = set()
                catalogues = []
                for j, chosen in zip(active, profile["individual"], strict=True):
                    single = requirements([value[j] for value in labels], answers)
                    paid, catalog = optimum(
                        prices, single, enumerate_ties=len(active) >= 2
                    )
                    chosen = set(chosen)
                    assert paid == sum(prices[i] for i in chosen) and covers_all(
                        chosen, single
                    )
                    union |= chosen
                    catalogues.append(catalog)
                charged = sum(prices[i] for i in union)
                assert charged == profile["union_price"]
                if len(active) >= 2:
                    multi = True
                    scores["joint_multi_profiles"] += 1
                    scores["joint_multi_cost"] += want
                    scores["independent_union_cost"] += charged
                    scores["strictly_better"] += want < charged
                    tie_cost, best_selected = union_of_ties(catalogues, prices)
                    assert want <= tie_cost <= charged
                    assert covers_all(
                        {i for i in range(len(prices)) if best_selected & (1 << i)},
                        all_pairs,
                    )
                    bids.update(
                        {
                            "profiles": 1,
                            "joint_cost": want,
                            "fixed_tie_union": charged,
                            "best_tie_union": tie_cost,
                            "strict_before_ties": want < charged,
                            "strict_after_ties": want < tie_cost,
                            "tie_effect_profiles": tie_cost < charged,
                        }
                    )
                    if example is None and want < tie_cost:
                        example = {
                            "id": key,
                            "anchor": anchor,
                            "joint": want,
                            "best_tie": tie_cost,
                            "fixed_tie": charged,
                        }
            scores["distinct_joint_multi_archives"] += multi
            if multi:
                bids["distinct_archives"] += 1
        for name in ("all", src):
            counters[name].update(scores)
            tie[name].update(bids)
    result = json.loads((out / "interval-fault-joint-source-results.json").read_bytes())
    assert result["counts"] == counters
    total = counters["all"]
    assert result["utility_gate"] == (
        total["distinct_joint_multi_archives"] >= 20
        and 20 * total["joint_multi_cost"] <= 19 * total["independent_union_cost"]
    )
    main = tie["all"]
    return {
        "anchors": total["anchor_profiles"],
        "replayed_transcripts": total_transcripts,
        "witnesses": witnesses,
        "tie_benchmark": dict(tie),
        "example": example,
        "best_tie_utility_gate": main["distinct_archives"] >= 20
        and 20 * main["joint_cost"] <= 19 * main["best_tie_union"],
    }


def matching_tests(rng):
    from interval_fault_joint_source import minimum_pair_cover

    statuses = Counter()
    for trial in range(200):
        n = rng.randint(2, 7)
        rows = [
            tuple(sorted(rng.sample(range(n), rng.randint(1, 2))))
            for _ in range(rng.randint(4, 15))
        ]
        demand = [1, 3, 5][trial % 3]
        if trial % 2:
            rows.extend((i,) for i in range(n) for _ in range(demand))
        prices = [rng.randint(1, 10) for _ in rows]
        old = {
            frozenset(i for i, positions in enumerate(rows) if j in positions)
            for j in range(n)
        }
        expected, _ = optimum(prices, old, demand)
        chosen = minimum_pair_cover(prices, rows, [demand] * n)
        assert expected == (None if chosen is None else sum(prices[i] for i in chosen))
        if chosen is not None:
            assert covers_all(set(chosen), old, demand)
        statuses["feasible" if chosen is not None else "infeasible"] += 1
    return statuses


def ring_portfolio(m, leaves):
    # Raw cut 0, cut 1, and the last cut share the all-false target vector.
    _, _, raw = connected_ring(m + 2)
    coords = raw[1:] + raw[:1]
    targets = tuple((i, i + 1) for i in range(1, m))
    labels = [tuple(x[v] - x[u] >= 1 for u, v in targets) for x in coords]
    offers = [(price, tuple((0, j) for j in positions)) for price, positions in leaves]
    assert all((0, j) not in targets for _, pairs in offers for _, j in pairs)
    return labels, tables(coords, offers)


def reduction_tests(rng):
    subsets = 0
    for _ in range(60):
        n = rng.randint(4, 7)
        elementary = [(0, 1)]
        degree = [1, 1] + [0] * (n - 2)
        slate = list(combinations(range(n), 2))
        rng.shuffle(slate)
        for u, v in slate:
            if (
                (u, v) not in elementary
                and degree[u] < 3
                and degree[v] < 3
                and rng.randrange(3)
            ):
                elementary.append((u, v))
                degree[u] += 1
                degree[v] += 1
        m = len(elementary)
        vertex_sources = [
            (1, [i + 1 for i, e in enumerate(elementary) if u in e]) for u in range(n)
        ]
        padding = [(1, (u, u + m)) for u in range(1, m + 1) for _ in range(2)]
        padding.extend((1, (u,)) for u in range(m + 1, 2 * m + 1))
        leaves = vertex_sources + padding
        assert all(len(pairs) <= 3 for _, pairs in leaves)
        labels, answers = ring_portfolio(2 * m, leaves)
        want = requirements(labels, answers)
        guards = set(range(n, n + len(padding)))
        assert all(not covers_all(set(range(len(leaves))) - {q}, want) for q in guards)
        old, new = inf, inf
        for mask in range(1 << n):
            chosen = {i for i in range(n) if mask & (1 << i)}
            graph_cover = all(u in chosen or v in chosen for u, v in elementary)
            physical = covers_all(guards | chosen, want)
            assert graph_cover == physical
            subsets += 1
            if graph_cover:
                old = min(old, len(chosen))
                new = min(new, len(chosen) + len(guards))
        assert new == old + 3 * m
    return {"subcubic_graphs": 60, "embedded_source_subsets": subsets}


def examples():
    from interval_fault_joint_source import joint_plan
    from interval_fault_noisy import Offer

    _, _, coords = connected_ring(4)
    labels = [(w[3] - w[0] >= 1, w[2] - w[1] >= 1) for w in coords]
    answers = tables(coords, [(1, ((0, 1),))] * 3 + [(1, ((2, 3),))] * 3)
    assert all(
        sum(col[i] != col[(i + 1) % 4] for col in answers) == 3 for i in range(4)
    )
    assert labels[0] != labels[2] and all(col[0] == col[2] for col in answers)
    try:
        joint_plan(labels, [Offer(1, col) for col in answers], 1)
    except ValueError as err:
        assert "noncontiguous" in str(err)
    else:
        raise AssertionError("unsupported native order accepted")

    portfolio = [(2, (i,)) for i in (1, 2, 3) for _ in range(3)] + [(3, (1, 3))] * 3
    labels, answers = ring_portfolio(3, portfolio)
    prices = [p for p, _ in portfolio]
    solo = [
        optimum(
            prices, requirements([w[i] for w in labels], answers), enumerate_ties=True
        )
        for i in range(2)
    ]
    joint = joint_plan(
        labels, [Offer(c, col) for c, col in zip(prices, answers, strict=True)], 1
    )
    ties, _ = union_of_ties([options for _, options in solo], prices)
    assert [c for c, _ in solo] == [12, 12]
    assert (
        optimum(prices, requirements(labels, answers))[0] == joint.cost == 15
        and ties == 18
    )
    return {
        "unaligned_adjacent_distances": [3, 3, 3, 3],
        "indistinguishable": [0, 2],
        "aligned_five_ring": {
            "individual": [12, 12],
            "best_individual_union": ties,
            "joint": joint.cost,
        },
    }


if __name__ == "__main__":
    n, b, o = map(Path, sys.argv[1:])
    rng = Random(203594)
    print(
        json.dumps(
            {
                "replay": verify(n, b, o),
                "matching": matching_tests(rng),
                "reduction": reduction_tests(rng),
                "examples": examples(),
                "verified": True,
            }
        )
    )
