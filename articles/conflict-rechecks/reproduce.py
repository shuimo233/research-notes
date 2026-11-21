"""Run with Python 3.10+; stdout is the complete deterministic evidence.json."""

from collections import deque
from contextlib import closing
from functools import lru_cache
from itertools import combinations, combinations_with_replacement
import json
import sqlite3

from diagnose import attribute, minimum_cover


def require(condition, message):
    if not condition:
        raise ValueError(message)


def error_words(length, errors):
    for count in range(min(errors, length) + 1):
        for times in combinations(range(length), count):
            yield sum(1 << i for i in times)


def minimax(columns, n, errors, cap):
    """Search every first move and feasible answer; extension's clean bit is zero."""
    @lru_cache(None)
    def wins(old, left, depth):
        if not old or left < 0:
            return True
        if depth == 0:
            return False
        return any(wins(old & ~q, left, depth - 1) and wins(old & q, left - 1, depth - 1)
                   for q in columns)
    return next((d for d in range(cap + 1) if wins((1 << n) - 1, errors, d)), None)


def fixed_search(columns, n, errors, cap):
    """Try all unordered fixed schedules; test transcript intersection explicitly."""
    for length in range(cap + 1):
        extension_answers = set(error_words(length, errors))
        for schedule in combinations_with_replacement(columns, length):
            old_answers = {sum(((q >> i) & 1) << t for t, q in enumerate(schedule)) for i in range(n)}
            if not old_answers.intersection(extension_answers):
                return length
    return None


def multicover(columns, n, demand):
    start = (0,) * n
    todo, seen = deque([(start, 0)]), {start}
    while todo:
        counts, depth = todo.popleft()
        if min(counts) == demand:
            return depth
        for q in columns:
            nxt = tuple(min(demand, v + ((q >> i) & 1)) for i, v in enumerate(counts))
            if nxt not in seen:
                seen.add(nxt)
                todo.append((nxt, depth + 1))
    return None


def check_two_batches(columns, cover, n, errors):
    first = [columns[j] for j in cover]
    worst = 0
    for row in [None, *range(n)]:
        for flips in error_words(len(first) + errors, errors if row is None else 0):
            def answer(mask, time):
                return ((flips >> time) & 1) if row is None else ((mask >> row) & 1)
            readings = [answer(mask, t) for t, mask in enumerate(first)]
            extra = []
            if 1 in readings:
                witness = first[readings.index(1)]
                extra = [answer(witness, t + len(first)) for t in range(errors)]
            attributed_old = 1 in readings and all(extra)
            require(attributed_old == (row is not None), (first, row, flips, extra))
            worst = max(worst, len(first) + len(extra))
    return worst


def table_suite():
    counts = {"finite": 0, "inseparable": 0, "strict_adaptive_advantage": 0, "ties": 0}
    for n in range(1, 4):
        masks = tuple(range(1, 1 << n))
        for size in range(len(masks) + 1):
            for columns in combinations(masks, size):
                cover = minimum_cover(columns, n)
                for errors in range(3):
                    cap = n * (errors + 1)
                    adaptive = minimax(columns, n, errors, cap)
                    fixed = fixed_search(columns, n, errors, cap)
                    expected = len(cover) + errors if cover is not None else None
                    require((adaptive, fixed) == (expected, multicover(columns, n, errors + 1)),
                            (n, columns, errors, adaptive, fixed))
                    if adaptive is None:
                        # A concrete old row identical to the extension on every available probe.
                        require(any(all((q >> i) & 1 == 0 for q in columns) for i in range(n)), columns)
                        counts["inseparable"] += 1
                    else:
                        require(check_two_batches(columns, cover, n, errors) == adaptive, (columns, errors))
                        counts["finite"] += 1
                        counts["ties" if fixed == adaptive else "strict_adaptive_advantage"] += 1
    return counts


# Binary sensors on a single, reset transaction. The model table is specified
# separately from the SQL statements used for measurement.
PREDICTIONS = {
    "ROLLBACK": (0, 0, 0, 0), "ABORT": (1, 0, 0, 0), "FAIL": (1, 1, 0, 0),
    "IGNORE": (1, 1, 1, 0), "REPLACE": (1, 1, 1, 1),
}
SENSORS = ("key1", "key2", "key3", "new1")
PREDICATES = dict(zip(SENSORS, ("k=1", "k=2", "k=3", "k=1 AND v='new'")))
COMBINED = "key2_without_key3"


