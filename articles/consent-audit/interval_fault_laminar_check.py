"""Rebuild configured budgets and compare purchases with explicit fault unions."""

from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_cut_check import components
from interval_fault_noisy import Offer
from interval_fault_plan_check import all_worlds, prepared, reports_for
from interval_fault_source_bundle_check import connected_ring
from interval_fault_world_tree_check import independent_market, quotations


def independent_inventory(key, budget, size, edges):
    targets, quotes = independent_market(key, budget, size, edges)
    original = len(quotes) - 3
    forest = quotes[-1][1]
    for j in range(3, 7):
        b = sha256(
            "/".join(map(str, (key, "tree", budget, "full", j))).encode()
        ).digest()
        quotes.append((7 + 2 * len(forest) + b[0] % 7, forest))
    stem = "/".join(map(str, (key, "quota", budget))) + "/"
    rotation = sha256((stem + "rotation").encode()).digest()[0] % 3
    labels = [
        sha256((stem + f"domain/{i}").encode()).digest()[0] % 3 for i in range(original)
    ]
    labels += [(i + rotation) % 3 for i in range(7)]
    return targets, quotes, labels


def subsets_that_fail(positions, limits):
    selected = set(positions)
    covered = set().union(*(g for g, _ in limits))
    total = len(selected - covered) + sum(cap for _, cap in limits)
    total = min([total, *(cap for g, cap in limits if selected <= g)])
    for k in range(min(len(positions), total) + 1):
        for s in combinations(positions, k):
            chosen = set(s)
            if all(len(g & chosen) <= cap for g, cap in limits):
                yield s


def official_limits(domains):
    groups = [
        (set(i for i, label in enumerate(domains) if label == j), 1) for j in range(3)
    ]
    all_ids = set(range(len(domains)))
    return {
        "nested": [(all_ids, 2), *groups],
        "domains": groups,
        "flat_two": [(all_ids, 2)],
        "flat_one": [(all_ids, 1)],
    }


def can_confuse(limits, n):
    all_masks = [
        sum(1 << i for i in bad) for bad in subsets_that_fail(tuple(range(n)), limits)
    ]
    return {a | b for a in all_masks for b in all_masks}


def costs_lower_than(prices, threshold, exact):
    ordered = sorted(range(len(prices)), key=lambda i: prices[i])
    suffix = [0] * (len(prices) + 1)
    for j in range(len(ordered) - 1, -1, -1):
        suffix[j] = suffix[j + 1] | (1 << ordered[j])

    def seek(index, spent, mask):
        if exact(mask):
            return True
        if index >= len(ordered) or spent + prices[ordered[index]] >= threshold:
            return False
        if not exact(mask | suffix[index]):
            return False
        for j in range(index, len(ordered)):
            i = ordered[j]
            charge = spent + prices[i]
            if charge >= threshold:
                break
            if seek(j + 1, charge, mask | (1 << i)):
                return True
        return False

    return seek(0, 0, 0)


def certificate(entry, offers, chosen, labels, limits, extended):
    if extended:
        a, b, reply, ea, eb = entry
    else:
        a, b, reply = entry
    assert labels[a] != labels[b] and len(reply) == len(chosen)
    actual = [
        set(
            i
            for i, ans in zip(chosen, reply, strict=True)
            if offers[i].values[w] != tuple(ans)
        )
        for w in (a, b)
    ]
    for s in actual:
        assert all(len(s & source) <= k for source, k in limits)
    if extended:
        assert (ea, eb) == tuple(sum(1 << i for i in s) for s in actual)


