"""Reproduce the finite checks using Python 3.10+ and the standard library."""

from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations, combinations_with_replacement, product
import json
import sqlite3


@dataclass(frozen=True)
class Rule:
    name: str
    bits: tuple
    actions: frozenset


def check(ok, case):
    if not ok:
        raise AssertionError(case)


def common(rules):
    return set.intersection(*(set(r.actions) for r in rules)) if rules else set()


def solve(rules, budgets):
    """Exact minimax by trying all permitted probes and both feasible outcomes."""
    width = len(rules[0].bits)
    def advance(state, q, y):
        return tuple(max(-1, v - int(r.bits[q] != y)) for r, v in zip(rules, state))

    @lru_cache(None)
    def choice(state, left):
        live = [r for r, v in zip(rules, state) if v >= 0]
        actions = common(live)
        if not live or actions:
            return ("stop", min(actions) if actions else None)
        if left:
            for q in range(width):
                branches = [advance(state, q, y) for y in (0, 1)]
                if state in branches:
                    continue  # This move can leave exactly the same decision problem.
                if all(choice(s, left - 1) is not None for s in branches):
                    return ("ask", q)
        return None

    cap = width * (2 * max(budgets) + 1)
    # Repeating each probe 2*max(budgets)+1 times determines the full signature.
    depth = next((d for d in range(cap + 1) if choice(budgets, d) is not None), None)
    return depth, choice, advance


def bounds(old, new, f):
    """Compute the local certificate by enumerating query multisets, independently of solve."""
    width = len(old[0].bits)
    signatures = {b.bits for b in old}
    @lru_cache(None)
    def old_depth(group):
        if len(group) <= 1:
            return 0
        splits = []
        for q in range(width):
            z = tuple(sig for sig in group if sig[q] == 0)
            o = tuple(sig for sig in group if sig[q] == 1)
            if z and o:
                splits.append(max(old_depth(z), old_depth(o)))
        return 1 + min(splits)

    def certificate(sig, action):
        bad = [e for e in new if action not in e.actions]
        if any(e.bits == sig for e in bad):
            return float("inf")
        if not bad:
            return 0
        for length in range(1, width * (f + 1) + 1):
            for schedule in combinations_with_replacement(range(width), length):
                if all(sum(sig[q] != e.bits[q] for q in schedule) > f for e in bad):
                    return length
        raise AssertionError("enumeration missed the repeated full signature")

    lower = max(min((certificate(sig, a) for a in common([b for b in old if b.bits == sig])),
                    default=float("inf")) for sig in signatures)
    return lower, old_depth(tuple(sorted(signatures)))


def tables():
    signatures = tuple(product((0, 1), repeat=2))
    action_sets = tuple(map(frozenset, (("x",), ("y",), ("x", "y"))))
    counts = Counter()
    for old_sigs in combinations(signatures, 2):
        new_sigs = [s for s in signatures if s not in old_sigs]
        for labels in product(action_sets, repeat=4):
            rules = tuple(Rule(str(i), s, a) for i, (s, a) in enumerate(zip((*old_sigs, *new_sigs), labels)))
            if not common(rules[2:]):
                continue
            for f in range(3):
                low, d = bounds(rules[:2], rules[2:], f)
                t = solve(rules, (0, 0, f, f))[0]
                check(low <= t <= low + d, (old_sigs, labels, f, low, d, t))
                counts[(f, t - low)] += 1
    return [{"f": f, "excess_over_L": gap, "cases": n} for (f, gap), n in sorted(counts.items())]


