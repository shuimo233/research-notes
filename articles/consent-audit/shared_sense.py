"""Exact sentence-level clarification for a collection of binary relation tables."""

from fractions import Fraction
from functools import cached_property, lru_cache

from sense_inquiry import SenseInquiry


def minimum_cover(edges):
    """Minimum cardinality, then lexicographically first cover of an undirected graph."""

    @lru_cache(None)
    def solve(remaining):
        if not remaining:
            return ()
        u, v = remaining[0]
        options = []
        for vertex in (u, v):
            rest = tuple(e for e in remaining if vertex not in e)
            options.append(tuple(sorted((vertex, *solve(rest)))))
        return min(options, key=lambda cover: (len(cover), cover))

    return solve(tuple(sorted({tuple(sorted(e)) for e in edges})))


class SharedInquiry:
    """Give each occurrence its own ID. A revealed sense is reusable across all incident edges."""

    def __init__(self, domains, edges, relation):
        self.domains = {u: tuple(sorted(set(vals))) for u, vals in domains.items()}
        self.tables = {}
        for u, v in edges:
            if u == v or (u, v) in self.tables or (v, u) in self.tables:
                raise ValueError(
                    "each pair must contain two different IDs and occur once"
                )
            self.tables[u, v] = SenseInquiry(self.domains[u], self.domains[v], relation)
        self.order = sorted(self.tables, key=lambda e: tuple(sorted(e)))
        self.free = {u: vals[0] for u, vals in self.domains.items() if len(vals) == 1}

    @cached_property
    def cover(self):
        live = self.pending(self.free)
        forced = {
            v
            for e in live
            for v in e
            if v not in self.free and any(u in self.free for u in e)
        }
        return forced | set(
            minimum_cover(e for e in live if not forced.intersection(e))
        )

    def answer(self, edge, known):
        table = self.tables[edge]
        u, v = edge
        if u in known and v in known:
            return table.cells[known[u], known[v]]
        if u in known:
            return table.after[0][known[u]]
        if v in known:
            return table.after[1][known[v]]
        return table.constant

    def pending(self, known):
        return [e for e in self.order if self.answer(e, known) is None]

    def next(self, observed, policy="cover"):
        if any(
            u not in self.domains or val not in self.domains[u]
            for u, val in observed.items()
        ):
            raise ValueError("invalid observed sense")
        known = {**self.free, **observed}
        pending = self.pending(known)
        if not pending:
            return "answers", {e: self.answer(e, known) for e in self.order}
        if policy in ("forward_table", "forward_more", "reverse_table", "reverse_more"):
            order, mode = policy.split("_")
            edge = pending[0] if order == "forward" else pending[-1]
            unknown = [u for u in edge if u not in known]
            return "ask", unknown[0] if len(unknown) == 1 else edge[
                self.tables[edge].first(mode)
            ]
        if policy not in ("greedy", "cover"):
            raise ValueError("unknown policy")
        scores = {}
        for edge in pending:
            unknown = [u for u in edge if u not in known]
            for u in unknown:
                expected, degree = scores.get(u, (Fraction(0), 0))
                gain = (
                    1 if len(unknown) == 1 else self.tables[edge].rates[edge.index(u)]
                )
                scores[u] = expected + gain, degree + 1
        pool = (self.cover & scores.keys()) if policy == "cover" else set()
        return "ask", min(
            pool or scores, key=lambda u: (-scores[u][0], -scores[u][1], u)
        )

    def certificate(self, truth):
        """Compute an offline minimum certificate at the supplied truth assignment."""
        forced, choices = set(), []
        for edge in self.pending(self.free):
            sufficient = [
                u
                for u in edge
                if u not in self.free
                and self.answer(edge, {**self.free, u: truth[u]}) is not None
            ]
            if len(sufficient) == 2:
                choices.append(edge)
            else:
                forced.update(sufficient or [u for u in edge if u not in self.free])
        return sorted(
            forced
            | set(minimum_cover(e for e in choices if not forced.intersection(e)))
        )
