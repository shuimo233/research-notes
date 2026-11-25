"""Reconstruct source vectors, check optimum by subsets, and replay one whole-source lie."""

from collections import Counter, defaultdict
import gzip
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_plan_check import all_worlds, inventory, prepared, reports_for


def independent_sources(key, number, pairs, size):
    result = []
    for pos in range(size):
        flags = [p for p in pairs if pos == p[0] or pos == p[1]]
        for slot in range(2):
            h = sha256(
                "/".join(map(str, (key, "bundle", "anchor", pos, slot))).encode()
            ).digest()
            if slot == 1:
                if h[0] & 1:
                    break
                items = [list(p) for b, p in zip(h[1:], flags) if b % 3 != 0]
            else:
                items = [list(p) for p in flags]
            if items:
                result.append(
                    [
                        f"anchor-{pos}-{slot}",
                        2 + h[0] % 4 + (len(items) - 1) // 2,
                        items,
                    ]
                )
    base = len(result)
    eligible = [
        [list(a), list(b)] for a, b in combinations(pairs, 2) if len(set((*a, *b))) == 4
    ]
    for slot in range(2):
        if not eligible:
            break
        digest = sha256(
            "/".join(map(str, (key, "bundle", "mixed", number, slot))).encode()
        ).hexdigest()
        index = int(digest[:8], 16) % len(eligible)
        result.append([f"mixed-{slot}", 3 + int(digest[8:10], 16) % 5, eligible[index]])
    return result, base


def brute(prices, contributions, demand):
    """Enumerate chosen-source subsets; contributions indexed by rival then source."""
    if any(sum(row) < demand for row in contributions):
        return None
    useful = [i for i in range(len(prices)) if any(row[i] for row in contributions)]
    incumbent = sum(prices[i] for i in useful)
    for n in range(1, len(useful) + 1):
        for ids in combinations(useful, n):
            charge = sum(prices[i] for i in ids)
            if charge < incumbent and all(
                sum(row[i] for i in ids) >= demand for row in contributions
            ):
                incumbent = charge
    return incumbent


def convert_worlds(coords, sources):
    return [
        tuple(tuple(w[v] - w[u] for u, v in edges) for w in coords)
        for _, _, edges in sources
    ]


def costs(sources):
    return [p for _, p, _ in sources]


def difference_rows(answers, reference, rivals):
    return [
        [
            sum(x != y for x, y in zip(table[reference], table[i], strict=True))
            for table in answers
        ]
        for i in rivals
    ]


def witness(record, labels, answers):
    a, b, sequence = record
    assert labels[a] != labels[b]
    assert len(sequence) == len(answers)
    for w in (a, b):
        assert (
            sum(
                tuple(value) != table[w]
                for value, table in zip(sequence, answers, strict=True)
            )
            <= 1
        )


def plan(saved, labels, prices, answers, counts):
    optimum = brute(prices, counts, 3)
    assert saved.get("cost") == optimum
    if optimum is None:
        witness(saved["witness"], labels, answers)
        return None, []
    chosen = saved["selected"]
    assert chosen == sorted(set(chosen))
    assert sum(prices[i] for i in chosen) == optimum
    assert all(sum(row[i] for i in chosen) >= 3 for row in counts)
    return optimum, [answers[i] for i in chosen]


def replay_errors(labels, selected):
    from interval_fault_noisy import Offer, possible_labels

    wrapped = [Offer(1, table) for table in selected]
    checked = 0
    for w, label in enumerate(labels):
        exact = [table[w] for table in selected]
        assert possible_labels(labels, wrapped, exact, 1) == {label}
        checked += 1
        for i, table in enumerate(selected):
            bad = set(table) - {table[w]}
            alien = (max(x[0] for x in table) + 1, *table[w][1:])
            for replacement in bad | {alien}:
                record = exact.copy()
                record[i] = replacement
                assert possible_labels(labels, wrapped, record, 1) == {label}
                direct = {
                    l
                    for j, l in enumerate(labels)
                    if sum(col[j] != a for col, a in zip(selected, record, strict=True))
                    <= 1
                }
                assert direct == {label}
                checked += 1
    return checked


