"""Exact fixed and adaptive costs for trusted cross-checks on finite worlds."""

from bisect import bisect_left
from dataclasses import dataclass
from functools import cache
from math import inf


@dataclass(frozen=True)
class Probe:
    cost: int
    answers: tuple
    interval: tuple | None = None


def _answer_masks(probe):
    by_answer = {}
    for i, answer in enumerate(probe.answers):
        by_answer[answer] = by_answer.get(answer, 0) | (1 << i)
    return by_answer


def _terminal(state, truth):
    return not (state & truth and state & ~truth)


def _split(state, by_answer):
    return tuple(p for mask in by_answer.values() if (p := state & mask))


def _bits(mask):
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def indistinguishable(labels, probes):
    seen = {}
    for i, label in enumerate(labels):
        signature = tuple(q.answers[i] for q in probes)
        if signature in seen and labels[seen[signature]] != label:
            return seen[signature], i
        seen[signature] = i
    return None


@dataclass(frozen=True)
class Plan:
    root: int
    truth: int
    probes: tuple
    masks: tuple
    cost: int | None
    choices: dict
    visited: int
    counterexample: tuple | None = None

    def start(self):
        if self.cost is None:
            raise ValueError("no guaranteed policy exists")
        return Cursor(self)

    def walk(self, world):
        """Return a possible world's label, charged cost and probe indices."""
        cursor = self.start()
        questions = []
        while (i := cursor.next_probe()) is not None:
            questions.append(i)
            cursor.observe(self.probes[i].answers[world])
        assert cursor.state & (1 << world)
        return cursor.label, cursor.charges, questions


class Cursor:
    def __init__(self, plan):
        self.plan = plan
        self.state = plan.root
        self.charges = 0
        self.tail = None
        self.pending = None

    @property
    def label(self):
        if _terminal(self.state, self.plan.truth):
            return bool(self.state & self.plan.truth)
        return None

    def next_probe(self):
        if self.label is not None:
            return None
        if self.pending is not None:
            return self.pending
        if self.tail is None:
            decision = self.plan.choices[self.state]
            if isinstance(decision, int):
                self.pending = decision
                return decision
            self.tail = iter(decision)
        for j in self.tail:
            if len(_split(self.state, self.plan.masks[j])) > 1:
                self.pending = j
                return j
        raise AssertionError("the selected cover must settle the label")

    def observe(self, answer):
        i = self.next_probe()
        if i is None:
            raise ValueError("the label is already settled")
        state = self.state & self.plan.masks[i].get(answer, 0)
        if not state:
            raise ValueError("probe answer contradicts the compatible worlds")
        self.state = state
        self.charges += self.plan.probes[i].cost
        self.pending = None


def _cover(state, intervals, probes):
    """Cover the remaining ordered points by minimum-cost intervals."""
    points = list(_bits(state))
    steps = [None] * len(points)
    cost = [inf] * len(points) + [0]
    spans = []
    for i in intervals:
        start, end = probes[i].interval
        a, b = bisect_left(points, start), bisect_left(points, end)
        if a < b:
            spans.append((a, b, i))
    for j in range(len(points) - 1, -1, -1):
        for a, b, i in spans:
            if a <= j < b and probes[i].cost + cost[b] < cost[j]:
                steps[j] = (i, b)
                cost[j] = probes[i].cost + cost[b]
    selected, j = [], 0
    if cost[0] != inf:
        while j < len(points):
            i, j = steps[j]
            selected.append(i)
    return cost[0], tuple(selected)


def _make_plan(labels, probes, structured):
    if not labels or any(label not in (False, True) for label in labels):
        raise ValueError("nonempty Boolean labels required")
    if any(q.cost <= 0 or len(q.answers) != len(labels) for q in probes):
        raise ValueError("nonempty aligned worlds and positive probe costs required")
    masks = tuple(_answer_masks(q) for q in probes)
    truth = sum(int(label) << i for i, label in enumerate(labels))
    root = (1 << len(labels)) - 1
    recursive, tails = [], ([], [])
    for i, q in enumerate(probes):
        by_answer = masks[i]
        if len(by_answer) <= 1:
            continue
        if structured:
            if q.interval is None or len(by_answer) != 2:
                raise ValueError("an interval is required for every variable probe")
            a, b = q.interval
            if not 0 <= a < b <= len(labels):
                raise ValueError("invalid probe interval")
            segment = ((1 << b) - 1) ^ ((1 << a) - 1)
            if segment not in by_answer.values():
                raise ValueError("probe responses do not match its interval")
            if _terminal(segment, truth):
                tails[bool(segment & truth)].append(i)
                continue
        recursive.append(i)

    conflict = indistinguishable(labels, probes)
    if conflict is not None:
        return Plan(root, truth, tuple(probes), masks, None, {}, 0, conflict)

    future = {}
    pending = [root] if not _terminal(root, truth) else []
    while pending:
        state = pending.pop()
        if state in future:
            continue
        next_states = []
        for i in recursive:
            children = _split(state, masks[i])
            if len(children) > 1:
                next_states.append((i, children))
                pending.extend(
                    c for c in children if c not in future and not _terminal(c, truth)
                )
        future[state] = next_states

    costs, choices = {}, {}
    for state in sorted(future, key=int.bit_count):
        best, decision = inf, ()
        if structured:
            best, decision = min(
                (
                    _cover(state & ~truth, tails[0], probes),
                    _cover(state & truth, tails[1], probes),
                )
            )
        for i, children in future[state]:
            total = probes[i].cost + max(costs.get(c, 0) for c in children)
            if total < best:
                best, decision = total, i
        costs[state], choices[state] = best, decision
    result = costs.get(root, 0)
    return Plan(
        root,
        truth,
        tuple(probes),
        masks,
        None if result == inf else result,
        choices,
        len(future),
    )


def interval_plan(labels, probes):
    """Exact integer minimax cost, parameterized by ordered label boundaries."""
    return _make_plan(labels, probes, True)


def finite_plan(labels, probes):
    """Exact arbitrary-probe minimax cost on small finite world tables."""
    return _make_plan(labels, probes, False)


def fixed_cost(labels, probes):
    """Minimum up-front cost to separate every opposite-label pair."""
    pairs = [(i, j) for i, a in enumerate(labels) for j in range(i) if a != labels[j]]
    covered = []
    for q in probes:
        bits = sum(
            (q.answers[i] != q.answers[j]) << r for r, (i, j) in enumerate(pairs)
        )
        if bits:
            covered.append((bits, q.cost))
    by_pair = [[] for _ in pairs]
    for bits, cost in covered:
        for i in _bits(bits):
            by_pair[i].append((bits, cost))

    @cache
    def visit(state):
        if not state:
            return 0
        first = (state & -state).bit_length() - 1
        return min(
            (cost + visit(state & ~bits) for bits, cost in by_pair[first]), default=inf
        )

    cost = visit((1 << len(pairs)) - 1)
    return None if cost == inf else cost
