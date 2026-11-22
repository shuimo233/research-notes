"""Single-coordinate bounds from two- and four-row linear aggregates."""

from itertools import combinations_with_replacement


def _signatures(items, radii):
    tightest = {}
    for i, r in enumerate(radii):
        signature = sum(((mask >> i) & 1) << j for j,(mask, _) in enumerate(items))
        if signature not in tightest or r < tightest[signature][0]:
            tightest[signature] = (r, i)
    return tightest

def count_intervals(columns, radii):
    """Return inclusive intervals, or None if the derived bounds contradict."""
    items = tuple(columns.items())
    sizes = [n for _, n in items]
    total = sum(sizes)
    full = (1 << len(items)) - 1
    tightest = _signatures(items, radii)

    intervals = []
    for j, n in enumerate(sizes):
        lo, hi = 0, n
        bit = 1 << j
        flip = full ^ bit
        for signature, (r, _) in tightest.items():
            partner = signature ^ flip
            if partner < signature or partner not in tightest:
                continue
            slack = (r + tightest[partner][0] - (total - n)) // 2
            if signature & bit:
                lo = max(lo, n - slack)
            else:
                hi = min(hi, slack)
            if lo > hi:
                return None
        intervals.append((lo, hi))
    return intervals


def four_intervals(columns, radii):
    """Index row-pair sums and match them outside each target coordinate."""
    return report_intervals(tuple(columns.items()), radii)


def audit_row_sums(problem, cores, minimal):
    """Find useful aggregates for each original core and each one-row deletion."""
    rows = {r["name"]: r for r in problem["rules"]}
    counts = [int(probe["count"]) for probe in problem["probes"]]
    hints = set()
    for core in cores:
        for skip in ([None, *core] if minimal else [None]):
            names = [s for s in core if s != skip]
            if not names:
                continue
            items = [(sum(rows[s]["bits"][j] << i for i,s in enumerate(names)), n)
                     for j,n in enumerate(counts)]
            sources = []
            report_intervals(items, [int(rows[s]["errors"]) for s in names], sources)
            hints.update(tuple(sorted(names[i] for i in group)) for group in sources)
    return [list(s) for s in sorted(hints)]


def report_intervals(items, radii, sources=None):
    """Preserve probe order even when multiple probes have the same raw signature."""
    full = (1 << len(items)) - 1
    signs = _signatures(items, radii)
    rows = [(s, r - sum(n for j,(_, n) in enumerate(items) if (s >> j) & 1), i)
            for s, (r, i) in signs.items()]
    # Each pair has coefficients +2 on positive, -2 on negative, 0 elsewhere.
    costs = {}
    for (a, ra, i), (b, rb, k) in combinations_with_replacement(rows, 2):
        key = full ^ (a | b), a & b
        if key not in costs or ra + rb < costs[key][0]:
            costs[key] = (ra + rb, i, k)
    intervals = []
    for j, (_, n) in enumerate(items):
        bit = 1 << j
        lo, hi = 0, n
        lower_source = upper_source = None
        for (positive, negative), (cost, i, k) in costs.items():
            first = int(bool(positive & bit)) - int(bool(negative & bit))
            pos, neg = negative & ~bit, positive & ~bit
            for second, key in ((0, (pos, neg)), (1, (pos | bit, neg)), (-1, (pos, neg | bit))):
                other = costs.get(key)
                if other is None:
                    continue
                coefficient = 2 * (first + second)
                rhs = cost + other[0]
                if coefficient > 0 and rhs // coefficient < hi:
                    hi = rhs // coefficient
                    upper_source = (i, k, *other[1:])
                elif coefficient < 0 and -((-rhs) // coefficient) > lo:
                    lo = -((-rhs) // coefficient)
                    lower_source = (i, k, *other[1:])
                elif coefficient == 0 and rhs < 0:
                    if sources is not None:
                        sources.append((i, k, *other[1:]))
                    return None
            if lo > hi:
                if sources is not None:
                    sources.extend(s for s in (lower_source, upper_source) if s is not None)
                return None
        if sources is not None:
            sources.extend(s for s in (lower_source, upper_source) if s is not None)
        intervals.append((lo, hi))
    return intervals


def restrict_counts(columns, radii, intervals):
    """Subtract compulsory mismatches and retain only the undecided positions."""
    remainder = {}
    budgets = list(radii)
    for (mask, n), (lo, hi) in zip(columns.items(), intervals):
        if hi > lo:
            remainder[mask] = hi - lo
        if lo or hi < n:
            for i in range(len(budgets)):
                budgets[i] -= n - hi if (mask >> i) & 1 else lo
    return remainder, tuple(budgets)
