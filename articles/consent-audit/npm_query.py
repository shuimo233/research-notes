"""Exact declared-dependency labels from coarse npm package version bands."""

from collections import Counter
from fractions import Fraction as Q
from itertools import product
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batched_query_plan import batched
from frontier_inquiry import RelationInquiry
from shared_sense import SharedInquiry


def table_data(task):
    domains = {r["id"]: tuple(r["versions"]) for r in task["vertices"]}
    by_pair = {}
    for e in task["relations"]:
        u, v = e["from"], e["to"]
        x, y = sorted((u, v))
        grid = {
            (a, b): e["grid"][i][j]
            for i, a in enumerate(domains[u])
            for j, b in enumerate(domains[v])
        }
        if (u, v) != (x, y):
            grid = {(b, a): label for (a, b), label in grid.items()}
        by_pair.setdefault((x, y), []).append((u, v, grid))
    return domains, by_pair


class VersionInquiry:
    def __init__(self, task):
        self.raw, self.by_pair = table_data(task)
        source = {
            u: [(e, e.index(u)) for e in self.by_pair if u in e] for u in self.raw
        }
        self.representative = {}
        for u, xs in self.raw.items():
            classes = {}
            translated = {}
            for x in xs:
                signature = tuple(
                    grid[(x, y) if side == 0 else (y, x)]
                    for e, side in source[u]
                    for _, _, grid in self.by_pair[e]
                    for y in self.raw[e[1 - side]]
                )
                translated[x] = classes.setdefault(signature, x)
            self.representative[u] = translated
        domains = {
            u: tuple((u, x) for x in set(row.values()))
            for u, row in self.representative.items()
        }

        def relation(a, b):
            u, x = a
            v, y = b
            return "".join(grid[x, y] for _, _, grid in self.by_pair[u, v])

        self.service = SharedInquiry(domains, self.by_pair, relation)
        variable = {u: dom for u, dom in domains.items() if len(dom) > 1}
        self.planner = None
        self.initial_forced = 0
        if variable:
            weights = {
                u: {
                    (u, s): Q(n, len(self.raw[u]))
                    for s, n in Counter(self.representative[u].values()).items()
                }
                for u in variable
            }
            self.planner = RelationInquiry(
                variable,
                [e for e in self.by_pair if all(u in variable for u in e)],
                relation,
                weights,
            )
            for e in self.service.pending(self.service.free):
                missing = [u for u in e if u not in self.service.free]
                if len(missing) == 1:
                    self.initial_forced |= 1 << self.planner.types_by_id[missing[0]]
            self.batch = batched(self.planner.plan)

    def state(self, truth):
        return {u: (u, self.representative[u][x]) for u, x in truth.items()}

    def expand(self, answers):
        return sorted(
            (u, v, c)
            for e, code in answers.items()
            for (u, v, _), c in zip(self.by_pair[e], code, strict=True)
        )

    def replay(self, ask, mode="optimal"):
        seen = dict(self.service.free)
        path = []

        def read(u):
            x = ask(u)
            seen[u] = (u, self.representative[u][x])
            return seen[u]

        if self.planner is not None:
            path, _, _ = self.planner.execute(
                read,
                mode,
                planner=self.batch if mode == "optimal" else None,
                initial_forced=self.initial_forced,
            )
        answers = {e: self.service.answer(e, seen) for e in self.service.order}
        if None in answers.values():
            raise ArithmeticError("query controller stopped without a certificate")
        return path, self.expand(answers)

    def verify_projection(self):
        for (u, v), rows in self.by_pair.items():
            for x, y in product(self.raw[u], self.raw[v]):
                rx = self.representative[u][x]
                ry = self.representative[v][y]
                assert all(grid[x, y] == grid[rx, ry] for _, _, grid in rows)
