"""Audit price and safety through allowed faults and interval intersections."""

from collections import Counter
from functools import cache
import gzip
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_asymmetric_quota_check import bitmask, fault_masks, mode as policy
from interval_fault_cut_check import components
from interval_fault_laminar_check import costs_lower_than, independent_inventory
from interval_fault_noisy import Offer
from interval_fault_plan_check import all_worlds, prepared, reports_for
from interval_fault_shared_calibration import (
    certificate_sources,
    compatible_labels,
    disagreement_sweep,
    plan,
)
from interval_fault_shared_calibration_run import INVENTORIES, MODES, STEM, summarize
from interval_fault_world_tree_check import quotations


def opposite_pairs(labels, offers, offsets, errors, faults):
    unions = {}
    for a, b in combinations(range(len(labels)), 2):
        if labels[a] == labels[b]:
            continue
        # The independent oracle combines allowable faults, then tests for a
        # single value in the intersection of all remaining closed intervals.
        low = offsets[a][0] - offsets[b][1]
        high = offsets[a][1] - offsets[b][0]
        left, right = [], []
        for q, e in zip(offers, errors, strict=True):
            gaps = tuple(v - u for u, v in zip(q.values[a], q.values[b], strict=True))
            left.append(max(low, max(gaps) - 2 * e))
            right.append(min(high, min(gaps) + 2 * e))
        key = id(faults[a]), id(faults[b])
        if key not in unions:
            unions[key] = {x | y for x, y in product(faults[a], faults[b])}
        yield a, b, left, right, unions[key]


def conflict_oracle(intervals_left, intervals_right, allowed, marginal=False):
    if marginal:
        forced = bitmask(
            i
            for i, (lo, hi) in enumerate(
                zip(intervals_left, intervals_right, strict=True)
            )
            if lo > hi
        )
        return lambda observed: (forced & observed) in allowed

    largest = sorted(range(len(intervals_left)), key=lambda i: -intervals_left[i])
    smallest = sorted(range(len(intervals_right)), key=lambda i: intervals_right[i])
    low_order = [(1 << i, intervals_left[i]) for i in largest]
    high_order = [(1 << i, intervals_right[i]) for i in smallest]

    @cache
    def common(observed):
        def intersection(omitted):
            if omitted not in allowed:
                return False
            survivors = observed & ~omitted
            if not survivors:
                return True
            x, lower = next((bit, v) for bit, v in low_order if bit & survivors)
            y, upper = next((bit, v) for bit, v in high_order if bit & survivors)
            if lower <= upper:
                return True
            # Every feasible allowed failure set must hit the two incompatible
            # witnesses. All other supersets can be skipped.
            return intersection(omitted | x) or (x != y and intersection(omitted | y))

        return intersection(0)

    return common


def portfolios(labels, offers, offsets, errors, faults, marginal=False):
    tests = []
    registered = set()
    for _, _, left, right, allowed in opposite_pairs(
        labels, offers, offsets, errors, faults
    ):
        feature = (tuple(left), tuple(right), id(allowed))
        if feature not in registered:
            registered.add(feature)
            tests.append(conflict_oracle(left, right, allowed, marginal))
    return lambda observed: all(not test(observed) for test in tests)


def verify_witness(proof, labels, offers, offsets, errors, faults, method):
    a, b, biases, replies, failing_a, failing_b = proof
    assert a in range(len(labels)) and b in range(len(labels))
    assert labels[a] != labels[b]
    assert len(replies) == len(offers) == len(biases)
    if method != "marginal":
        assert len(set(map(tuple, biases))) == 1
    fa, fb = [], []
    for i, (reply, (ta, tb), q, error) in enumerate(
        zip(replies, biases, offers, errors, strict=True)
    ):
        assert (
            offsets[a][0] <= ta <= offsets[a][1]
            and offsets[b][0] <= tb <= offsets[b][1]
        )
        mismatches = [
            any(
                abs(value - truth - bias) > error
                for value, truth in zip(reply, q.values[w], strict=True)
            )
            for w, bias in ((a, ta), (b, tb))
        ]
        if mismatches[0]:
            fa.append(i)
        if mismatches[1]:
            fb.append(i)
    assert bitmask(fa) == failing_a in faults[a]
    assert bitmask(fb) == failing_b in faults[b]