def sharp_examples():
    result = []
    for d in range(3):
        ids = list(product((0, 1), repeat=d))
        old = tuple(Rule(str(x), x + (0, 0, 0), frozenset([str(x)])) for x in ids)
        new = tuple(Rule(str((x, y)), x + y, frozenset(["fallback"]))
                    for x in ids for y in ((1, 1, 0), (1, 0, 1), (0, 1, 1)))
        for f in range(3):
            low, depth = bounds(old, new, f)
            t = solve(old + new, (0,) * len(old) + (f,) * len(new))[0]
            check((low, depth, t) == ((3 * (f + 1) + 1) // 2, d, low + d), (d, f, t))
            result.append({"d": d, "f": f, "L": low, "T": t})
    return result


def no_fallback():
    old = (Rule("old", (1, 0), frozenset("ab")),)
    new = (Rule("left", (0, 0), frozenset("a")), Rule("right", (0, 1), frozenset("b")))
    rows = []
    for f in range(3):
        low, d = bounds(old, new, f)
        t = solve(old + new, (0, f, f))[0]
        check((low, d, t) == (f + 1, 0, 2 * f + 1), f)
        rows.append({"f": f, "L": low, "T": t})
    return rows


POLICIES = ("ROLLBACK", "REPLACE", "ABORT", "FAIL", "IGNORE")
PREDICTIONS = ((0, 0, 0, 0), (1, 1, 1, 1), (1, 0, 0, 0), (1, 1, 0, 0), (1, 1, 1, 0))
PREDICATES = ("k=1", "k=2", "k=3", "k=1 AND v='new'")
CONTINUATIONS = {
    "insert_all": "INSERT INTO items VALUES(1,'old'),(2,'prefix'),(3,'suffix')",
    "fill_tail": "INSERT OR IGNORE INTO items VALUES(2,'prefix'),(3,'suffix')",
    "restore_header": "INSERT OR REPLACE INTO items VALUES(1,'old')",
}
GOAL = [(1, "old"), (2, "prefix"), (3, "suffix")]
EXPECTED_ACTIONS = (("insert_all",), ("restore_header",), ("fill_tail",), ("fill_tail",),
                    ("fill_tail", "restore_header"))


def database(mode):
    check(mode in POLICIES, mode)
    db = sqlite3.connect(":memory:", isolation_level=None)
    db.execute("CREATE TABLE items(k INTEGER PRIMARY KEY, v TEXT)")
    db.execute("BEGIN")
    db.execute("INSERT INTO items VALUES(1,'old')")
    try:
        db.execute(f"INSERT OR {mode} INTO items VALUES(2,'prefix'),(1,'new'),(3,'suffix')")
    except sqlite3.IntegrityError:
        pass
    return db


def read(mode, q):
    with closing(database(mode)) as db:
        return db.execute(f"SELECT EXISTS(SELECT 1 FROM items WHERE {PREDICATES[q]})").fetchone()[0]


def action_rows(mode, action):
    with closing(database(mode)) as db:
        try:
            db.execute(CONTINUATIONS[action])
        except sqlite3.IntegrityError:
            return None
        return db.execute("SELECT k,v FROM items ORDER BY k").fetchall()


def sqlite_check():
    rules = tuple(Rule(m, bits, frozenset(a)) for m, bits, a in zip(POLICIES, PREDICTIONS, EXPECTED_ACTIONS))
    applied = {}
    for i, r in enumerate(rules):
        check(r.bits == tuple(read(r.name, q) for q in range(4)), r.name)
        applied[r.name] = {a: action_rows(r.name, a) for a in CONTINUATIONS}
        check(r.actions == {a for a, rows in applied[r.name].items() if rows == GOAL}, r.name)
        # Match the two shared historical readings by flipping exactly one bit in each old world.
        h = (read(r.name, 0) ^ (i == 0), read(r.name, 3) ^ (i == 1))
        check(h == (1, 0), (r.name, h))
    rows = []
    for f in range(3):
        budgets = (0, 0, f, f, f)
        low, d = bounds(rules[:2], rules[2:], f)
        t, choice, advance = solve(rules, budgets)
        identify = solve(tuple(Rule(r.name, r.bits, frozenset([r.name])) for r in rules), budgets)[0]
        counts = Counter()
        def visit(i, state, left, flips):
            kind, move = choice(state, left)
            if kind == "stop":
                check(action_rows(rules[i].name, move) == GOAL, (i, move))
                counts["verified_leaves_by_world"] += 1
                if sum(v >= 0 for v in state) > 1:
                    counts["leaves_with_ambiguity"] += 1
                return
            true = read(rules[i].name, move)
            for error in range(1 + int(flips > 0)):
                visit(i, advance(state, move, true ^ error), left - 1, flips - error)
        for i, budget in enumerate(budgets):
            visit(i, budgets, t, budget)
        check(low == f + 1 and t == low + d == f + 2, (f, t))
        rows.append({"f": f, "L": low, "D": d, "safe_action": t, "identify_mode": identify, **counts})
    return rows, applied


if __name__ == "__main__":
    sqlite_results, applied = sqlite_check()
    print(json.dumps({"small_tables": tables(), "sharp": sharp_examples(), "no_fallback": no_fallback(),
                      "sqlite": sqlite_results, "sqlite_action_rows": applied}, indent=2, sort_keys=True))
