"""Exact purchase and decoding with a scalar offset shared by honest replies."""

from dataclasses import dataclass
from itertools import combinations

from numpy import ones, zeros
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from interval_fault_asymmetric_quota import hierarchy, split, two_level_conditions


@dataclass(frozen=True)
class Plan:
    cost: int | None
    selected: tuple = ()
    proof: tuple | None = None


def agreement(left, right, error, band):
    """Clip the offsets where two honest vector replies can coincide."""
    low, high = band
    for a, b in zip(left, right, strict=True):
        gap = b - a
        low, high = max(low, gap - 2 * error), min(high, gap + 2 * error)
    return low, high


def disagreement_sweep(intervals, band):
    """Give (mask, offset) for potentially maximal simultaneous agreements."""
    boundaries = {band[0]: [0, 0]}
    for i, (low, high) in enumerate(intervals):
        low, high = max(low, band[0]), min(high, band[1])
        if low <= high:
            boundaries.setdefault(low, [0, 0])[0] |= 1 << i
            boundaries.setdefault(high, [0, 0])[1] |= 1 << i
    full, present = (1 << len(intervals)) - 1, 0
    for x, (enters, exits) in sorted(boundaries.items()):
        present |= enters
        if enters or x == band[0]:
            yield full ^ present, x
        present &= ~exits


def _minimal_conflicts(states):
    kept = []
    for mask, offset in sorted(states, key=lambda s: (s[0].bit_count(), s[0], s[1])):
        if not any(mask & smaller == smaller for smaller, _ in kept):
            kept.append((mask, offset))
    return kept


def certificate_sources(intervals, selected, budget, band):
    """Keep extremes that preserve separation under a total mismatch cap."""
    if budget < 0:
        raise ValueError("nonnegative total mismatch cap required")
    bounds = {
        i: (low, high) if low <= high else (band[1] + 1, band[0] - 1)
        for i in selected
        for low, high in (intervals[i],)
    }
    lower = sorted(bounds, key=lambda i: (-bounds[i][0], i))
    upper = sorted(bounds, key=lambda i: (bounds[i][1], i))
    return tuple(sorted(set(lower[: budget + 1]) | set(upper[: budget + 1])))


def _witness(offers, a, b, bounds, tolerances, delta, bad_a, bad_b, mode):
    if mode == "shared":
        chosen_a = max(bounds[a][0], bounds[b][0] + delta)
        chosen_b = chosen_a - delta
    else:
        chosen_a = chosen_b = 0
    replies, offsets = [], []
    for i, (offer, error) in enumerate(zip(offers, tolerances, strict=True)):
        left, right = offer.values[a], offer.values[b]
        if mode == "marginal":
            d = agreement(left, right, error, delta)
            if not (bad_a | bad_b) & (1 << i):
                chosen_a = max(bounds[a][0], bounds[b][0] + d[0])
                chosen_b = chosen_a - d[0]
            else:
                chosen_a, chosen_b = bounds[a][0], bounds[b][0]
        offsets.append((chosen_a, chosen_b))
        x = tuple(v + chosen_a for v in left)
        y = tuple(v + chosen_b for v in right)
        if bad_a & (1 << i):
            replies.append(y)
        elif bad_b & (1 << i):
            replies.append(x)
        else:
            replies.append(tuple(max(u, v) - error for u, v in zip(x, y, strict=True)))
    return a, b, tuple(offsets), tuple(replies), bad_a, bad_b


def _minimum_purchase(prices, clauses):
    if not clauses:
        return 0, ()
    n = len(prices)
    required = {menu[0] for menu in clauses if len(menu) == 1}
    disjunctive = sorted(
        menu for menu in clauses if len(menu) > 1 and not required.intersection(menu)
    )
    choices = {
        rule: n + j
        for j, rule in enumerate(
            sorted({rule for menu in disjunctive for rule in menu})
        )
    }
    entries, row_ids, columns, lower = [], [], [], []

    def add_row(terms, bound):
        for column, coefficient in terms:
            columns.append(column)
            entries.append(coefficient)
            row_ids.append(len(lower))
        lower.append(bound)

    for (mask, count), aux in choices.items():
        terms = [(i, 1) for i in range(n) if mask & (1 << i)]
        add_row((*terms, (aux, -count)), 0)
    for menu in disjunctive:
        add_row(((choices[rule], 1) for rule in menu), 1)
    for mask, count in sorted(required):
        add_row(((i, 1) for i in range(n) if mask & (1 << i)), count)
    width = n + len(choices)
    matrix = coo_array((entries, (row_ids, columns)), shape=(len(lower), width))
    outcome = milp(
        [*prices, *zeros(len(choices))],
        integrality=ones(width),
        bounds=Bounds(zeros(width), ones(width)),
        constraints=LinearConstraint(matrix, lower, float("inf")),
        options={"mip_rel_gap": 0.0},
    )
    if not outcome.success:
        raise RuntimeError(outcome.message)
    selected = tuple(i for i in range(n) if outcome.x[i] > 0.5)
    bought = sum(1 << i for i in selected)
    price = sum(prices[i] for i in selected)
    if abs(price - outcome.fun) > 1e-5 or any(
        not any((mask & bought).bit_count() >= count for mask, count in menu)
        for menu in clauses
    ):
        raise RuntimeError("optimizer did not return a valid integer purchase")
    return price, selected