def replay_errors(labels, offers, chosen, limits):
    from interval_fault_laminar import Quota, label_options

    q = tuple(Quota(sum(1 << i for i in s), cap) for s, cap in limits)
    pattern = tuple(subsets_that_fail(chosen, limits))
    by_index = {i: j for j, i in enumerate(chosen)}
    cases = 0
    for world, truth in enumerate(labels):
        correct = [offers[i].values[world] for i in chosen]
        for bad in pattern:
            alternatives = []
            for i in bad:
                history = offers[i].values
                own = correct[by_index[i]]
                sample = (max(x[0] for x in history) + 1, *own[1:])
                alternatives.append((set(history) | {sample}) - {own})
            for replacement in product(*alternatives):
                observed = correct.copy()
                for i, value in zip(bad, replacement, strict=True):
                    observed[by_index[i]] = value
                assert label_options(labels, offers, chosen, observed, q) == {truth}
                cases += 1
    return cases


def audit(noaa, bart, out):
    data = json.loads(
        gzip.decompress((out / "interval-fault-laminar-ledger.json.gz").read_bytes())
    )
    checked, matched = defaultdict(Counter), defaultdict(set)
    diagnostics, example = Counter(), None
    for entry, (key, budget, truth, bands, edges, _, theta, selection) in zip(
        data, prepared(noaa, bart, False), strict=True
    ):
        assert (entry["id"], entry["budget"]) == (key, budget)
        labels_for_count = ("all", key.split("/")[0], f"budget-{budget}")
        if truth is None:
            reason = selection
        else:
            relative = [(a, b, truth[b] - truth[a]) for a, b in edges]
            connected = len(set(components(len(truth), None, relative, ())[0])) == 1
            if connected:
                solutions, reason = all_worlds(
                    bands, reports_for(key, budget, truth, edges), budget
                )
            else:
                reason = "disconnected"
        assert entry.get("excluded") == reason
        if reason:
            for tag in labels_for_count:
                checked[tag][reason] += 1
            continue
        ids = [tuple(x) for x in entry["repairs"]]
        coords = [solutions[x] for x in ids]
        assert set(ids) == solutions.keys() and len(ids) == len(solutions)
        assert tuple(x - truth[0] for x in truth) in coords
        targets, quotes, categories = independent_inventory(
            key, budget, len(truth), edges
        )
        labels = [tuple(x[v] - x[u] >= theta for u, v in targets) for x in coords]
        counters = Counter(profiles=1)
        if len(set(labels)) == 1:
            assert entry["known"] == list(labels[0])
            counters["known"] += 1
            for tag in labels_for_count:
                checked[tag].update(counters)
            continue
        counters["ambiguous"] = 1
        cols = quotations(coords, quotes)
        offers = [
            Offer(price, col) for (price, _), col in zip(quotes, cols, strict=True)
        ]
        prices = [q.cost for q in offers]
        conditions = official_limits(categories)
        opp = {}
        for a, b in combinations(range(len(labels)), 2):
            if labels[a] != labels[b]:
                opp[a, b] = sum((col[a] != col[b]) << i for i, col in enumerate(cols))
        for mode, limits in conditions.items():
            forbidden = can_confuse(limits, len(offers))
            distinct = set(opp.values())

            def safe(mask):
                return all((x & mask) not in forbidden for x in distinct)

            plan = entry[mode]
            if "witness" in plan:
                assert not safe((1 << len(offers)) - 1)
                certificate(
                    plan["witness"],
                    offers,
                    tuple(range(len(offers))),
                    labels,
                    limits,
                    mode in ("nested", "domains"),
                )
                diagnostics["unavailable"] += 1
                continue
            chosen = tuple(plan["selected"])
            assert len(set(chosen)) == len(chosen)
            mask = sum(1 << i for i in chosen)
            assert safe(mask) and sum(prices[i] for i in chosen) == plan["cost"]
            assert not costs_lower_than(prices, plan["cost"], safe), (key, mode)
            diagnostics[mode + "_optimal"] += 1
            diagnostics[mode + "_transcripts"] += replay_errors(
                labels, offers, chosen, limits
            )
        counters["nested_safe"] += "cost" in entry["nested"]
        counters["flat_two_safe"] += "cost" in entry["flat_two"]
        counters["domains_safe"] += "cost" in entry["domains"]
        old = entry["flat_one"].get("selected")
        found = entry.get("flat_one_insufficient")
        if old is not None:
            chosen = sum(1 << i for i in old)
            confluent = can_confuse(conditions["nested"], len(offers))
            invalid = any(x & chosen in confluent for x in opp.values())
            assert invalid == bool(found)
            if invalid:
                certificate(
                    found, offers, tuple(old), labels, conditions["nested"], True
                )
                counters["old_flat_one_insufficient"] += 1
                if example is None:
                    a, b, _, fa, fb = found
                    example = {
                        "id": key,
                        "budget": budget,
                        "worlds": [a, b],
                        "mismatches": [fa.bit_count(), fb.bit_count()],
                        "selected": old,
                        "nested": entry["nested"]["cost"],
                        "flat_two": entry["flat_two"]["cost"],
                    }
            else:
                counters["old_flat_one_insufficient"] += 0
        else:
            assert found is None
            counters["old_flat_one_insufficient"] += 0
        assert 0 <= entry["matching_calls"] <= entry["calls"]
        counters["calls"] = entry["calls"]
        counters["matching_calls"] = entry["matching_calls"]
        if "cost" in entry["flat_two"]:
            n, f = entry["nested"]["cost"], entry["flat_two"]["cost"]
            assert n <= f
            counters.update(
                matched=1, nested_matched=n, flat_two_matched=f, nested_saves=n < f
            )
            for tag in labels_for_count:
                matched[tag].add(key)
        if "cost" in entry["domains"]:
            n, q = entry["nested"]["cost"], entry["domains"]["cost"]
            assert n <= q
            counters.update(
                domain_matched_profiles=1,
                domain_matched_price=q,
                nested_domain_matched_price=n,
                global_quota_saves=n < q,
            )
        for tag in labels_for_count:
            checked[tag].update(counters)
    for tag in checked:
        checked[tag]["unique_matched"] = len(matched[tag])
    published = json.loads((out / "interval-fault-laminar-results.json").read_bytes())
    assert published["counts"] == checked
    c = checked["all"]
    assert published["utility_gate"] == (
        c["unique_matched"] >= 100
        and 10 * c["nested_matched"] <= 9 * c["flat_two_matched"]
    )
    return {
        "checked_profiles": c["profiles"],
        "exact": diagnostics,
        "old_contract_witness": example,
    }


