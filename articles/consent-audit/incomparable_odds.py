"""Exact observation windows for channels with complete local product supports."""

from collections import defaultdict
from fractions import Fraction
from math import lcm, prod

from sparse_odds import subsets


def windows_for(numerator, denominator, *, binary_heuristic=False):
    """Yield the windows sufficient for one directed comparison."""
    show = free = 0
    for i, (x, y) in enumerate(zip(numerator, denominator, strict=True)):
        if not x & y:
            continue
        if x <= y:
            show |= 1 << i
        elif len(y) > 1 and not (binary_heuristic and y < x):
            free |= 1 << i
    return (show | w for w in subsets(free))


class WindowAudit:
    """Read positive weighted joint rows; normalize each row before comparing."""

    def __init__(self, rows):
        if not rows or not rows[0]:
            raise ValueError("at least one nonempty distribution is required")
        self.width = len(next(iter(rows[0])))
        self.support = []
        self.tables = []
        self.totals = []
        self.projected = []
        for row in rows:
            if not row or any(len(p) != self.width for p in row):
                raise ValueError(
                    "world outcomes must be nonempty and have the same width"
                )
            local = tuple(frozenset(p[i] for p in row) for i in range(self.width))
            if prod(map(len, local)) != len(row):
                raise ValueError(
                    "world outcomes must have full Cartesian-product support"
                )
            exact = {k: Fraction(v) for k, v in row.items()}
            if any(v <= 0 for v in exact.values()):
                raise ValueError("every allowed combination must have positive weight")
            scale = lcm(*(v.denominator for v in exact.values()))
            integral = {k: int(v * scale) for k, v in exact.items()}
            self.support.append(local)
            self.tables.append(integral)
            self.totals.append(sum(integral.values()))
            self.projected.append({(1 << self.width) - 1: integral})

    def projection(self, i, w):
        registry = self.projected[i]
        if w not in registry:
            view = [j for j in range(self.width) if w >> j & 1]
            counts = defaultdict(int)
            for message, x in self.tables[i].items():
                counts[tuple(message[k] for k in view)] += x
            registry[w] = counts
        return registry[w]

    def directed(self, i, j, windows=None, *, binary_heuristic=False):
        """Return the highest odds ratio (baseline one), comparison count and witness."""
        if windows is None:
            windows = windows_for(
                self.support[i], self.support[j], binary_heuristic=binary_heuristic
            )
        high, low = 1, 1
        checked = 0
        witness = None
        X, Y = self.totals[i], self.totals[j]
        for w in windows:
            top = self.projection(i, w)
            bottom = self.projection(j, w)
            for message in top.keys() & bottom.keys():
                checked += 1
                a, b = top[message] * Y, bottom[message] * X
                if a * low > high * b:
                    high, low, witness = a, b, (w, message)
        return Fraction(high, low), checked, witness


def main():
    import argparse
    from itertools import permutations
    import json
    from pathlib import Path

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("table", type=Path)
    p.add_argument("--limit", type=Fraction)
    p.add_argument("--ordered-pair", nargs=2, metavar=("NUMERATOR", "DENOMINATOR"))
    args = p.parse_args()
    try:
        names = []
        rows = []
        for world in json.loads(args.table.read_bytes(), parse_float=Fraction)[
            "worlds"
        ]:
            name = world["id"]
            if type(name) is not str or name in names:
                raise ValueError("world identifiers must be distinct strings")
            names.append(name)
            outcomes = world["outcomes"]
            row = {
                tuple(entry["labels"]): Fraction(entry["weight"]) for entry in outcomes
            }
            if len(row) != len(outcomes):
                raise ValueError("duplicate outcome in one world")
            rows.append(row)
        audit = WindowAudit(rows)
        if args.ordered_pair:
            i, j = map(names.index, args.ordered_pair)
            if i == j:
                raise ValueError("choose two distinct worlds")
            pairs = [(i, j)]
        else:
            pairs = permutations(range(len(names)), 2)
        best, count = Fraction(1), 0
        why = None
        for i, j in pairs:
            ratio, checks, witness = audit.directed(i, j)
            count += checks
            if ratio > best:
                best = ratio
                w, message = witness
                why = dict(
                    numerator=names[i],
                    denominator=names[j],
                    positions=[k for k in range(audit.width) if w >> k & 1],
                    labels=message,
                )
        report = dict(ratio=str(best), comparisons=count, witness=why)
        if args.limit is not None:
            if args.limit < 1:
                raise ValueError("limit must be at least one")
            report["within_limit"] = best <= args.limit
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError) as error:
        p.exit(2, f"{error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