def plan(labels, offers, group_masks, limits, bounds, tolerances, mode="shared"):
    """Minimize price under a shared, per-source, or known-zero offset."""
    n = len(offers)
    root = (1 << n) - 1
    groups = tuple(group_masks)
    if (
        len(groups) < 2
        or any(g <= 0 or g & ~root for g in groups)
        or any(g & h for g, h in combinations(groups, 2))
        or sum(groups) != root
    ):
        raise ValueError("nonempty disjoint groups must cover all sources")
    if (
        not labels
        or len(labels) != len(bounds)
        or len(labels) != len(limits)
        or len(tolerances) != n
        or any(lo > hi for lo, hi in bounds)
        or any(e < 0 for e in tolerances)
        or any(set(row) != {root, *groups} or min(row.values()) < 0 for row in limits)
        or any(
            q.cost <= 0
            or len(q.values) != len(labels)
            or not q.values[0]
            or any(len(v) != len(q.values[0]) for v in q.values)
            for q in offers
        )
    ):
        raise ValueError(
            "complete world profiles, replies, and positive prices required"
        )
    if mode == "zero":
        bounds = [(0, 0)] * len(labels)
    elif mode not in ("shared", "marginal"):
        raise ValueError("unknown calibration mode")
    clauses = set()
    for a, b in combinations(range(len(labels)), 2):
        if labels[a] == labels[b]:
            continue
        delta = bounds[a][0] - bounds[b][1], bounds[a][1] - bounds[b][0]
        intervals = [
            agreement(q.values[a], q.values[b], e, delta)
            for q, e in zip(offers, tolerances, strict=True)
        ]
        if mode == "marginal":
            impossible = sum((lo > hi) << i for i, (lo, hi) in enumerate(intervals))
            states = [(impossible, delta)]
        else:
            states = _minimal_conflicts(disagreement_sweep(intervals, delta))
        caps = tuple((g, limits[a][g], limits[b][g]) for g in groups)
        for difference, position in states:
            options = two_level_conditions(
                difference, limits[a][root], limits[b][root], caps
            )
            if not options:
                tree = hierarchy(n, (root, *groups))
                ea, eb = split(
                    tree,
                    difference,
                    tree.capacities(limits[a]),
                    tree.capacities(limits[b]),
                )
                return Plan(
                    None,
                    proof=_witness(
                        offers, a, b, bounds, tolerances, position, ea, eb, mode
                    ),
                )
            clauses.add(options)
    price, selected = _minimum_purchase([q.cost for q in offers], clauses)
    return Plan(price, selected)


def compatible_labels(labels, offers, selected, replies, limits, bounds, tolerances):
    """Find labels that can produce the observed vectors under one offset per world."""
    if len(selected) != len(set(selected)) or any(
        i not in range(len(offers)) for i in selected
    ):
        raise ValueError("each available source may be selected once")
    observed = tuple(zip(selected, replies, strict=True))
    if any(len(v) != len(offers[i].values[0]) for i, v in observed):
        raise ValueError("reply width must match the purchased source")
    possible = set()
    for w, label in enumerate(labels):
        band = bounds[w]
        intervals = []
        for i, v in observed:
            shifts = [y - x for x, y in zip(offers[i].values[w], v, strict=True)]
            intervals.append((max(shifts) - tolerances[i], min(shifts) + tolerances[i]))
        for disagreement, _ in disagreement_sweep(intervals, band):
            bad = sum(
                (1 << i) for j, i in enumerate(selected) if disagreement & (1 << j)
            )
            if all((bad & g).bit_count() <= cap for g, cap in limits[w].items()):
                possible.add(label)
                break
    return possible
