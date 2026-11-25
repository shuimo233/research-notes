"""Verify asymmetric contracts by enumerating allowed faults, then check both solvers."""

from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_asymmetric_quota import (
    compatible_labels,
    hierarchy,
    obstruction,
    split,
    two_level_conditions,
    two_level_plan,
)
from interval_fault_cut_check import components
from interval_fault_laminar_check import (
    costs_lower_than,
    independent_inventory,
    subsets_that_fail,
)
from interval_fault_noisy import Offer
from interval_fault_plan_check import all_worlds, prepared, reports_for
from interval_fault_world_tree_check import quotations

STEM = "interval-fault-asymmetric-quota"


def bitmask(indices):
    return sum(1 << i for i in indices)


def fault_masks(n, limits):
    contract = [
        ({i for i in range(n) if g & (1 << i)}, cap) for g, cap in limits.items()
    ]
    return {bitmask(s) for s in subsets_that_fail(tuple(range(n)), contract)}


def mode(key, budget, repair):
    token = "/".join((key, "asymmetric", str(budget), "repair", str(min(repair))))
    return sha256(token.encode()).digest()[0] % 3


def audit(noaa, bart, out):
    rows = json.loads(gzip.decompress((out / (STEM + "-ledger.json.gz")).read_bytes()))
    counts, matched = defaultdict(Counter), defaultdict(set)
    info = Counter()
    summary = json.loads((out / (STEM + "-results.json")).read_bytes())
    for entry, (key, budget, truth, bands, edges, _, theta, exclusion) in zip(
        rows, prepared(noaa, bart, False), strict=True
    ):
        assert (entry["id"], entry["budget"]) == (key, budget)
        tags = ("all", key.split("/")[0], f"budget-{budget}")
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
            for tag in tags:
                counts[tag][reason] += 1
            continue
        repairs = [tuple(s) for s in entry["repairs"]]
        assert len(repairs) == len(solutions) and set(repairs) == set(solutions)
        coords = [solutions[r] for r in repairs]
        assert tuple(v - truth[0] for v in truth) in coords
        targets, quotes, vendors = independent_inventory(key, budget, len(truth), edges)
        labels = [tuple(x[v] - x[u] >= theta for u, v in targets) for x in coords]
        stats = Counter(profiles=1)
        if len(set(labels)) == 1:
            assert entry["known"] == list(labels[0])
            stats["known"] += 1
            for tag in tags:
                counts[tag].update(stats)
            continue
        stats["ambiguous"] += 1
        prices = [q[0] for q in quotes]
        cols = quotations(coords, quotes)
        offers = [Offer(p, col) for p, col in zip(prices, cols, strict=True)]
        n = len(offers)
        full = (1 << n) - 1
        domains = tuple(
            bitmask(i for i, v in enumerate(vendors) if v == j) for j in range(3)
        )
        policies = [mode(key, budget, r) for r in repairs]
        caps = [
            {
                full: 2,
                **dict(
                    zip(
                        (domains[(j + k) % 3] for k in range(3)), (2, 1, 0), strict=True
                    )
                ),
            }
            for j in range(3)
        ]
        masks = [fault_masks(n, budget_row) for budget_row in caps]
        envelope = fault_masks(
            n, {g: max(caps[p][g] for p in policies) for g in (full, *domains)}
        )
        envelope_unions = {a | b for a in envelope for b in envelope}
        unions = {
            (a, b): {x | y for x in masks[a] for y in masks[b]}
            for a, b in product(range(3), repeat=2)
        }
        pairs = {
            (a, b): bitmask(i for i, c in enumerate(cols) if c[a] != c[b])
            for a, b in combinations(range(len(labels)), 2)
            if labels[a] != labels[b]
        }
        exact_pairs = [
            (d, unions[policies[a], policies[b]]) for (a, b), d in pairs.items()
        ]
        summed_pairs = [
            tuple(
                (d & g, caps[policies[a]][g] + caps[policies[b]][g])
                for g in (full, *domains)
            )
            for (a, b), d in pairs.items()
        ]

        def safe_exact(s):
            return all(s & d not in forbidden for d, forbidden in exact_pairs)

        def safe_summed(s):
            return all(
                any((s & d).bit_count() > cap for d, cap in rows)
                for rows in summed_pairs
            )

        def safe_envelope(s):
            return all(s & d not in envelope_unions for d in pairs.values())

        seen_cuts = set()
        for a, b, left, right, cut in entry["exact"]["cuts"]:
            pair = pairs[a, b]
            assert left in masks[policies[a]] and right in masks[policies[b]]
            assert not left & right and (left | right) & ~pair == 0
            assert cut == pair ^ (left | right) and cut and cut not in seen_cuts
            assert all(
                (left | right | (1 << i)) not in unions[policies[a], policies[b]]
                for i in range(n)
                if cut & (1 << i)
            )
            seen_cuts.add(cut)
        stats["cuts"] = len(seen_cuts)
        for name, safe in (
            ("exact", safe_exact),
            ("summed", safe_summed),
            ("envelope", safe_envelope),
        ):
            plan = entry[name]
            cost = plan.get("cost")
            stats[f"{name}_safe"] += cost is not None
            if cost is None:
                assert not safe(full)
                if name == "summed":
                    a, b = plan["unavailable"]
                    pair = pairs[a, b]
                    assert all(
                        (g & pair).bit_count()
                        <= caps[policies[a]][g] + caps[policies[b]][g]
                        for g in (full, *domains)
                    )
                else:
                    a, b, responses, *parts = plan["witness"]
                    assert (a, b) in pairs and len(responses) == n
                    actual = [
                        bitmask(
                            i for i, r in enumerate(responses) if tuple(r) != cols[i][w]
                        )
                        for w in (a, b)
                    ]
                    admissible = (
                        [envelope] * 2
                        if name == "envelope"
                        else [masks[policies[w]] for w in (a, b)]
                    )
                    assert all(
                        f in permitted
                        for f, permitted in zip(actual, admissible, strict=True)
                    )
                    assert not parts or parts == actual
                continue
            selected = plan["selected"]
            assert len(selected) == len(set(selected)) and all(
                0 <= i < n for i in selected
            )
            purchased = bitmask(selected)
            assert cost == sum(prices[i] for i in selected)
            assert safe(purchased) and safe_exact(purchased)
            assert not costs_lower_than(prices, cost, safe)
        exact = entry["exact"]["cost"]
        compiled, selection, positive, calls = two_level_plan(
            labels, offers, domains, [caps[p] for p in policies]
        )
        assert compiled == exact
        if compiled is not None:
            assert compiled == sum(prices[i] for i in selection) and safe_exact(
                bitmask(selection)
            )
        info.update(compiler_cases=1, positive_options=positive, solver_calls=calls)

        if exact is not None:
            tree = hierarchy(n, (full, *domains))
            prof = [tree.capacities(caps[p]) for p in policies]
            selected = entry["exact"]["selected"]
            purchased = bitmask(selected)
            for w, label in enumerate(labels):
                for mask in masks[policies[w]]:
                    if mask & ~purchased:
                        continue
                    options = []
                    for i in selected:
                        own = cols[i][w]
                        if mask & (1 << i):
                            fresh = (max(r[0] for r in cols[i]) + 1, *own[1:])
                            options.append((set(cols[i]) | {fresh}) - {own})
                        else:
                            options.append((own,))
                    for replies in product(*options):
                        assert compatible_labels(
                            labels, offers, selected, replies, tree, prof
                        ) == {label}
                        info["transcripts"] += 1

        for name in ("summed", "envelope"):
            price = entry[name].get("cost")
            if price is not None:
                assert exact <= price
                stats[f"exact_{name}_price"] = exact
                stats[f"{name}_price"] = price
                stats[f"exact_less_than_{name}"] = exact < price
        for tag in tags:
            counts[tag].update(stats)
            counts[tag]["max_cuts"] = max(counts[tag]["max_cuts"], len(seen_cuts))
            if entry["envelope"].get("cost") is not None:
                matched[tag].add(key)
    for tag, record in counts.items():
        record["matched_unique"] = len(matched[tag])
    assert counts == {tag: Counter(row) for tag, row in summary["counts"].items()}
    all_rows = counts["all"]
    assert summary["gates"] == {
        "over_envelope": len(matched["all"]) >= 100
        and 10 * all_rows["exact_envelope_price"] <= 9 * all_rows["envelope_price"],
        "over_summed": bool(all_rows["summed_price"])
        and 20 * all_rows["exact_summed_price"] <= 19 * all_rows["summed_price"],
    }
    return {"audit": dict(info), **summary}


