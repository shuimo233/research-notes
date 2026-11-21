"""Independent finite-horizon transcript checker, separate from the survivor-budget solver."""

from collections import Counter
from functools import lru_cache
from itertools import combinations, combinations_with_replacement, product
import json
from pathlib import Path


def ensure(test, message):
    if not test:
        raise RuntimeError(message)


def possible(rows, actions, budgets, n, *, fixed=False):
    # Expand a finite-horizon adversary into deterministic time-indexed error tapes.
    # A branch can stop when no valid world remains or a single action works for all tapes.
    masks = []
    for i, limit in enumerate(budgets):
        for count in range(min(n, limit) + 1):
            for slots in combinations(range(n), count):
                masks.append((i, sum(1 << j for j in slots)))
    full = (1 << len(masks)) - 1
    allowed = [sum(1 << j for j, (i, _) in enumerate(masks) if a in actions[i])
               for a in set().union(*actions)]
    width = len(rows[0])
    yes = [[sum(1 << j for j, (i, flip) in enumerate(masks) if rows[i][q] ^ ((flip >> t) & 1))
            for q in range(width)] for t in range(n)]

    def done(live):
        return any(live & a == live for a in allowed)

    @lru_cache(None)
    def tree(live, t):
        return done(live) or (t < n and any(tree(live & mask, t + 1) and tree(live & ~mask, t + 1)
                                              for mask in yes[t]))

    if not fixed:
        return tree(full, 0)
    for schedule in combinations_with_replacement(range(width), n):
        cells = [full]
        for t, q in enumerate(schedule):
            mask = yes[t][q]
            cells = [part for c in cells for part in (c & mask, c & ~mask) if part]
        if all(done(c) for c in cells):
            return True
    return False


def sqlite(rows):
    words = [(0, 0, 0, 0), (1, 1, 1, 1), (1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0)]
    actions = [{"insert"}, {"header"}, {"tail"}, {"tail"}, {"tail", "header"}]
    for case in rows:
        f = case["f"]
        for label, valid in (("safe_action", actions), ("identify_mode", [{i} for i in range(5)])):
            d = case[label]
            options = (words, valid, [0, 0, f, f, f])
            ensure(possible(*options, d) and not possible(*options, d - 1), (case, label))


def small_tables(expected):
    rows = tuple(product((0, 1), repeat=2))
    result, adaptive_counts = Counter(), Counter()
    for old in combinations(range(4), 2):
        names = old + tuple(i for i in range(4) if i not in old)
        words = [rows[i] for i in names]
        for acts in product(({0}, {1}, {0, 1}), repeat=4):
            if not acts[2] & acts[3]:
                continue
            for f in range(3):
                cap = 2 * (f + 1)
                best = [None, None]
                joint = None
                for n in range(cap + 1):
                    for k0 in range(n + 1):
                        # Enumerate count vectors on two probes. Derive admissibility on each old path
                        # from its surviving noisy classes; impose the same vector on both for joint.
                        found = []
                        for i in (0, 1):
                            allowed = set(acts[i])
                            for j in (2, 3):
                                dist = k0 * (words[i][0] != words[j][0]) + (n-k0) * (words[i][1] != words[j][1])
                                if dist <= f:
                                    allowed &= acts[j]
                            found.append(bool(allowed))
                            if allowed and best[i] is None:
                                best[i] = n
                        if all(found) and joint is None:
                            joint = n
                    if joint is not None:
                        break
                low = max(best)
                options = (words, acts, (0, 0, f, f))
                def exact(lower, fixed):
                    # The two old rows differ, so their identification cost in either mode is 1.
                    ensure(lower == 0 or not possible(*options, lower - 1, fixed=fixed), options)
                    if possible(*options, lower, fixed=fixed):
                        return lower
                    ensure(possible(*options, lower + 1, fixed=fixed), options)
                    return lower + 1
                a, p = exact(low, False), exact(joint, True)
                adaptive_counts[f, a - low] += 1
                result[f, p - joint, p > a] += 1
    ensure(adaptive_counts == {(r["f"], r["excess_over_L"]): r["cases"] for r in expected}, expected)
    return [{"f": f, "fixed_excess": gap, "feedback_saves": win, "cases": count}
            for (f, gap, win), count in sorted(result.items())]


def alias_check():
    # Equal observable signatures cannot split a group of worlds with no jointly valid action.
    words = [(0,), (0,), (0,)]
    for f in (0, 1, 2):
        ensure(not possible(words, [{"a", "b"}, {"b", "c"}, {"a", "c"}], [0, 0, f], 2 * f + 1), f)
        ensure(possible(words, [{"a", "b"}, {"b", "c"}, {"b"}], [0, 0, f], 0), f)


def address(k, f):
    d = (k - 1).bit_length()
    ids = [tuple((i >> t) & 1 for t in range(d)) for i in range(k)]
    # Old i has only marker i set. New i copies its address but all markers are clear.
    old = [x + tuple(int(i == t) for t in range(k)) for i, x in enumerate(ids)]
    new = [x + (0,) * k for x in ids]
    valid = [{i} for i in range(k)] + [{"fallback"}] * k
    options = (old + new, valid, [0] * k + [f] * k)
    upper = d + f + 1
    best = next(n for n in range(upper + 1) if possible(*options, n))
    # Each same-address cross-pair differs only on its own marker; these k requirements are disjoint.
    for i in range(k):
        ensure([q for q in range(d + k) if old[i][q] != new[i][q]] == [d + i], (k, i))
    # Explicit fixed schedule: every marker f+1 times. Check all conflicting pairs' answer distances.
    program = tuple(q for q in range(d, d + k) for _ in range(f + 1))
    words = old + new
    for i, j in combinations(range(2 * k), 2):
        if valid[i].isdisjoint(valid[j]):
            ensure(sum(words[i][q] != words[j][q] for q in program) > options[2][i] + options[2][j],
                   (i, j, program))
    if k == 2:
        ensure(not possible(*options, len(program) - 1, fixed=True), (k, f))
    return {"k": k, "f": f, "adaptive": best, "two_batch_upper": upper, "fixed": len(program)}


if __name__ == "__main__":
    expected = json.loads(Path(__file__).with_name("evidence.json").read_text(encoding="utf8"))
    sqlite(expected["sqlite"])
    alias_check()
    print(json.dumps({"tables": small_tables(expected["small_tables"]),
                      "address": [address(k, f) for k, f in product((2, 3, 4), range(3))]}, indent=2))
