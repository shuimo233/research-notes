"""Verify the lag-protection study with raw difference paths and literal decoding."""

import argparse
from collections import Counter, defaultdict
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle, verify_bad
from lag_protection_run import verify_source
from public_optimality_check import distances, model
from transit_optimality_check import known_can_certify
from unlocked_attestation_check import hitting_feasible, independent_menu, mask


def after(oracle, facts):
    return distances(oracle.n, [*oracle.original, *((v, u, -t) for u, v, t in facts)])


def newly_fixed(oracle, facts):
    refined = after(oracle, facts)
    assert refined is not None
    return [
        [u, v]
        for u, v in combinations(range(oracle.n), 2)
        if -oracle.f[v][u] < oracle.f[u][v] and -refined[v][u] == refined[u][v]
    ]


def verify_decoding(oracle, comparisons, rational):
    n, original = oracle.n, oracle.original
    denominator, num = rational["denominator"], rational["numerators"]
    assert all(type(x) is int for x in num)
    assert len(num) == n and num[0] == 0
    assert all(num[v] - num[u] <= cap * denominator for u, v, cap in original)
    assert all(num[v] - num[u] >= cut * denominator for u, v, cut in comparisons)
    representatives = [
        min(j for j in range(n) if oracle.f[i][j] == -oracle.f[j][i]) for i in range(n)
    ]
    assert len(set(representatives)) == denominator
    records = [[(v + k) // denominator for v in num] for k in range(denominator)]
    for record in records:
        assert record[0] == 0 and all(
            record[v] - record[u] <= cap for u, v, cap in original
        )
        assert all(record[v] - record[u] >= cut for u, v, cut in comparisons)
    for u, v in combinations(range(n), 2):
        varies = len({rec[v] - rec[u] for rec in records}) > 1
        assert varies == (representatives[u] != representatives[v])
    moved = set()
    for earlier, later in zip(records, records[1:]):
        changed = {i for i in range(n) if later[i] - earlier[i] == 1}
        assert len(changed) == sum(l != e for l, e in zip(later, earlier, strict=True))
        (c,) = {representatives[i] for i in changed}
        assert (
            changed == {i for i, r in enumerate(representatives) if r == c}
            and c not in moved
        )
        moved.add(c)
    assert moved == set(representatives) - {0}


def check_mode(c, oracle, grid, both, result):
    actual, packet = c["actual"], c["packet"]
    facts = sorted(independent_menu(oracle.f, actual, grid, both))
    ids = {atom: key for key, atom in enumerate(facts)}
    state = result["status"]
    if state == "dictionary_impossible":
        w = result["counterexample"]
        verify_bad(packet, w)
        assert all(w["record"][v] - w["record"][u] >= cut for u, v, cut in facts)
        return
    assert state in {"proved", "protection_impossible"}
    positive, negative = [], []
    for w in result["bad"]:
        verify_bad(packet, w)
        positive.append(
            mask(
                i
                for i, (u, v, cut) in enumerate(facts)
                if w["record"][v] - w["record"][u] < cut
            )
        )
    for locked in result["lock"]:
        assert newly_fixed(oracle, locked)
        negative.append(mask(ids[tuple(a)] for a in locked))
    if state == "protection_impossible":
        assert not hitting_feasible(positive, negative, len(facts))
        return
    published = result["attested"]
    assert all(actual[v] - actual[u] >= b and b % grid == 0 for u, v, b in published)
    assert not hitting_feasible(positive, negative, len(published) - 1)
    assert not oracle.query(published) and not newly_fixed(oracle, published)
    if both:
        assert all(
            oracle.query([*published[:i], (u, v, cut - grid), *published[i + 1 :]])
            for i, (u, v, cut) in enumerate(published)
        )
    else:
        assert all(tuple(p) in ids for p in published)
    verify_decoding(oracle, published, result["rational"])


def check(sources, output):
    cases = verify_source(sources, "attested-optimality-cases.json.gz")
    old = verify_source(sources, "unlocked-attestation-ledger.json.gz")
    events, packets = (
        json.loads(
            gzip.decompress((output / f"lag-protection-{tag}.json.gz").read_bytes())
        )
        for tag in ("ledger", "packets")
    )
    public = {(r["source"], r["packet"]["job"]): r for r in packets}
    total = defaultdict(Counter)
    for case, prior, row in zip(cases, old, events, strict=True):
        packet, actual = case["packet"], case["actual"]
        assert (
            packet["job"] == prior["job"] == row["job"] and packet["run"] == row["run"]
        )
        assert case["source"] == prior["source"] == row["source"]
        raw_size, _, _, _, original, _, alt = model(packet)
        assert len(actual) == raw_size and actual[0] == 0
        assert all(actual[v] - actual[u] <= b for u, v, b in original)
        assert not known_can_certify(
            raw_size, actual, alt, len(packet["certificate"]["disclosed"]) - 1
        )
        verify_bad(packet, case["prior_counterexample"])
        oracle = DirectOracle(packet, case["groups"])
        for grid, variants in row["grids"].items():
            old_score = prior["grids"][grid]["both"]
            before_pass = old_score["status"] == "proved"
            losses = newly_fixed(oracle, old_score["attested"]) if before_pass else []
            assert (
                variants["prior_absolute"] == before_pass
                and variants["prior_exact_lags"] == losses
            )
            for name, both in (("both", True), ("strongest", False)):
                check_mode(case, oracle, int(grid), both, variants[name])
            for key in ("total", case["source"]):
                c = total[key]
                c[grid + "_prior_absolute"] += before_pass
                c[grid + "_prior_lag_preserved"] += before_pass and not losses
                c[grid + "_prior_leaked_instances"] += bool(losses)
                c[grid + "_prior_leaked_pairs"] += len(losses)
                for mode in ("both", "strongest"):
                    method = variants[mode]
                    k = f"{grid}_{mode}_"
                    c[k + method["status"]] += 1
                    c[k + "nodes"] += method.get("nodes", 0)
                    if method["status"] == "proved":
                        d = method["rational"]["denominator"]
                        c[k + "facts"] += len(method["attested"])
                        c[k + "classes"] += d
                        c[k + "compressed_values"] += raw_size + 1
                        c[k + "expanded_values"] += raw_size * d
                        if mode == "both":
                            c[grid + "_recovered"] += bool(losses)
                            c[grid + "_over_strongest"] += (
                                variants["strongest"]["status"] != "proved"
                            )
        sample = row["grids"]["60"]["both"]
        if sample["status"] == "proved":
            assert public.pop((case["source"], row["job"])) == dict(
                source=case["source"],
                packet=packet,
                groups=case["groups"],
                grid=60,
                attested=sample["attested"],
                rational=sample["rational"],
            )
        for key in ("total", case["source"]):
            total[key]["tasks"] += 1
            total[key]["checks"] += row["checks"]
    assert not public
    expected = json.loads((output / "lag-protection-results.json").read_bytes())
    assert total == expected["by_source"]
    gate = total["total"]["tasks"] == 35 and total["total"]["60_both_proved"] >= 18
    assert gate == expected["gate"]
    return dict(
        tasks=len(cases),
        solver_settings=6 * len(cases),
        public_packets=len(packets),
        gate=gate,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    parser.add_argument("replayed", type=Path)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(args.sources, args.replayed), indent=2))
