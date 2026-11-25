"""Certify a runtime-sharing limit over one uncertain categorical distribution."""

from fractions import Fraction as F
from heapq import heappop, heappush
from itertools import combinations
from math import prod

CAP = F(21, 20)
MAX_SHARE = F(1, 2)
DRIFT = F(1, 4)
RESOLUTION = F(1, 1000)
SPLITS = 96


def contract(rates, center):
    rates = tuple(tuple(tuple(map(F, v)) for v in table) for table in rates)
    if len(rates) != 2 or len(rates[0]) != len(rates[1]) or len(rates[0]) < 2:
        raise ValueError("expected two matching worlds with at least two requests")
    m = len(rates[0][0])
    if not m or any(
        len(row) != m or any(not 0 < r < 1 for r in row)
        for world in rates
        for row in world
    ):
        raise ValueError(
            "expected one common mode inventory with positive interior refusal rates"
        )
    center = (F(1, m),) * m if center is None else tuple(map(F, center))
    if len(center) != m or min(center) < 0 or sum(center) != 1:
        raise ValueError("expected a probability distribution over the modes")
    return rates, center


def model_inventory(rates, center):
    """Return one representative per relevant window and its grouped mode index."""
    unique = {}
    for depth in range(2, len(rates[0]) + 1):
        for window in combinations(range(len(rates[0])), depth):
            groups = []
            for table in rates:
                varying = sorted(table[i] for i in window if len(set(table[i])) > 1)
                groups.append(varying if len(varying) >= 2 else [])
            rows = [*groups[0], *groups[1]]
            if not rows:
                continue
            class_index = {}
            for i, column in enumerate(zip(*rows, strict=True)):
                class_index.setdefault(column, []).append(i)
            columns = tuple(sorted(class_index))
            means = tuple(sum(center[i] for i in class_index[c]) for c in columns)
            geometry = len(groups[0]), columns, means
            if geometry not in unique:
                unique[geometry] = (window, tuple(class_index[c][0] for c in columns))
    return [(shape, window, origin) for shape, (window, origin) in unique.items()]


def simplex(n):
    return tuple(tuple(F(i == j) for i in range(n)) for j in range(n))


def midpoint(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b, strict=True))


def centroid(points):
    return tuple(sum(v) / len(points) for v in zip(*points, strict=True))


def caps_from_slopes(slope, cap, maximum):
    return maximum if slope * maximum <= cap - 1 else (cap - 1) / slope


def categories(shape):
    cut, columns, _ = shape
    rates = tuple(zip(*columns, strict=True))
    return rates[:cut], rates[cut:]


def mixed(center, contamination, amount):
    return tuple(
        (1 - amount) * a + amount * b
        for a, b in zip(center, contamination, strict=True)
    )


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def evaluations(shape, weights):
    """The shared and independent masses with stable factors already removed."""
    for table in categories(shape):
        if not table:
            yield 1, 1
            continue
        shared = dot(weights, map(prod, zip(*table, strict=True)))
        independent = prod(dot(weights, row) for row in table)
        yield shared, independent


def slope_at(shape, weights, cap):
    (s, a), (t, b) = evaluations(shape, weights)
    x, y = F(s, a) - 1, F(t, b) - 1
    return max(x - cap * y, y - cap * x)


def monomial_product(factors, vertices):
    """Ordinary homogeneous monomial coefficients, shared scale in both ratios."""
    result = {(0,) * vertices: F(1)}
    for factor in factors:
        updated = {}
        for power, value in result.items():
            for i, scale in enumerate(factor):
                key = power[:i] + (power[i] + 1,) + power[i + 1 :]
                updated[key] = updated.get(key, 0) + value * scale
        result = updated
    return result