def audit(weather, bart, out):
    rows = json.loads(gzip.decompress((out / (STEM + "-ledger.json.gz")).read_bytes()))
    replay, rejected, certificates = Counter(), Counter(), Counter()
    for entry, (key, budget, truth, bands, edges, _, theta, exclusion) in zip(
        rows, prepared(weather, bart, False), strict=True
    ):
        assert (entry["id"], entry["budget"]) == (key, budget)
        reason = exclusion if truth is None else None
        if truth is not None:
            relative = [(a, b, truth[b] - truth[a]) for a, b in edges]
            if len(set(components(len(truth), None, relative, ())[0])) > 1:
                reason = "disconnected"
            else:
                solutions, reason = all_worlds(
                    bands, reports_for(key, budget, truth, edges), budget
                )
        assert entry.get("excluded") == reason
        if reason:
            continue
        repairs = [tuple(r) for r in entry["repairs"]]
        assert len(repairs) == len(solutions) and set(repairs) == set(solutions)
        coords = [solutions[r] for r in repairs]
        assert tuple(v - truth[0] for v in truth) in coords
        targets, quotes, vendors = independent_inventory(key, budget, len(truth), edges)
        labels = [tuple(x[v] - x[u] >= theta for u, v in targets) for x in coords]
        if len(set(labels)) == 1:
            assert entry["known"] == list(labels[0])
            continue
        columns = quotations(coords, quotes)
        original = [Offer(p, col) for (p, _), col in zip(quotes, columns, strict=True)]
        radius = 6 if key.startswith("weather/") else 90
        bias = [(-radius, radius)] * len(labels)
        policies = [policy(key, budget, repair) for repair in repairs]
        for variant in INVENTORIES:
            offers, slots = original[:], vendors[:]
            if variant == "references":
                offers.extend(Offer(p, ((0,),) * len(labels)) for p in (4, 5, 6))
                slots.extend((0, 1, 2))
            n = len(offers)
            full = (1 << n) - 1
            group = [
                bitmask(i for i, j in enumerate(slots) if j == v) for v in range(3)
            ]
            allowances = [
                {
                    full: 2,
                    **{group[(j + k) % 3]: cap for k, cap in enumerate((2, 1, 0))},
                }
                for j in range(3)
            ]
            listed = [fault_masks(n, c) for c in allowances]
            faults = [listed[j] for j in policies]
            limits = [allowances[j] for j in policies]
            prices = [q.cost for q in offers]
            errors = [1] * n
            shared = portfolios(labels, offers, bias, errors, faults)
            selected_shared = None
            for method in MODES:
                bounds = [(0, 0)] * len(labels) if method == "zero" else bias
                safe = (
                    shared
                    if method == "shared"
                    else portfolios(
                        labels, offers, bounds, errors, faults, method == "marginal"
                    )
                )
                rec = entry[variant][method]
                if rec["cost"] is None:
                    assert not rec["selected"] and not safe(full)
                    verify_witness(
                        rec["proof"], labels, offers, bounds, errors, faults, method
                    )
                    if method == "shared":
                        assert (
                            len(
                                compatible_labels(
                                    labels,
                                    offers,
                                    range(n),
                                    rec["proof"][3],
                                    limits,
                                    bias,
                                    errors,
                                )
                            )
                            >= 2
                        )
                    continue
                s = rec["selected"]
                assert len(s) == len(set(s)) and all(i in range(n) for i in s)
                purchased = bitmask(s)
                assert safe(purchased) and sum(prices[i] for i in s) == rec["cost"]
                assert not costs_lower_than(prices, rec["cost"], safe)
                if method == "shared":
                    selected_shared = purchased, s
                if method == "marginal":
                    assert shared(purchased)
                if method == "zero":
                    rejected[variant] += not shared(purchased)
            if selected_shared is None:
                continue
            purchased, s = selected_shared
            for a, b, left, right, allowed in opposite_pairs(
                labels, offers, bias, errors, faults
            ):
                local = certificate_sources(
                    tuple(zip(left, right, strict=True)),
                    s,
                    limits[a][full] + limits[b][full],
                    (-2 * radius, 2 * radius),
                )
                assert set(local) <= set(s) and len(local) <= 10
                assert not conflict_oracle(left, right, allowed)(bitmask(local))
                certificates[variant] += 1
            for w, label in enumerate(labels):
                for failure in faults[w]:
                    if failure & ~purchased:
                        continue
                    for t in (-radius, 0, radius):
                        reply = [
                            tuple(
                                x
                                + t
                                + (1 if j % 2 else -1)
                                + (10_000 if failure & (1 << i) else 0)
                                for j, x in enumerate(offers[i].values[w])
                            )
                            for i in s
                        ]
                        assert compatible_labels(
                            labels, offers, s, reply, limits, bias, errors
                        ) == {label}
                        replay[variant] += 1
    actual = summarize(rows)
    assert json.loads((out / (STEM + "-results.json")).read_bytes()) == actual
    return {
        "summary": actual,
        "zero_purchase_unsafe": dict(rejected),
        "shared_replay": dict(replay),
        "short_pair_certificates": dict(certificates),
    }


