"""Literal finite worlds for the attestation, hull, and two/three-reading boundary."""

from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality import (
    ShorterWorlds,
    impose,
    largest_two_read_zone,
    repair,
    true_comparisons,
)
from conclusion_replay import closure
from public_optimality import PublicAudit
from slack_certificate import classifications


def space(bands, facts):
    return [
        x
        for x in (
            (0, *values) for values in product(*(range(lo, hi + 1) for lo, hi in bands))
        )
        if all(a <= x[v] - x[u] <= b for u, v, a, b in facts)
    ]


def actual_case(bands, facts, targets, actual, disclosed=None):
    target = classifications(targets, actual)
    universe = space(bands, facts)
    wrong = [w for w in universe if classifications(targets, w) != target]
    templates = {}
    ids = range(1, len(actual))

    def excluded(positions):
        if positions not in templates:
            templates[positions] = {tuple(w[i] for i in positions) for w in wrong}
        return templates[positions]

    if disclosed is None:
        disclosed = next(
            s
            for k in range(len(actual))
            for s in combinations(ids, k)
            if tuple(actual[i] for i in s) not in excluded(s)
        )

    p = len(disclosed)
    public = [w for w in universe if all(w[i] == actual[i] for i in disclosed)]
    substitutes = list(combinations(ids, max(p - 1, 0)))
    bad = [
        w
        for w in public
        if p and any(tuple(w[i] for i in s) not in excluded(s) for s in substitutes)
    ]
    audit = PublicAudit(
        closure(bands, facts),
        targets,
        dict(labels=target, disclosed=[(i, actual[i]) for i in disclosed]),
    )
    assert actual not in bad
    return audit, public, bad


def hull_contains(points, record):
    return all(
        record[v] - record[u] <= max(x[v] - x[u] for x in points)
        for u, v in product(range(len(record)), repeat=2)
    )


def direct_verify(audit, bad, actual, grid):
    oracle = ShorterWorlds(audit, [])
    result = repair(oracle, actual, grid)
    claims = true_comparisons(audit.fibre, actual, grid)
    if result["status"] == "unavailable":
        assert any(all(w[v] - w[u] >= t for u, v, t in claims) for w in bad)
        return
    assert result["status"] == "proved"
    chosen = result["attested"]
    assert all(any(w[v] - w[u] < t for u, v, t in chosen) for w in bad)
    assert not any(
        all(any(w[v] - w[u] < t for u, v, t in s) for w in bad)
        for s in combinations(claims, len(chosen) - 1)
    )
    if grid == 1:
        assert (len(chosen) == 1) == (not hull_contains(bad, actual))
    assert all(actual[v] - actual[u] >= t for u, v, t in chosen)


def check_random():
    rng = Random(16822)
    two, total, bad_cases, dictionaries = 0, 0, 0, 0
    for _ in range(120):
        n = rng.choice((3, 4))
        bands = [(-1, rng.choice((0, 1)))] * n
        actual = (0, *(rng.randrange(lo, hi + 1) for lo, hi in bands))
        true_facts, targets = [], []
        for u, v in combinations(range(n + 1), 2):
            d = actual[v] - actual[u]
            if rng.random() < 0.35:
                true_facts.append((u, v, d - rng.randrange(3), d + rng.randrange(3)))
            if rng.random() < 0.5:
                targets.append((u, v, tuple(sorted(rng.sample(range(-3, 4), 2)))))
        audit, public, bad = actual_case(bands, true_facts, targets, actual)
        total += 1
        if bad:
            bad_cases += 1
            for grid in (1, 2):
                direct_verify(audit, bad, actual, grid)
                dictionaries += 1
        if len(audit.disclosed) == 2:
            z, _ = largest_two_read_zone(audit, actual)
            for x in public:
                in_largest = all(
                    x[v] - x[u] <= z[u][v] for u, v in product(range(n + 1), repeat=2)
                )
                pair_ok = not any(hull_contains([actual, x], w) for w in bad)
                assert in_largest == pair_ok
            two += 1
    return dict(
        random_networks=total,
        random_information_gaps=bad_cases,
        dictionary_optima=dictionaries,
        two_read_regions=two,
    )


def check_boundaries():
    bands = [(0, 1)] * 4 + [(0, 2)]
    facts = [(a, e, -1, 0) for a in (1, 2) for e in (3, 4)]
    actual = (0, 1, 1, 0, 0, 1)
    audit, public, bad = actual_case(
        bands, facts, [(0, i, (1,)) for i in (3, 4)], actual, (3, 4)
    )
    assert hull_contains(bad, actual)
    oracle = ShorterWorlds(audit, [])
    assert len(repair(oracle, actual, 1)["attested"]) == 2
    assert repair(oracle, actual, 60)["status"] == "unavailable"
    z, facts = largest_two_read_zone(audit, actual)
    assert z[0][5] == 2 and -z[5][0] == 0
    assert oracle.find(facts) is None

    bands = [(0, 1)] * 11
    # g1..g3 = positions 1..3, six targets = 4..9, a,b = positions 10,11.
    facts = [(v, j, 0, 1) for v in (1, 2, 3) for j in (2 * v + 2, 2 * v + 3)]
    facts.extend((10 + i % 2, i, 0, 1) for i in range(4, 10))
    targets = [(0, i, (1,)) for i in range(4, 10)]
    actual = (0, *([1] * 9), 0, 0)
    audit, public, bad = actual_case(bands, facts, targets, actual, (1, 2, 3))
    assert len(bad) == 1 and bad[0][-2:] == (1, 1)
    assert hull_contains([w for w in public if 0 in w[-2:]], bad[0])
    oracle = ShorterWorlds(audit, [])
    assert oracle.find([(10, 0, 0)]) is None
    assert oracle.find([(11, 0, 0)]) is None
    try:
        impose(audit.fibre, [(0, 10, 2)])
    except ValueError:
        pass
    else:
        raise AssertionError("contradictory attestation was accepted")
    return dict(
        hull_obstruction=True, coarse_dictionary_gap=True, three_read_nonunique=True
    )


def check_structured_gaps():
    rng = Random(16473)
    count = 0
    for _ in range(48):
        m = rng.choice((2, 3))
        high = rng.choice((1, 2))
        regions = [
            set(rng.sample(range(3, m + 3), rng.randrange(2, m + 1))) for _ in range(2)
        ]
        actual = (0, rng.randint(1, high), rng.randint(1, high), *([0] * m))
        bands = [(0, high)] * (m + 2)
        facts = [
            (i, e, -high, 0)
            for i, region in enumerate(regions, 1)
            for e in sorted(region)
        ]
        targets = [(0, e, (1,)) for e in range(3, m + 3)]
        audit, _, bad = actual_case(
            bands, facts, targets, actual, tuple(range(3, m + 3))
        )
        assert bad
        for grid in (1, 2):
            direct_verify(audit, bad, actual, grid)
            count += 1
    return dict(structured_information_gaps=48, structured_dictionary_optima=count)


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(
        json.dumps(
            dict(**check_random(), **check_boundaries(), **check_structured_gaps())
        )
    )
