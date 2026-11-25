"""Check optimal routing partitions via an independent cubic identity test."""

import argparse
from collections import Counter
from fractions import Fraction as F
from functools import cache
import gzip
from itertools import combinations, combinations_with_replacement
import json
from pathlib import Path
import sys

# The pinned input decoder is shared with the prior independent audit checker.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_runtime_drift_check import inputs, pinned

PIN = "7ab8549962cc6f4af64229a9fd9f44682f89c754"
FILES = (
    "audit-runtime-partition-policies.json.gz",
    "audit-runtime-partition-results.json",
)


@cache
def compatible(first, second, third, fourth):
    """Evaluate the homogeneous cubic cross difference on the full 3-lattice."""
    prod1 = tuple(a * b for a, b in zip(first, second, strict=True))
    prod2 = tuple(a * b for a, b in zip(third, fourth, strict=True))
    for lattice in combinations_with_replacement(range(len(first)), 3):
        # Pure assignments normalize to one by construction.
        if lattice[0] == lattice[-1]:
            continue
        p1, p2, q1, q2, i1, i2 = (
            sum(column[i] for i in lattice)
            for column in (first, second, third, fourth, prod1, prod2)
        )
        if i1 * q1 * q2 != i2 * p1 * p2:
            return False
    return True


def check_partition(rates, part):
    n = len(rates[0])
    blocks = part["blocks"]
    clique = part["clique"]
    flat = [i for row in blocks for i in row]
    assert (
        all(blocks)
        and all(type(i) is int for i in flat)
        and sorted(flat) == list(range(n))
    )
    assert len(clique) == len(blocks) == len(set(clique))
    assert all(type(j) is int and 0 <= j < n for j in clique)

    def allowed(pair):
        i, j = pair
        p, q = rates
        return compatible(p[i], p[j], q[i], q[j])

    for block in blocks:
        assert all(allowed(pair) for pair in combinations(block, 2))
    assert not any(allowed(pair) for pair in combinations(clique, 2))
    # Check all pair statuses independently when assigning class counts.
    return sum(not allowed(pair) for pair in combinations(range(n), 2))


def records(ledger, archive, drift):
    by_case = json.loads(gzip.decompress(pinned(drift.read_bytes(), PIN)))
    for (key, rates), boundary in zip(inputs(ledger, archive), by_case, strict=True):
        assert key[0] == boundary["case"]
        yield key, rates, boundary


def cost(draws, modes):
    return modes * (1 - F(modes - 1, modes) ** draws)


def summary(ledger, archive, drift, policies, verify=True):
    report = {}
    cases = records(ledger, archive, drift)
    for ((i, split, threshold, kind, _), rates, previous), out in zip(
        cases, policies, strict=True
    ):
        assert out["case"] == i
        bounds = out["partition"]
        if verify:
            conflicts = check_partition(rates, bounds)
            assert (not conflicts) == (len(bounds["blocks"]) == 1)
        k = len(bounds["blocks"])
        n = len(rates[0])
        m = len(rates[0][0])
        full = cost(n, m)
        chosen = (full + cost(k, m)) / 2
        certain_low = full - F(previous["ceiling"]) * (full - 1)
        certain_high = full - F(previous["safe"]) * (full - 1)
        assert [str(x) for x in (chosen, certain_low, certain_high)] == out["costs"]
        verdict = (
            "block_better"
            if chosen < certain_low
            else (
                "old_better"
                if chosen > certain_high
                else "equal"
                if certain_low == certain_high == chosen
                else "unresolved"
            )
        )
        for label in (kind, f"{kind}/{split}/{threshold}"):
            state = report.setdefault(
                label,
                {"counts": Counter(), "max_proved_saving": F(0), "best_case": None},
            )
            c = state["counts"]
            c["profiles"] += 1
            c[verdict] += 1
            c[f"{k}_blocks"] += 1
            c["below_independent"] += chosen < full
            saving = certain_low - chosen
            if saving > state["max_proved_saving"]:
                state["max_proved_saving"] = saving
                state["best_case"] = i
    result = {}
    for tag in sorted(report):
        row = report[tag]
        result[tag] = {
            "counts": {
                k: row["counts"][k]
                for k in (
                    "profiles",
                    "block_better",
                    "old_better",
                    "equal",
                    "unresolved",
                    "below_independent",
                    "1_blocks",
                    "2_blocks",
                    "3_blocks",
                    "4_blocks",
                )
            },
            "max_proved_saving": str(row["max_proved_saving"]),
            "best_case": row["best_case"],
        }
    assert (
        result["main"]["counts"]["profiles"]
        == result["diagnostic"]["counts"]["profiles"]
        == 1254
    )
    return {"sections": result, "gate": result["main"]["counts"]["block_better"] > 0}


def verify(ledger, archive, drift, destination):
    plans = json.loads(gzip.decompress((destination / FILES[0]).read_bytes()))
    report = summary(ledger, archive, drift, plans)
    assert report == json.loads((destination / FILES[1]).read_bytes())
    print(
        json.dumps({"verified": True, "profiles": len(plans), "gate": report["gate"]})
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("ledger", "archive", "drift", "destination"):
        cli.add_argument(key, type=Path)
    args = cli.parse_args()
    verify(args.ledger, args.archive, args.drift, args.destination)
