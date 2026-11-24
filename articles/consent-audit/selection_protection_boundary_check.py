"""Exhaustive small-world tests of selection leakage, ordering, and basis packing."""

from collections import Counter
from itertools import combinations, permutations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle
from conclusion_replay import closure
from selection_packing import exchange, extract, packed
from selection_protection import (
    comparison,
    fibre_log,
    safe_order,
    selected_by_bases,
    true_indices,
)
from selection_protection_check import affine_rank


def literal_family(atoms, worlds):
    return [{x for x in worlds if x[v] - x[u] >= b} for u, v, b in atoms]


def ordered(sets, order, rank):
    seen = set()
    for i in order:
        if affine_rank(sets[i] - seen) != rank:
            return False
        seen |= sets[i]
    return True


def can_pack(domains, rank):
    if len(set().union(*domains)) < len(domains) * rank:
        return False
    pools = [
        [set(c) for c in combinations(sorted(d), rank) if affine_rank(c) == rank]
        for d in sorted(domains, key=len)
    ]

    def extend(i, used):
        return i == len(pools) or any(
            extend(i + 1, used | q) for q in pools[i] if not used & q
        )

    return extend(0, set())


def check_tiny(rng):
    out = Counter()
    for _ in range(100):
        n = rng.randint(2, 3)
        bounds = [(0, rng.choice((1, 2))) for _ in range(n)]
        raw = [
            (a, b, 0, 2)
            for a, b in combinations(range(1, n + 1), 2)
            if rng.random() < 0.3
        ]
        zone = closure(bounds, raw)
        worlds = [
            x
            for x in ((0, *z) for z in product(*(range(t + 1) for _, t in bounds)))
            if all(s <= x[j] - x[i] <= t for i, j, s, t in raw)
        ]
        r = affine_rank(worlds)
        clauses = [
            (u, v, cut)
            for u, v in product(range(n + 1), repeat=2)
            if u != v
            for cut in (-1, 0, 1, 2)
            if r == affine_rank([x for x in worlds if x[v] - x[u] >= cut])
            and any(x[v] - x[u] < cut for x in worlds)
        ]
        ns = rng.randrange(min(4, len(clauses)) + 1)
        atoms = rng.sample(clauses, ns)
        if not atoms:
            continue
        zones = [comparison(zone, q) for q in atoms]
        family = literal_family(atoms, worlds)
        guess = safe_order(zone, atoms)
        truth = any(ordered(family, o, r) for o in permutations(range(ns)))
        assert truth == (guess["status"] == "proved")
        for i, fibre in enumerate(fibre_log(zone, atoms, range(ns))):
            seen = set().union(*family[:i])
            remaining = family[i] - seen
            assert fibre["empty"] == (not remaining)
            if remaining:
                assert bool(fibre["fixed"]) == (affine_rank(remaining) < r)
                assert bool(fibre["narrowed"]) == (remaining < family[i])
        scheme = packed(zone, zones)
        assert scheme["status"] in {"proved", "impossible"}
        assert (scheme["status"] == "proved") == can_pack(family, r)
        if scheme["status"] == "proved":
            hand = scheme["bases"]
            assert len({v for w in hand for v in w}) == ns * r
            for i in range(ns):
                assigned = [x for x in worlds if selected_by_bases(x, atoms, hand) == i]
                assert set(assigned) <= family[i] and affine_rank(assigned) == r
        out["nonempty_catalogues"] += 1
        out["priority_infeasible"] += not truth
        out["partition_infeasible"] += scheme["status"] == "impossible"
    return out


def exchange_checks(rng):
    worlds = [(0, x, y) for x, y in product(range(3), repeat=2)]
    for _ in range(30):
        available = rng.sample(worlds, 5)
        sets = [rng.sample(available, rng.randint(2, 5)) for _ in range(3)]
        result = exchange(sets, (1, 2))
        best = 0
        cases = product(
            *[[-1, *(i for i, s in enumerate(sets) if t in s)] for t in available]
        )
        for a in cases:
            ranks = [
                [w for w, k in zip(available, a, strict=True) if k == i]
                for i in range(3)
            ]
            if all(affine_rank(r) == len(r) for r in ranks):
                best = max(best, sum(len(r) for r in ranks))
        assert sum(len(r) for r in result) == best
    public = closure([(0, 4)])
    found = packed(public, [closure([(1, 4)]), closure([(3, 4)])])
    assert (
        found["status"] == "proved"
        and found["method"] == "kernel and matroid intersection"
    )
    assert set(found["bases"][1]) == {(0, 3), (0, 4)}
    bounded = closure([(-(10**12), 10**12), (2, 4)], [(1, 2, -(10**12), 10**12)])
    raw = {(0, 10**12, 4), (0, 10**12 - 1, 4)}
    counts = Counter()
    picked = extract(bounded, (1, 2), raw, counts, 100)
    assert affine_rank(picked) == 3 and all(w not in raw for w in picked)
    assert counts["cells"] < 10


def check_hard_gap():
    # Old g marks positions 1..3, output coordinates 4..9, alternate helpers 10,11.
    caps = [(0, 1)] * 9 + [(0, 2)] * 2
    rules = [(g, i, -1, 0) for g in range(1, 4) for i in (2 * g + 2, 2 * g + 3)]
    rules.extend((10 + i % 2, i, -2, 0) for i in range(4, 10))
    packet = dict(
        archive=dict(
            bands=caps, bounds=rules, targets=[(0, i, (1,)) for i in range(4, 10)]
        ),
        certificate=dict(disclosed=[(i, 0) for i in (1, 2, 3)], labels=[0] * 6),
    )
    oracle = DirectOracle(packet, [])
    atoms = [(0, 10, 1), (0, 11, 1)]
    assert (
        oracle.query([])
        and not oracle.query([atoms[0]])
        and not oracle.query([atoms[1]])
    )
    public = tuple(map(tuple, oracle.f))
    states = [(0, *[0] * 9, x, y) for x, y in product(range(3), repeat=2)]
    for x in states:
        assert oracle.query(
            [(0, 10, x[10]), (10, 0, -x[10]), (0, 11, x[11]), (11, 0, -x[11])]
        ) == (x[-2:] == (0, 0))
    assert safe_order(public, atoms)["status"] == "impossible"
    for order in ([0, 1], [1, 0]):
        first, second = fibre_log(public, atoms, order)
        assert not first["fixed"] and second["fixed"]
    witnesses = packed(public, [comparison(public, q) for q in atoms])
    assert witnesses["status"] == "proved"
    assigned = [
        [x for x in states if selected_by_bases(x, atoms, witnesses["bases"]) == i]
        for i in range(2)
    ]
    assert [affine_rank(a) for a in assigned] == [3, 3]
    for i, q in enumerate(atoms):
        probabilities = [
            1 / len(ks) for x in states if i in (ks := true_indices(x, atoms))
        ]
        assert max(probabilities) / min(probabilities) == 2
        assert {x for x in states if i in true_indices(x, atoms)} == literal_family(
            atoms, states
        )[i]
    return dict(
        same_contract_first_match_leak=True,
        deterministic_partition_avoids_exact_leak=True,
        randomized_ratio=2,
    )


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("enable assertions")
    rng = Random(1840630)
    outputs = check_tiny(rng)
    exchange_checks(rng)
    print(
        json.dumps(
            dict(
                **outputs,
                exchange_instances=30,
                greedy_repaired_by_exchange=True,
                **check_hard_gap(),
            )
        )
    )
