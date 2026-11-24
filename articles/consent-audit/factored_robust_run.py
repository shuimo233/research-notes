"""Replay independently calibrated query modules and check exact whole-game bounds."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
import gzip
from itertools import product
import json
from math import prod
from pathlib import Path
from random import Random
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from factored_robust import ContextGame, FactoredPlan, partition
from frontier_inquiry import RelationInquiry
from frontier_plan import bits
from mandatory_reuse_run import pair_data


def independent_laws(service, laws):
    _, parts = partition(service)
    return {
        tuple(sorted(service.members[i][0] for i in bits(block))): [
            {service.members[i][0]: model[service.members[i][0]] for i in bits(block)}
            for model in laws
        ]
        for block, _ in parts
    }


def global_laws(known, parts):
    for choices in product(*(parts[names] for names in parts)):
        combined = dict(known)
        for law in choices:
            combined.update(law)
        yield combined


def global_witness(plan, known, local, answer):
    service = plan.service
    ordered = {
        part["component"]: local[part["component"]] for part in answer["components"]
    }
    scenarios = list(global_laws(known, ordered))
    dual = tuple(
        prod(combination)
        for combination in product(
            *(row["least_favorable"] for row in answer["components"])
        )
    )
    # scenario order is the component iteration order used by the controller.
    whole = ContextGame(service, scenarios)
    lower = whole.oracle_cost(dual) - sum(
        a * b for a, b in zip(dual, whole.budgets, strict=True)
    )
    worst = Q(0)
    for assignment, direct in zip(
        product(*(range(len(local[c["component"]])) for c in answer["components"])),
        whole.budgets,
        strict=True,
    ):
        true_value = sum(
            service.plan.cost[service.types_by_id[u]] for u in plan.sources
        )
        risk = Q(0)
        for z, (_, _, game), certificate in zip(
            assignment, plan.components, answer["components"], strict=True
        ):
            true_value += game.budgets[z]
            risk += certificate["risks"][z]
        assert true_value == direct
        worst = max(worst, risk)
    assert lower == worst == answer["regret"]
    return len(scenarios)


def hard_problem(k, exposure=Q(1, 4), uneven=False):
    pairs = [(f"a{i:02}", f"b{i:02}") for i in range(k)]
    domains = {u: tuple((u, x) for x in (0, 1)) for pair in pairs for u in pair}
    domains["u"] = tuple(("u", (h, t)) for h, t in product((0, 1), repeat=2))

    def label(lhs, rhs):
        a, x = lhs
        b, y = rhs
        if a != "u":
            return x & y
        h, t = x
        if uneven and b == pairs[1][0]:
            t = 1 - t
        return h ^ (t & y)

    def mode(u, p):
        return {(u, 0): 1 - p, (u, 1): p}

    known = {
        "u": {x: (exposure if x[1][1] else 1 - exposure) / 2 for x in domains["u"]}
    }
    local = {}
    for a, b in pairs:
        local[(a, b)] = [
            {a: mode(a, p), b: mode(b, 1 - p)} for p in (Q(1, 10), Q(9, 10))
        ]
    edges = [*pairs, *(("u", a) for a, _ in pairs)]
    first = {**known, **{u: r for ms in local.values() for u, r in ms[0].items()}}
    service = RelationInquiry(domains, edges, label, first)
    return service, known, local


def synthetic():
    rows = []
    for k in (2, 3, 4, 24):
        service, known, local = hard_problem(k)
        plan = FactoredPlan(service, local)
        answer = plan.solve()
        assert answer["regret"] == Q(3 * k, 10)
        count = global_witness(plan, known, local, answer) if k < 5 else 0
        truth = {u: svc[0] for u, svc in service.service.domains.items()}
        trace, labels = plan.execute(answer, truth.__getitem__, Random(849))
        assert len(trace) == k + 1
        assert labels == {
            e: service.service.answer(e, truth) for e in service.service.order
        }
        rows.append(
            dict(
                pairs=k,
                configurations=answer["scenario_count"],
                globally_verified=count,
                worst_regret=str(answer["regret"]),
                local_policy_cases=sum(
                    len(c["policies"]) for c in answer["components"]
                ),
                example_reads=len(trace),
            )
        )
    svc, known, parts = hard_problem(2, Q(1, 10), uneven=True)
    alternate = {x: (Q(9, 10) if x[1][1] else Q(1, 10)) / 2 for x in known["u"]}
    models = []
    for prefix in (known, {"u": alternate}):
        models.extend(global_laws(prefix, parts))
    exact = ContextGame(svc, models).solve()
    assert exact["regret"] == Q(2, 5)
    result = dict(
        known_prefix=rows,
        unknown_prefix={
            "scenarios": len(models),
            "global": str(exact["regret"]),
            "duplicated_local_upper": str(2 * Q(9, 10) * Q(2, 5)),
        },
    )
    return result


def run(snapshot, wordnet, semcor, out):
    data = defaultdict(Counter)
    rng = Random(2343)
    rows = []
    audit = []

    for key, old, new, truth, laws in pair_data(snapshot, wordnet, semcor):
        local = independent_laws(old, laws)
        plan = FactoredPlan(old, local)
        result = plan.solve()
        known = {u: laws[0][u] for u in plan.sources}
        with_edges = sum(
            any(game.service.plan.neighbors) for _, _, game in plan.components
        )
        configs = result["scenario_count"]
        n_global = 0
        if with_edges >= 2 and configs <= 8:
            n_global = global_witness(plan, known, local, result)
        trace, labels = plan.execute(result, truth.__getitem__, rng)
        assert labels == {e: old.service.answer(e, truth) for e in old.service.order}
        for s in (key[0], "total"):
            d = data[s]
            d["tasks"] += 1
            d["nonzero_robust_regret"] += result["regret"] > 0
            d["split_nontrivial"] += with_edges >= 2
            d["split_nontrivial_checked_globally"] += n_global > 0
            d["global_configurations_checked"] += n_global
            d["compulsory_tasks"] += bool(plan.sources)
            d["queries"] += len(trace)
            d["sum_regret"] += float(result["regret"])
        if result["regret"] > 0 and len(audit) < 24:
            audit.append((key, plan, result, truth))
        rows.append(
            dict(
                task=key,
                trace=trace,
                labels=list(labels.items()),
                nontrivial_components=with_edges,
                checked_globally=n_global,
                compulsory=plan.sources,
                **result,
            )
        )
    result = dict(by_source=data, synthetic=synthetic())
    for c in data.values():
        c["sum_regret"] = round(c["sum_regret"], 9)
    if audit:
        rng = Random(621)
        read_total = 0
        for key, plan, cert, truth in audit:
            path, labels = plan.execute(cert, truth.__getitem__, rng)
            assert labels == {
                e: plan.service.service.answer(e, truth)
                for e in plan.service.service.order
            }
            read_total += len(path)
        result["natural_batch"] = dict(
            independently_calibrated_tasks=len(audit),
            global_configurations=prod(
                cert["scenario_count"] for _, _, cert, _ in audit
            ),
            nonzero_local_games=sum(
                part["regret"] > 0
                for _, _, cert, _ in audit
                for part in cert["components"]
            ),
            distinct_distributions=prod(
                len(
                    {
                        tuple(
                            tuple(sorted(laws[z].items()))
                            for laws in game.conditional.values()
                        )
                        for z in range(len(game.modes))
                    }
                )
                for _, plan, _, _ in audit
                for _, _, game in plan.components
            ),
            worst_regret=str(sum(cert["regret"] for _, _, cert, _ in audit)),
            verified_real_traces=len(audit),
            actual_queries=read_total,
        )
    out.mkdir(parents=True, exist_ok=False)
    (out / "factored-robust-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    ledger = "".join(
        json.dumps(r, default=str, separators=(",", ":")) + "\n" for r in rows
    )
    (out / "factored-robust-ledger.jsonl.gz").write_bytes(
        gzip.compress(ledger.encode(), mtime=0)
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "wordnet", "semcor", "output"):
        p.add_argument(name, type=Path)
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.snapshot, a.wordnet, a.semcor, a.output), indent=2))
