"""Independently verify multiworld groups and optimality certificates."""

from collections import Counter
import csv
from fractions import Fraction as F
from functools import cache
import gzip
from hashlib import sha256
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
from struct import unpack
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_runtime_partition_check import check_partition, compatible, cost

MODES = (0, 16, 24, 32, 48, 64, 96, 128)
LEVELS = tuple(map(F, ("0", "1/4", "1/2", "1", "2", "4")))
NAMES = (
    "audit-runtime-multiworld-policies.json.gz",
    "audit-runtime-multiworld-results.json",
)


def inputs(ledger):
    with ledger.open(encoding="utf-8", newline="") as f:
        records = list(csv.DictReader(f, delimiter="\t"))
    assert len(records) == 1440
    assert len({row["source"] for row in records}) == 1440
    assert len({row["premise"] for row in records}) == 480
    for case in range(60):
        now = records[24 * case : 24 * (case + 1)]
        slots = []
        for i in range(8):
            rows = now[3 * i : 3 * (i + 1)]
            assert len({x["premise"] for x in rows}) == 1
            assert {x["gold"] for x in rows} == {"0", "1", "2"}
            scores = []
            for j, row in enumerate(rows):
                assert (int(row["case"]), int(row["slot"]), int(row["world"])) == (
                    case,
                    i,
                    j,
                )
                n = int(row["length"])
                assert 0 < n <= 512 and 0 <= int(row["source"]) < 10000
                gold = int(row["gold"])
                aliases = {}
                margins = []
                for w in MODES:
                    z = tuple(row[f"w{w}_{v}"] for v in "ENC")
                    assert aliases.setdefault(max(n, w), z) == z
                    vals = tuple(F(unpack(">f", bytes.fromhex(s))[0]) for s in z)
                    margins.append(
                        vals[gold] - max(vals[k] for k in range(3) if k != gold)
                    )
                scores.append(tuple(margins))
            slots.append(scores)
        for level in LEVELS:
            rates = tuple(
                tuple(
                    tuple(
                        F(1, 20) if x > 0 and x >= level else F(19, 20) for x in slot[j]
                    )
                    for slot in slots
                )
                for j in range(3)
            )
            yield case, str(level), rates


def groups_checked(blocks, n):
    assert blocks and all(blocks)
    indexed = [i for b in blocks for i in b]
    assert all(type(i) is int for i in indexed) and sorted(indexed) == list(range(n))


def is_compatible(rates, i, j):
    p, *remaining = rates
    return all(compatible(p[i], p[j], q[i], q[j]) for q in remaining)


def core_bound(masks, proof, worlds):
    core = tuple(i for i in masks if masks[i].bit_count() > 1)
    adj = {i: {j for j in core if not masks[i] & masks[j]} for i in core}
    if proof["kind"] == "matching":
        for v in core:
            assert not any(c in adj[b] for b, c in combinations(adj[v], 2))
        pairs = proof["pairs"]
        touched = set()
        for i, j in pairs:
            assert j in adj[i] and i not in touched and j not in touched
            touched.update((i, j))
        separator = proof["barrier"]
        assert len(separator) == len(set(separator)) and set(separator) <= set(core)
        remaining = set(core) - set(separator)
        odd = 0
        while remaining:
            queue = [remaining.pop()]
            size = 1
            for v in queue:
                edges = remaining & adj[v]
                size += len(edges)
                queue.extend(edges)
                remaining -= edges
            odd += size % 2
        assert len(core) + len(separator) - odd == 2 * len(pairs)
        minimum = len(core) - len(pairs)
    else:
        assert proof["kind"] == "counts"
        minimum = proof["core_colors"]
        # An independently enumerated coloring decision on the original vertices.
        masks_ordered = sorted(
            (masks[i] for i in core),
            key=lambda a: (-sum(bool(a & masks[i]) for i in core), -a),
        )

        @cache
        def possible(i, bins):
            if i == len(masks_ordered):
                return True
            target = masks_ordered[i]
            for j, packed in enumerate(bins):
                if j and packed == bins[j - 1]:
                    continue
                if not target & packed and possible(
                    i + 1, tuple(sorted((*bins[:j], packed | target, *bins[j + 1 :])))
                ):
                    return True
            return False

        assert type(minimum) is int and 1 <= minimum <= len(core)
        assert not possible(0, (0,) * (minimum - 1))
    load = max(sum(bool(m & (1 << j)) for m in masks.values()) for j in range(worlds))
    return max(load, minimum)


