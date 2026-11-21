"""Exact small-instance follow-up design for a finite, binary, repeatable probe library."""

from collections import deque
from dataclasses import dataclass


def minimum_cover(columns, size):
    """Indices of a smallest cover, or None if some old rule is indistinguishable."""
    full = (1 << size) - 1
    parent = {0: None}
    queue = deque([0])
    while queue:
        mask = queue.popleft()
        if mask == full:
            path = []
            while parent[mask] is not None:
                mask, j = parent[mask]
                path.append(j)
            return tuple(reversed(path))
        for j, col in enumerate(columns):
            nxt = mask | col
            if nxt not in parent:
                parent[nxt] = (mask, j)
                queue.append(nxt)
    return None


def bit(value):
    if type(value) not in (bool, int) or value not in (0, 1):
        raise ValueError("expected a binary observation")
    return int(value)


@dataclass(frozen=True)
class Result:
    family: str
    existing_rules: tuple
    extension_possible: bool
    observations: tuple
    reason: str


def attribute(existing, extension, probes, history, observe, *, extension_errors=1, budget=None):
    """Use one lifetime error per existing rule and extension_errors for the new rule.

    Model functions and the adapter take one probe key. Each call must start from
    the same state. The objective is the family label, not the individual rule.
    """
    if type(extension_errors) is not int or extension_errors < 0:
        raise ValueError("extension_errors must be a nonnegative integer")
    if budget is not None and (type(budget) is not int or budget < 0):
        raise ValueError("budget must be a nonnegative integer")
    history = [(q, bit(y)) for q, y in history]
    probes = tuple(dict.fromkeys(probes))
    def mismatches(rule):
        return sum(bit(rule(q)) != y for q, y in history)

    used = {name: mismatches(rule) for name, rule in existing.items()}
    live = [name for name, count in used.items() if count <= 1]
    remaining = extension_errors - mismatches(extension)
    followup = []

    def finish(reason):
        possible = remaining >= 0
        if live:
            family = "ambiguous" if possible else "existing"
        else:
            family = "extension" if possible else "inconsistent"
        return Result(family, tuple(live), possible, tuple(followup), reason)

    if not live or remaining < 0:
        return finish("history")
    if any(used[name] == 0 for name in live):
        raise ValueError("expected a history contradicting every error-free existing rule")
    expected = {q: bit(extension(q)) for q in probes}
    outputs = {q: {n: bit(existing[n](q)) for n in live} for q in probes}
    columns = [sum(1 << i for i, n in enumerate(live) if outputs[q][n] != expected[q])
               for q in probes]
    cover = minimum_cover(columns, len(live))
    if cover is None:
        return finish("no_guaranteed_separation")

    for index in cover:
        q = probes[index]
        while True:
            if budget is not None and len(followup) == budget:
                return finish("budget")
            y = bit(observe(q))
            followup.append((q, y))
            live = [n for n in live if outputs[q][n] == y]
            if y != expected[q]:
                remaining -= 1
            if not live or remaining < 0:
                return finish("evidence")
            if y == expected[q]:
                break
            # All surviving old rules predict the opposite of the extension here.
            # Repeating this same probe now distinguishes the two families.
    raise AssertionError("cover left an existing rule on the all-extension path")