def exercise():
    rng = Random(68051)
    checks = 0
    for _ in range(100):
        n = rng.randint(3, 8)
        full = (1 << n) - 1
        first = bitmask(rng.sample(range(n), rng.randint(1, n - 1)))
        groups = first, full ^ first
        labels = (0, 1)
        offers = [
            Offer(
                rng.randint(1, 7),
                tuple(tuple(rng.randint(-4, 4) for _ in range(k)) for _ in labels),
            )
            for k in (rng.randint(1, 3) for _ in range(n))
        ]
        bounds = [
            (x, x + rng.randint(0, 4)) for x in (rng.randint(-3, 1) for _ in labels)
        ]
        tolerances = [rng.randrange(3) for _ in range(n)]
        limits = [{g: rng.randrange(4) for g in (full, *groups)} for _ in labels]
        faults = [fault_masks(n, row) for row in limits]
        for method in MODES:
            active = [(0, 0)] * 2 if method == "zero" else bounds
            safe = portfolios(
                labels, offers, active, tolerances, faults, method == "marginal"
            )
            a, b, left, right, allowed = next(
                opposite_pairs(labels, offers, active, tolerances, faults)
            )
            bands = active[a][0] - active[b][1], active[a][1] - active[b][0]
            intervals = tuple(zip(left, right, strict=True))
            states = list(disagreement_sweep(intervals, bands))
            best = None
            for s in range(full + 1):
                if method != "marginal":
                    exact = all((s & d) not in allowed for d, _ in states)
                    assert exact == safe(s)
                    positions = [i for i in range(n) if s & (1 << i)]
                    short = certificate_sources(
                        intervals, positions, limits[a][full] + limits[b][full], bands
                    )
                    assert safe(bitmask(short)) == exact
                if safe(s):
                    spend = sum(q.cost for i, q in enumerate(offers) if s & (1 << i))
                    best = min(best, spend) if best is not None else spend
                checks += 1
            result = plan(labels, offers, groups, limits, bounds, tolerances, method)
            assert result.cost == best
            if best is None:
                verify_witness(
                    result.proof, labels, offers, active, tolerances, faults, method
                )
            else:
                assert safe(bitmask(result.selected))
    # The two closed intervals share exactly the endpoint. Dropping that
    # boundary would falsely certify a portfolio.
    assert (0, 0) in disagreement_sweep(((-2, 0), (0, 2)), (-2, 2))
    # Uniform cap r has tight 2(r+1) support bound even with point intervals.
    r = 4
    offers = tuple([(-1, -1)] * (r + 1) + [(1, 1)] * (r + 1))
    full = (1 << len(offers)) - 1
    allowed = {s for s in range(full + 1) if s.bit_count() <= r}
    safe = conflict_oracle(*zip(*offers), allowed)
    assert not safe(full) and all(safe(full ^ (1 << i)) for i in range(len(offers)))
    return {
        "market_mode_portfolios": checks,
        "random_markets": 100,
        "tight_support_bound": 10,
    }


if __name__ == "__main__":
    result = audit(*map(Path, sys.argv[1:]))
    result["finite_exercise"] = exercise()
    print(json.dumps(result))
