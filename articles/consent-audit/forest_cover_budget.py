"""Exact dependence bounds for a strict reveal plan when its residual factor graph is a forest."""

from collections import defaultdict
from fractions import Fraction
import json
import argparse
from pathlib import Path


def forest_bounds(groups):
    """groups maps first-stage IDs to (forced-ID collection, probability) alternatives."""
    marginals = defaultdict(dict)
    for u, choices in groups.items():
        total = Fraction(0)
        for ids, weight in choices:
            weight = Fraction(weight)
            if weight < 0:
                raise ValueError("negative mass")
            total += weight
            for v in set(ids):
                marginals[v][u] = marginals[v].get(u, 0) + weight
        if total != 1:
            raise ValueError("marginal weights must sum to one")
    # Merge only variable factors; a certainly forced outside ID contributes a constant.
    parent = {}

    def root(key):
        parent.setdefault(key, key)
        while key != parent[key]:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    lo, hi = Fraction(0), Fraction(0)
    for v, weights in marginals.items():
        lo += max(weights.values())
        hi += min(1, sum(weights.values()))
        if 1 in weights.values():
            continue
        for u, weight in weights.items():
            if not weight:
                continue
            left, right = root((0, u)), root((1, v))
            if left == right:
                return None
            parent[left] = right
    return {"minimum_extra": str(lo), "maximum_extra": str(hi)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "groups",
        type=Path,
        help="JSON mapping IDs to [forced-ID list, marginal probability] alternatives",
    )
    a = p.parse_args()
    result = forest_bounds(json.loads(a.groups.read_bytes()))
    print(
        json.dumps(
            result if result is not None else {"requires_joint_solver": True}, indent=2
        )
    )
