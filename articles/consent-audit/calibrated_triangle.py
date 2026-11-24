"""Run strict, frequency-weighted three-word clarification using a deterministic minimax first batch."""

import argparse
from fractions import Fraction as Q
from itertools import combinations
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from shared_sense import SharedInquiry
from wordnet_paths import NounPaths


class TriangleInquiry:
    """Counts are nonnegative observations for the exact candidate senses. Omitted senses have zero count."""

    def __init__(self, graph, counts):
        self.names = tuple(sorted(counts))
        if len(self.names) != 3:
            raise ValueError("supply three different noun lemmas")
        domains = {u: graph.senses(u) for u in self.names}
        if any(len(d) < 2 for d in domains.values()):
            raise ValueError("each word requires at least two senses")
        masses = {}
        for u, d in domains.items():
            row = {int(k): n for k, n in counts[u].items()}
            if (
                len(row) != len(counts[u])
                or not row.keys() <= d
                or any(type(n) is not int or n < 0 for n in row.values())
            ):
                raise ValueError(
                    "counts require distinct valid sense offsets and nonnegative integers"
                )
            total = len(d) + sum(row.values())
            masses[u] = {x: Q(1 + row.get(x, 0), total) for x in d}
        self.service = SharedInquiry(
            domains, combinations(self.names, 2), graph.relation
        )
        if any(t.constant is not None for t in self.service.tables.values()):
            raise ValueError("all three relation tables must be nonconstant")
        risk = {}
        for v in self.names:
            forced = Q(0)
            for u in self.names:
                if u == v:
                    continue
                edge = tuple(sorted((u, v)))
                forced += sum(
                    p
                    for x, p in masses[u].items()
                    if self.service.answer(edge, {u: x}) is None
                )
            risk[v] = 2 + min(Q(1), forced)
        self.omit = min(self.names, key=lambda u: (risk[u], u))
        self.worst_cost = risk[self.omit]

    def execute(self, ask, omit=None, *, known=None):
        """Ask for missing senses only. known maps this task's lemmas to previously revealed offsets."""
        omit = self.omit if omit is None else omit
        if omit not in self.names:
            raise ValueError("invalid deferred word")
        observed = dict(known) if known is not None else {}
        if any(
            u not in self.service.domains or x not in self.service.domains[u]
            for u, x in observed.items()
        ):
            raise ValueError("invalid known sense")
        batches = []

        def reveal(batch):
            response = ask(tuple(batch))
            if set(response) != set(batch) or any(
                v not in self.service.domains[u] for u, v in response.items()
            ):
                raise ValueError("answer each requested ID with a valid sense offset")
            batches.append(list(batch))
            observed.update(response)

        pending_vertices = {u for e in self.service.pending(observed) for u in e}
        first = [
            u
            for u in self.names
            if u != omit and u in pending_vertices and u not in observed
        ]
        if first:
            reveal(first)
        if self.service.pending(observed):
            reveal([omit])
        return {
            "batches": batches,
            "relations": [
                [u, v, self.service.answer((u, v), observed)]
                for u, v in self.service.order
            ],
        }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument(
        "counts", type=Path, help="JSON object of lemma to sense offset to past count"
    )
    p.add_argument(
        "--ask",
        action="store_true",
        help="prompt for senses and return all three relations",
    )
    a = p.parse_args()
    counts = json.loads(a.counts.read_bytes())
    inquiry = TriangleInquiry(NounPaths(a.wordnet), counts)
    result = {
        "first_batch": [u for u in inquiry.names if u != inquiry.omit],
        "defer": inquiry.omit,
        "worst_expected_questions": str(inquiry.worst_cost),
    }
    if a.ask:
        with ZipFile(a.wordnet) as z:
            raw = z.read("wordnet/data.noun")

        def ask(batch):
            ans = {}
            for u in batch:
                print(u)
                for x in inquiry.service.domains[u]:
                    end = raw.index(b"\n", x)
                    print(x, raw[x:end].split(b"|", 1)[1].decode("utf8").strip())
                ans[u] = int(input("sense offset: "))
            return ans

        result.update(inquiry.execute(ask))
    print(json.dumps(result, indent=2))
