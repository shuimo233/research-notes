"""Compile proofs into a finite decision service that accepts named fact withdrawals."""

import argparse
import json
from pathlib import Path


def make_package(queries):
    """queries yields (ID, fallback, alternative, record, lexical departure direction)."""
    queries = list(queries)
    retained = set()
    for _, _, _, rec, direction in queries:
        need = int(rec["depart_" + direction]["needed"], 16)
        retained.update(e for i, e in enumerate(rec["edges"]) if need >> i & 1)
    edges = sorted(retained)
    lookup = {e: i for i, e in enumerate(edges)}
    rules = []
    by_rule = {}
    items = {}
    for key, base, other, rec, direction in queries:
        if key in items or base == other:
            raise ValueError("need unique IDs and distinct output choices")

        def family(side):
            out = []
            for value in rec[side]:
                mask = int(value, 16)
                names = [e for i, e in enumerate(rec["edges"]) if mask >> i & 1]
                # A removed variable is fixed false: discard the entire proof that requires it.
                if all(e in lookup for e in names):
                    out.append(tuple(lookup[e] for e in names))
            return tuple(sorted(out))

        rule = family(direction), family("ba" if direction == "ab" else "ab")
        if rule not in by_rule:
            by_rule[rule] = len(rules)
            rules.append(rule)
        items[key] = [base, other, by_rule[rule]]
    return {"facts": edges, "rules": rules, "queries": items}


class DecisionService:
    def __init__(self, package):
        self.facts = package["facts"]
        self.index = {e: i for i, e in enumerate(self.facts)}
        self.queries = package["queries"]

        def mask(path):
            if any(type(i) is not int or not 0 <= i < len(self.facts) for i in path):
                raise ValueError("bad fact index")
            return sum(1 << i for i in set(path))

        self.rules = [
            (tuple(mask(p) for p in a), tuple(mask(p) for p in b)) for a, b in package["rules"]
        ]
        if len(self.index) != len(self.facts) or any(
            base == other or type(i) is not int or not 0 <= i < len(self.rules)
            for base, other, i in self.queries.values()
        ):
            raise ValueError("invalid decision package")

    def decide(self, key, withdrawn=()):
        base, other, index = self.queries[key]
        missing = sum(1 << self.index[e] for e in set(withdrawn) if e in self.index)
        proposals, blockers = self.rules[index]
        deviation = any(not p & missing for p in proposals) and not any(
            not q & missing for q in blockers
        )
        return other if deviation else base


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("query")
    parser.add_argument("--withdraw", nargs="*", default=[])
    a = parser.parse_args()
    svc = DecisionService(json.loads(a.package.read_bytes()))
    print(svc.decide(a.query, a.withdraw))
