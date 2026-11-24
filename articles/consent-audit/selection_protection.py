"""Compile and audit single-comparison releases, including selection inference."""

from itertools import product

from attested_optimality import ShorterWorlds
from conclusion_replay import interval
from lag_protection import exact_lags
from public_optimality import tighten


def comparison(zone, atom, true=True):
    if zone is None:
        return None
    u, v, cut = atom
    if true:
        return tighten(zone, v, u, -cut)
    return tighten(zone, u, v, cut - 1)


def catalogue(audit, groups, grid=60):
    if type(grid) is not int or grid < 1:
        raise ValueError("grid must be a positive integer")
    oracle = ShorterWorlds(audit, groups)
    if oracle.find() is None:
        return [], oracle.checked
    entries = []
    seen = set()
    for u, v in product(range(len(audit.fibre)), repeat=2):
        if u == v:
            continue
        lo, hi = interval(audit.fibre, u, v)
        ceiling = hi - hi % grid
        if ceiling <= lo or oracle.find(((u, v, ceiling),)) is not None:
            continue
        atom = oracle.weakest([], (u, v, ceiling), grid)
        zone = comparison(audit.fibre, atom)
        if not exact_lags(audit.fibre, zone) and zone not in seen:
            entries.append(atom)
            seen.add(zone)
    return entries, oracle.checked


def fibre_log(public, atoms, order):
    pending = public
    result = []
    for i in order:
        yes = comparison(pending, atoms[i])
        plain = comparison(public, atoms[i])
        narrowed = (
            0
            if yes is None
            else sum(
                c < b
                for row, inherited in zip(yes, plain, strict=True)
                for c, b in zip(row, inherited, strict=True)
            )
        )
        result.append(
            dict(
                index=i,
                empty=yes is None,
                fixed=[] if yes is None else exact_lags(public, yes),
                narrowed=narrowed,
            )
        )
        pending = comparison(pending, atoms[i], False)
    return result


def safe_order(public, atoms):
    remaining = list(range(len(atoms)))
    reverse = []
    while remaining:
        for j in remaining:
            unique = comparison(public, atoms[j])
            for i in remaining:
                if i != j:
                    unique = comparison(unique, atoms[i], False)
                    if unique is None:
                        break
            if unique is not None and not exact_lags(public, unique):
                remaining.remove(j)
                reverse.append(j)
                break
        else:
            return dict(status="impossible", blocked=remaining)
    return dict(status="proved", order=list(reversed(reverse)))


def true_indices(record, predicates):
    return [i for i, (u, v, b) in enumerate(predicates) if record[v] - record[u] >= b]


def selected_by_bases(record, predicates, planned):
    for i, rows in enumerate(planned):
        if tuple(record) in {tuple(r) for r in rows}:
            return i
    return next(iter(true_indices(record, predicates)), None)
