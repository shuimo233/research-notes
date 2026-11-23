"""Execute the compressed runtime and quantify transfer beyond its compiled question list."""

import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monli_package import FrozenComparator, for_budget, load_package, package
from monli_preserver import optimal_frontier, requirements
from monli_scope import LexicalEvidence, decide_downward_pair
from monli_scope_run import read_source


def replay(data, model, ledger, frontier, example):
    source = data / "pmonli.jsonl"
    all_edges = LexicalEvidence(read_source(data, "pmonli")).edges
    with ledger.open(encoding="utf8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    raw = {s: read_source(data, s) for s in ("nmonli_train", "nmonli_test")}
    endpoints = {}
    calc = FrozenComparator(model)
    for budget in (23, 64, 192):
        obj = for_budget(source, frontier, budget)
        if budget == 23:
            assert obj == json.loads(example.read_bytes())
        graph = load_package(obj)
        before = calc.calls
        covered = correct = 0
        for r in rows:
            original = raw[r["subset"]][int(r["ab_line"]) - 1]
            response = decide_downward_pair(original["sentence1"], original["sentence2"], graph, calc)
            assert response.direction == r["evidence_first"]
            covered += response.basis == "evidence"
            correct += response.direction == r["gold"]
        calls = calc.calls - before
        assert calls == 2 * (len(rows) - covered)
        endpoints[str(budget)] = {
            "same_directions": len(rows),
            "correct": correct,
            "grounded": covered,
            "measured_model_calls": calls,
        }
    transfer = {}
    for s in raw:
        subset = [r for r in rows if r["subset"] == s]
        qs = [(r["a_term"], r["b_term"], r["invert_affirmative"]) for r in subset]
        profile, _ = optimal_frontier(requirements(all_edges, qs))
        budget = min(profile)
        graph = load_package(package(source, profile[budget][1]))
        held = [r for r in rows if r["subset"] != s]
        changed = grounded = 0
        for r in held:
            original = raw[r["subset"]][int(r["ab_line"]) - 1]
            proof = graph.downward(original["sentence1"], original["sentence2"])
            actual = proof.direction if proof else r["invert_affirmative"]
            changed += actual != r["evidence_first"]
            grounded += proof is not None
        transfer[s] = {
            "compiled_pairs": len(subset),
            "selected": budget,
            "other_cohort_pairs": len(held),
            "different_from_full_on_other_cohort": changed,
            "grounded_on_other_cohort": grounded,
        }
    return {"deployed_packages": endpoints, "cross_cohort": transfer}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "ledger", "frontier", "example"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    print(json.dumps(replay(a.data, a.model, a.ledger, a.frontier, a.example), indent=2))
