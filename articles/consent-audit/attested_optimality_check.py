"""Independent verification of optimality repairs using raw integer constraints."""

import argparse
from collections import Counter, defaultdict
import gzip
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from public_optimality_check import check_shorter, distances, groups_valid, model
from slack_certificate_check import potential
from transit_optimality_check import known_can_certify


def facts_from_pairs(f, actual, grid):
    for u, v in combinations(range(len(f)), 2):
        for a, b in ((u, v), (v, u)):
            c = actual[b] - actual[a]
            rounded = c - c % grid
            if rounded > -f[b][a]:
                yield a, b, rounded


class DirectOracle:
    """Raw Bellman–Ford on each disjunction chosen by a substitute reading set."""

    def __init__(self, packet, groups):
        self.n, self.archive, _, _, self.original, self.f, alt = model(packet)
        groups_valid(self.n, self.f, alt, groups)
        target = len(packet["certificate"]["disclosed"]) - 1
        self.problems = set()
        for kept in combinations(range(1, self.n), target):
            if any(not set(g).intersection(kept) for g, _ in groups):
                continue
            facts = set()
            for b in alt.values():
                disj = set()
                satisfied = False
                for i in (0, *kept):
                    for j in (0, *kept):
                        delta = b[i][j]
                        if -self.f[j][i] > delta:
                            satisfied = True
                        if self.f[i][j] > delta:
                            disj.add((j, i, -delta - 1))
                if not satisfied:
                    facts.add(tuple(sorted(disj)))
            if () not in facts:
                self.problems.add(tuple(sorted(facts, key=lambda d: (len(d), d))))

    def query(self, filters):
        extra = [(v, u, -cut) for u, v, cut in filters]
        known = [*self.original, *extra]
        assert potential(self.n, known) is not None

        def investigate(claim, source, problem):
            if claim == len(problem):
                return True
            for test in problem[claim]:
                next_source = [*source, test]
                if potential(self.n, next_source) is not None and investigate(
                    claim + 1, next_source, problem
                ):
                    return True
            return False

        return any(investigate(0, known, pr) for pr in sorted(self.problems))

    def locks(self, filters):
        state = distances(
            self.n, [*self.original, *((v, u, -b) for u, v, b in filters)]
        )
        assert state is not None
        return [
            i
            for i in range(1, self.n)
            if self.f[0][i] > -self.f[i][0] and state[0][i] == -state[i][0]
        ]

    def weakest(self, a, b, c, grid):
        start, end = (-self.f[b][a]) // grid, c // grid
        while end - start > 1:
            mid = (start + end) // 2
            if self.query([(a, b, mid * grid)]):
                start = mid
            else:
                end = mid
        return a, b, end * grid


def verify_bad(packet, w):
    check_shorter(
        packet,
        len(w["readings"]),
        {
            "record": w["record"],
            "disclosed": w["readings"],
        },
    )


def check_dictionary(case, oracle, grid, scored):
    actual, packet = case["actual"], case["packet"]
    candidates = sorted(facts_from_pairs(oracle.f, actual, grid))
    if scored["status"] == "unavailable":
        witness = scored["counterexample"]
        verify_bad(packet, witness)
        assert all(
            witness["record"][v] - witness["record"][u] >= t for u, v, t in candidates
        )
        return False
    assert scored["status"] == "proved"
    chosen = scored["attested"]
    assert all(actual[v] - actual[u] >= t and t % grid == 0 for u, v, t in chosen)
    assert not oracle.query(chosen)
    assert oracle.locks(chosen) == scored["newly_exact"]
    assert all(
        oracle.query([*chosen[:i], (u, v, t - grid), *chosen[i + 1 :]])
        for i, (u, v, t) in enumerate(chosen)
    )
    counterexamples = scored["trace"]
    for counterexample in counterexamples:
        verify_bad(packet, counterexample)
    narrower = []
    for w in counterexamples:
        narrower.append(
            {
                i
                for i, (u, v, t) in enumerate(candidates)
                if w["record"][v] - w["record"][u] < t
            }
        )
    assert chosen and counterexamples
    for proposed in combinations(range(len(candidates)), len(chosen) - 1):
        assert any(not set(proposed).intersection(conflict) for conflict in narrower)
    single = [f for f in candidates if not oracle.query([f])]
    assert scored["single_unary"] == any(0 in f[:2] for f in single)
    assert scored["single_pair"] == any(0 not in f[:2] for f in single)
    if len(chosen) == 1:
        best = min(len(oracle.locks([oracle.weakest(*f, grid)])) for f in single)
        assert best == len(scored["newly_exact"])
    return len(chosen) == 1 and not scored["newly_exact"]


