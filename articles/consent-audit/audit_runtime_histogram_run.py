"""Compile the frozen histogram plans, then run the matched CPU comparison."""

import argparse
import gzip
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import platform
from random import Random
from time import perf_counter_ns

import numpy as np
import onnxruntime as ort

from audit_runtime_histogram import optimize, replay_histograms
from audit_runtime_histogram_check import (
    ARMS,
    CASES,
    GRAPH,
    PLANS,
    RESULTS,
    TRACE,
    lengths_from,
    source_records,
    summarize,
)
from audit_runtime_latency import balanced, encoded_rows, scores_as_bytes
from audit_runtime_latency_check import MODES, expected, process_cost
from audit_runtime_pack import routed_batch
from audit_runtime_strata import balanced_strata
from go_model_fetch import verify
from point_runtime import make_session


def routes(groups, plans):
    rng = Random(7559597)
    solo = [[i] for i in range(8)]
    for rep, c, w in product(range(2), CASES, range(3)):
        common = balanced(solo, rng)
        schedules = (
            common + balanced(solo, rng),
            common + balanced_strata(groups[c], rng),
            common + replay_histograms(plans[str(c)], rng),
        )
        for step, arms in enumerate(zip(*schedules, strict=True)):
            yield [rep, c, w, step], dict(zip(ARMS, arms, strict=True))


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8", newline="\n")


def run(selected, ledger, policies, model, graph, out):
    verify(graph, GRAPH)
    rows, groups = source_records(ledger, policies)
    plans = {str(c): optimize(lengths_from(rows, c), groups[c]) for c in CASES}
    out.mkdir(parents=True, exist_ok=True)
    save(out / PLANS, plans)
    print(
        json.dumps(
            {
                "compiled": len(plans),
                "falling_back": [k for k, v in plans.items() if not v["blocks"]],
            }
        ),
        flush=True,
    )
    tokens = encoded_rows(selected, model, rows)
    session = make_session(graph)
    for _ in ARMS:
        routed_batch(session, tokens[CASES[0], 0], list(MODES), bucketed=True)
    records = []
    env = {
        "python": platform.python_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "cpu": platform.processor(),
        "runtime": ort.__version__,
        "numpy": np.__version__,
        "providers": session.get_providers(),
        "threads": 4,
    }
    for key, assignment in routes(groups, plans):
        rep, c, w, step = key
        shift = (rep + c + w + step) % 3
        order = ARMS[shift:] + ARMS[:shift]
        elapsed = {}
        digests = {}
        for arm in order:
            floors = [MODES[x] for x in assignment[arm]]
            start = perf_counter_ns()
            r = routed_batch(session, tokens[c, w], floors, bucketed=True)
            elapsed[arm] = perf_counter_ns() - start
            raw = scores_as_bytes(r)
            assert raw == expected(rows[c, w], assignment[arm])
            digests[arm] = sha256(raw).hexdigest()
        records.append(
            {
                "key": key,
                "route": assignment,
                "order": list(order),
                "timing": elapsed,
                "sha256": digests,
                "work": {
                    arm: process_cost(rows[c, w], z) for arm, z in assignment.items()
                },
            }
        )
        if w == 2 and step == 15:
            print(
                json.dumps(
                    {"round": rep + 1, "catalog": c, "measurements": len(records) * 3}
                ),
                flush=True,
            )
    trace = {"graph": GRAPH, "environment": env, "batches": records}
    report = summarize(ledger, policies, plans, trace, verify=False)
    (out / TRACE).write_bytes(
        gzip.compress(json.dumps(trace, separators=(",", ":")).encode(), mtime=0)
    )
    save(out / RESULTS, report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "measurements",
                    "bitwise_scores",
                    "fallbacks",
                    "primary_gate",
                    "transfer_gate",
                )
            }
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("selected", "ledger", "policies", "model", "graph", "out"):
        cli.add_argument(name, type=Path)
    a = cli.parse_args()
    run(a.selected, a.ledger, a.policies, a.model, a.graph, a.out)
