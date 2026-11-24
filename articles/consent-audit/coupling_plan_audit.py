"""Compare upper-bound witnesses and optimize deterministic strict first-stage plans."""

import argparse
from collections import Counter
from fractions import Fraction as Q
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from cover_dependence import footprints, audit
from coupling_clock import certificate
from coalesced_forest_budget import bounds as coalesced_bounds
from certified_cover_plan import minimal_covers, plan
from forest_cover_budget import forest_bounds
from go_model_fetch import verify
from wordnet_paths import NounPaths


def observed_cost(graph, row, cover):
    outside = set()
    truth = row["truth"]
    words = row["words"]
    for u, v, _ in row["queries"]:
        if u not in cover:
            u, v = v, u
        if (
            u in cover
            and v not in cover
            and len({graph.relation(truth[u], s) for s in graph.senses(words[v])}) > 1
        ):
            outside.add(v)
    return len(cover) + len(outside)


def evaluate(graph, row):
    words = row["words"]
    edges = [
        (u, v)
        for u, v, _ in row["queries"]
        if len(
            {
                graph.relation(x, y)
                for x in graph.senses(words[u])
                for y in graph.senses(words[v])
            }
        )
        > 1
    ]
    plans = []
    for cover in minimal_covers(words, edges):
        groups = footprints(graph, {**row, "cover_first_stage": cover})
        lp = audit(groups)
        upper, lower = (certificate(groups, q) for q in ("upper", "lower"))
        if upper["status"] == "witness" and Q(upper["local"]) != Q(
            lp["maximum"]["extra"]
        ):
            raise AssertionError("invalid upper witness")
        if lower["status"] == "witness" and Q(lower["local"]) != Q(
            lp["minimum"]["extra"]
        ):
            raise AssertionError("invalid lower witness")
        forest = forest_bounds(groups) is not None
        merged = coalesced_bounds(groups)
        if merged and (
            Q(merged["minimum_extra"]) != Q(lp["minimum"]["extra"])
            or Q(merged["maximum_extra"]) != Q(lp["maximum"]["extra"])
        ):
            raise AssertionError("coalesced forest disagrees with joint optimizer")
        plans.append(
            {
                "cover": cover,
                "forest": forest,
                "posthoc_coalesced": merged,
                "upper_clock": upper,
                "lower_clock": lower,
                "observed": observed_cost(graph, row, set(cover)),
                **lp,
            }
        )

    def rank(p, k):
        return (
            Q(p[k]["extra"] if k == "maximum" else p[k]) + len(p["cover"]),
            len(p["cover"]),
            p["cover"],
        )

    chosen = {
        k: min(range(len(plans)), key=lambda j: rank(plans[j], k))
        for k in ("independent", "local_upper", "maximum")
    }
    chosen["original"] = next(
        j for j, p in enumerate(plans) if list(p["cover"]) == row["cover_first_stage"]
    )
    selected = plans[chosen["local_upper"]]
    ub = rank(selected, "local_upper")[0]

    def certifiable(include_forest):
        return all(
            ub
            <= rank(
                p,
                "local_upper"
                if p["upper_clock"]["status"] == "witness"
                or include_forest
                and p["forest"]
                else "independent",
            )[0]
            for p in plans
            if p is not selected
        )

    independent_only = all(
        ub <= rank(p, "independent")[0] for p in plans if p is not selected
    )
    full = {}
    for u, w in words.items():
        neighbors = {v for e in edges if u in e for v in e if v != u}
        senses = graph.senses(w)
        full[u] = [
            (
                tuple(
                    v
                    for v in sorted(neighbors)
                    if len({graph.relation(x, y) for y in graph.senses(words[v])}) > 1
                ),
                Q(1, len(senses)),
            )
            for x in sorted(senses)
        ]
    deployed = plan(full)
    if deployed["cover"] != list(selected["cover"]) or deployed[
        "certified_optimal"
    ] != certifiable(True):
        raise AssertionError("standalone plan disagrees with portfolio")
    return {
        "source": row["source"],
        "sentence": row["sentence"],
        "chosen": chosen,
        "planner": deployed,
        "independence_proves_optimal": independent_only,
        "forest_proves_optimal": all(
            ub <= rank(p, "local_upper" if p["forest"] else "independent")[0]
            for p in plans
            if p is not selected
        ),
        "clock_proves_optimal": certifiable(False),
        "forest_or_clock_proves_optimal": certifiable(True),
        "plans": plans,
    }


def summarize(rows):
    fixed = [r["plans"][r["chosen"]["original"]] for r in rows]
    portfolio = [p for r in rows for p in r["plans"]]

    def description(ps):
        missing = [p for p in ps if not p["forest"]]
        return {
            "plans": len(ps),
            "forest": len(ps) - len(missing),
            "posthoc_coalesced_exact": sum(
                p["posthoc_coalesced"] is not None for p in ps
            ),
            "posthoc_coalesced_or_clock_upper": sum(
                p["posthoc_coalesced"] is not None
                or p["upper_clock"]["status"] == "witness"
                for p in ps
            ),
            "upper_status": dict(Counter(p["upper_clock"]["status"] for p in ps)),
            "lower_status": dict(Counter(p["lower_clock"]["status"] for p in ps)),
            "upper_added_to_forest": sum(
                p["upper_clock"]["status"] == "witness" for p in missing
            ),
            "both_added_to_forest": sum(
                p["upper_clock"]["status"] == p["lower_clock"]["status"] == "witness"
                for p in missing
            ),
            "upper_genuinely_loose": sum(
                Q(p["local_upper"]) > Q(p["maximum"]["extra"]) for p in ps
            ),
            "lower_genuinely_loose": sum(
                Q(p["lower_clock"]["local"]) < Q(p["minimum"]["extra"]) for p in ps
            ),
        }

    comparisons = {}
    for k in ("original", "independent", "local_upper", "maximum"):
        selections = [r["plans"][r["chosen"][k]] for r in rows]

        def worst(p):
            return len(p["cover"]) + Q(p["maximum"]["extra"])

        comparisons[k] = {
            "sum_worst_expectation": str(sum(map(worst, selections))),
            "actual_reveals": sum(p["observed"] for p in selections),
            "attains_optimum": sum(
                worst(p) == worst(r["plans"][r["chosen"]["maximum"]])
                for p, r in zip(selections, rows)
            ),
        }
    return {
        "sentences": len(rows),
        "fixed": description(fixed),
        "all_plans": description(portfolio),
        "choice": comparisons,
        "optimality_certified_independence_only": sum(
            r["independence_proves_optimal"] for r in rows
        ),
        "optimality_certified_clock": sum(r["clock_proves_optimal"] for r in rows),
        "optimality_certified_forest": sum(r["forest_proves_optimal"] for r in rows),
        "optimality_certified_forest_or_clock": sum(
            r["forest_or_clock_proves_optimal"] for r in rows
        ),
    }


def run(archive, destination):
    verify(archive, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(archive)
    rows = [
        evaluate(graph, row)
        for l in (ROOT / "shared-sense-ledger.jsonl").read_bytes().splitlines()
        if (row := json.loads(l))["shared"]
    ]
    result = {
        s: summarize([r for r in rows if r["source"] == s]) for s in ("wsd", "semcor")
    }
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "coupling-witness-ledger.jsonl").open(
        "x", encoding="utf8", newline="\n"
    ) as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    (destination / "coupling-witness-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("new_directory", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.new_directory), indent=2))
