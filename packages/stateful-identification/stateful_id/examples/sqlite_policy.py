"""Identify a real SQLite database's treatment of a UNIQUE conflict from final rows."""

from contextlib import closing
from functools import partial
import sqlite3

from .. import Domain, traces


POLICIES = ("ROLLBACK", "ABORT", "FAIL", "IGNORE", "REPLACE")
ROWS = {
    "seed": ((1, "old"),),
    "batch": ((2, "prefix"), (1, "new"), (3, "suffix")),
    "tail": ((4, "tail"),),
}
ACTIONS = tuple(ROWS)


def predict(policy, actions):
    table = {}
    for action in actions:
        before = table.copy()
        for key, value in ROWS[action]:
            if key not in table or policy == "REPLACE":
                table[key] = value
            elif policy == "IGNORE":
                continue
            else:
                if policy == "ROLLBACK":
                    table.clear()
                elif policy == "ABORT":
                    table = before
                break
    return [[k, table[k]] for k in sorted(table)]


def adapter(policy):
    """Start with a fresh database per trace. Only the final sorted rows are visible."""
    if policy not in POLICIES:
        raise ValueError(f"unknown SQLite policy {policy!r}")

    def observe(actions):
        with closing(sqlite3.connect(":memory:", isolation_level=None)) as db:
            db.execute("CREATE TABLE items (k INTEGER PRIMARY KEY, v TEXT NOT NULL)")
            for action in actions:
                values = ROWS[action]
                if not db.in_transaction:
                    db.execute("BEGIN")
                placeholders = ", ".join("(?, ?)" for _ in values)
                try:
                    db.execute(f"INSERT OR {policy} INTO items(k,v) VALUES {placeholders}",
                               tuple(v for row in values for v in row))
                except sqlite3.IntegrityError:
                    # A rejected statement is task behavior. Submit subsequent actions too.
                    pass
            return [list(r) for r in db.execute("SELECT k,v FROM items ORDER BY k")]

    return observe


def domain():
    checks = (("seed", "batch", "tail"), ("tail", "seed", "batch"))
    return Domain("sqlite/primary-key-conflict-v1", {k: partial(predict, k) for k in POLICIES},
                  traces(ROWS, 2), checks=checks)
