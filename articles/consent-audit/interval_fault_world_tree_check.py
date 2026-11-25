"""Verify every decision from all opposed pairs and audit the two tree notions."""

from collections import Counter, defaultdict
from fractions import Fraction
import gzip
from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_cut_check import components
from interval_fault_joint_source_check import check_through_replies, covers_all, optimum
from interval_fault_noisy import Offer
from interval_fault_plan_check import all_worlds, prepared, reports_for


def independent_market(key, budget, size, edges):
    stem = "/".join((key, "tree", str(budget))) + "/"
    parity = sha256((stem + "targets").encode()).digest()[0] & 1
    targets = list(edges)[parity::2]
    excluded = {frozenset(p) for p in targets}
    allowed = [p for p in combinations(range(size), 2) if frozenset(p) not in excluded]
    market = []
    for i in range(12):
        if not allowed:
            break
        batch = sha256((stem + "offer/" + str(i)).encode()).digest()
        pairs = sorted(allowed, key=lambda p: sha256(batch + bytes([*p])).hexdigest())
        root = pairs[0][0]
        kept = tuple(p for p in pairs if root in p)[: 1 + batch[0] % 3]
        market.append((2 + len(kept) + batch[1] % 8, kept))
    links = []
    reached = list(range(size))
    for u, v in allowed:
        if reached[u] != reached[v]:
            old = reached[v]
            reached = [reached[u] if earlier == old else earlier for earlier in reached]
            links.append((u, v))
    for i in range(3):
        h = sha256((stem + "full/" + str(i)).encode()).hexdigest()
        market.append((7 + 2 * len(links) + int(h[:2], 16) % 7, tuple(links)))
    return targets, market


def quotations(worlds, market):
    return [
        tuple(tuple(state[v] - state[u] for u, v in edges) for state in worlds)
        for _, edges in market
    ]


def requirements(labels, answers):
    grouped = defaultdict(list)
    for i, j in combinations(range(len(labels)), 2):
        if labels[i] != labels[j]:
            supported = frozenset(
                k for k, col in enumerate(answers) if col[i] != col[j]
            )
            grouped[supported].append((i, j))
    retained = {
        x: y for x, y in grouped.items() if all(not other < x for other in grouped)
    }
    return grouped, retained


def edge_rank(n, edges):
    owner = list(range(n))
    merges = 0
    for a, b in edges:
        if owner[a] != owner[b]:
            old = owner[b]
            owner = [owner[a] if i == old else i for i in owner]
            merges += 1
    return merges


def task_tree(n, retained):
    if len(retained) >= n:
        return False
    blocks = tuple(retained.values())
    return all(
        edge_rank(n, (p for group in part for p in group)) >= length
        for length in range(1, len(blocks) + 1)
        for part in combinations(blocks, length)
    )


def inspect_tree(n, answers, recorded):
    pairs = [(i, j) for i, j in recorded["edges"]]
    assert len(pairs) == n - 1 == edge_rank(n, pairs)
    w = {
        (i, j): sum(column[i] == column[j] for column in answers)
        for i, j in combinations(range(n), 2)
    }
    edge_score = sum(w[tuple(sorted(e))] for e in pairs)
    assert edge_score == recorded["agreement"]
    assert recorded["upper"] == sum(n - len(set(col)) for col in answers)
    # Maximum spanning tree cycle optimality, independently of the production ordering.
    adjacency = [[] for _ in range(n)]
    for a, b in pairs:
        z = w[tuple(sorted((a, b)))]
        adjacency[a].append((b, z))
        adjacency[b].append((a, z))
    for i in range(n):
        minimum = {i: len(answers)}
        queue = [i]
        for a in queue:
            for v, cost in adjacency[a]:
                if v not in minimum:
                    minimum[v] = min(cost, minimum[a])
                    queue.append(v)
        assert all(w[i, b] <= minimum[b] for b in range(i + 1, n))
    if edge_score == recorded["upper"]:
        for col in answers:
            assert sum(col[a] != col[b] for a, b in pairs) == len(set(col)) - 1
    return pairs, edge_score == recorded["upper"]


def greedy(prices, constraints):
    picked = set()
    gap = {s: 3 for s in constraints}
    while any(gap.values()):
        residual = [s for s, d in gap.items() if d]
        choice = min(
            (i for i in range(len(prices)) if i not in picked),
            key=lambda i: (
                -Fraction(sum(i in s for s in residual), prices[i]),
                prices[i],
                i,
            ),
        )
        assert any(choice in s for s in residual)
        picked.add(choice)
        for s in residual:
            if choice in s:
                gap[s] -= 1
    for i in sorted(picked, key=lambda j: (prices[j], j), reverse=True):
        if covers_all(picked - {i}, constraints):
            picked.remove(i)
    return picked, sum(prices[i] for i in picked)


