"""Compile temperature-style tolerance comparisons using edge marginals and known interval ends."""

import argparse
from collections import Counter
from fractions import Fraction as Q
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frontier_plan import FrontierPlan


def threshold_label(delta, tolerance):
    return (delta >= tolerance) - (delta <= -tolerance)


def trigger_shape(interval, neighbor, tolerance):
    """Return the trigger set's shape and its cut or omitted point."""
    a, b = interval
    c, d = neighbor
    parts = []
    for lo, hi in (
        (c - tolerance + 1, d - tolerance),
        (c + tolerance, d + tolerance - 1),
    ):
        lo, hi = max(a, lo), min(b, hi)
        if lo <= hi:
            if parts and lo <= parts[-1][1] + 1:
                parts[-1] = parts[-1][0], hi
            else:
                parts.append((lo, hi))
    if not parts:
        return "none", None
    if len(parts) == 2:
        (left, upper), (lower, right) = parts
        if left == a and right == b and lower == upper + 2:
            return "except", upper + 1
        raise ValueError("trigger set has more than one cut or omitted point")
    ((lo, hi),) = parts
    if lo == a and hi == b:
        return "all", None
    if lo == a:
        return "prefix", hi
    if hi == b:
        return "suffix", lo - 1
    raise ValueError("trigger set is strictly inside the interval")


def triggered(shape, x):
    kind, boundary = shape
    return (
        kind == "all"
        or kind == "prefix"
        and x <= boundary
        or kind == "suffix"
        and x > boundary
        or kind == "except"
        and x != boundary
    )


def compile_end_cuts(intervals, edges, rates, tolerance, costs=None):
    if type(tolerance) is not int or tolerance < 1:
        raise ValueError("positive integer tolerance required")
    if any(
        type(a) is not int or type(b) is not int or a > b for a, b in intervals.values()
    ):
        raise ValueError("each range must have ordered integer endpoints")
    if set(intervals) != set(rates):
        raise ValueError("each position needs a rates record")
    targets = {u: set() for u in intervals}
    active = []
    seen = set()
    for u, v in edges:
        a, b = intervals[u]
        c, d = intervals[v]
        key = frozenset((u, v))
        if u == v or key in seen:
            raise ValueError("only distinct positions and unique edges")
        seen.add(key)
        if threshold_label(a - d, tolerance) == threshold_label(b - c, tolerance):
            continue
        targets[u].add(v)
        targets[v].add(u)
        active.append((u, v))
    choices = {}
    for u, neighbors in targets.items():
        if set(rates[u]) != neighbors:
            raise ValueError("rates must match the nonconstant edges")
        lo, hi = intervals[u]
        cuts = {lo - 1: Q(0), hi: Q(1)}
        known_atoms = {}
        flags = {}
        for v in sorted(neighbors):
            shape = trigger_shape(intervals[u], intervals[v], tolerance)
            kind, place = shape
            flags[v] = shape
            p = Q(rates[u][v])
            if kind in ("none", "all"):
                if p != int(kind == "all"):
                    raise ValueError("rate contradicts a constant trigger")
                continue
            mass = p if kind == "prefix" else 1 - p
            fixed = known_atoms if kind == "except" else cuts
            if not 0 < mass < 1 or fixed.get(place, mass) != mass:
                raise ValueError(
                    "rates contradict a common strictly positive interval law"
                )
            fixed[place] = mass
        outcomes = Counter()
        for x, mass in known_atoms.items():
            outcomes[tuple(v for v, s in flags.items() if triggered(s, x))] += mass
        endpoints = sorted(cuts)
        for a, b in zip(endpoints, endpoints[1:]):
            atoms = [p for x, p in known_atoms.items() if a < x <= b]
            remainder = cuts[b] - cuts[a] - sum(atoms)
            has_unknown_value = b - a > len(atoms)
            if remainder < 0 or (remainder > 0) != has_unknown_value:
                raise ValueError(
                    "rates contradict positive mass in a region between cuts"
                )
            if has_unknown_value:
                x = a + 1
                while x in known_atoms:
                    x += 1
                outcomes[tuple(v for v, s in flags.items() if triggered(s, x))] += (
                    remainder
                )
        choices[u] = list(outcomes.items())
    return FrontierPlan(dict.fromkeys(intervals, 1), choices, active, costs)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    args = p.parse_args()
    planner = compile_end_cuts(**json.loads(args.instance.read_bytes()))
    value, i = planner.optimum(planner.counts, 0)
    print(
        json.dumps(
            dict(expected=str(value), first=None if i is None else planner.names[i]),
            indent=2,
        )
    )
