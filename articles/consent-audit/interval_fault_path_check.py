"""Compare path compression with direct enumeration of every report removal."""

from itertools import combinations
import gzip
import json
from pathlib import Path
from random import Random
import sys

from interval_fault_cut_check import EDGES, PAIRS, components, source_days
from interval_fault_path import compile_path


def oracle(size, bands, reports):
    graph_repairs, feasible = [], {}
    for i in range(len(reports)):
        relative = components(size, None, reports, {i})
        if relative is not None:
            ids, offset, _ = relative
            assert ids == [0] * size
            graph_repairs.append(i)
            low = max(a - x for (a, _), x in zip(bands, offset, strict=True))
            high = min(b - x for (_, b), x in zip(bands, offset, strict=True))
            if low <= high:
                feasible[i] = offset
    return graph_repairs, feasible


def check_values(packed, expected, pairs):
    assert set(packed.repair_edges) == expected.keys()
    out = {}
    for a, b in pairs:
        model = {i: x[b] - x[a] for i, x in expected.items()}
        assert len(set(model.values())) <= 2
        assert packed.values(a, b) == set(model.values())
        for i, value in model.items():
            assert packed.value_at(a, b, i) == value
        out[a, b] = model
    return out


def expect_outcomes(packed, model, target, limit, probes):
    s, t = target
    expected = {i: value >= limit for i, value in model[target].items()}
    labels = set(expected.values())
    assert packed.outcomes(s, t, limit) == labels
    found = []
    for u, v in probes:
        side = [
            {model[u, v][i] for i, x in expected.items() if x == label}
            for label in (False, True)
        ]
        decisive = len(labels) == 2 and not (side[0] & side[1])
        assert packed.can_settle(s, t, limit, u, v) == decisive
        answers = side[0] | side[1]
        impossible = max(answers, default=0) + 1
        for value in answers | {impossible}:
            want = {bool(i) for i, feasible in enumerate(side) if value in feasible}
            assert packed.after_probe(s, t, limit, u, v, value) == want
        if decisive:
            found.append((u, v))
    return found


def real(path, output):
    rows = json.loads(
        gzip.decompress((output / "interval-fault-cut-ledger.json.gz").read_bytes())
    )
    damaged = (row for row in rows if row["injection"] is not None)
    daily, queries, ambiguous, references = 0, 0, 0, 0
    for row, (panel, date, actual, bands) in zip(
        damaged, source_days(path), strict=True
    ):
        assert (row["panel"], row["date"]) == (panel, date)
        idx, error = row["injection"]
        reports = [
            (u, v, actual[v] - actual[u] + (error if i == idx else 0))
            for i, (u, v) in enumerate(EDGES)
        ]
        repairs, expected = oracle(5, bands, reports)
        assert idx in expected
        for choice in [None, *repairs]:
            compiled = compile_path(bands, reports, reference_edge=choice)
            model = check_values(compiled, expected, PAIRS)
            references += 1
            for pair, saved in zip(EDGES, row["targets"], strict=True):
                probes = [p for p in PAIRS if p != pair]
                found = expect_outcomes(compiled, model, pair, 10, probes)
                assert saved["query"] == (probes.index(found[0]) if found else None)
                for flag, (witness, ranges) in enumerate(
                    zip(saved["witnesses"], saved["ranges"], strict=True)
                ):
                    assert (witness is not None) == any(
                        (v >= 10) == flag for v in model[pair].values()
                    )
                    for probe, intervals in zip(probes, ranges, strict=True):
                        values = {
                            v
                            for i, v in model[probe].items()
                            if (model[pair][i] >= 10) == flag
                        }
                        assert values == {
                            x for lo, hi in intervals for x in range(lo, hi + 1)
                        }
        daily += 1
        queries += sum(t["query"] is not None for t in row["targets"])
        ambiguous += sum(
            all(w is not None for w in t["witnesses"]) for t in row["targets"]
        )
    return {
        "archives": daily,
        "decisions": daily * len(EDGES),
        "references_including_automatic": references,
        "ambiguous": ambiguous,
        "guaranteed_cross_checks": queries,
    }


def synthetic():
    rng = Random(281619)
    attempts, hypotheses, empty, cannot_repair, nontrivial = 0, 0, 0, 0, 0
    bridge_cases = 0
    for case in range(480):
        n = rng.randint(3, 8 if case % 8 == 0 else 9)
        cycle = [(i, (i + 1) % n) for i in range(n)]
        undirected = {tuple(sorted(edge)) for edge in cycle}
        links = cycle + [
            p
            for p in combinations(range(n), 2)
            if p not in undirected and rng.randrange(5) == 0
        ]
        bad = rng.sample(range(len(links)), 2 if case % 4 == 0 else 1)
        if case % 8 == 0:
            links.append((rng.randrange(n), n))
            n += 1
            bridge_cases += 1
        truth = [rng.randint(-25, 25) for _ in range(n)]
        bands = [
            (v - rng.randint(0, 7), v + rng.randint(0, 7))
            if rng.randrange(5)
            else (v, v)
            for v in truth
        ]
        reports = [
            (
                u,
                v,
                truth[v]
                - truth[u]
                + (rng.choice([-13, -3, -1, 1, 3, 13]) if i in bad else 0),
            )
            for i, (u, v) in enumerate(links)
        ]
        if components(n, None, reports, set()) is not None:
            # Keep the synthetic contract inconsistent if two perturbations cancel.
            i = bad[-1]
            u, v, delta = reports[i]
            reports[i] = (u, v, delta + 29)
            assert components(n, None, reports, set()) is None
        pairs = list(combinations(range(n), 2))
        repairs, expected = oracle(n, bands, reports)
        empty += not expected
        cannot_repair += not repairs
        nontrivial += len(expected) > 1
        for choice in [None, *repairs]:
            packed = compile_path(bands, reports, reference_edge=choice)
            model = check_values(packed, expected, pairs)
            attempts += 1
            for target, values in model.items():
                probes = [p for p in pairs if p != target]
                for threshold in sorted(
                    {0} | {x + d for x in values.values() for d in (0, 1)}
                ):
                    expect_outcomes(packed, model, target, threshold, probes)
                    hypotheses += len(probes)
    return {
        "graphs": 480,
        "with_bridges": bridge_cases,
        "compiled": attempts,
        "candidate_query_checks": hypotheses,
        "multiple_feasible_repairs": nontrivial,
        "no_feasible_repair": empty,
        "no_reading_repair": cannot_repair,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "noaa": real(*map(Path, sys.argv[1:])),
                "synthetic": synthetic(),
                "verified": True,
            }
        )
    )
