"""Solve a private mixed-cover game against one unknown joint distribution with fixed marginals."""

import argparse
from fractions import Fraction as Q
from itertools import product
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from certified_cover_plan import minimal_covers
from coupling_clock import canonical


def solve(groups, preferred=None):
    from scipy.optimize import linprog
    import numpy as np
    from scipy.sparse import csr_matrix, hstack

    # Zero-probability alternatives still determine which questions must be answered.
    edges = set()
    for u, g in groups.items():
        for targets, _ in g:
            for t in targets:
                if t not in groups or t == u:
                    raise ValueError("invalid target ID")
                edges.add(tuple(sorted((u, t))))
    groups = canonical(groups)
    vertices = list(groups)
    covers = list(minimal_covers(vertices, edges))
    arrays = list(groups.values())
    worlds = list(product(*(range(len(g)) for g in arrays)))
    forced = [set().union(*(g[k][0] for g, k in zip(arrays, w))) for w in worlds]
    costs = [[len(c) + len(f.difference(c)) for f in forced] for c in covers]
    eq = [[1] * len(worlds)]
    rhs = [Q(1)]
    for i, g in enumerate(arrays):
        for k, (_, p) in enumerate(g[:-1]):
            eq.append([int(w[i] == k) for w in worlds])
            rhs.append(p)
    matrix = csr_matrix(eq, dtype=float)

    def rational(v):
        return Q(float(v)).limit_denominator(10**7)

    lp = linprog(
        [0] * len(worlds) + [-1],
        A_eq=hstack((matrix, csr_matrix((len(eq), 1)))),
        b_eq=list(map(float, rhs)),
        A_ub=hstack((-csr_matrix(costs, dtype=float), np.ones((len(covers), 1)))),
        b_ub=[0] * len(covers),
        bounds=[(0, None)] * len(worlds) + [(None, None)],
        method="highs-ds",
    )
    if not lp.success:
        raise RuntimeError(lp.message)
    mass = {j: rational(x) for j, x in enumerate(lp.x[:-1]) if x > 0}
    mixed = {i: rational(-v) for i, v in enumerate(lp.ineqlin.marginals) if v < 0}
    prices = [rational(-v) for v in lp.eqlin.marginals]
    value = rational(lp.x[-1])
    if preferred is not None:
        i = covers.index(tuple(sorted(preferred)))
        single = linprog(
            [-x for x in costs[i]],
            A_eq=matrix,
            b_eq=list(map(float, rhs)),
            method="highs-ds",
        )
        if not single.success:
            raise RuntimeError(single.message)
        alt = [rational(-v) for v in single.eqlin.marginals]
        if sum(p * b for p, b in zip(alt, rhs)) == value and all(
            sum(p * r[j] for p, r in zip(alt, eq)) >= v for j, v in enumerate(costs[i])
        ):
            mixed = {i: Q(1)}
            prices = alt
    if sum(mixed.values()) != 1 or not all(
        p >= 0 for p in (*mixed.values(), *mass.values())
    ):
        raise ArithmeticError("invalid rational strategies")
    if any(sum(row[j] * p for j, p in mass.items()) != b for row, b in zip(eq, rhs)):
        raise ArithmeticError("joint strategy violates marginals")
    if any(sum(row[j] * p for j, p in mass.items()) < value for row in costs):
        raise ArithmeticError(
            "a deterministic cover beats the claimed saddle lower bound"
        )
    if sum(b * p for b, p in zip(rhs, prices)) != value or any(
        sum(pr * row[j] for pr, row in zip(prices, eq))
        < sum(p * costs[i][j] for i, p in mixed.items())
        for j in range(len(worlds))
    ):
        raise ArithmeticError("upper price certificate failed")
    return {
        "value": str(value),
        "sources": vertices,
        "world_count": len(worlds),
        "covers": len(covers),
        "mixture": [[list(covers[i]), str(p)] for i, p in mixed.items()],
        "adverse": [[list(worlds[j]), str(p)] for j, p in mass.items()],
        "prices": list(map(str, prices)),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "groups",
        type=Path,
        help="all token IDs, each with [possibly forced IDs, marginal mass] alternatives",
    )
    a = p.parse_args()
    print(json.dumps(solve(json.loads(a.groups.read_bytes())), indent=2))
