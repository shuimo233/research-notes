"""Exhaust all small interval endpoint arrangements, including ties, gaps and nesting."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from receipt_design import capacity, design
from run_receipt import RunReceipt
from run_receipt_check import archives, minimum_checks, raw_checks


def arrangements(q):
    # Relabeling intervals has no effect. Duplicate intervals repeat an answer and
    # are covered by arrangements with fewer queries. Compress consecutive equal columns.
    for length in range(1, 2*q+2):
        candidates = []
        for a in range(length):
            for b in range(a, length):
                changes = (1 << (a-1) if a else 0) | (1 << b if b < length-1 else 0)
                candidates.append((a,b,changes))
        for tests in combinations(candidates, q):
            changes = 0
            for _, _, flip in tests:
                changes |= flip
            if changes == (1 << (length-1))-1:
                yield [frozenset(k for k,(a,b,_) in enumerate(tests) if a <= t <= b)
                       for t in range(length)]


def independent_shape_limits(signatures, colors):
    ranges = []
    for v, runs in Counter(signatures).items():
        first = signatures.index(v)
        last = len(signatures)-1-signatures[::-1].index(v)
        left = any(other < v for other in signatures[:first])
        right = any(other < v for other in signatures[last+1:])
        ranges.append((runs, left+right))
    limit = 1 << colors
    return sum(limit-flags for _,flags in ranges) if all(runs+flags <= limit for runs,flags in ranges) else 0


def has_one_bit(layouts, conflicts, menu):
    fields = [raw_checks(layout, menu) for layout in layouts]
    graph = [set() for _ in layouts]
    for i,j in conflicts:
        if fields[i] == fields[j]:
            graph[i].add(j)
            graph[j].add(i)
    sides = {}
    for vertex in range(len(layouts)):
        if vertex in sides:
            continue
        sides[vertex] = 0
        stack = [vertex]
        while stack:
            v = stack.pop()
            for w in graph[v]:
                if w in sides and sides[w] == sides[v]:
                    return False
                if w not in sides:
                    sides[w] = 1-sides[v]
                    stack.append(w)
    return True


def run():
    best = {r: 1 << r for r in range(1,6)}
    shape_counts, frontier = {}, {}
    for q in range(1,6):
        count = 0
        for shape in arrangements(q):
            count += 1
            for r in best:
                best[r] = max(best[r], independent_shape_limits(shape, r))
        assert all(best[r] == capacity(q,r) for r in best), (q,best)
        shape_counts[str(q)] = count
        frontier[str(q)] = list(best.values())
    direct = {}
    for n in range(2,12):
        data = archives(n)
        layouts, _, conflicts = data
        intervals = [(a,b) for a in range(1,n+1) for b in range(a,n+1)]
        optimum = next(q for q in range(len(intervals)+1)
                       if any(has_one_bit(layouts,conflicts,menu) for menu in combinations(intervals,q)))
        assert optimum == len(design(n,1)["intervals"])
        direct[str(n)] = optimum
        if n <= 8:
            assert minimum_checks(n,data) == len(design(n,0)["intervals"])
    configurations = 0
    for n in range(2,181):
        for bits in range(5):
            menu = design(n,bits)["intervals"]
            codec = RunReceipt(n,menu)
            q = len(menu)
            assert codec.bits <= bits and (not q or capacity(q-1,1<<bits) < n)
            configurations += 1
    return {"arrangements":shape_counts, "max_cuts_for_1_to_5_symbols":frontier,
            "raw_archive_min_checks_for_one_bit":direct, "constructed_designs_checked":configurations,
            "31_cut_min_checks_for_0_to_3_bits":[len(design(31,b)["intervals"]) for b in range(4)]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
