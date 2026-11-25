"""Independent optimization and exhaustive bounded-error replay for the frozen offers."""

from collections import Counter, defaultdict
from functools import cache
import gzip
from hashlib import sha256
import json
from math import inf
from pathlib import Path
from random import Random
import sys

from interval_fault_plan_check import all_worlds, inventory, prepared, reports_for


def offers_for(key, values, edges, target):
    groups = []
    existing = {frozenset(p) for p in edges}
    for u, v, price in inventory(key, 1, len(values[0]), edges, False):
        if {u, v} == set(target):
            continue
        h = sha256("/".join((key, "protected", str(u), str(v))).encode()).digest()
        outcomes = tuple(x[v] - x[u] for x in values)
        rows = [(price + (z % 5), outcomes) for z in h[1 : 2 + h[0] % 4]]
        groups.append((frozenset((u, v)) in existing, rows))
    return groups


def best_cover(offers, reference, rivals, demand):
    """Independent clipped coverage-vector dynamic program."""
    start = (0,) * len(rivals)
    goal = (demand,) * len(rivals)
    state = {start: 0}
    for price, values in offers:
        hit = tuple(i for i, r in enumerate(rivals) if values[r] != values[reference])
        if not hit:
            continue
        nxt = state.copy()
        for vector, cost in state.items():
            updated = list(vector)
            for i in hit:
                updated[i] = min(demand, updated[i] + 1)
            code = tuple(updated)
            nxt[code] = min(nxt.get(code, inf), cost + price)
        state = nxt
    return state.get(goal)


def dual_certificate(saved, offers, reference, rivals, demand):
    chosen = saved["selected"]
    assert len(chosen) == len(set(chosen)) and all(0 <= i < len(offers) for i in chosen)
    assert sum(offers[i][0] for i in chosen) == saved["cost"]
    potentials = saved["potentials"]
    assert len(potentials) == len(rivals) + 1
    total = [0] * len(rivals)
    for i, (price, answers) in enumerate(offers):
        mask = [
            j for j, other in enumerate(rivals) if answers[reference] != answers[other]
        ]
        if not mask:
            assert i not in chosen
            continue
        a, b = min(mask), max(mask) + 1
        assert mask == list(range(a, b))
        if i in chosen:
            assert potentials[b] - potentials[a] >= price
            for j in mask:
                total[j] += 1
        else:
            assert potentials[b] - potentials[a] <= price
    for i, coverage in enumerate(total):
        assert coverage >= demand and potentials[i + 1] >= potentials[i]
        if coverage > demand:
            assert potentials[i + 1] == potentials[i]


def match_count(offers, world, record):
    return sum(
        table[world] != answer
        for (_, table), answer in zip(offers, record, strict=True)
    )


def traces(offers, count):
    for world in range(count):
        accurate = [table[world] for _, table in offers]
        yield world, accurate
        for i, (_, table) in enumerate(offers):
            different = (set(table) - {accurate[i]}) | {max(table) + 1}
            for val in different:
                altered = accurate[:]
                altered[i] = val
                yield world, altered


def exact_blocks(prices, error_budget):
    n = len(prices)

    def labels(used, ones):
        total = sum(ones)
        return (
            total <= error_budget,
            any(total + used[j] - 2 * ones[j] <= error_budget for j in range(n)),
        )

    @cache
    def minimax(used, ones):
        if sum(labels(used, ones)) <= 1:
            return 0
        best = inf
        for j, row in enumerate(prices):
            current = used[j]
            if current == len(row):
                continue
            after = list(used)
            after[j] += 1
            answers = []
            for answer in (0, 1):
                found = list(ones)
                found[j] += answer
                if any(labels(after, found)):
                    answers.append(minimax(tuple(after), tuple(found)))
            best = min(best, row[current] + max(answers))
        return best

    return minimax((0,) * n, (0,) * n)