def exercise():
    rng = Random(11307)
    checked = Counter()
    for _ in range(120):
        n = rng.randint(3, 8)
        full = (1 << n) - 1
        shuffled = list(range(n))
        rng.shuffle(shuffled)
        breaks = [0, *sorted(rng.sample(range(1, n), rng.randint(1, min(3, n - 1)))), n]
        groups = tuple(bitmask(shuffled[a:b]) for a, b in zip(breaks, breaks[1:]))
        levels = (full, *groups)
        base = [{g: rng.randrange(4) for g in levels} for _ in range(2)]
        finer = tuple(g & (g - 1) for g in groups if g.bit_count() > 2)
        deep = [p | {g: rng.randrange(4) for g in finer} for p in base]
        for rows, declared in ((base, levels), (deep, (*levels, *finer))):
            a, b = rows
            left, right = fault_masks(n, a), fault_masks(n, b)
            forbidden = {x | y for x, y in product(left, right)}
            tree = hierarchy(n, declared)
            ca, cb = tree.capacities(a), tree.capacities(b)
            alternatives = (
                two_level_conditions(
                    full, a[full], b[full], tuple((g, a[g], b[g]) for g in groups)
                )
                if rows is base
                else None
            )
            for d in range(full + 1):
                proof = split(tree, d, ca, cb)
                reject = obstruction(tree, d, ca, cb)
                assert (proof is not None) == (d in forbidden)
                if alternatives is not None:
                    assert any((s & d).bit_count() >= k for s, k in alternatives) == (
                        d not in forbidden
                    )
                    checked["compiled_masks"] += 1
                if proof is not None:
                    x, y = proof
                    assert x in left and y in right and not x & y and x | y == d
                    assert reject is None
                else:
                    g, pa, pb = reject
                    target = d & tree.masks[g]
                    for nodes in (pa, pb):
                        gm = [tree.masks[i] for i in nodes]
                        assert target & ~sum(gm) == 0
                        assert all(m & h == 0 for m, h in combinations(gm, 2))
                    assert (
                        sum(ca[i] for i in pa) + sum(cb[i] for i in pb)
                        < target.bit_count()
                    )
                checked["partition_masks"] += 1
    full, groups, d = 511, (7, 56, 448), 63
    a = {full: 3, 7: 2, 56: 2, 448: 2}
    b = {full: 3, 7: 1, 56: 1, 448: 2}
    assert all((d & g).bit_count() <= a[g] + b[g] for g in a)
    assert d not in {x | y for x, y in product(fault_masks(9, a), fault_masks(9, b))}
    assert any(
        (s & d).bit_count() >= k
        for s, k in two_level_conditions(
            full, 3, 3, tuple((g, a[g], b[g]) for g in groups)
        )
    )
    assert 1 in {
        x | y for x, y in product(fault_masks(1, {1: 1}), fault_masks(1, {1: 0}))
    }
    assert 1 not in fault_masks(1, {1: 0})
    return dict(checked)


if __name__ == "__main__":
    result = audit(*map(Path, sys.argv[1:]))
    result["finite_exercise"] = exercise()
    print(json.dumps(result))
