"""Necessary refusal budget under truth, service, and single-view odds contracts."""

from fractions import Fraction

SERVICE = Fraction(1, 2)


def binary_pair_policy(modes, floor_fraction=SERVICE):
    """Return the sharp joint ratio and rows when each side has one real label."""
    modes = tuple(map(tuple, modes))
    floor_fraction = Fraction(floor_fraction)
    pairs = set(modes)
    if (
        (0, 0) not in pairs
        or not pairs <= {(0, 0), (1, 0), (0, 1), (1, 1)}
        or {m[0] for m in pairs} != {0, 1}
        or {m[1] for m in pairs} != {0, 1}
        or not 0 < floor_fraction <= 1
    ):
        raise ValueError(
            "expected two binary views, a joint empty mode, and a positive floor"
        )
    rows = {
        (0, 0): {(-1, -1): Fraction(1)},
        (1, 0): {(-1, -1): SERVICE, (0, -1): SERVICE},
        (0, 1): {(-1, -1): SERVICE, (-1, 0): SERVICE},
    }
    ratio = Fraction(2)
    if (1, 1) in pairs:
        same = SERVICE - floor_fraction / 4
        if (1, 0) in pairs or (0, 1) in pairs:
            same = min(same, Fraction(1, 3))
        mixed = SERVICE - same
        rows[1, 1] = {(-1, -1): same, (0, 0): same, (0, -1): mixed, (-1, 0): mixed}
        ratio = 1 / same
    return ratio, [rows[mode] for mode in modes]


def refusal_budget(supports, caps, label_floors, pair_floors, ratio):
    """Find an over-budget refusal row or column without solving a policy."""
    if not any(all(len(axis) == 1 for axis in world) for world in supports):
        raise ValueError(
            "the refusal budget requires a feasible world with no releases"
        )
    lower = []
    for axis in (0, 1):
        labels = {j for world in supports for j in world[axis] if j >= 0}
        isolated = {
            next(j for j in world[axis] if j >= 0)
            for world in supports
            if len(world[axis]) == 2
        }
        lower.append(
            {
                j: max(label_floors[axis], SERVICE / caps[axis])
                if j in isolated
                else label_floors[axis]
                for j in labels
            }
        )
    both_null = max(Fraction(1) / ratio, pair_floors[-1, -1])
    for side in (0, 1):
        other = 1 - side
        exposure = {}
        for world in supports:
            if len(world[side]) == 1:
                for j in world[other]:
                    if j >= 0:
                        amount = SERVICE if len(world[other]) == 2 else lower[other][j]
                        exposure[j] = max(exposure.get(j, 0), amount)
        for k, world in enumerate(supports):
            if len(world[side]) == 1:
                continue
            capacity = 1 - max(
                SERVICE, sum(lower[side][i] for i in world[side] if i >= 0)
            )
            mass = both_null
            for j in world[other]:
                if j >= 0:
                    cell = (-1, j) if side == 0 else (j, -1)
                    mass += max(pair_floors[cell], exposure.get(j, 0) / ratio)
            if mass > capacity:
                return dict(
                    world=k, side=side, required=str(mass), capacity=str(capacity)
                )
    return None