def audit(noaa, bart, out):
    led = json.loads(
        gzip.decompress(
            (out / "interval-fault-source-bundle-ledger.json.gz").read_bytes()
        )
    )
    candidates = [row for row in prepared(noaa, bart, False) if row[1] == 1]
    computed = defaultdict(Counter)
    checked, count_witnesses, strictly_underpriced, unsafe_impossible = 0, 0, 0, 0
    max_exceptions = 0
    example = None
    for r, (key, _, v, bands, edges, targets, limit, kind) in zip(
        led, candidates, strict=True
    ):
        assert r["id"] == key
        totals = Counter()
        source = key.split("/")[0]
        if v is None:
            assert r["excluded"] == kind
            totals[kind] += 1
        else:
            reports = reports_for(key, 1, v, edges)
            model, reason = all_worlds(bands, reports, 1)
            assert reason is None
            assert set(r["repairs"]) == {i for (i,) in model} and len(
                r["repairs"]
            ) == len(model)
            coords = [model[i,] for i in r["repairs"]]
            assert tuple(x - v[0] for x in v) in coords
            totals["archives"] = 1
            pair_inventory = [
                (a, b) for a, b, _ in inventory(key, 1, len(v), edges, False)
            ]
            for target_no, ((s, t), action) in enumerate(
                zip(targets, r["targets"], strict=True)
            ):
                labels = [p[t] - p[s] >= limit for p in coords]
                totals["targets"] += 1
                if len(set(labels)) == 1:
                    assert action == {"known": labels[0]}
                    totals["known"] += 1
                    continue
                totals["ambiguous"] += 1
                pairs = [p for p in pair_inventory if set(p) != {s, t}]
                sources, n_anchors = independent_sources(key, target_no, pairs, len(v))
                assert action["sources"] == sources
                answers = convert_worlds(coords, sources)
                prices = costs(sources)
                ref = action["reference"]
                rivals = [
                    i
                    for i in (*range(ref + 1, len(coords)), *range(ref))
                    if labels[i] != labels[ref]
                ]
                assert rivals == action["rivals"]
                for j, flag in enumerate(labels):
                    if flag == labels[ref]:
                        assert all(col[j] == col[ref] for col in answers)
                raw = difference_rows(answers, ref, rivals)
                counted = [[int(x > 0) for x in row] for row in raw]
                masks = [
                    [j for j, row in enumerate(counted) if row[i]]
                    for i in range(len(answers))
                ]
                exceptions = [
                    [i, m]
                    for i, m in enumerate(masks)
                    if m and len(m) != m[-1] - m[0] + 1
                ]
                assert exceptions == action["exceptions"]
                assert all(i >= n_anchors for i, _ in exceptions)
                max_exceptions = max(len(exceptions), max_exceptions)
                total_cost, selected = plan(
                    action["combined"], labels, prices, answers, counted
                )
                anchor_cost, _ = plan(
                    action["only_anchors"],
                    labels,
                    prices[:n_anchors],
                    answers[:n_anchors],
                    [row[:n_anchors] for row in counted],
                )
                count_witnesses += (total_cost is None) + (anchor_cost is None)
                rr = action["rows_as_votes"]
                q = brute(prices, raw, 3)
                assert (None if rr is None else rr["cost"]) == q
                unsafe = q is not None and (total_cost is None or q < total_cost)
                if rr is not None:
                    chosen = rr["selected"]
                    assert len(set(chosen)) == len(chosen)
                    assert sum(prices[i] for i in chosen) == q
                    assert all(sum(row[i] for i in chosen) >= 3 for row in raw)
                    assert ("counterexample" in rr) == unsafe
                    if unsafe:
                        record = rr["counterexample"]
                        witness(record, labels, [answers[i] for i in chosen])
                        count_witnesses += 1
                        strictly_underpriced += total_cost is not None
                        unsafe_impossible += total_cost is None
                        if example is None:
                            a, b, _ = record
                            counts_on_picked = [
                                sum(
                                    m != n
                                    for m, n in zip(
                                        answers[i][a], answers[i][b], strict=True
                                    )
                                )
                                for i in chosen
                            ]
                            example = {
                                "id": key,
                                "target": [s, t],
                                "row_price": q,
                                "safe_price": total_cost,
                                "chosen_source_names": [sources[i][0] for i in chosen],
                                "differences_by_source": counts_on_picked,
                            }
                assert 0 <= action["flow_calls"] <= (1 << len(exceptions))
                if total_cost is not None:
                    assert action["flow_calls"] > 0
                    checked += replay_errors(labels, selected)
                else:
                    assert action["flow_calls"] == 0
                totals.update(
                    {
                        "source_feasible": total_cost is not None,
                        "anchor_feasible": anchor_cost is not None,
                        "mixed_only": total_cost is not None and anchor_cost is None,
                        "optimistic_feasible": q is not None,
                        "false_assurances": unsafe,
                        "source_models_with_exceptions": bool(exceptions),
                        "noncontiguous_offers": len(exceptions),
                        "flow_calls": action["flow_calls"],
                    }
                )
                if anchor_cost is not None:
                    totals["combined_common_cost"] += total_cost
                    totals["anchor_common_cost"] += anchor_cost
        for name in (source, "all"):
            computed[name].update(totals)
    expected = json.loads(
        (out / "interval-fault-source-bundle-results.json").read_bytes()
    )
    assert expected["counts"] == computed
    c = computed["all"]
    assert expected["gates"] == {
        "provenance": c["source_feasible"] >= 50 and c["false_assurances"] >= 20,
        "mixed_gain": c["mixed_only"] >= 5
        or (
            bool(c["anchor_common_cost"])
            and 20 * c["combined_common_cost"] <= 19 * c["anchor_common_cost"]
        ),
    }
    return {
        "archives": len(led),
        "targets": c["targets"],
        "replayed_transcripts": checked,
        "witnesses": count_witnesses,
        "strictly_underpriced": strictly_underpriced,
        "unsafe_without_any_plan": unsafe_impossible,
        "max_exceptions": max_exceptions,
        "example": example,
    }