def check_laminar(rng):
    from interval_fault_laminar import Quota, common_reply, normalize, separated

    outcomes = Counter()
    for _ in range(120):
        n = rng.randint(3, 8)
        symbols = rng.sample(range(n), n)
        split = rng.randint(1, n - 1)
        pieces = [symbols[:split], symbols[split:]]
        parent = max(pieces, key=len)
        cut = rng.randint(1, len(parent) - 1)
        groups = [set(x) for x in [symbols, *pieces, parent[:cut], parent[cut:]]]
        raw = [(x, rng.randint(0, 3)) for x in groups]
        quotas = normalize([Quota(sum(1 << i for i in g), b) for g, b in raw], n)
        allowed = can_confuse(raw, n)
        for mask in range(1 << n):
            assert (mask not in allowed) == separated(mask, quotas)
            outcomes["difference_sets"] += 1
            if mask in allowed:
                data = [Offer(1, (0, (mask >> i) & 1)) for i in range(n)]
                a, b, actual, aa, bb = common_reply(data, 0, 1, tuple(range(n)), quotas)
                assert (a, b) == (0, 1)
                for w, invalid in ((0, aa), (1, bb)):
                    assert (
                        sum(
                            (old.values[w] != y) << i
                            for i, (old, y) in enumerate(zip(data, actual, strict=True))
                        )
                        == invalid
                    )
                outcomes["equal_transcripts"] += 1
    triangle = [({0, 1}, 1), ({1, 2}, 1), ({0, 2}, 1)]
    assert 7 not in can_confuse(triangle, 3)
    assert not any(len(s) > 2 * b for s, b in triangle)
    try:
        normalize([Quota(sum(1 << i for i in s), b) for s, b in triangle], 3)
    except ValueError:
        pass
    else:
        raise AssertionError("unrestricted overlaps were accepted")
    return outcomes


