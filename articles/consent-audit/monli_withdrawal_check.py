"""Independently check row-withdrawal guarantees with raw annotations, reachability, and exhaustive pairs."""

import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monli_package import POSITIVE_BLOB, load_package
from go_model_fetch import verify
from monli_preserver import queries_from_ledger
from monli_withdrawal import WithdrawalAudit, withdraw


def active_mask(edges, queries, contract):
    graph = defaultdict(list)
    for x, y in edges:
        graph[x].append(y)
    closure = {}

    def walk(node):
        if node not in closure:
            reach = set(graph[node])
            for n in graph[node]:
                reach.update(walk(n))
            closure[node] = reach
        return closure[node]

    mask = 0
    for idx, (x, y, fallback) in enumerate(queries):
        direction = "reverse" if y in walk(x) else ("forward" if x in walk(y) else None)
        if direction and (contract == "coverage" or direction != fallback):
            mask |= 1 << idx
    return mask


def state(groups, queries, contract):
    # Removing one whole lexical edge exposes exactly the queries depending on it.
    # On unique-path workloads the loss caused by several disabled edges is their bitwise union.
    keys = set(groups)
    base = active_mask(keys, queries, contract)
    effect = {edge: base ^ active_mask(keys - {edge}, queries, contract) for edge in keys}
    single = defaultdict(int)
    double = defaultdict(int)
    for e, lines in groups.items():
        if len(lines) == 1:
            single[lines[0]] |= effect[e]
        elif len(lines) == 2:
            double[tuple(sorted(lines))] |= effect[e]
    return base, single, double, effect


def check(source, ledger):
    verify(source, POSITIVE_BLOB)
    rows = [json.loads(line) for line in source.read_bytes().splitlines()]
    qs = queries_from_ledger(ledger)
    groups = defaultdict(list)
    for i, r in enumerate(rows, 1):
        if r["gold_label"] == "entailment":
            groups[r["sentence1_lex"].casefold(), r["sentence2_lex"].casefold()].append(i)
    ids = sorted(v for g in groups.values() for v in g)
    result = {}
    for contract in ("answers", "coverage"):
        base, single, double, effect = state(groups, qs, contract)
        necessary = {k for k, v in effect.items() if v}
        cert = WithdrawalAudit(rows, qs, contract == "coverage")
        assert {cert.terms[i] for i in cert.witness} == necessary
        cases = {}
        for budget in (0, 1, 2):
            kept = set(cert.smallest(budget))
            selected = {
                e: [i for i in g if i in kept] for e, g in groups.items() if kept.intersection(g)
            }
            start, drop1, drop2, _ = state(selected, qs, contract)
            assert base == start
            # Independent lower bound: omitting a lexical edge changes the output even without withdrawals;
            # if an individual required edge retains fewer than min(s,r+1), dropping its retained rows suffices.
            assert len(kept) == sum(min(budget + 1, len(groups[e])) for e in necessary)
            bad1 = sum(single[i] != drop1[i] for i in ids)
            bad2 = 0
            for i, j in combinations(ids, 2):
                if (single[i] | single[j] | double.get((i, j), 0)) != (
                    drop1[i] | drop1[j] | drop2.get((i, j), 0)
                ):
                    bad2 += 1
            if budget >= 1:
                assert bad1 == 0
            if budget >= 2:
                assert bad2 == 0
            witness = cert.first_failure(kept)
            if witness:
                lost = set(witness["remove_lines"])

                def remain(g):
                    return {e for e, lines in g.items() if set(lines) - lost}

                changed = active_mask(remain(groups), qs, contract) ^ active_mask(
                    remain(selected), qs, contract
                )
                assert changed
            else:
                assert all(set(selected[e]) == set(groups[e]) for e in necessary)
            if contract == "answers" and budget == 1:
                packed = cert.pack(budget)
                after = withdraw(packed, [62])
                assert load_package(after).edges["granny"]["woman"] == 290
                assert withdraw(after, [62]) == after
                both = withdraw(after, [290])
                assert both == withdraw(packed, [290, 62])
                assert "woman" not in load_package(both).edges.get("granny", {})
            cases[str(budget)] = {
                "selected_rows": len(kept),
                "mismatching_single_withdrawals": bad1,
                "mismatching_double_withdrawals": bad2,
            }
        result[contract] = cases
    return {
        "positive_rows": len(ids),
        "single_withdrawals_checked_per_package": len(ids),
        "double_withdrawals_checked_per_package": len(ids) * (len(ids) - 1) // 2,
        "packages": result,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("positive", type=Path)
    p.add_argument("ledger", type=Path)
    a = p.parse_args()
    print(json.dumps(check(a.positive, a.ledger), indent=2))
