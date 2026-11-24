"""Replay prior changes in previously published temperature and word-sense tasks."""

import argparse
from collections import Counter, defaultdict
from fractions import Fraction as Q
from functools import lru_cache
import gzip
import json
from math import prod
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from frontier_inquiry import RelationInquiry
from frontier_information import actual_cost
from frontier_run import inputs, lines, sense_marginals
from gloss_frontier import semcor_counts
from prior_reuse import transfer_bound
from station_query import EDGES, STATIONS, label, load_snapshot
from wordnet_paths import NounPaths


def temperatures(snapshot):
    old, days, bases = load_snapshot(snapshot)
    new = {k: v.copy() for k, v in old.items()}
    for date, readings in days.items():
        if date < "2025":
            m = int(date[5:7])
            for s, x in readings.items():
                new[s, m][x] += 1
    with gzip.open(
        ROOT / "mixture-station-ledger.jsonl.gz", "rt", encoding="ascii"
    ) as f:
        for line in f:
            row = json.loads(line)
            region, day = row["region"], row["date"]
            ids = {u: "USW000" + n for u, n in STATIONS[region].items()}
            truth = {u: days[day][s] for u, s in ids.items()}
            m = int(day[5:7])
            lows = {u: truth[u] - (truth[u] - bases[s, m]) % 20 for u, s in ids.items()}
            assert row["lows"] == list(lows.values())
            weights = []
            for model in (old, new):
                fitted = {}
                for u, lo in lows.items():
                    histogram = model[ids[u], m]
                    xs = range(lo, lo + 20)
                    total = sum(histogram[x] + 1 for x in xs)
                    fitted[u] = {x: Q(histogram[x] + 1, total) for x in xs}
                weights.append(fitted)
            p, q = (RelationInquiry(w, EDGES, label, w) for w in weights)
            yield ("temperature", region, day), p, q, truth, weights


def word_tasks(wordnet, semcor):
    graph = NounPaths(wordnet)
    tasks = inputs()
    for row in lines("frontier-ledger.jsonl"):
        if row["source"] == "semcor":
            k = "semcor", row["group"], row["sentence"]
            yield k, row["expected_optimal"], graph, tasks[k]
    senses = lru_cache(None)(graph.senses)
    _, fitted = semcor_counts(wordnet, semcor, senses)
    for row in lines("gloss-frontier-ledger.jsonl"):
        task = dict(
            words={u: w for u, _, w, _ in row["positions"]},
            truth={u: x for u, _, _, x in row["positions"]},
            edges=row["edges"],
            counts={
                w: {str(x): fitted[w][x] for x in senses(w)}
                for _, _, w, _ in row["positions"]
            },
        )
        yield (
            ("princeton", row["stratum"], row["definition"]),
            row["expected_optimal"],
            graph,
            task,
        )


def coarse_bound(p, weights):
    discrete_tvs = []
    a, b = weights
    for u, row in a.items():
        discrete_tvs.append(sum(abs(p - b[u][x]) for x, p in row.items()) / 2)
    return 2 * sum(p.cost) * (1 - prod(1 - t for t in discrete_tvs))


def word_prior_pair(graph, task):
    weights = [sense_marginals(graph, task, add) for add in (1, 2)]
    return [
        RelationInquiry(w, sorted(task["edges"]), graph.relation, w, task["words"])
        for w in weights
    ], weights


def score(k, p, q, truth, weights):
    loss, gain = transfer_bound(p.plan, q.plan)
    bound = loss + gain
    reuse = bound <= Q(1, 20)
    actual, answers, _ = q.execute(
        truth.__getitem__, planner=p.plan if reuse else q.plan
    )
    q_opt = q.plan.root_value()
    p_opt = p.plan.root_value()
    old_cost = actual_cost(p.plan, q.plan)
    assert -loss <= q_opt - p_opt <= gain and -loss <= old_cost - p_opt <= gain
    assert 0 <= old_cost - q_opt <= bound
    old_path, res1, _ = p.execute(truth.__getitem__)
    new_path, res2, _ = q.execute(truth.__getitem__)
    assert actual == (old_path if reuse else new_path)
    labels = {e: q.service.answer(e, truth) for e in q.service.order}
    assert answers == res1 == res2 == labels
    tv = coarse_bound(p.plan, weights)
    assert old_cost - q_opt <= tv
    if k[0] == "temperature":
        exact_scalar = sum(
            abs(q.plan.rates[i][j] - r) * q.plan.cost[j]
            for i, rs in enumerate(p.plan.rates)
            for j, r in rs.items()
        )
        assert exact_scalar == bound
    return dict(
        task=k,
        reuse=reuse,
        tv_reuse=tv <= Q(1, 20),
        bound=str(bound),
        down=str(loss),
        up=str(gain),
        joint_tv_bound=str(tv),
        old_expected=str(p_opt),
        new_expected=str(q_opt),
        reuse_expected=str(old_cost),
        old_reads=len(old_path),
        new_reads=len(new_path),
        dispatch_reads=len(actual),
        paths={"old": old_path, "new": new_path, "dispatch": actual},
        labels=list(labels.items()),
    )


def run(snapshot, wordnet, semcor, out):
    report = defaultdict(Counter)
    rows = []
    for item in temperatures(snapshot):
        rows.append(score(*item))
    for k, exact, graph, task in word_tasks(wordnet, semcor):
        counts = report[k[0]]
        if exact is None:
            counts["excluded_no_exact_root"] += 1
            continue
        opts, weights = word_prior_pair(graph, task)
        if any(n != 1 for n in opts[0].plan.counts):
            counts["excluded_coalesced"] += 1
            continue
        assert opts[0].plan.root_value() == Q(exact)
        rows.append(score(k, *opts, task["truth"], weights))
    for row in rows:
        loss = Q(row["reuse_expected"]) - Q(row["new_expected"])
        for group in (row["task"][0], "total"):
            c = report[group]
            c["scored"] += 1
            c["reused"] += row["reuse"]
            c["tv_reused"] += row["tv_reuse"]
            c["strict_loss_reusing_all"] += loss > 0
            c["strict_loss_in_certified_cases"] += loss > 0 and row["reuse"]
            c["zero_transport_bound"] += Q(row["bound"]) == 0
            c["tighter_than_joint_tv"] += Q(row["bound"]) < Q(row["joint_tv_bound"])
            for k in ("old_reads", "new_reads", "dispatch_reads"):
                c[k] += row[k]
            c["certified_expected_extra"] += float(loss) if row["reuse"] else 0
    result = dict(report)
    result["gate"] = (
        report["total"]["scored"] >= 500
        and 5 * report["total"]["reused"] >= report["total"]["scored"]
    )
    for counts in report.values():
        counts["certified_expected_extra"] = round(
            counts["certified_expected_extra"], 8
        )
    out.mkdir(parents=True, exist_ok=False)
    ledger = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode(
        "utf-8"
    )
    (out / "prior-reuse-ledger.jsonl.gz").write_bytes(gzip.compress(ledger, mtime=0))
    (out / "prior-reuse-results.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode("utf-8")
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("snapshot", "wordnet", "semcor", "output"):
        parser.add_argument(key, type=Path)
    a = parser.parse_args()
    if not __debug__:
        raise RuntimeError("enable assertions")
    print(json.dumps(run(a.snapshot, a.wordnet, a.semcor, a.output), indent=2))
