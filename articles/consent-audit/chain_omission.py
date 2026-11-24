"""Exact robust one-omission policy for all-pairs comparison on a binary active-sense chain."""

import argparse
from fractions import Fraction as Q
import json
from pathlib import Path
from itertools import combinations
from secrets import choice


def plan(probabilities):
    ordered = sorted(
        ((u, Q(p)) for u, p in probabilities.items()),
        key=lambda item: (-item[1], item[0]),
    )
    n = len(ordered)
    if n < 2 or any(p < 0 or p > 1 for _, p in ordered):
        raise ValueError(
            "supply at least two named positions with probabilities in [0,1]"
        )
    mu = sum(p for _, p in ordered)
    suffix = mu - ordered[0][1]
    pure = max(Q(0), 1 - suffix)
    saving, support = pure, 1
    for k, (_, p) in enumerate(ordered[1:], 2):
        suffix -= p
        candidate = (2 - mu - suffix) / k
        if candidate > saving:
            saving, support = candidate, k
    if mu <= 1:
        adverse = {
            "empty": str(1 - mu),
            "singletons": {u: str(p) for u, p in ordered if p},
        }
    elif mu >= 2:
        adverse = {"systematic_mass": "1", "inclusion": {u: str(p) for u, p in ordered}}
    else:
        pair_mass = mu - 1
        singletons = {u: max(Q(0), p - pair_mass) for u, p in ordered}
        remaining = 2 - mu - sum(singletons.values())
        for u, p in ordered:
            take = min(remaining, min(p, saving) - singletons[u])
            singletons[u] += take
            remaining -= take
        assert remaining == 0
        adverse = {
            "singletons": {u: str(p) for u, p in singletons.items() if p},
            "systematic_mass": str(pair_mass),
            "inclusion": {u: str((p - singletons[u]) / pair_mass) for u, p in ordered},
        }
    return {
        "cost": str(n - saving),
        "pure_cost": str(n - pure),
        "omit_uniformly_from": [u for u, _ in ordered[:support]],
        "adverse": adverse,
    }


def compare(positions, probabilities, ask, choose=choice):
    """Positions run from narrow to broad. ask(batch) returns one active/inactive bool per requested ID."""
    positions = list(positions)
    if len(set(positions)) != len(positions) or set(positions) != set(probabilities):
        raise ValueError("positions must list each marginal ID exactly once")
    policy = plan(probabilities)
    options = policy["omit_uniformly_from"]
    later = choose(options)
    if later not in options:
        raise ValueError("invalid random choice")
    batches = []

    def reveal(batch):
        response = ask(tuple(batch))
        if set(response) != set(batch) or any(
            type(v) is not bool for v in response.values()
        ):
            raise ValueError("each requested position needs one boolean response")
        batches.append(list(batch))
        return dict(response)

    known = reveal([u for u in positions if u != later])
    if any(known.values()):
        known.update(reveal([later]))
    relations = [
        [
            u,
            v,
            "left_narrower"
            if known.get(u, False) and known.get(v, False)
            else "neither",
        ]
        for u, v in combinations(positions, 2)
    ]
    return {"batches": batches, "relations": relations}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "marginals",
        type=Path,
        help="JSON object mapping a position to a rational string",
    )
    p.add_argument(
        "--compare",
        nargs="+",
        metavar="ID",
        help="interactively resolve all pairs; give IDs ordered narrow to broad",
    )
    args = p.parse_args()
    marginals = json.loads(args.marginals.read_bytes())

    def ask(batch):
        response = {}
        for u in batch:
            bit = input(f"{u}: is its chain sense active? [0/1] ").strip()
            if bit not in ("0", "1"):
                raise ValueError("expected 0 or 1")
            response[u] = bit == "1"
        return response

    result = (
        compare(args.compare, marginals, ask)
        if args.compare is not None
        else plan(marginals)
    )
    print(json.dumps(result, indent=2))
