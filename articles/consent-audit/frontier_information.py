"""Compare exact block profiles and two scalar-rate completions with the measured full sense profiles."""

import argparse
from collections import Counter
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_plan import FrontierPlan
from block_query_plan import compile_blocks, marginal_profiles
from frontier_run import compile_task, inputs
from go_model_fetch import verify
from wordnet_paths import NounPaths


def with_rates(p, data, method):
    distributions = {}
    for i, u in enumerate(p.names):
        rates = {p.names[j]: r for j, r in p.rates[i].items()}
        if method == "independent":
            choices = {(): Q(1)}
            for v, r in rates.items():
                updated = {}
                for vs, m in choices.items():
                    if r:
                        updated[vs + (v,)] = m * r
                    if r != 1:
                        updated[vs] = m * (1 - r)
                choices = updated
        elif method == "nested":
            cuts = sorted({Q(0), Q(1), *rates.values()})
            choices = Counter()
            for lo, hi in zip(cuts, cuts[1:]):
                choices[tuple(v for v, r in rates.items() if r > lo)] += hi - lo
        else:
            raise ValueError("unknown completion")
        distributions[u] = list(choices.items())
    return FrontierPlan(
        data["multiplicities"], distributions, data["edges"], data["costs"]
    )


def actual_cost(model, truth):
    @lru_cache(None)
    def evaluate(counts, forced):
        i, _ = model.action(counts, forced)
        if i is None:
            return Q(0)
        nxt = tuple(n - int(j == i) for j, n in enumerate(counts))
        live = sum(1 << j for j, n in enumerate(nxt) if n)
        return truth.cost[i] + sum(
            p * evaluate(nxt, (forced | mask) & live) for mask, p in truth.groups[i]
        )

    value = evaluate(truth.counts, 0)
    evaluate.cache_clear()
    return value


def run(wordnet, folder, output):
    verify(wordnet, "3c68cd207844f071a5206f7fbed23e5c607ec02f")
    graph = NounPaths(wordnet)
    tasks = inputs()
    rows = []
    for line in (folder / "frontier-ledger.jsonl").read_bytes().splitlines():
        r = json.loads(line)
        key = r["source"], r["group"], r["sentence"]
        if r["expected_optimal"] is None:
            continue
        task = tasks[key]
        service = compile_task(graph, task)
        p = service.plan
        exact = Q(r["expected_optimal"])
        data = marginal_profiles(p)
        answer = {
            "source": key[0],
            "group": key[1],
            "sentence": key[2],
            "exact": str(exact),
            "gold": len(r["optimal"]),
        }
        for mode in ("block", "independent", "nested"):
            model = (
                compile_blocks(**data) if mode == "block" else with_rates(p, data, mode)
            )
            if mode == "block":
                answer["types_with_split_scopes"] = sum(
                    len(v) > 1 for v in data["profiles"].values()
                )
                answer["types_with_changed_cross_block_law"] = sum(
                    dict(a) != dict(b) for a, b in zip(p.groups, model.groups)
                )
            forecast = model.root_value()
            cost = actual_cost(model, p)
            assert cost >= exact
            remaining = list(p.counts)
            forced = 0
            known = {}
            while True:
                i, _ = model.action(tuple(remaining), forced)
                if i is None:
                    break
                u = service.members[i][p.counts[i] - remaining[i]]
                x = task["truth"][u]
                known[u] = x
                forced |= service.masks[u][x]
                remaining[i] -= 1
            assert all(
                service.service.answer(e, known)
                == graph.relation(*(task["truth"][u] for u in e))
                for e in task["edges"]
            )
            if mode == "block":
                assert forecast == cost == exact and set(known) == set(r["optimal"])
            answer[mode] = {
                "forecast": str(forecast),
                "actual_expected": str(cost),
                "queries": len(known),
            }
        rows.append(answer)
    result = {}
    for src in ("semcor", "wsd"):
        result[src] = {}
        for g in ("new", "previous"):
            rs = [r for r in rows if r["source"] == src and r["group"] == g]
            result[src][g] = {}
            for mode in ("block", "independent", "nested"):
                diffs = [Q(r[mode]["forecast"]) - Q(r["exact"]) for r in rs]
                loss = [Q(r[mode]["actual_expected"]) - Q(r["exact"]) for r in rs]
                result[src][g][mode] = {
                    "cases": len(rs),
                    "incorrect_forecast": sum(d != 0 for d in diffs),
                    "strict_expected_regret": sum(d > 0 for d in loss),
                    "summed_regret": str(sum(loss)),
                    "gold_queries": sum(r[mode]["queries"] for r in rs),
                    "exact_gold": sum(r["gold"] for r in rs),
                }
                if mode == "block":
                    result[src][g][mode].update(
                        sentences_with_split_scopes=sum(
                            bool(r["types_with_split_scopes"]) for r in rs
                        ),
                        sentences_replacing_cross_block_law=sum(
                            bool(r["types_with_changed_cross_block_law"]) for r in rs
                        ),
                    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "frontier-information-ledger.jsonl").write_bytes(
        ("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)).encode()
    )
    (output / "frontier-information-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("wordnet", type=Path)
    p.add_argument("frontier_audit", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.wordnet, a.frontier_audit, a.output), indent=2))
