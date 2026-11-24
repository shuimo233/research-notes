"""Certify sharp marginal union bounds by orienting quantile intervals on one shared uniform."""

import argparse
from bisect import bisect_right
from collections import Counter
from fractions import Fraction
from itertools import accumulate, combinations
import json
from pathlib import Path


def solve_2sat(size, clauses):
    """Return one satisfying orientation, or None. Literals are signed one-based indices."""
    graph = {v: [] for i in range(1, size + 1) for v in (i, -i)}
    reverse = {v: [] for v in graph}
    for c in clauses:
        if not c:
            return None
        a, b = c[0], c[-1]
        for u, v in ((-a, b), (-b, a)):
            graph[u].append(v)
            reverse[v].append(u)
    order = []
    seen = set()
    for u in graph:
        if u in seen:
            continue
        stack = [(u, False)]
        while stack:
            v, done = stack.pop()
            if done:
                order.append(v)
            elif v not in seen:
                seen.add(v)
                stack.append((v, True))
                stack.extend((w, False) for w in graph[v] if w not in seen)
    components = {}
    for u in reversed(order):
        if u in components:
            continue
        number = len(components)
        stack = [u]
        while stack:
            v = stack.pop()
            if v not in components:
                components[v] = number
                stack.extend(reverse[v])
    if any(components[i] == components[-i] for i in range(1, size + 1)):
        return None
    return [components[i] > components[-i] for i in range(1, size + 1)]


def canonical(groups):
    out = {}
    for u, parts in sorted(groups.items()):
        freq = Counter()
        for forced, p in parts:
            p = Fraction(p)
            if p < 0:
                raise ValueError("negative probability")
            if p:
                freq[tuple(sorted(set(forced)))] += p
        if sum(freq.values()) != 1:
            raise ValueError("each marginal must sum to one")
        out[u] = sorted(freq.items())
    return out


def certificate(groups, endpoint="upper"):
    if endpoint not in ("upper", "lower"):
        raise ValueError("unknown endpoint")
    choices = canonical(groups)
    arrays = list(choices.values())
    ends = [list(accumulate(p for _, p in g)) for g in arrays]
    breaks = sorted(
        {Fraction(0), Fraction(1)} | {r for e in ends for b in e for r in (b, 1 - b)}
    )
    probs = {}
    for i, g in enumerate(arrays):
        for vs, p in g:
            for v in vs:
                owners = probs.setdefault(v, Counter())
                owners[i] += p
    clauses = set()

    def clause(items):
        if any(x is True for x in items):
            return
        lits = {x for x in items if x is not False}
        if any(-x in lits for x in lits):
            return
        clauses.add(tuple(sorted(lits)))

    def neg(x):
        return not x if type(x) is bool else -x

    for a, b in zip(breaks, breaks[1:]):
        mid = (a + b) / 2
        active = [
            (g[bisect_right(e, mid)][0], g[bisect_right(e, 1 - mid)][0])
            for g, e in zip(arrays, ends)
        ]
        for v, owners in probs.items():

            def literal(i):
                fwd, rev = (v in t for t in active[i])
                return fwd if fwd == rev else (i + 1 if rev else -i - 1)

            flags = [literal(i) for i in owners]
            if endpoint == "lower":
                main = literal(max(owners, key=owners.get))
                for x in flags:
                    clause([neg(x), main])
            else:
                total = sum(owners.values())
                if total <= 1:
                    for x, y in combinations(flags, 2):
                        clause([neg(x), neg(y)])
                if total >= 1:
                    clause(flags)
    target = sum(
        (
            min(1, sum(o.values())) if endpoint == "upper" else max(o.values())
            for o in probs.values()
        ),
        Fraction(),
    )
    width = max(map(len, clauses), default=0)
    report = {
        "local": str(target),
        "intervals": len(breaks) - 1,
        "clauses": len(clauses),
        "width": width,
    }
    if width > 2:
        return {**report, "status": "wide"}
    values = solve_2sat(len(arrays), sorted(clauses))
    if values is None:
        return {**report, "status": "unsat_in_clock_family"}
    return {
        **report,
        "status": "witness",
        "reverse": [u for u, rev in zip(choices, values) if rev],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "groups",
        type=Path,
        help="JSON mapping each source ID to [forced IDs, probability] entries",
    )
    p.add_argument("--endpoint", choices=("upper", "lower"), default="upper")
    a = p.parse_args()
    print(
        json.dumps(certificate(json.loads(a.groups.read_bytes()), a.endpoint), indent=2)
    )