def check(cases, scored):
    fixtures, reports, attestations = (
        json.loads(gzip.decompress(p.read_bytes()))
        for p in (
            cases,
            scored / "attested-optimality-ledger.json.gz",
            scored / "attested-optimality-packets.json.gz",
        )
    )
    packets = {(e["source"], e["job"]): e for e in attestations}
    counts = defaultdict(Counter)
    audit_counts = Counter()
    for c, row in zip(fixtures, reports, strict=True):
        packet, actual = c["packet"], c["actual"]
        assert (
            row["source"] == c["source"]
            and row["job"] == packet["job"]
            and row["run"] == packet["run"]
        )
        n, _, _, _, f, _, alt = model(packet)
        assert actual[0] == 0 and len(actual) == n
        assert all(actual[v] - actual[u] <= h for u, v, h in f)
        p = len(packet["certificate"]["disclosed"])
        assert not known_can_certify(n, actual, alt, p - 1)
        verify_bad(packet, c["prior_counterexample"])
        oracle = DirectOracle(packet, c["groups"])
        assert oracle.query([])
        raw = next(
            (
                i
                for i in range(1, n)
                if oracle.f[0][i] > -oracle.f[i][0]
                and not oracle.query([(0, i, actual[i]), (i, 0, -actual[i])])
            ),
            None,
        )
        assert raw == row["one_exact"]
        audit_counts["actual_minima"] += 1
        for grid, witness in row["grids"].items():
            criterion = check_dictionary(c, oracle, int(grid), witness)
            audit_counts["dictionary_checks"] += 1
            for src in (row["source"], "total"):
                result = counts[src]
                result[f"{grid}_{witness['status']}"] += 1
                if witness["status"] == "proved":
                    depth = len(witness["attested"])
                    result[f"{grid}_clauses_{depth}"] += 1
                    result[f"{grid}_unary_single"] += witness["single_unary"]
                    result[f"{grid}_pair_single"] += witness["single_pair"]
                    result[f"{grid}_new_exact_values"] += len(witness["newly_exact"])
                    result[f"{grid}_single_no_new_exact"] += criterion
                    result[f"{grid}_single_no_raw_repair"] += depth == 1 and raw is None
        for src in (row["source"], "total"):
            counts[src]["tasks"] += 1
            counts[src]["one_exact"] += raw is not None
            counts[src]["queries"] += row["queries"]
        chosen = row["grids"]["60"]
        if chosen["status"] == "proved":
            key = (row["source"], row["job"])
            published = packets.pop(key)
            assert set(published) == {
                "source",
                "job",
                "run",
                "packet",
                "groups",
                "grid",
                "attested",
            }
            assert published["groups"] == c["groups"] and published["packet"] == packet
            assert (
                published["attested"] == chosen["attested"] and published["grid"] == 60
            )
            audit_counts["public_repairs"] += 1
    assert not packets
    aggregate = json.loads((scored / "attested-optimality-results.json").read_bytes())
    assert counts == aggregate["by_source"]
    gate = (
        counts["total"]["tasks"] == 35
        and counts["total"]["60_single_no_new_exact"] >= 21
    )
    assert gate == aggregate["gate"]
    return dict(counts=audit_counts, gate=gate)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cases", type=Path)
    p.add_argument("scored", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.cases, a.scored), indent=2))
