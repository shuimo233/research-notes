"""Evaluate whole-sentence plans on the frozen natural word-sense comparison tasks."""

import argparse
from collections import defaultdict
from fractions import Fraction as Q
from itertools import combinations
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_inquiry import RelationInquiry
from go_model_fetch import verify
from wordnet_paths import NounPaths


def lines(name):
    return [json.loads(l) for l in (ROOT / name).read_bytes().splitlines()]


def inputs():
    fits = lines("heldout-triangle-plans.jsonl")
    sentences = defaultdict(
        lambda: {"words": {}, "truth": {}, "counts": {}, "edges": set()}
    )
    for r, f in zip(
        lines("natural-triangle-cases.jsonl"),
        lines("heldout-triangle-cases.jsonl"),
        strict=True,
    ):
        k = (r["source"], r["group"], r["sentence"])
        task = sentences[k]
        assert r["ids"] == f["ids"] and r["sentence"] == f["sentence"]
        training = fits[f["context"]]["training"]
        for u, w, x in zip(r["ids"], r["words"], r["truth"]):
            found_word = task["words"].setdefault(u, w)
            found_truth = task["truth"].setdefault(u, x)
            counts = task["counts"].setdefault(w, training[w])
            if (found_word, found_truth, counts) != (w, x, training[w]):
                raise ValueError("inconsistent occurrence or training counts")
        task["edges"].update(tuple(sorted(e)) for e in combinations(r["ids"], 2))
    return sentences


def compile_task(graph, task):
    domains = {u: graph.senses(w) for u, w in task["words"].items()}
    weights = {}
    for u, w in task["words"].items():
        counts = task["counts"][w]
        weights[u] = {
            x: Q(1 + counts[str(x)], len(counts) + sum(counts.values()))
            for x in domains[u]
        }
    return RelationInquiry(
        domains, sorted(task["edges"]), graph.relation, weights, task["words"]
    )


def run(wordnet, output):
    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(wordnet)
    baseline = {
        (r["source"], r["group"], r["sentence"]): len(r["forward"]["fitted"])
        for r in lines("cached-triangle-ledger.jsonl")
    }
    rows = []
    for (src, group, sent), task in sorted(inputs().items()):
        svc = compile_task(graph, task)
        p = svc.plan
        exact = p.root_value(limit=4096)
        fixed = p.fixed_cover()[1]
        assert exact is None or exact <= fixed
        truth = task["truth"]
        correct = {e: graph.relation(truth[e[0]], truth[e[1]]) for e in task["edges"]}
        oracle = svc.service.certificate(truth)
        row = {
            "source": src,
            "group": group,
            "sentence": sent,
            "positions": len(truth),
            "edges": len(correct),
            "classes": len(p.names),
            "cached": baseline.pop((src, group, sent)),
            "oracle": oracle,
            "expected_fixed": str(fixed),
            "expected_optimal": None if exact is None else str(exact),
        }
        for mode in ("fixed", "greedy", "optimal"):
            path, answers, fallback = svc.execute(truth.__getitem__, mode, limit=4096)
            assert answers == correct and len(path) >= len(oracle)
            row[mode] = path
            if mode == "optimal":
                row["fallback_decisions"] = fallback
        row["states"] = p.optimum.cache_info().currsize
        rows.append(row)
    assert not baseline
    report = {}
    for src in ("semcor", "wsd"):
        report[src] = {}
        for group in ("new", "previous"):
            rs = [r for r in rows if r["source"] == src and r["group"] == group]
            ex = [r for r in rs if r["expected_optimal"] is not None]
            sums = {
                k: sum(len(r[k]) for r in rs)
                for k in ("optimal", "fixed", "greedy", "oracle")
            }
            cached = sum(r["cached"] for r in rs)
            report[src][group] = {
                "sentences": len(rs),
                "certified_roots": len(ex),
                "observed_fallback_sentences": sum(
                    bool(r["fallback_decisions"]) for r in rs
                ),
                "expected_fixed_on_certified": str(
                    sum(Q(r["expected_fixed"]) for r in ex)
                ),
                "expected_optimal_on_certified": str(
                    sum(Q(r["expected_optimal"]) for r in ex)
                ),
                "strict_model_advantage_over_fixed": sum(
                    Q(r["expected_optimal"]) < Q(r["expected_fixed"]) for r in ex
                ),
                "realized_cached": cached,
                **sums,
                "realized_versus_cached": {
                    label: sum((len(r["optimal"]) - r["cached"]) * sign > 0 for r in rs)
                    for label, sign in (("fewer", -1), ("more", 1))
                },
                "maximum_states": max((r["states"] for r in rs), default=0),
                "primary_gate": bool(rs)
                and sums["optimal"] <= Q(99, 100) * cached
                and sums["optimal"] < sums["greedy"],
            }
    output.mkdir(parents=True, exist_ok=False)
    (output / "frontier-ledger.jsonl").write_bytes(
        ("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)).encode()
    )
    (output / "frontier-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.output), indent=2))
