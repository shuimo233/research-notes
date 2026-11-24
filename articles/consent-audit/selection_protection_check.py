"""Independently verify catalogue completeness, first-match cells, and disjoint bases."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import gzip
from itertools import combinations, product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attested_optimality_check import DirectOracle, verify_bad
from lag_protection_check import verify_decoding
from public_optimality_check import distances, model
from selection_protection_run import count, source
from slack_certificate_check import potential
from transit_optimality_check import known_can_certify


def require(atom):
    u, v, b = atom
    return v, u, -b


def refuse(atom):
    u, v, b = atom
    return u, v, b - 1


def new_lags(before, after):
    return [
        [i, j]
        for i, j in combinations(range(len(before)), 2)
        if before[i][j] > -before[j][i] and after[i][j] == -after[j][i]
    ]


def compile_independently(checker, grid):
    q = []
    n, before = checker.n, checker.f
    used = set()
    for i, j in product(range(n), repeat=2):
        if i == j:
            continue
        low = -before[j][i] // grid
        high = before[i][j] // grid
        if high <= low or checker.query([(i, j, high * grid)]):
            continue
        while high - low > 1:
            mid = (high + low) // 2
            if checker.query([(i, j, mid * grid)]):
                low = mid
            else:
                high = mid
        atom = (i, j, high * grid)
        world = distances(n, [*checker.original, require(atom)])
        assert world is not None
        shape = tuple(map(tuple, world))
        if shape not in used and not new_lags(before, world):
            used.add(shape)
            q.append(list(atom))
    return q


def replay(checker, atoms, ordering):
    inherited = list(checker.original)
    out = []
    for index in ordering:
        atom = atoms[index]
        cell = distances(checker.n, [*inherited, require(atom)])
        canonical = distances(checker.n, [*checker.original, require(atom)])
        out.append(
            dict(
                index=index,
                empty=cell is None,
                fixed=[] if cell is None else new_lags(checker.f, cell),
                narrowed=0
                if cell is None
                else sum(
                    cell[i][j] < canonical[i][j]
                    for i, j in product(range(checker.n), repeat=2)
                ),
            )
        )
        inherited.append(refuse(atom))
    return out


def verify_order(oracle, atoms, result):
    if result["status"] == "proved":
        assert sorted(result["order"]) == list(range(len(atoms)))
        assert all(
            not r["empty"] and not r["fixed"]
            for r in replay(oracle, atoms, result["order"])
        )
        return
    assert result["status"] == "impossible"
    subset = result["blocked"]
    assert subset and len(subset) == len(set(subset))
    for j in subset:
        exc = [
            *oracle.original,
            require(atoms[j]),
            *(refuse(atoms[i]) for i in subset if i != j),
        ]
        z = distances(oracle.n, exc)
        assert z is None or new_lags(oracle.f, z)


def affine_rank(rows):
    basis = {}
    for x in rows:
        t = list(map(Fraction, (1, *x)))
        for i in sorted(basis):
            factor = t[i]
            if factor:
                t = [a - factor * b for a, b in zip(t, basis[i], strict=True)]
        if any(t):
            k = next(i for i, x in enumerate(t) if x)
            basis[k] = [a / t[k] for a in t]
    return len(basis)


def verify_bases(oracle, atoms, r):
    if not atoms:
        assert r == dict(status="empty")
        return
    assert r["status"] == "proved"
    d = oracle.f
    classes = {
        min(j for j in range(oracle.n) if d[i][j] == -d[j][i]) for i in range(oracle.n)
    }
    all_rows = set()
    for atom, samples in zip(atoms, r["bases"], strict=True):
        assert len(samples) == len(classes) == affine_rank(samples)
        u, v, b = atom
        for x in samples:
            assert len(x) == oracle.n and x[0] == 0
            assert all(type(p) is int for p in x)
            assert tuple(x) not in all_rows
            all_rows.add(tuple(x))
            assert all(x[j] - x[i] <= t for i, j, t in oracle.original)
            assert x[v] - x[u] >= b


def independent_selection(x, atoms, plan):
    possible = [i for i, (u, v, c) in enumerate(atoms) if x[v] - x[u] >= c]
    table = {tuple(w): j for j, rows in enumerate(plan.get("bases", [])) for w in rows}
    winner = next(iter(possible), None)
    assigned = table.get(tuple(x), winner)
    if assigned is not None:
        assert assigned in possible
    return possible, winner, assigned


def check(directory, output):
    cases = source(directory, "attested-optimality-cases.json.gz")
    prior = source(directory, "lag-protection-ledger.json.gz")
    samples, packages = (
        json.loads(
            gzip.decompress(
                (output / f"selection-protection-{tag}.json.gz").read_bytes()
            )
        )
        for tag in ("ledger", "packets")
    )
    published = {(r["source"], r["job"]): r for r in packages}
    verified = defaultdict(Counter)
    for case, old, row in zip(cases, prior, samples, strict=True):
        packet = case["packet"]
        assert all(packet[k] == row[k] == old[k] for k in ("run", "job"))
        assert case["source"] == row["source"] == old["source"]
        assert row["status"] == "scored"
        n, _, _, _, f_edges, _, alt = model(packet)
        actual = case["actual"]
        assert actual[0] == 0 and all(actual[v] - actual[u] <= t for u, v, t in f_edges)
        assert not known_can_certify(
            n, actual, alt, len(packet["certificate"]["disclosed"]) - 1
        )
        verify_bad(packet, case["prior_counterexample"])
        oracle = DirectOracle(packet, case["groups"])
        assert oracle.query([])
        atoms = compile_independently(oracle, 60)
        policy = row["basis_plan"]
        assert len(atoms) == row["labels"]
        assert row["first_fibres"] == replay(oracle, atoms, range(len(atoms)))
        verify_order(oracle, atoms, row["priority"])
        verify_bases(oracle, atoms, policy)
        public_pairs = sum(
            potential(oracle.n, [*oracle.original, require(a), require(b)]) is not None
            for a, b in combinations(atoms, 2)
        )
        assert public_pairs == row["intersecting_supports"]
        if atoms:
            pub = published.pop((row["source"], row["job"]))
            assert pub["packet"] == packet and pub["groups"] == case["groups"]
            assert (
                pub["grid"] == 60
                and pub["basis_plan"] == policy
                and pub["priority"] == row["priority"]
            )
            assert [r["comparison"] for r in pub["entries"]] == atoms
            for item in pub["entries"]:
                verify_decoding(oracle, [item["comparison"]], item["rational"])
        labels, selected, assigned = independent_selection(actual, atoms, policy)
        assert labels == row["true_labels"] and selected == row["selected_first"]
        assert assigned == row["selected_by_bases"]
        past_min = old["grids"]["60"]["both"]
        assert (
            bool(labels)
            == row["prior_single"]
            == (past_min["status"] == "proved" and len(past_min["attested"]) == 1)
        )
        for name in ("total", row["source"]):
            count(verified[name], row)
    assert not published
    expected = json.loads((output / "selection-protection-results.json").read_bytes())
    assert expected["by_source"] == verified
    reality = verified["total"]
    assert expected["gate"] == (
        reality["tasks"] == 35 and reality["actual_basis_safe"] >= 18
    )
    return dict(
        cases=len(samples),
        catalogues=len(packages),
        labels=reality["labels"],
        distinct_affine_witnesses=reality["witness_worlds"],
        gate=expected["gate"],
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sources", type=Path)
    p.add_argument("replayed", type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(check(a.sources, a.replayed), indent=2))
