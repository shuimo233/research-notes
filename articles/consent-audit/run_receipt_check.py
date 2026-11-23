"""Independent small-domain checks from raw binary archives and exact graph coloring."""

from collections import defaultdict
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_receipt import RunReceipt


def archives(n):
    layouts = list(combinations(range(1, n+1), 2))
    records = []
    by_word = defaultdict(lambda: (set(), set()))
    for layout_id, (a, b) in enumerate(layouts):
        for x, y, z in product((0, 1), repeat=3):
            word = bytes([x])*a + bytes([y])*(b-a) + bytes([z])*(n+1-b)
            truth = int(x+y+z >= 2)
            records.append((layout_id, word, truth))
            by_word[word][truth].add(layout_id)
    conflicts = {tuple(sorted((i, j))) for zero, one in by_word.values() for i in zero for j in one}
    return layouts, records, sorted(conflicts)


def raw_checks(layout, intervals):
    a, b = layout
    return sum((low <= a <= high or low <= b <= high) << k for k, (low, high) in enumerate(intervals))


def chromatic(graph):
    """Try k-colorability in order, choosing vertices by saturation, without a formula bound."""
    vertices = sorted(graph)
    colors = {}
    def search(k):
        if len(colors) == len(vertices):
            return True
        options = [(len({colors[j] for j in graph[i] if j in colors}), len(graph[i]), i)
                   for i in vertices if i not in colors]
        _, _, i = max(options)
        blocked = {colors[j] for j in graph[i] if j in colors}
        for color in range(min(k, max(colors.values(), default=-1)+2)):
            if color not in blocked:
                colors[i] = color
                if search(k):
                    return True
                del colors[i]
        return False
    return next(k for k in range(1, len(vertices)+2) if search(k))


def check_menu(n, data, menu, totals):
    codec = RunReceipt(n, menu)
    layouts, records, edges = data
    fields = [raw_checks(layout, menu) for layout in layouts]
    issued = [codec.issue(*layout) for layout in layouts]
    assert fields == [r["existing"] for r in issued]
    graphs = {mask: defaultdict(set) for mask in fields}
    for i, j in edges:
        if fields[i] == fields[j]:
            g = graphs[fields[i]]
            g[i].add(j)
            g[j].add(i)
    optima = {mask: chromatic(g) for mask, g in graphs.items()}
    assert codec.symbols == max(optima.values()), (n, menu, codec.describe(), optima)
    for mask, optimum in optima.items():
        formula = codec.groups[mask].alphabet if mask in codec.groups else 1
        assert formula == optimum
    for i, word, truth in records:
        assert codec.decide(issued[i], word) == truth, (n, menu, word, issued[i])
    totals["menus"] += 1
    totals["fibers"] += len(graphs)
    totals["decoded_raw_archives"] += len(records)


def minimum_checks(n, data):
    intervals = list(combinations(range(n+1), 2))
    candidates = [(i+1,j) for i,j in intervals]
    layouts, _, conflicts = data
    full = (1 << len(conflicts))-1
    masks = []
    for query in candidates:
        answer = [raw_checks(layout, [query]) for layout in layouts]
        mask = sum((answer[i] != answer[j]) << k for k, (i, j) in enumerate(conflicts))
        if mask and mask not in masks:
            masks.append(mask)
    for size in range(len(masks)+1):
        for panel in combinations(masks, size):
            covered = 0
            for mask in panel:
                covered |= mask
            if covered == full:
                return size


def run():
    totals = dict(menus=0, fibers=0, decoded_raw_archives=0)
    rng = Random(73719)
    minimum = {}
    for n in range(2, 11):
        data = archives(n)
        intervals = [(a, b) for a in range(1, n+1) for b in range(a, n+1)]
        if n <= 4:
            for size in range(len(intervals)+1):
                for menu in combinations(intervals, size):
                    check_menu(n, data, menu, totals)
        elif n == 5:
            for size in range(4):
                for menu in combinations(intervals, size):
                    check_menu(n, data, menu, totals)
        else:
            for menu in [[], *[[interval] for interval in intervals],
                         *[rng.choices(intervals, k=rng.randrange(2,9)) for _ in range(28)]]:
                check_menu(n, data, menu, totals)
        if n <= 8:
            answer = minimum_checks(n, data)
            assert answer == min(n-2, (n+1)//2)
            minimum[str(n)] = answer
    one_query = {}
    for colors in (1, 2, 3, 4, 5):
        capacity = 2 * (1 << colors) - 1
        values = []
        for count in (capacity, capacity+1):
            best = min(RunReceipt(count, [(i,j)]).symbols
                       for i in range(1,count+1) for j in range(i,count+1))
            values.append(best)
        assert values == [colors, colors+1]
        one_query[str(colors)] = capacity
    # When the public catalog is sparse, compilation should never visit each possible cut.
    n = 10**15
    huge = RunReceipt(n, [(2, n-1), (5, n//2), (n//2+1, n)])
    assert sum(group.size for group in huge.groups.values()) == n
    probe = huge.issue(n-2, n-1)
    assert probe["tag"] < huge.symbols
    witness = RunReceipt(7, [(3,5)])
    try:
        witness.decide(witness.issue(2, 4), [0,1,0,1,0,0,0,0])
    except ValueError:
        pass
    else:
        raise AssertionError("accepted four visible changes")
    return {"seed":73719, **totals, "minimum_fixed_checks":minimum, "one_check_capacity":one_query,
            "sparse_catalog_test":{"cut_positions":n, "intervals":3, "constant_segments":len(huge.starts)}}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
