"""Check whether a coordinate group is needed for every public-compatible record."""

from functools import lru_cache
from itertools import combinations, product

from public_optimality import tighten
from public_optimality_exact import possible


def outside(audit, group):
    group = frozenset(group)
    if any(type(i) is not int or not 0 < i < len(audit.archive) for i in group):
        raise ValueError("a witness group must contain payable positions")
    return tuple(i for i in range(1, len(audit.archive)) if i not in group)


def provider_search(audit, group, budget=50_000):
    """Use at most two extremal-provider choices per hidden coordinate."""
    group = frozenset(group)
    free = (0, *outside(audit, group))
    distance = audit.archive
    targets = tuple(audit.alternatives)
    kinds = sorted(
        {(0, u) for u, _, _ in targets if u in group}
        | {(1, v) for _, v, _ in targets if v in group}
    )
    count = 0
    for selection in product(free, repeat=len(kinds)):
        if budget is not None and count >= budget:
            return None, count, True
        count += 1
        providers = dict(zip(kinds, selection, strict=True))
        d = audit.fibre
        for u, v, b in targets:
            i = providers.get((0, u), u)
            j = providers.get((1, v), v)
            d = tighten(d, i, j, b - distance[u][i] - distance[j][v])
            if d is None:
                break
        if d is not None:
            return d[0], count, False
    return None, count, False


def refutable(audit, group, method, budget=50_000):
    """Return a record certifiable without this group, a count, and a budget flag."""
    free = outside(audit, group)
    if method == "providers":
        return provider_search(audit, group, budget)
    if method == "pairs":
        return possible(audit, free, budget)
    raise ValueError("unknown group verification method")


def binary_compatible(audit, group):
    """Find a multicolored clique of excluding pairs on a binary domain."""
    fixed = (0, *outside(audit, group))
    f = audit.fibre
    if any(-f[i][0] < 0 or f[0][i] > 1 for i in range(1, len(f))):
        raise ValueError("binary clique compilation requires domains within {0,1}")
    colours = []
    for u, v, b in audit.alternatives:
        alternative = tighten(audit.archive, v, u, -b - 1)
        choices = set()
        for i, j in combinations(fixed, 2):
            for a, c in product(
                range(-f[i][0], f[0][i] + 1), range(-f[j][0], f[0][j] + 1)
            ):
                if not -f[j][i] <= c - a <= f[i][j]:
                    continue
                if c - a > alternative[i][j] or a - c > alternative[j][i]:
                    choices.add(tuple((u, x) for u, x in ((i, a), (j, c)) if u))
        if not choices:
            return None
        singles = {p[0] for p in choices if len(p) == 1}
        colours.append(
            sorted(
                (p for p in choices if len(p) == 1 or not singles.intersection(p)),
                key=lambda p: (len(p), p),
            )
        )
    colours.sort(key=len)

    @lru_cache(maxsize=None)
    def clique(k, assigned):
        values = dict(assigned)
        if k == len(colours):
            return values
        for pair in colours[k]:
            if all(
                -f[j][i] <= c - a <= f[i][j] for i, a in pair for j, c in values.items()
            ):
                found = clique(k + 1, tuple(sorted({**values, **dict(pair)}.items())))
                if found is not None:
                    return found
        return None

    found = clique(0, ((0, 0),))
    if found is None:
        return None
    return tuple(min(a + f[i][j] for i, a in found.items()) for j in range(len(f)))
