"""Certified bounds on additional sense reveals for a fixed strict first-stage cover."""

import argparse
from collections import Counter
from fractions import Fraction
from itertools import product
import json
from math import prod
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from go_model_fetch import verify
from wordnet_paths import NounPaths
from forest_cover_budget import forest_bounds


def footprints(graph, batch):
    cover = set(batch["cover_first_stage"])
    words = batch["words"]
    effects = {u: {x: set() for x in graph.senses(words[u])} for u in sorted(cover)}
    for a, b, _ in batch["queries"]:
        if (a in cover) == (b in cover):
            if a not in cover:
                labels = {
                    graph.relation(x, y)
                    for x in graph.senses(words[a])
                    for y in graph.senses(words[b])
                }
                if len(labels) != 1:
                    raise ValueError("first stage misses a nonconstant relation")
            continue
        u, v = (a, b) if a in cover else (b, a)
        for x, forced in effects[u].items():
            labels = {graph.relation(x, y) for y in graph.senses(words[v])}
            if len(labels) > 1:
                forced.add(v)
    return {
        u: [
            (fp, Fraction(n, len(by_sense)))
            for fp, n in sorted(
                Counter(tuple(sorted(vs)) for vs in by_sense.values()).items()
            )
        ]
        for u, by_sense in effects.items()
    }


def audit(groups):
    """groups maps each paid ID to (tuple of forced IDs, marginal mass) pairs."""
    from scipy.optimize import linprog

    arrays = list(groups.values())
    if any(
        not group or any(p <= 0 for _, p in group) or sum(p for _, p in group) != 1
        for group in arrays
    ):
        raise ValueError("each marginal must be positive and sum to one")
    worlds = list(product(*(range(len(g)) for g in arrays)))
    costs = [
        len(set().union(*(arrays[i][k][0] for i, k in enumerate(w)))) for w in worlds
    ]
    probs = [
        prod((arrays[i][k][1] for i, k in enumerate(w)), start=Fraction(1))
        for w in worlds
    ]
    matrix = [[1] * len(worlds)]
    marginals = [Fraction(1)]
    for i, g in enumerate(arrays):
        for k, (_, p) in enumerate(g[:-1]):
            matrix.append([int(w[i] == k) for w in worlds])
            marginals.append(p)

    def endpoint(sign):
        target = [sign * c for c in costs]
        lp = linprog(
            target,
            A_eq=matrix,
            b_eq=[float(p) for p in marginals],
            bounds=(0, None),
            method="highs-ds",
        )
        if not lp.success:
            raise ValueError(lp.message)

        def rational(x):
            return Fraction(float(x)).limit_denominator(10**7)

        mass = {j: rational(x) for j, x in enumerate(lp.x) if x > 0}
        prices = [rational(x) for x in lp.eqlin.marginals]
        if any(
            sum(row[j] * x for j, x in mass.items()) != b
            for row, b in zip(matrix, marginals, strict=True)
        ):
            raise ArithmeticError(
                "floating solution did not recover exact marginal constraints"
            )
        if any(
            sum(matrix[i][j] * p for i, p in enumerate(prices)) > v
            for j, v in enumerate(target)
        ):
            raise ArithmeticError("could not certify a feasible dual")
        value = sum(x * costs[j] for j, x in mass.items())
        if sign * value != sum(p * b for p, b in zip(prices, marginals, strict=True)):
            raise ArithmeticError("nonzero rational duality gap")
        return {
            "extra": str(value),
            "mass": {str(j): str(x) for j, x in mass.items()},
            "dual": list(map(str, prices)),
        }

    per_vertex = Counter()
    for choices in arrays:
        for ids, p in choices:
            for v in ids:
                per_vertex[v] += p
    return {
        "groups": {u: [[list(ids), str(p)] for ids, p in g] for u, g in groups.items()},
        "worlds": len(worlds),
        "independent": str(sum(p * c for p, c in zip(probs, costs, strict=True))),
        "local_upper": str(sum(min(1, v) for v in per_vertex.values())),
        "minimum": endpoint(1),
        "maximum": endpoint(-1),
    }


def run(archive, directory):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    rows = []
    for line in (ROOT / "shared-sense-ledger.jsonl").read_bytes().splitlines():
        batch = json.loads(line)
        if batch["shared"]:
            groups = footprints(graph, batch)
            rows.append(
                {
                    "source": batch["source"],
                    "sentence": batch["sentence"],
                    "paid": len(groups),
                    "posthoc_forest_bounds": forest_bounds(groups),
                    **audit(groups),
                }
            )
    result = {}
    for src in ("wsd", "semcor"):
        selected = [r for r in rows if r["source"] == src]
        values = [
            (
                Fraction(r["minimum"]["extra"]),
                Fraction(r["independent"]),
                Fraction(r["maximum"]["extra"]),
                Fraction(r["local_upper"]),
            )
            for r in selected
        ]
        paid = sum(r["paid"] for r in selected)
        result[src] = {
            "sentences": len(selected),
            "first_stage_cost": paid,
            "total_with_first_stage": {
                k: str(paid + sum(v[i] for v in values))
                for i, k in enumerate(
                    ("minimum", "independent", "maximum", "local_upper")
                )
            },
            "maximum_above_independent": sum(v[2] > v[1] for v in values),
            "local_upper_above_maximum": sum(v[3] > v[2] for v in values),
            "posthoc_certified_by_forest": sum(
                r["posthoc_forest_bounds"] is not None for r in selected
            ),
            "largest_compressed_state_count": max(r["worlds"] for r in selected),
        }
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "cover-dependence-ledger.jsonl").write_bytes(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode()
    )
    (directory / "cover-dependence-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("new_directory", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.new_directory), indent=2))