def upper_slopes(shape, vertices, amount, cap, coarse_only=False):
    _, _, center = shape
    points = [mixed(center, v, amount) for v in vertices]
    rates, shared = [], []
    loose = []
    for table in categories(shape):
        rates.append([tuple(dot(w, row) for w in points) for row in table])
        shared.append(
            tuple(dot(w, map(prod, zip(*table, strict=True))) for w in points)
            if table
            else (F(1),) * len(points)
        )
        loose.append(
            (
                min(shared[-1]) / prod(map(max, rates[-1])) - 1,
                max(shared[-1]) / prod(map(min, rates[-1])) - 1,
            )
        )
    rough = max(loose[0][1] - cap * loose[1][0], loose[1][1] - cap * loose[0][0])
    if coarse_only:
        return rough

    n = len(vertices)
    den = monomial_product([*rates[0], *rates[1]], n)
    nums = [
        monomial_product(
            [*rates[1 - i], shared[i], *([(F(1),) * n] * (len(rates[i]) - 1))], n
        )
        if rates[i]
        else den
        for i in range(2)
    ]
    # If D has strictly positive coefficients, each term N_alpha / D_alpha
    # is averaged with the nonnegative weight D_alpha * barycentric^alpha.
    best = max(
        max(
            (nums[0][k] - v) - cap * (nums[1][k] - v),
            (nums[1][k] - v) - cap * (nums[0][k] - v),
        )
        / v
        for k, v in den.items()
    )
    return min(best, rough)


def plan(
    rates,
    center=None,
    drift=DRIFT,
    cap=CAP,
    max_share=MAX_SHARE,
    resolution=RESOLUTION,
    budget=SPLITS,
):
    rates, center = contract(rates, center)
    drift, cap, max_share, resolution = map(F, (drift, cap, max_share, resolution))
    if (
        not 0 <= drift <= 1
        or cap < 1
        or not 0 < max_share <= 1
        or resolution <= 0
        or type(budget) is not int
        or budget < 0
    ):
        raise ValueError("invalid uncertainty, cap, resolution, or split budget")
    inventory = model_inventory(rates, center)
    best, witness = F(0), None
    initial_center, initial_vertices, coarse = F(0), F(0), F(0)
    pending, cuts = [], []
    full_modes = len(center)

    def consider(k, point):
        nonlocal best, witness
        shape, window, origins = inventory[k]
        value = slope_at(shape, mixed(shape[2], point, drift), cap)
        if value > best:
            best = value
            u = [F(0)] * full_modes
            for i, p in zip(origins, point, strict=True):
                u[i] = p
            witness = {"window": list(window), "contamination": list(map(str, u))}
        return value

    for k, (shape, _, _) in enumerate(inventory):
        initial_center = max(initial_center, consider(k, shape[2]))
        key = simplex(len(shape[2]))
        initial_vertices = max(initial_vertices, *(consider(k, v) for v in key))
        coarse = max(coarse, upper_slopes(shape, key, drift, cap, coarse_only=True))
        heappush(pending, (-upper_slopes(shape, key, drift, cap), k, "", key))
        consider(k, centroid(key))

    def share(h):
        return caps_from_slopes(h, cap, max_share)

    for _ in range(budget):
        upper = max(best, -pending[0][0]) if pending else best
        if share(best) - share(upper) <= resolution:
            break
        _, k, path, vertices = heappop(pending)
        i, j = max(
            combinations(range(len(vertices)), 2),
            key=lambda ij: sum(
                (a - b) ** 2
                for a, b in zip(vertices[ij[0]], vertices[ij[1]], strict=True)
            ),
        )
        mid = midpoint(vertices[i], vertices[j])
        cuts.append([k, path, i, j])
        consider(k, mid)
        for digit, position in (("0", i), ("1", j)):
            v = vertices[:position] + (mid,) + vertices[position + 1 :]
            upper = upper_slopes(inventory[k][0], v, drift, cap)
            consider(k, centroid(v))
            heappush(pending, (-upper, k, path + digit, v))
    upper = max(best, -pending[0][0]) if pending else best
    return {
        "center_cap": str(share(initial_center)),
        "vertex_cap": str(share(initial_vertices)),
        "separate_safe": str(share(coarse)),
        "safe": str(share(upper)),
        "ceiling": str(share(best)),
        "models": len(inventory),
        "max_modes": max((len(shape[2]) for shape, _, _ in inventory), default=0),
        "splits": cuts,
        "witness": witness,
    }


def main():
    import argparse
    import json
    from pathlib import Path

    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("contract", type=Path)
    arg = cli.parse_args()
    data = json.loads(arg.contract.read_text(encoding="utf-8"))
    print(json.dumps(plan(**data)))


if __name__ == "__main__":
    main()