def exact_groups(rates, result):
    n = len(rates[0])
    groups_checked(result["blocks"], n)
    masks = {
        i: sum(1 << w for w in range(len(rates)) if len(set(rates[w][i])) > 1)
        for i in range(n)
    }
    all_bits = (1 << len(rates)) - 1
    universal = {i for i, m in masks.items() if m == all_bits}
    remaining = {i: m for i, m in masks.items() if m and m != all_bits}
    clique = result["global_clique"]
    assert len(clique) == len(set(clique)) and set(clique) <= universal
    for i, j in combinations(clique, 2):
        assert not is_compatible(rates, i, j)
    assert all(not is_compatible(rates, i, j) for i in clique for j in remaining)
    for block in result["blocks"]:
        assert all(is_compatible(rates, i, j) for i, j in combinations(block, 2))
    bound = core_bound(remaining, result["partial_core"], len(rates))
    assert len(result["blocks"]) == max(1, len(clique) + bound)


def safe_baseline(rates, evidence):
    n = len(rates[0])
    groups_checked(evidence["blocks"], n)
    masks = {
        i: sum(1 << w for w, q in enumerate(rates) if max(q[i]) != min(q[i]))
        for i in range(n)
    }
    for b in evidence["blocks"]:
        assert all(not masks[i] & masks[j] for i, j in combinations(b, 2))
    assert len(evidence["blocks"]) == max(
        1, core_bound(masks, evidence["core"], len(rates))
    )


def normalized_pair(rates, i, j, weights):
    values = []
    for world in rates:
        a, b = world[i], world[j]
        shared = sum(w * x * y for w, x, y in zip(weights, a, b, strict=True))
        product_of_means = sum(w * x for w, x in zip(weights, a, strict=True)) * sum(
            w * y for w, y in zip(weights, b, strict=True)
        )
        values.append((1 + shared / product_of_means) / 2)
    return values


def failure_witness(rates, old):
    for block in old["blocks"]:
        for i, j in combinations(block, 2):
            if is_compatible(rates, i, j):
                continue
            m = len(rates[0][0])
            for triple in combinations_with_replacement(range(m), 3):
                w = tuple(F(3, 4 * m) + F(triple.count(k), 12) for k in range(m))
                factors = normalized_pair(rates, i, j, w)
                if min(factors) != max(factors):
                    return {
                        "pair": [i, j],
                        "weights": list(map(str, w)),
                        "normalized": list(map(str, factors)),
                    }
            raise ArithmeticError("a nonzero cubic lacked a witness")
    return None


def check_failure(rates, old, witness):
    fails = any(
        not is_compatible(rates, i, j)
        for b in old["blocks"]
        for i, j in combinations(b, 2)
    )
    assert fails == (witness is not None)
    if fails:
        i, j = witness["pair"]
        assert i != j and any(i in b and j in b for b in old["blocks"])
        m = len(rates[0][0])
        w = tuple(map(F, witness["weights"]))
        assert len(w) == m and min(w) >= F(3, 4 * m) and sum(w) == 1
        actual = normalized_pair(rates, i, j, w)
        assert actual == list(map(F, witness["normalized"]))
        assert actual[0] == actual[1] != actual[2]


def report(ledger, policies, verify):
    counts = Counter()
    scopes = {}
    worst = F(1)
    notable = None
    maximum_saving = F(0)
    for (case, level, rates), row in zip(inputs(ledger), policies, strict=True):
        assert (row["case"], row["threshold"]) == (case, level)
        old, new, base, witness = (
            row[t] for t in ("old", "new", "conservative", "witness")
        )
        if verify:
            check_partition(rates[:2], old)
            exact_groups(rates, new)
            safe_baseline(rates, base)
            check_failure(rates, old, witness)
        a, b, c = (len(p["blocks"]) for p in (old, new, base))
        assert a <= b <= c <= 8
        gain = (cost(c, 8) - cost(b, 8)) / 2
        against_independent = (cost(8, 8) - cost(b, 8)) / 2
        assert row["gains"] == [str(gain), str(against_independent)]
        maximum_saving = max(maximum_saving, gain)
        if witness:
            v = list(map(F, witness["normalized"]))
            multiplier = max(v) / min(v)
            if multiplier > worst:
                worst = multiplier
                notable = [case, level]
        row_counts = {
            "catalog_thresholds": 1,
            "old_invalid": int(witness is not None),
            "new_more_groups": int(b > a),
            "improved_over_conservative": int(b < c),
            "improved_over_independent": int(against_independent > 0),
        }
        counts.update(row_counts)
        scopes.setdefault(level, Counter()).update(row_counts)
    assert counts["catalog_thresholds"] == 360
    return {
        "counts": dict(counts),
        "by_threshold": {k: dict(v) for k, v in scopes.items()},
        "witness_max_factor": str(worst),
        "notable": notable,
        "largest_saving_over_conservative": str(maximum_saving),
        "ledger_sha256": sha256(
            ledger.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "gate": counts["old_invalid"] > 0,
    }


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("ledger", type=Path)
    cli.add_argument("folder", type=Path)
    a = cli.parse_args()
    entries = json.loads(gzip.decompress((a.folder / NAMES[0]).read_bytes()))
    out = report(a.ledger, entries, True)
    assert out == json.loads((a.folder / NAMES[1]).read_bytes())
    print(json.dumps({"verified": True, "counts": out["counts"], "gate": out["gate"]}))
