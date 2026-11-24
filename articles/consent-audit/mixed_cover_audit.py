"""Evaluate the preregistered private-randomization comparison on the frozen shared-sense tasks."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from coupling_clock import canonical
from forest_cover_budget import forest_bounds
from go_model_fetch import verify
from mixed_sense_game import solve
from wordnet_paths import NounPaths


def read_rows(name):
    return (json.loads(line) for line in (ROOT / name).read_bytes().splitlines())


def evaluate(graph, task, previous):
    words = task["words"]
    neighbors = {u: set() for u in words}
    for u, v, _ in task["queries"]:
        neighbors[u].add(v)
        neighbors[v].add(u)
    groups = {}
    observed = set()
    for u, word in words.items():
        weights = Counter()
        senses = graph.senses(word)
        for sense in senses:
            targets = tuple(
                v
                for v in sorted(neighbors[u])
                if len({graph.relation(sense, y) for y in graph.senses(words[v])}) > 1
            )
            weights[targets] += Q(1, len(senses))
            if sense == task["truth"][u]:
                observed.update(targets)
        groups[u] = list(weights.items())
    groups = canonical(groups)
    plans = previous["plans"]
    pure = plans[previous["chosen"]["maximum"]]
    game = solve(groups, pure["cover"])
    assert game["covers"] == len(plans)
    baseline = len(pure["cover"]) + Q(pure["maximum"]["extra"])
    value = Q(game["value"])
    independent = min(len(p["cover"]) + Q(p["independent"]) for p in plans)
    assert independent <= value <= baseline
    forest = forest_bounds(groups) is not None
    if forest:
        assert (
            value
            == baseline
            == min(len(p["cover"]) + Q(p["local_upper"]) for p in plans)
        )
    realized = sum(Q(mass) * len(observed.union(c)) for c, mass in game["mixture"])
    assert len(observed.union(pure["cover"])) == pure["observed"]
    return {
        "source": task["source"],
        "sentence": task["sentence"],
        "pure": str(baseline),
        "pure_cover": pure["cover"],
        "independent": str(independent),
        "forest": forest,
        "observed": str(realized),
        "pure_observed": pure["observed"],
        **game,
    }


def summary(rows):
    def total(field):
        return str(sum(Q(r[field]) for r in rows))

    return {
        "sentences": len(rows),
        "covers": sum(r["covers"] for r in rows),
        "joint_categories_checked": sum(r["world_count"] for r in rows),
        "largest_joint_space": max(r["world_count"] for r in rows),
        "strict_improvements": sum(Q(r["value"]) < Q(r["pure"]) for r in rows),
        "independent_bound_tight": sum(r["value"] == r["independent"] for r in rows),
        "full_forest": sum(r["forest"] for r in rows),
        "pure_worst": total("pure"),
        "mixed_worst": total("value"),
        "independent_optimum": total("independent"),
        "gold_pure": total("pure_observed"),
        "gold_mixed": total("observed"),
    }


def run(archive, destination):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    previous = {
        (r["source"], r["sentence"]): r
        for r in read_rows("coupling-witness-ledger.jsonl")
    }
    rows = [
        evaluate(graph, t, previous.pop((t["source"], t["sentence"])))
        for t in read_rows("shared-sense-ledger.jsonl")
        if t["shared"]
    ]
    assert not previous
    report = {
        s: summary([r for r in rows if r["source"] == s]) for s in ("wsd", "semcor")
    }
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "mixed-cover-ledger.jsonl").write_bytes(
        ("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)).encode()
    )
    (destination / "mixed-cover-results.json").write_bytes(
        (json.dumps(report, indent=2) + "\n").encode()
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("new_directory", type=Path)
    args = p.parse_args()
    print(json.dumps(run(args.wordnet, args.new_directory), indent=2))