def audit_archive(key, labels, references, groups, saved):
    from interval_fault_noisy import adaptive_one_error

    reference, rivals = references
    all_offers = [q for _, rows in groups for q in rows]
    archive_ids = []
    k = 0
    for archived, rows in groups:
        if archived:
            archive_ids.extend(range(k, k + len(rows)))
        k += len(rows)
    logical = [[] for _ in rivals]
    for i in archive_ids:
        _, column = all_offers[i]
        diff = [j for j, r in enumerate(rivals) if column[r] != column[reference]]
        assert len(diff) <= 1
        if diff:
            logical[diff[0]].append(i)
    results = saved["adaptive"]
    if any(len(b) < 3 for b in logical):
        assert results is None
        return 0
    assert len(logical) == results["rivals"]
    lookup = {i: j for j, b in enumerate(logical) for i in b}
    prices = [sorted(all_offers[i][0] for i in b) for b in logical]
    chosen = results["order"]
    assert len(chosen) == len(logical)
    result_groups = []
    for triple in chosen:
        assert len(triple) == 3 and len(set(triple)) == 3
        group = lookup[triple[0]]
        assert all(lookup[i] == group for i in triple)
        assert [all_offers[i][0] for i in triple] == prices[group][:3]
        result_groups.append(group)
    assert len(set(result_groups)) == len(logical)
    assert results["fixed"] == sum(sum(p[:3]) for p in prices)
    assert results["adaptive"] == exact_blocks(prices, 1), key
    compact = [i for triple in chosen for i in triple]
    used_offers = [all_offers[i] for i in compact]
    worst, checked = 0, 0
    for world, replies in traces(used_offers, len(labels)):
        table = dict(zip(compact, replies, strict=True))
        seen = []

        def answer(i):
            assert i not in seen
            seen.append(i)
            return table[i] != all_offers[i][1][reference]

        hypothesis = adaptive_one_error(chosen, answer)
        assert hypothesis == (labels[world] != labels[reference])
        worst = max(worst, sum(all_offers[i][0] for i in seen))
        checked += 1
    assert worst == results["adaptive"]
    return checked