def connected_ring(n):
    edges = [(i, i + 1, 0) for i in range(n - 1)] + [(0, n - 1, 1)]
    bands = [(0, 1)] * n
    all_coordinates, err = all_worlds(bands, edges, 1)
    assert err is None and len(all_coordinates) == n
    worlds = [all_coordinates[i,] for i in (n - 1, *range(n - 1))]
    return edges, bands, worlds


def reduction():
    from interval_fault_noisy import Offer
    from interval_fault_source_bundle import source_plan

    rng = Random(764219)
    exists, missing, largest_exception_count = 0, 0, 0
    for _ in range(80):
        n, m = rng.randint(5, 10), rng.randint(3, 10)
        library, subsets = [], []
        for _ in range(m):
            points = set()
            for _ in range(rng.randint(1, 2)):
                a, b = sorted(rng.sample(range(n + 1), 2))
                points.update(range(a + 1, b + 1))
            chunk = []
            for i in sorted(points):
                if chunk and i == chunk[-1][1] + 1:
                    chunk[-1][1] = i
                else:
                    chunk.append([i - 1, i])
            assert len(chunk) <= 2
            library.append(chunk)
            subsets.append(points)
        old_matrix = [[int(j in s) for s in subsets] for j in range(1, n + 1)]
        old = brute([1] * m, old_matrix, 1)
        _, _, worlds = connected_ring(n + 2)
        labels = [x[-1] - x[0] >= 1 for x in worlds]
        assert labels == [False] + [True] * (n + 1)
        library.extend(([(0, n), (n, n + 1)], [(0, n), (n, n + 1)], [(n, n + 1)]))
        assert all(
            0 < len(s) <= 2 and all((a, b) != (0, n + 1) for a, b in s) for s in library
        )
        vectors = convert_worlds(
            worlds, [(str(i), 1, edges) for i, edges in enumerate(library)]
        )
        plan = source_plan(labels, [Offer(1, table) for table in vectors], 1)
        mat = difference_rows(vectors, 0, tuple(range(1, n + 2)))
        assert [int(x != 0) for x in mat[-1]] == [0] * m + [1, 1, 1]
        assert all([int(x != 0) for x in row[-3:]] == [1, 1, 0] for row in mat[:-1])
        assert plan.cost == (None if old is None else old + 3)
        largest_exception_count = max(largest_exception_count, len(plan.exceptions))
        if old is None:
            missing += 1
        else:
            exists += 1
            assert set(range(m, m + 3)) <= set(plan.selected)
    assert exists and missing
    return {
        "verified_reductions": 80,
        "feasible": exists,
        "infeasible": missing,
        "max_noncontiguous_bundles": largest_exception_count,
    }


def geometry():
    from interval_fault_path import compile_path
    from interval_fault_source_bundle import source_disagreements

    checked = 0
    for n in range(4, 13):
        edges, bands, coords = connected_ring(n)
        model = compile_path(bands, edges, reference_edge=n - 1)
        assert model.repair_edges == (n - 1, *range(n - 1))
        for ref in range(n):
            ranks = tuple(i for i in (*range(ref + 1, n), *range(ref)) if (i - ref) % 3)
            for center in range(n):
                group = [
                    (center, i)
                    for i in range(n)
                    if i != center and (i + n - center) % 3
                ]
                a = group[0][1]
                b = group[-1][1]
                expanded = group + [(a, b)]
                signature = convert_worlds(
                    coords, [("s", 1, group), ("more", 1, expanded)]
                )
                wanted = tuple(
                    j
                    for j, i in enumerate(ranks)
                    if signature[0][i] != signature[0][ref]
                )
                assert wanted == tuple(
                    j
                    for j, i in enumerate(ranks)
                    if signature[1][i] != signature[1][ref]
                )
                assert not wanted or len(wanted) == wanted[-1] + 1 - wanted[0]
                assert source_disagreements(model, expanded, ref, ranks) == wanted
                checked += 1
    return {"connected_rotations": checked}


if __name__ == "__main__":
    noaa, bart, out = map(Path, sys.argv[1:])
    print(
        json.dumps(
            {
                "data": audit(noaa, bart, out),
                "reduction": reduction(),
                "geometry": geometry(),
                "verified": True,
            }
        )
    )
