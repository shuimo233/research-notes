"""Compile a batch of finite relation questions and execute an adaptive policy without exposing future answers."""

from collections import Counter, defaultdict
import argparse
import json
from fractions import Fraction as Q
from itertools import product
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_plan import FrontierPlan
from shared_sense import SharedInquiry


class RelationInquiry:
    """types optionally describes identical nonadjacent occurrences. Without it every occurrence is its own type."""

    def __init__(self, domains, edges, relation, marginals, types=None):
        self.service = SharedInquiry(domains, edges, relation)
        if self.service.free:
            raise ValueError(
                "reduce singleton domains before compiling; this adapter expects uncertain inputs"
            )
        self.types = dict(types) if types is not None else {u: u for u in domains}
        members = defaultdict(list)
        for u in sorted(domains):
            members[self.types[u]].append(u)
        self.names = tuple(sorted(members))
        self.members = [members[t] for t in self.names]
        index = {u: i for i, group in enumerate(self.members) for u in group}
        self.types_by_id = index
        adjacency = {u: set() for u in domains}
        typed_edges = set()
        for (u, v), table in self.service.tables.items():
            if table.constant is not None:
                continue
            if index[u] == index[v]:
                raise ValueError("split adjacent positions into different types")
            typed_edges.add(tuple(sorted((self.types[u], self.types[v]))))
            adjacency[u].add(v)
            adjacency[v].add(u)
        for a, b in typed_edges:
            if not all(v in adjacency[u] for u, v in product(members[a], members[b])):
                raise ValueError("types must have complete cross adjacency")
        groups = {}
        self.masks = {}
        for u, ss in self.service.domains.items():
            if set(marginals[u]) != set(ss):
                raise ValueError("marginals and candidate domain differ")
            masks = {x: 0 for x in ss}
            for v in adjacency[u]:
                e = (u, v) if (u, v) in self.service.tables else (v, u)
                for x in ss:
                    if self.service.answer(e, {u: x}) is None:
                        masks[x] |= 1 << index[v]
            # A class flag means that the whole remaining neighbor class is required.
            for x, mask in masks.items():
                for v in adjacency[u]:
                    e = (u, v) if (u, v) in self.service.tables else (v, u)
                    if bool(mask >> index[v] & 1) != (
                        self.service.answer(e, {u: x}) is None
                    ):
                        raise ValueError("a footprint splits a target class")
            mass = Counter()
            for x, p in marginals[u].items():
                if Q(p) <= 0:
                    raise ValueError(
                        "all semantic alternatives need positive marginal probability"
                    )
                mass[masks[x]] += Q(p)
            t = self.types[u]
            if t in groups and mass != groups[t]:
                raise ValueError("class members need identical footprint distributions")
            groups[t] = mass
            self.masks[u] = masks
        choices = {
            t: [
                ([name for i, name in enumerate(self.names) if mask >> i & 1], p)
                for mask, p in row.items()
            ]
            for t, row in groups.items()
        }
        self.plan = FrontierPlan(
            {t: len(members[t]) for t in self.names}, choices, typed_edges
        )

    def execute(self, ask, mode="optimal", limit=None, *, planner=None):
        """ask(position_id) returns only that position's categorical value."""
        if planner is None:
            planner = self.plan
        elif (planner.names, planner.counts, planner.neighbors) != (
            self.plan.names,
            self.plan.counts,
            self.plan.neighbors,
        ):
            raise ValueError("policy planner must use the same relation graph")
        known = {}
        trace = []
        counts = list(planner.counts)
        forced = 0
        fallback = 0

        def request(i):
            nonlocal forced
            u = self.members[i][len(self.members[i]) - counts[i]]
            x = ask(u)
            if x not in self.masks[u]:
                raise ValueError("answer outside candidate domain")
            trace.append(u)
            known[u] = x
            counts[i] -= 1
            forced |= self.masks[u][x]

        if mode == "fixed":
            initial, _ = planner.fixed_cover()
            for i in initial:
                while counts[i]:
                    request(i)
            for i in range(len(counts)):
                while counts[i] and forced >> i & 1:
                    request(i)
        else:
            while True:
                i, used = planner.action(tuple(counts), forced, mode, limit)
                if i is None:
                    break
                fallback += int(used)
                request(i)
        answers = {e: self.service.answer(e, known) for e in self.service.order}
        if any(v is None for v in answers.values()):
            raise ArithmeticError("policy stopped before the output was determined")
        return trace, answers, fallback


if __name__ == "__main__":
    from wordnet_paths import NounPaths
    from go_model_fetch import verify

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wordnet", type=Path)
    parser.add_argument("instance", type=Path)
    parser.add_argument(
        "--ask",
        action="store_true",
        help="show candidate glosses and resolve the requested pairs",
    )
    args = parser.parse_args()
    verify(args.wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(args.wordnet)
    problem = json.loads(args.instance.read_bytes())
    words = problem["words"]
    domains = {u: graph.senses(w) for u, w in words.items()}
    weights = {}
    for u, w in words.items():
        row = {int(k): n for k, n in problem["counts"].get(w, {}).items()}
        if not row.keys() <= domains[u] or any(
            type(n) is not int or n < 0 for n in row.values()
        ):
            raise ValueError("invalid historical sense counts")
        weights[u] = {
            x: Q(1 + row.get(x, 0), len(domains[u]) + sum(row.values()))
            for x in domains[u]
        }
    inquiry = RelationInquiry(
        domains,
        [tuple(e) for e in problem["edges"]],
        graph.relation,
        weights,
        problem.get("types"),
    )
    plan = inquiry.plan
    value = plan.root_value(4096)
    first, _ = plan.action(plan.counts, 0, limit=4096)
    result = {
        "expected": None if value is None else str(value),
        "first": None if first is None else inquiry.members[first][0],
    }
    if args.ask:
        with ZipFile(args.wordnet) as archive:
            raw = archive.read("wordnet/data.noun")

        def ask(u):
            print(u, words[u])
            for x in sorted(domains[u]):
                print(
                    x, raw[x : raw.index(b"\n", x)].split(b"|", 1)[1].decode().strip()
                )
            return int(input("sense offset: "))

        trace, answers, fallback = inquiry.execute(ask, limit=4096)
        result.update(
            asked=trace,
            relations=[[a, b, val] for (a, b), val in answers.items()],
            fallback_decisions=fallback,
        )
    print(json.dumps(result, indent=2))