def audit(noaa, bart, out):
    ledger = json.loads(
        gzip.decompress((out / "interval-fault-world-tree-ledger.json.gz").read_bytes())
    )
    scores, cohort, extra = defaultdict(Counter), defaultdict(set), defaultdict(Counter)
    witnessed, transmissions = 0, 0
    for row, (key, budget, truth, intervals, edges, _, threshold, reason) in zip(
        ledger, prepared(noaa, bart, False), strict=True
    ):
        assert (row["id"], row["budget"]) == (key, budget)
        if truth is None:
            exclusion = reason
        else:
            check_edges = [(u, v, truth[v] - truth[u]) for u, v in edges]
            family = components(len(truth), None, check_edges, ())[0]
            if len(set(family)) > 1:
                exclusion = "disconnected"
            else:
                reported = reports_for(key, budget, truth, edges)
                solutions, exclusion = all_worlds(intervals, reported, budget)
        assert row.get("excluded") == exclusion
        tags = ("all", key.split("/")[0], f"budget-{budget}")
        if exclusion:
            for tag in tags:
                scores[tag][exclusion] += 1
            continue
        ids = [tuple(arr) for arr in row["repairs"]]
        assert set(ids) == set(solutions) and len(ids) == len(solutions)
        coords = [solutions[i] for i in ids]
        assert tuple(n - truth[0] for n in truth) in coords
        targets, market = independent_market(key, budget, len(truth), edges)
        prices = [price for price, _ in market]
        labels = [tuple(v[b] - v[a] >= threshold for a, b in targets) for v in coords]
        counters = Counter(profiles=1)
        if len(set(labels)) == 1:
            assert row["known"] == list(labels[0])
            counters["known"] += 1
            for tag in tags:
                scores[tag].update(counters)
            continue
        values = quotations(coords, market)
        all_pairs, constraints = requirements(labels, values)
        assert sum(len(ps) for ps in all_pairs.values()) == row["opposite_pairs"]
        packed = {}
        for mask, pair in row["constraints"]:
            keyset = frozenset(i for i in range(len(market)) if (1 << i) & mask)
            assert (
                tuple(pair) in constraints[keyset]
                or tuple(pair[::-1]) in constraints[keyset]
            )
            packed[keyset] = pair
        assert packed.keys() == constraints.keys() and len(packed) == len(
            row["constraints"]
        )
        tree, convex = inspect_tree(len(coords), values, row["tree"])
        candidate_count = (
            sum(labels[a] != labels[b] for a, b in tree)
            if convex
            else row["opposite_pairs"]
        )
        assert row["candidate_pairs"] == candidate_count
        supported = task_tree(len(coords), constraints)
        assert not convex or supported
        anchor = set(range(len(truth)))
        for column, (_, pairs) in zip(values, market, strict=True):
            if len(set(column)) > 1:
                anchor &= {v for pair in pairs for v in pair}
        assert row["common_vertices"] == sorted(anchor)
        full = set(range(len(market) - 3, len(market)))
        full_price = (
            sum(prices[i] for i in full) if covers_all(full, all_pairs) else None
        )
        assert full_price == row["full_price"]
        wide = Counter(
            tuple(j for j, s in enumerate(constraints) if i in s)
            for i in range(len(market))
        )
        wide = {k: v for k, v in wide.items() if len(k) > 2}
        assert (
            len(wide) == row["wide_types"]
            and sum(min(3, k) for k in wide.values()) == row["wide_sources"]
        )
        counters.update(
            {
                "ambiguous": 1,
                "tree_recognized": convex,
                "full_pairs": row["opposite_pairs"],
                "pairs_after_tree": candidate_count,
                "constraints": len(constraints),
                "matching_calls": row["matching_calls"],
            }
        )
        review = Counter(
            target_tree=supported,
            target_tree_without_answer_tree=supported and not convex,
            no_target_tree=not supported,
        )
        exact, _ = optimum(prices, set(all_pairs))
        if exact is None:
            i, j, witness = row["witness"]
            assert labels[i] != labels[j]
            assert all(
                sum(
                    col[k] != tuple(rep)
                    for col, rep in zip(values, witness, strict=True)
                )
                <= 1
                for k in (i, j)
            )
            assert row["matching_calls"] == 0
            witnessed += 1
            counters["unavailable"] += 1
        else:
            selected = set(row["selected"])
            assert len(selected) == len(row["selected"])
            assert exact == row["price"] == sum(prices[i] for i in selected)
            assert covers_all(selected, all_pairs)
            transmissions += check_through_replies(
                labels, [values[i] for i in sorted(selected)]
            )
            purchase, charge = greedy(prices, constraints)
            assert covers_all(purchase, all_pairs) and charge >= exact
            review.update(
                {
                    "exact_price": exact,
                    "greedy_price": charge,
                    "greedy_strict": charge > exact,
                    "pure_without_target_tree": row["wide_sources"] == 0
                    and not supported,
                }
            )
            assert row["matching_calls"] >= 1
            counters["safe"] += 1
            if row["wide_sources"] == 0:
                counters["pure_matching"] += 1
                counters["pure_without_physical_anchor"] += not anchor
                counters["pure_without_tree"] += not convex
            if full_price is not None:
                counters.update(
                    {
                        "matched": 1,
                        "baseline_price": full_price,
                        "optimized_price": exact,
                    }
                )
                for tag in tags:
                    cohort[tag].add(key)
        for tag in tags:
            scores[tag].update(counters)
            scores[tag]["max_wide_sources"] = max(
                scores[tag]["max_wide_sources"], row["wide_sources"]
            )
            scores[tag]["max_wide_types"] = max(
                scores[tag]["max_wide_types"], row["wide_types"]
            )
            extra[tag].update(review)
    for tag in scores:
        scores[tag]["matched_distinct_archives"] = len(cohort[tag])
    archived = json.loads((out / "interval-fault-world-tree-results.json").read_bytes())
    assert archived["counts"] == scores
    top = scores["all"]
    assert archived["gates"] == {
        "practical": top["matched_distinct_archives"] >= 50
        and 10 * top["optimized_price"] <= 9 * top["baseline_price"],
        "structure": top["pure_without_physical_anchor"] >= 20,
    }
    a = extra["all"]
    return {
        "checked_profiles": top["profiles"],
        "replies": transmissions,
        "witnesses": witnessed,
        "followup": dict(sorted(extra.items())),
        "greedy_gate": 20 * a["exact_price"] <= 19 * a["greedy_price"],
    }


