"""Certify source-row withdrawal tolerance for a fixed workload with unique evidence paths."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from go_model_fetch import verify
from monli_package import POSITIVE_BLOB, load_package
from monli_preserver import queries_from_ledger, requirements
from monli_scope import LexicalEvidence, changed_terms


class WithdrawalAudit:
    def __init__(self, positive, queries, coverage=False):
        positive = list(positive)
        union = LexicalEvidence(positive)
        demand = requirements(union.edges, queries)
        self.origins = defaultdict(list)
        self.terms = {}
        for line, r in enumerate(positive, 1):
            if r["gold_label"] == "entailment":
                pair = changed_terms(r["sentence1"], r["sentence2"])
                if pair is not None:
                    first = union.edges[pair[0]][pair[1]]
                    self.origins[first].append(line)
                    self.terms[line] = pair
        self.witness = {}
        for relation, (routes, _, required) in demand.items():
            if coverage or required:
                if len(routes) != 1:
                    raise ValueError(
                        "withdrawal certificate requires a unique path for each protected relation"
                    )
                for edge in routes[0]:
                    self.witness.setdefault(edge, relation)

    def smallest(self, budget):
        if budget is not None and (type(budget) is not int or budget < 0):
            raise ValueError("withdrawal budget must be a nonnegative integer or None")
        return sorted(
            line
            for edge in self.witness
            for line in (self.origins[edge] if budget is None else self.origins[edge][: budget + 1])
        )

    def first_failure(self, selected):
        selected = set(selected)
        if not selected <= self.terms.keys():
            raise ValueError("unknown usable positive source row")
        choices = []
        for edge, relation in self.witness.items():
            all_support = set(self.origins[edge])
            kept = selected & all_support
            if kept != all_support:
                choices.append((len(kept), sorted(kept), relation, min(all_support - kept)))
        if not choices:
            return None
        cost, removed, relation, still_valid = min(choices)
        return {
            "withdrawals": cost,
            "remove_lines": removed,
            "positive_relation": relation,
            "surviving_full_source": still_valid,
        }

    def pack(self, budget):
        selected = self.smallest(budget)
        return {
            "positive_git_blob": POSITIVE_BLOB,
            "edges": [[line, *self.terms[line]] for line in selected],
        }


def withdraw(package, removed):
    """Return remaining raw supports, so future withdrawals can compose with this one."""
    load_package(package)
    removed = set(removed)
    if any(type(i) is not int or i < 1 for i in removed):
        raise ValueError("withdrawals require 1-based integer source rows")
    return {
        "positive_git_blob": POSITIVE_BLOB,
        "edges": [e for e in package["edges"] if e[0] not in removed],
    }


def inputs(source, ledger):
    verify(source, POSITIVE_BLOB)
    return [json.loads(v) for v in source.read_bytes().splitlines()], queries_from_ledger(ledger)


def report(source, ledger):
    positive, queries = inputs(source, ledger)
    out = {}
    for name in ("answers", "evidence_coverage"):
        audit = WithdrawalAudit(positive, queries, name == "evidence_coverage")
        results = {}
        for budget in (0, 1, 2, None):
            selected = audit.smallest(budget)
            results["any" if budget is None else str(budget)] = {
                "min_source_rows": len(selected),
                "first_possible_failure": audit.first_failure(selected),
            }
        out[name] = {
            "required_edges": len(audit.witness),
            "positive_rows_per_required_edge": dict(
                sorted(Counter(len(audit.origins[i]) for i in audit.witness).items())
            ),
            "budgets": results,
        }
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    cmds = p.add_subparsers(dest="cmd", required=True)
    for name in ("report", "build"):
        sub = cmds.add_parser(name)
        sub.add_argument("positive", type=Path)
        sub.add_argument("ledger", type=Path)
        if name == "build":
            sub.add_argument("contract", choices=("answers", "evidence_coverage"))
            sub.add_argument("budget", help="nonnegative integer, or any")
            sub.add_argument("output", type=Path)
    sub = cmds.add_parser("withdraw")
    sub.add_argument("package", type=Path)
    sub.add_argument("output", type=Path)
    sub.add_argument("lines", type=int, nargs="*")
    a = p.parse_args()
    if a.cmd == "report":
        print(json.dumps(report(a.positive, a.ledger), indent=2))
    else:
        if a.cmd == "build":
            data, questions = inputs(a.positive, a.ledger)
            audit = WithdrawalAudit(data, questions, a.contract == "evidence_coverage")
            obj = audit.pack(None if a.budget == "any" else int(a.budget))
        else:
            obj = withdraw(json.loads(a.package.read_bytes()), a.lines)
        with a.output.open("x", encoding="utf8", newline="\n") as f:
            f.write(json.dumps(obj, indent=2) + "\n")
