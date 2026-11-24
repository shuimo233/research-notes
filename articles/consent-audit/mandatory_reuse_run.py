"""Replay forced-set removal and measure batched exact planning on the frozen tasks."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
import gzip
import json
from pathlib import Path
import sys
from time import process_time_ns

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from batched_query_plan import batched
from frontier_plan import FrontierPlan
from frontier_information import actual_cost
from prior_reuse import mandatory_first_regret_bound, transfer_bound
from prior_reuse_run import temperatures, word_prior_pair, word_tasks


def hard_graph(k, eps=Q(1, 100)):
    mandatory = [f"m{j:02}" for j in range(k)]
    optional = [f"z{j:02}" for j in range(k)]
    choices = {}
    for u, v in zip(mandatory, optional):
        others = [x for x in optional if x != v]
        choices[u] = [
            (targets, p / 2)
            for p, extras in [(1 - eps, []), (eps, others)]
            for targets in [extras, [*extras, v]]
        ]
        choices[v] = [(mandatory, Q(1))]
    return FrontierPlan(
        dict.fromkeys(mandatory + optional, 1),
        choices,
        [(u, v) for u in mandatory for v in optional],
    )


def synthetic():
    out = []
    for k in (4, 6, 8, 10, 40):
        old = hard_graph(k)
        model = batched(old)
        expected = Q(2 * k) - Q(k, 2) * Q(99, 100) ** (k - 1)
        assert model.root_value() == expected
        row = dict(
            k=k,
            expected=str(expected),
            batch_states=model.optimum.cache_info().currsize,
        )
        if k < 40:
            assert old.root_value() == expected
            row["sequential_states"] = old.optimum.cache_info().currsize
            assert row["sequential_states"] >= 2 ** (k - 1)
        out.append(row)
    return out


def pair_data(snapshot, wordnet, semcor):
    yield from temperatures(snapshot)
    for key, exact, graph, task in word_tasks(wordnet, semcor):
        if exact is None:
            continue
        (p, q), weights = word_prior_pair(graph, task)
        if any(n != 1 for n in p.plan.counts):
            continue
        yield key, p, q, task["truth"], weights


def pairs(snapshot, wordnet, semcor):
    for key, p, q, truth, _ in pair_data(snapshot, wordnet, semcor):
        yield key, p, q, truth


def evaluate(snapshot, wordnet, semcor):
    classes = defaultdict(Counter)
    plans = []
    rows = []
    with gzip.open(ROOT / "prior-reuse-ledger.jsonl.gz", "rt", encoding="utf-8") as f:
        frozen = {tuple(r["task"]): r for r in map(json.loads, f)}
    for key, p, q, truth in pairs(snapshot, wordnet, semcor):
        previous = frozen.pop(key)
        total = sum(transfer_bound(p.plan, q.plan))
        residual = mandatory_first_regret_bound(p.plan, q.plan)
        assert total == Q(previous["bound"]) and 0 <= residual <= total
        old, new = p.plan, q.plan
        loss = actual_cost(old, new) - new.root_value()
        assert loss == Q(previous["reuse_expected"]) - Q(previous["new_expected"])
        assert 0 <= loss <= residual
        day = []
        for service in (p, q):
            model = service.plan
            macro = batched(model)
            assert macro.root_value() == model.root_value()
            path, labels, _ = service.execute(truth.__getitem__, planner=macro)
            base, ref, _ = service.execute(truth.__getitem__)
            assert path == base and labels == ref == {
                e: service.service.answer(e, truth) for e in service.service.order
            }
            plans.append((model, macro))
            day.append(path)
        assert day == [previous["paths"]["old"], previous["paths"]["new"]]
        keep = residual <= Q(1, 20)
        originally = total <= Q(1, 20)
        compulsory = old.obligations(old.counts, 0).bit_count()
        for g in (key[0], "total"):
            d = classes[g]
            d["tasks"] += 1
            d["initial_compulsory_tasks"] += compulsory > 0
            d["reused"] += keep
            d["old_certificate_reused"] += originally
            d["strictly_tighter"] += residual < total
            d["zero_upper_bound"] += residual == 0
            d["absolute_budget_changes_despite_zero_bound"] += (
                residual == 0 and old.root_value() != new.root_value()
            )
            d["strict_loss_where_reused"] += keep and loss > 0
            d["total_certified_extra"] += float(loss) if keep else 0
            d["dispatch_reads"] += len(day[0] if keep else day[1])
            d["full_replan_reads"] += len(day[1])
        rows.append(
            dict(
                task=key,
                compulsory=compulsory,
                old_bound=str(total),
                new_bound=str(residual),
                reuse=keep,
                expected_extra=str(loss),
                dispatch=day[0] if keep else day[1],
            )
        )
    assert not frozen
    total = classes["total"]
    for c in classes.values():
        c["total_certified_extra"] = round(c["total_certified_extra"], 9)
    stats = dict(
        by_source=classes,
        gate=10 * (total["reused"] - total["old_certificate_reused"]) >= total["tasks"],
        synthetic=synthetic(),
    )
    return stats, rows, plans


def benchmark(plans):
    output = []
    for index in (0, 1, 1, 0):
        for models in plans:
            for cache in (
                models[index].optimum,
                models[index].parts,
                models[index].projections,
            ):
                cache.cache_clear()
        n = 0
        started = process_time_ns()
        for models in plans:
            models[index].root_value()
            n += models[index].optimum.cache_info().currsize
        output.append(
            dict(
                method=("sequential", "batch")[index],
                states=n,
                seconds=round((process_time_ns() - started) / 1_000_000_000, 6),
            )
        )
    return output


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("snapshot", "wordnet", "semcor", "output"):
        p.add_argument(key, type=Path)
    p.add_argument("--benchmark", action="store_true")
    a = p.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    results, rows, plans = evaluate(a.snapshot, a.wordnet, a.semcor)
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "mandatory-reuse-results.json").write_bytes(
        (json.dumps(results, indent=2) + "\n").encode()
    )
    content = "".join(
        json.dumps(r, separators=(",", ":")) + "\n" for r in rows
    ).encode()
    (a.output / "mandatory-reuse-ledger.jsonl.gz").write_bytes(
        gzip.compress(content, mtime=0)
    )
    print(json.dumps(results, indent=2))
    if a.benchmark:
        print(json.dumps(benchmark(plans), indent=2))