def predict(policy, q):
    row = PREDICTIONS[policy]
    return row[1] and not row[2] if q == COMBINED else row[SENSORS.index(q)]


def sql_read(policy, q):
    require(policy in PREDICTIONS, policy)
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
        db.execute("CREATE TABLE items(k INTEGER PRIMARY KEY, v TEXT)")
        db.execute("BEGIN")
        db.execute("INSERT INTO items VALUES(1,'old')")
        try:
            db.execute(f"INSERT OR {policy} INTO items VALUES(2,'prefix'),(1,'new'),(3,'suffix')")
        except sqlite3.IntegrityError:
            pass
        if q == COMBINED:
            query = "SELECT EXISTS(SELECT 1 FROM items WHERE k=2) AND NOT EXISTS(SELECT 1 FROM items WHERE k=3)"
        else:
            query = f"SELECT EXISTS(SELECT 1 FROM items WHERE {PREDICATES[q]})"
        return db.execute(query).fetchone()[0]


def sqlite_suite():
    new = "FAIL"
    existing = {name: (lambda q, name=name: predict(name, q)) for name in PREDICTIONS if name != new}
    history_keys = ("key2", "key3")
    result = {}
    for label, probes in (("four_sensors", SENSORS), ("extra_predicate", (*SENSORS, COMBINED))):
        columns = tuple(sum(1 << i for i, name in enumerate(existing) if predict(name, q) != predict(new, q))
                        for q in probes)
        expected_depth = minimax(columns, len(existing), 1, 8)
        record = {"optimal_adaptive": expected_depth, "optimal_fixed": fixed_search(columns, len(existing), 1, 8)}
        runs = []
        for name in PREDICTIONS:
            clean = tuple(sql_read(name, q) for q in history_keys)
            for q in probes:
                require(sql_read(name, q) == predict(name, q), (name, q))
            flipped = {"ROLLBACK": 0, "ABORT": 0, "FAIL": None, "IGNORE": 1, "REPLACE": 1}[name]
            history = [(q, y ^ int(i == flipped)) for i, (q, y) in enumerate(zip(history_keys, clean))]
            require([y for _, y in history] == [1, 0], name)
            # The old rule's only error was in the prefix; the extension may still flip one answer.
            for faults in error_words(expected_depth, int(name == new)):
                log = []
                def observe(q):
                    y = sql_read(name, q) ^ ((faults >> len(log)) & 1)
                    log.append(y)
                    return y
                out = attribute(existing, lambda q: predict(new, q), probes, history, observe)
                require(out.family == ("extension" if name == new else "existing"), (name, faults, out))
                runs.append({"mode": name, "future_flip_mask": faults, "family": out.family,
                             "followup": out.observations})
        require(max(len(r["followup"]) for r in runs) == expected_depth, label)
        record["runs"] = runs
        result[label] = record
    return result


def multiple_extensions(k, errors):
    """Separate two k-member families. A probe inspects one coordinate of a 2k-bit word."""
    words = tuple(1 << i for i in range(2 * k))
    base, new = words[:k], words[k:]
    columns = tuple(range(2 * k))
    @lru_cache(None)
    def win(old, budgets, depth):
        if not old or max(budgets) < 0:
            return True
        if not depth:
            return False
        def branch(q, answer):
            survivors = tuple(w for w in old if (w >> q) & 1 == answer)
            residual = tuple(max(-1, b - int(((w >> q) & 1) != answer)) for w, b in zip(new, budgets))
            return win(survivors, residual, depth - 1)
        return any(branch(q, 0) and branch(q, 1) for q in columns)

    cap = k * (errors + 1)
    adaptive = next(d for d in range(cap + 1) if win(base, (errors,) * k, d))
    def separates(schedule):
        # The discrepancy count of every cross-label pair must exceed the extension allowance.
        return all(sum(((a ^ b) >> q) & 1 for q in schedule) > errors for a in base for b in new)
    fixed = next(d for d in range(cap + 1)
                 if any(separates(s) for s in combinations_with_replacement(columns, d)))
    require((adaptive, fixed) == (k + errors, cap), (k, errors, adaptive, fixed))
    return {"k": k, "errors": errors, "adaptive": adaptive, "fixed": fixed}


if __name__ == "__main__":
    multi = [multiple_extensions(k, f) for k in range(1, 5) for f in range(3) if k < 4 or f < 2]
    print(json.dumps({"small_tables": table_suite(), "sqlite": sqlite_suite(),
                      "multiple_extensions": multi}, indent=2, sort_keys=True))
