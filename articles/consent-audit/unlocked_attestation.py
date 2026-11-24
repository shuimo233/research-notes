"""Minimum truthful repairs that do not fix any previously uncertain timestamp."""

from collections import deque
from functools import lru_cache

from attested_optimality import Exhausted, impose, new_exact
from conclusion_replay import components
from slack_certificate import Cover, minimal_rows, sites, visible


def menu(public, actual, grid, preserve_strict=True):
    if grid < 1:
        raise ValueError("comparison grid must be positive")
    facts = []
    representatives = components(public)
    equivalent = set()
    for u, row in enumerate(public):
        for v in range(len(row)):
            if u == v:
                continue
            d = actual[v] - actual[u]
            top = d - d % grid
            candidates = (top, top - grid) if preserve_strict and top == d else (top,)
            for cut in candidates:
                if cut > -public[v][u]:
                    a, b = representatives[u], representatives[v]
                    signature = (
                        a,
                        b,
                        cut + actual[u] - actual[a] - actual[v] + actual[b],
                    )
                    if signature not in equivalent:
                        facts.append((u, v, cut))
                        equivalent.add(signature)
    return tuple(facts)


def extremal_tables(zone):
    return [tuple(-row[0] for row in zone), zone[0]]


class AnchorPath:
    def __init__(self, public, actual, facts):
        self.source = len(public)
        self.sink = self.source + 1
        fixed = {i for i in range(len(public)) if public[0][i] == -public[i][0]}

        def split(u, v):
            if u != v and not (u in fixed and v in fixed):
                return self.source if u in fixed else u, self.sink if v in fixed else v
            return None

        self.base = [[] for _ in range(len(public) + 2)]
        for u, row in enumerate(public):
            for v, value in enumerate(row):
                if value == actual[v] - actual[u]:
                    e = split(u, v)
                    if e is not None:
                        self.base[e[0]].append((e[1], 0))
        self.tight = {}
        for i, (u, v, cut) in enumerate(facts, 1):
            if cut == actual[v] - actual[u]:
                arc = split(v, u)
                if arc is not None:
                    self.tight[i] = arc
        self.tight_mask = visible(self.tight)

    def conflict(self, chosen):
        return self._path(visible(chosen) & self.tight_mask)

    @staticmethod
    def witness(before, after):
        assert not new_exact(before, after)
        return dict(worlds=extremal_tables(after))

    @lru_cache(maxsize=8192)
    def _path(self, selected):
        if not selected:
            return ()
        arcs = [x.copy() for x in self.base]
        for i in sites(selected):
            u, v = self.tight[i]
            arcs[u].append((v, i))
        agenda = deque([self.source])
        seen = {self.source: None}
        while agenda:
            u = agenda.popleft()
            for v, mark in arcs[u]:
                if v not in seen:
                    seen[v] = (u, mark)
                    if v == self.sink:
                        cut = set()
                        while v != self.source:
                            v, mark = seen[v]
                            if mark:
                                cut.add(mark)
                        assert cut
                        return tuple(sorted(cut))
                    agenda.append(v)
        return ()


def signed_minimum(count, needed, blocked, limit=100_000, graph=None):
    """Choose a minimum cover of positive rows, without containing a blocked row."""
    if 0 in needed or 0 in blocked:
        return None, 0
    forbid = minimal_rows(blocked)
    cover = Cover(minimal_rows(needed), count + 1)
    best = None
    nodes = 0
    seen = set()
    bound = lru_cache(maxsize=8192)(cover.lower)

    signatures = {}
    for i in range(1, count + 1):
        coverage = cover.by_site[i]
        if not coverage:
            continue
        lock_pattern = tuple(j for j, row in enumerate(forbid) if row & (1 << i))
        if graph is None or not graph.tight_mask & (1 << i):
            relation = None
        else:
            relation = graph.tight[i]
        signatures.setdefault((coverage, lock_pattern, relation), i)
    active = visible(signatures.values())

    def branch(remaining, chosen):
        nonlocal best, nodes
        if any(chosen & no == no for no in blocked):
            return
        size = chosen.bit_count()
        if best is not None and size + bound(remaining) >= best.bit_count():
            return
        if graph is not None:
            conflict = graph._path(chosen & graph.tight_mask)
            if conflict:
                blocked.add(visible(conflict))
                return
        if not remaining:
            best = chosen
            return
        if chosen in seen:
            return
        if nodes >= limit:
            raise Exhausted("signed cover search budget exceeded")
        nodes += 1
        seen.add(chosen)
        i = (remaining & -remaining).bit_length() - 1
        for candidate in sorted(
            sites(cover.rows[i] & active),
            key=lambda j: (-(cover.by_site[j] & remaining).bit_count(), j),
        ):
            branch(remaining & ~cover.by_site[candidate], chosen | 1 << candidate)

    branch(cover.initial, 0)
    return (tuple(sites(best)) if best is not None else None), nodes


def solve(
    oracle,
    actual,
    grid,
    preserve_strict=True,
    rounds=500,
    limit=100_000,
    graph_type=AnchorPath,
):
    facts = menu(oracle.start, actual, grid, preserve_strict)
    infeasible = oracle.find(facts, limit)
    if infeasible is not None:
        return dict(status="dictionary_impossible", counterexample=infeasible)
    graph = graph_type(oracle.start, actual, facts)
    positives, negatives = set(), set()
    smaller = []
    explored = 0
    for cycle in range(1, rounds + 1):
        best, operations = signed_minimum(
            len(facts), positives, negatives, limit, graph
        )
        explored += operations
        info = dict(
            rounds=cycle,
            nodes=explored,
            bad=smaller,
            lock=[
                [facts[i - 1] for i in sites(clause)] for clause in sorted(negatives)
            ],
        )
        if best is None:
            return dict(status="protection_impossible", **info)

        picked = [facts[i - 1] for i in best]
        result = oracle.find(picked, limit)
        if result is not None:
            record = result["record"]
            row = visible(
                j for j, (u, v, b) in enumerate(facts, 1) if record[v] - record[u] < b
            )
            assert row and row not in positives
            positives.add(row)
            smaller.append(result)
            continue

        if preserve_strict:
            for i in range(len(picked)):
                picked[i] = oracle.weakest(
                    [*picked[:i], *picked[i + 1 :]], picked[i], grid
                )
        after = impose(oracle.start, picked)
        return dict(
            status="proved",
            attested=picked,
            **graph.witness(oracle.start, after),
            **info,
        )
    raise Exhausted("signed cover counterexample limit exceeded")