def subcubic(rng):
    n = rng.randint(4, 7)
    edges = [(i, i + 1, rng.randint(1, 10)) for i in range(n - 1)]
    degrees = [1, *([2] * (n - 2)), 1]
    candidates = [(u, v) for u, v in combinations(range(n), 2) if v - u > 1]
    rng.shuffle(candidates)
    for u, v in candidates:
        if degrees[u] < 3 and degrees[v] < 3 and rng.randrange(3):
            edges.append((u, v, rng.randint(1, 10)))
            degrees[u] += 1
            degrees[v] += 1
    return n, edges, degrees


def graph_purchase(n, edges, degrees, modes):
    prices, hits, colors = [], [], []

    def add(price, over, color):
        if over:
            prices.append(price)
            hits.append(tuple(over))
            colors.append(color)

    for a, b, weight in edges:
        for c in range(modes):
            add(weight, [v for v in (a, b) if v >= modes or v == c], c)
    for u in range(n):
        for c in range(modes):
            if u >= modes or u == c:
                for _ in range(3 - degrees[u]):
                    add(1, (u,), c)
    return prices, hits, colors


def cut_opt(n, edges, modes):
    optimum = min(
        sum(w for u, v, w in edges if labels[u] != labels[v])
        for rest in product(range(modes), repeat=n - modes)
        for labels in [(*range(modes), *rest)]
    )
    return optimum


def check_complexity(rng):
    from interval_fault_laminar import Quota, quota_cover, quota_plan, tight_two_domains

    metrics = Counter()
    for modes in (2, 3):
        for k in range(40):
            n, edges, degrees = subcubic(rng)
            prices, hits, domains = graph_purchase(n, edges, degrees, modes)
            masks = defaultdict(int)
            for i, (domain, rows) in enumerate(zip(domains, hits, strict=True)):
                for v in rows:
                    masks[v, domain] |= 1 << i
            assert all(mask.bit_count() == 3 for mask in masks.values())
            grouped = tuple(
                tuple((masks[v, c], 3) for c in range(modes) if (v, c) in masks)
                for v in range(n)
            )
            constant = sum(w for _, _, w in edges) + sum(3 - d for d in degrees)
            theory = constant + cut_opt(n, edges, modes)
            assert quota_cover(prices, grouped)[0] == theory
            metrics[f"{modes}_domains"] += 1
            if modes == 2:
                assert tight_two_domains(n, prices, hits, domains)[0] == theory
            elif k < 10:
                _, _, points = connected_ring(n + 2)
                labels = [
                    tuple(w[i + 1] - w[i] >= 1 for i in range(1, n)) for w in points
                ]
                offers = [
                    Offer(
                        price,
                        tuple(tuple(w[v + 1] - w[0] for v in group) for w in points),
                    )
                    for price, group in zip(prices, hits, strict=True)
                ]
                quotas = [
                    Quota(sum((x == g) << j for j, x in enumerate(domains)), 1)
                    for g in range(modes)
                ]
                assert quota_plan(labels, offers, quotas).cost == theory
                metrics["ring_embeddings"] += 1
    return metrics


if __name__ == "__main__":
    noaa, bart, output = map(Path, sys.argv[1:])
    rng = Random(302871)
    print(
        json.dumps(
            {
                "replay": audit(noaa, bart, output),
                "laminar": check_laminar(rng),
                "complexity": check_complexity(rng),
                "verified": True,
            }
        )
    )