def audit(noaa, bart, out):
    from interval_fault_noisy import Offer, possible_labels

    ledger = json.loads(
        gzip.decompress((out / "interval-fault-noisy-ledger.json.gz").read_bytes())
    )
    cases = [row for row in prepared(noaa, bart, False) if row[1] == 1]
    counted = defaultdict(Counter)
    fixed_traces, adaptive_traces, duals, witnesses = 0, 0, 0, 0
    for row, (key, _, values, bands, edges, targets, threshold, ring) in zip(
        ledger, cases, strict=True
    ):
        assert row["id"] == key
        sub = key.split("/")[0]
        if values is None:
            assert row["excluded"] == ring
            counted[sub][ring] += 1
            counted["all"][ring] += 1
            continue
        reports = reports_for(key, 1, values, edges)
        valid, issue = all_worlds(bands, reports, 1)
        assert issue is None
        deleted = row["repairs"]
        assert len(set(deleted)) == len(valid) == len(deleted)
        coordinates = [valid[i,] for i in deleted]
        summary = Counter(archives=1)
        for target, saved in zip(targets, row["targets"], strict=True):
            s, t = target
            summary["targets"] += 1
            labels = [row[t] - row[s] >= threshold for row in coordinates]
            if len(set(labels)) == 1:
                assert saved == {"known": labels[0]}
                summary["known"] += 1
                continue
            groups = offers_for(key, coordinates, edges, target)
            offers = [q for _, pool in groups for q in pool]
            reference, rivals = saved["reference"], saved["rivals"]
            assert len(rivals) == len(set(rivals))
            assert set(rivals) == {
                i for i, label in enumerate(labels) if label != labels[reference]
            }
            for i, label in enumerate(labels):
                if label == labels[reference]:
                    assert all(values[reference] == values[i] for _, values in offers)
            assert saved["no_error_cost"] == best_cover(offers, reference, rivals, 1)
            summary["no_error_cost"] += saved["no_error_cost"]
            summary["ambiguous"] += 1
            for r, term, plan_key in (
                (1, "one", "one_error"),
                (2, "two", "two_errors"),
            ):
                plan = saved[plan_key]
                d = 2 * r + 1
                opt = best_cover(offers, reference, rivals, d)
                majority = [
                    (sum(sorted(p for p, _ in rows)[:d]), rows[0][1])
                    for _, rows in groups
                    if len(rows) >= d
                ]
                opt_maj = best_cover(majority, reference, rivals, 1)
                assert plan.get("cost") == opt and saved[f"{term}_quorum"] == opt_maj
                summary[f"{term}_robust"] += opt is not None
                summary[f"{term}_quorum"] += opt_maj is not None
                summary[f"{term}_rescue"] += opt is not None and opt_maj is None
                if opt_maj is not None:
                    assert opt <= opt_maj
                    summary[f"{term}_matched_cost"] += opt
                    summary[f"{term}_matched_quorum_cost"] += opt_maj
                if opt is None:
                    i, j, record = plan["witness"]
                    assert labels[i] != labels[j]
                    assert (
                        match_count(offers, i, record) <= r
                        and match_count(offers, j, record) <= r
                    )
                    witnesses += 1
                    continue
                dual_certificate(plan, offers, reference, rivals, d)
                duals += 1
                if r == 1:
                    chosen = [offers[i] for i in plan["selected"]]
                    encoded = [Offer(c, a) for c, a in chosen]
                    for truth, reading in traces(chosen, len(coordinates)):
                        assert possible_labels(labels, encoded, reading, r) == {
                            labels[truth]
                        }
                        assert {
                            labels[i]
                            for i in range(len(labels))
                            if match_count(chosen, i, reading) <= r
                        } == {labels[truth]}
                        fixed_traces += 1
            adaptive_traces += audit_archive(
                key, labels, (reference, rivals), groups, saved
            )
            if saved["adaptive"] is not None:
                plan = saved["adaptive"]
                summary["adaptive_archives_targets"] += 1
                summary["adaptive_multiple_rivals"] += plan["rivals"] >= 2
                summary["adaptive_cost"] += plan["adaptive"]
                summary["adaptive_fixed_cost"] += plan["fixed"]
        for g in (sub, "all"):
            counted[g].update(summary)
    summary = json.loads((out / "interval-fault-noisy-results.json").read_bytes())
    assert summary["counts"] == counted
    all_counts = counted["all"]
    assert summary["gates"] == {
        "fixed_verified_sample": all_counts["one_robust"] >= 50,
        "mixing_gain": (
            all_counts["one_rescue"] >= 10
            or (
                bool(all_counts["one_matched_quorum_cost"])
                and 20 * all_counts["one_matched_cost"]
                <= 19 * all_counts["one_matched_quorum_cost"]
            )
        ),
        "adaptive_gain": (
            all_counts["adaptive_multiple_rivals"] >= 25
            and bool(all_counts["adaptive_fixed_cost"])
            and 20 * all_counts["adaptive_cost"]
            <= 19 * all_counts["adaptive_fixed_cost"]
        ),
    }
    return {
        "archives": len(ledger),
        "targets": all_counts["targets"],
        "fixed_transcripts": fixed_traces,
        "adaptive_transcripts": adaptive_traces,
        "optimality_certificates": duals,
        "impossibility_witnesses": witnesses,
    }


def synth():
    from interval_fault_noisy import Offer, order_blocks, weighted_one_error_cost

    rng = Random(55601)
    for case in range(20):
        count = 1 + case % 3
        prices = [sorted(rng.randint(1, 11) for _ in range(3)) for _ in range(count)]
        offers = [Offer(cost, ()) for row in prices for cost in row]
        blocks = [range(i, i + 3) for i in range(0, len(offers), 3)]
        order = order_blocks(blocks, offers)
        assert weighted_one_error_cost(order, offers) == exact_blocks(prices, 1)
    uniform = []
    for n in (1, 2):
        for r in range(3):
            got = exact_blocks([[1] * (2 * r + 1)] * n, r)
            assert got == (r + 1) * n + r
            uniform.append({"blocks": n, "errors": r, "value": got})
    return {"weighted": 20, "uniform": uniform}


if __name__ == "__main__":
    noaa, bart, out = map(Path, sys.argv[1:])
    print(
        json.dumps(
            {"data": audit(noaa, bart, out), "synthetic": synth(), "verified": True}
        )
    )