def trees(n):
    for code in product(range(n), repeat=n - 2):
        degree = [1 + code.count(i) for i in range(n)]
        edges = []
        for v in code:
            u = degree.index(1)
            edges.append(tuple(sorted((u, v))))
            degree[u] = 0
            degree[v] -= 1
        edges.append(tuple(i for i, d in enumerate(degree) if d))
        yield tuple(edges)


def direct_convex(n, tree, replies):
    for column in replies:
        for value in set(column):
            subset = {i for i, entry in enumerate(column) if value == entry}
            interior = ((a, b) for a, b in tree if a in subset and b in subset)
            if edge_rank(n, interior) != len(subset) - 1:
                return False
    return True


def synthetic():
    from interval_fault_world_tree import answer_tree, world_plan

    rng = Random(984177)
    audit = Counter()
    for i in range(80):
        n = rng.randint(4, 6)
        rows = []
        for _ in range(rng.randint(2, 5)):
            k = rng.randint(2, 4)
            data = [rng.randrange(k) for _ in range(n)]
            rows.append(tuple(sorted(data)) if i % 3 == 0 else tuple(data))
        offers = [Offer(rng.randint(1, 6), col) for col in rows]
        labels = tuple(rng.randrange(3) for _ in range(n))
        _, req = requirements(labels, rows)
        lookup = {pair: support for support, pairs in req.items() for pair in pairs}
        can_support, can_cover, enumerated = False, False, 0
        for t in trees(n):
            enumerated += 1
            can_support |= direct_convex(n, t, rows)
            can_cover |= {lookup[e] for e in t if e in lookup} == req.keys()
        model = answer_tree(offers, n)
        assert model.convex == can_support
        assert task_tree(n, req) == can_cover
        plan = world_plan(labels, offers, 0)
        assert plan.cost == optimum([q.cost for q in offers], set(req), 1)[0]
        if plan.witness is not None:
            u, v, seen = plan.witness
            assert labels[u] != labels[v]
            assert tuple(q.values[u] for q in offers) == seen
            assert tuple(q.values[v] for q in offers) == seen
        audit.update(
            {
                "catalogs": 1,
                "enumerated_trees": enumerated,
                "answer_tree": can_support,
                "task_tree": can_cover,
                "refused": plan.cost is None,
            }
        )
    leaves = [tuple(int(i == k) for i in range(4)) for k in (1, 2, 3)]
    star = world_plan(
        tuple(range(4)), [Offer(1, q) for q in leaves for _ in range(3)], 1
    )
    assert star.cost == 9 and star.tree.convex
    assert all((0, j) in star.tree.edges for j in (1, 2, 3))
    assert not any(
        direct_convex(4, t, leaves)
        and max(Counter(x for e in t for x in e).values()) <= 2
        for t in trees(4)
    )
    corners = [(0, 0, 1, 1), (0, 1, 0, 1)]
    square = world_plan(
        (0, 1, 1, 0), [Offer(1, q) for q in corners for _ in range(3)], 1
    )
    assert square.cost == 6 and not square.tree.convex and not square.wide_sources
    assert task_tree(4, requirements((0, 1, 1, 0), corners)[1])
    points = [tuple(int(i == k) for i in range(3)) for k in range(3)]
    triangle = world_plan((0, 1, 2), [Offer(1, q) for q in points for _ in range(3)], 1)
    assert not triangle.tree.convex and not task_tree(
        3, requirements((0, 1, 2), points)[1]
    )
    assert triangle.cost == 5 and not triangle.wide_sources
    return {
        "checks": audit,
        "star": {"cost": star.cost, "edges": star.tree.edges},
        "square": {"cost": square.cost, "task_tree": True},
        "triangle": {"cost": triangle.cost, "task_tree": False},
    }


if __name__ == "__main__":
    noaa, bart, output = map(Path, sys.argv[1:])
    print(
        json.dumps(
            {
                "replay": audit(noaa, bart, output),
                "synthetic": synthetic(),
                "verified": True,
            }
        )
    )
