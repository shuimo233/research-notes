"""Necessary refusal budget under truth, service, and single-view odds contracts."""

from fractions import Fraction

SERVICE = Fraction(1, 2)


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
