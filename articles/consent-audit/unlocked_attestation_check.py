"""Verify protected repairs and signed clauses with independent raw feasibility checks."""

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle, verify_bad
from public_optimality_check import model
from transit_optimality_check import known_can_certify
from unlocked_attestation_run import read


def independent_menu(public, actual, grid, both):
    options = {}
    n = len(public)
    cls = [
        min(j for j in range(n) if public[i][j] + public[j][i] == 0) for i in range(n)
    ]
    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            diff = actual[b] - actual[a]
            hi = (diff // grid) * grid
            cuts = [hi, hi - grid] if hi == diff and both else [hi]
            for cut in cuts:
                if cut + public[b][a] > 0:
                    # Normalize the offset between the two fixed-difference representatives.
                    adjusted = cut - public[cls[b]][b] + public[cls[a]][a]
                    options.setdefault((cls[a], cls[b], adjusted), (a, b, cut))
    return frozenset(options.values())


def hitting_feasible(needed, blocked, depth):
    """Decision test for the logged signed clauses, using substitution and propagation."""

    @lru_cache(maxsize=None)
    def visit(pos, neg, left):
        if 0 in pos or 0 in neg:
            return False
        if not pos:
            return True
        if left <= 0:
            return False
        prohibited = 0
        for mask in neg:
            if mask.bit_count() == 1:
                prohibited |= mask
        if prohibited:
            pos = tuple(sorted({p & ~prohibited for p in pos}))
            if 0 in pos:
                return False
            neg = tuple(x for x in neg if not x & prohibited)
        candidates = min(pos, key=lambda p: (p.bit_count(), p))
        while candidates:
            bit = candidates & -candidates
            candidates ^= bit
            remain = tuple(p for p in pos if not p & bit)
            negative = tuple(sorted({x & ~bit for x in neg}))
            if visit(remain, negative, left - 1):
                return True
        return False

    return visit(tuple(sorted(set(needed))), tuple(sorted(set(blocked))), depth)


def mask(indices):
    return sum(1 << i for i in set(indices))


def satisfies(n, edges, attested, records, protected):
    assert len(records) == 2
    for world in records:
        assert len(world) == n and world[0] == 0 and all(type(k) is int for k in world)
        assert all(world[v] - world[u] <= b for u, v, b in edges)
        assert all(world[v] - world[u] >= b for u, v, b in attested)
    assert all(records[0][i] != records[1][i] for i in protected)


def verify_mode(case, oracle, grid, both, row):
    actual, packet = case["actual"], case["packet"]
    menu = sorted(independent_menu(oracle.f, actual, grid, both))
    state = row["status"]
    if state == "dictionary_impossible":
        w = row["counterexample"]
        verify_bad(packet, w)
        assert all(w["record"][v] - w["record"][u] >= b for u, v, b in menu)
        return
    assert state in {"proved", "protection_impossible"}
    ids = {f: i for i, f in enumerate(menu)}
    need, forbid = [], []
    for profile in row["bad"]:
        verify_bad(packet, profile)
        w = profile["record"]
        need.append(mask(i for i, (u, v, b) in enumerate(menu) if w[v] - w[u] < b))
    for profile in row["lock"]:
        assert oracle.locks(profile)
        forbid.append(mask(ids[tuple(f)] for f in profile))
    if state == "protection_impossible":
        assert not hitting_feasible(need, forbid, len(menu))
        return
    picked = row["attested"]
    assert picked and all(
        actual[v] - actual[u] >= b and b % grid == 0 for u, v, b in picked
    )
    assert not hitting_feasible(need, forbid, len(picked) - 1)
    assert not oracle.query(picked) and not oracle.locks(picked)
    if both:
        assert all(
            oracle.query([*picked[:i], (u, v, b - grid), *picked[i + 1 :]])
            for i, (u, v, b) in enumerate(picked)
        )
    else:
        assert all(tuple(f) in ids for f in picked)
    protected = [i for i in range(1, oracle.n) if oracle.f[0][i] > -oracle.f[i][0]]
    satisfies(oracle.n, oracle.original, picked, row["worlds"], protected)


def check(sources, result_path):
    cases = read(sources, "attested-optimality-cases.json.gz")
    previous = read(sources, "attested-optimality-ledger.json.gz")
    rows, packets = (
        json.loads(
            gzip.decompress(
                (result_path / f"unlocked-attestation-{t}.json.gz").read_bytes()
            )
        )
        for t in ("ledger", "packets")
    )
    examples = {(r["source"], r["packet"]["job"]): r for r in packets}
    counts = defaultdict(Counter)
    for case, old, row in zip(cases, previous, rows, strict=True):
        packet = case["packet"]
        assert (
            row["source"] == case["source"]
            and row["job"] == packet["job"]
            and row["run"] == packet["run"]
        )
        oracle = DirectOracle(packet, case["groups"])
        n, _, _, _, f, _, alt = model(packet)
        actual = case["actual"]
        assert all(actual[v] - actual[u] <= b for u, v, b in f)
        assert actual[0] == 0 and not known_can_certify(
            n, actual, alt, len(packet["certificate"]["disclosed"]) - 1
        )
        verify_bad(packet, case["prior_counterexample"])
        for grid, options in row["grids"].items():
            legacy = old["grids"][grid]
            same = legacy["status"] == "proved" and not legacy["newly_exact"]
            assert options["prior_preserves"] == same
            for method, both in (("both", True), ("strongest", False)):
                fact = options[method]
                verify_mode(case, oracle, int(grid), both, fact)
            for name in ("total", case["source"]):
                c = counts[name]
                c[grid + "_prior_preserves"] += same
                for m in ("both", "strongest"):
                    fact = options[m]
                    k = f"{grid}_{m}_"
                    c[k + fact["status"]] += 1
                    c[k + "rounds"] += fact.get("rounds", 0)
                    c[k + "nodes"] += fact.get("nodes", 0)
                    if fact["status"] == "proved":
                        c[k + "facts"] += len(fact["attested"])
                        c[k + f"size_{len(fact['attested'])}"] += 1
                if options["both"]["status"] == "proved":
                    c[grid + "_additional_over_prior"] += not same
                    c[grid + "_additional_over_strongest"] += (
                        options["strongest"]["status"] != "proved"
                    )
        found = row["grids"]["60"]["both"]
        if found["status"] == "proved":
            s = examples.pop((case["source"], packet["job"]))
            assert s == dict(
                source=case["source"],
                packet=packet,
                groups=case["groups"],
                grid=60,
                attested=found["attested"],
                worlds=found["worlds"],
            )
        for name in ("total", row["source"]):
            counts[name]["tasks"] += 1
            counts[name]["checks"] += row["checks"]
    assert not examples
    expected = json.loads(
        (result_path / "unlocked-attestation-results.json").read_bytes()
    )
    assert counts == expected["by_source"]
    passed = len(rows) == 35 and counts["total"]["60_both_proved"] >= 25
    assert expected["gate"] == passed
    return dict(
        cases=len(rows),
        methods_verified=6 * len(rows),
        public_packets=len(packets),
        gate=passed,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path)
    p.add_argument("score_output", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.sources, a.score_output), indent=2))
