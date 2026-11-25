"""Time registered exchangeable stratified routing in the exact-width backend."""

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

from audit_runtime_latency import balanced, encoded_rows, scores_as_bytes
from audit_runtime_latency_check import MODES, expected, process_cost
from audit_runtime_pack import routed_batch
from audit_runtime_strata import balanced_strata
from audit_runtime_strata_check import (
    ARMS,
    CASES,
    GRAPH,
    RESULTS,
    TRACE,
    records,
    summarize,
)
from go_model_fetch import verify
from point_runtime import make_session


def replay_routes(groups):
    rng = Random(7441887)
    solo = [[i] for i in range(8)]
    for run, case, world in product(range(2), CASES, range(3)):
        first = balanced(solo, rng)
        rows = (
            first + balanced(solo, rng),
            first + balanced(groups[case], rng),
            first + balanced_strata(groups[case], rng),
        )
        for k, plans in enumerate(zip(*rows, strict=True)):
            yield [run, case, world, k], dict(zip(ARMS, plans, strict=True))


def run(selected, ledger, policies, model, graph, out):
    verify(graph, GRAPH)
    source, groups = records(ledger, policies)
    encoded = encoded_rows(selected, model, source)
    session = make_session(graph)
    for _ in ARMS:
        routed_batch(session, encoded[CASES[0], 0], list(MODES), bucketed=True)
    metadata = {
        "os": platform.system(),
        "os_release": platform.release(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "runtime": ort.__version__,
        "numpy": np.__version__,
        "provider": session.get_providers(),
        "threads": 4,
    }
    batches = []
    for tag, routes in replay_routes(groups):
        r, case, world, step = tag
        shift = (r + case + world + step) % 3
        order = ARMS[shift:] + ARMS[:shift]
        timings, digests = {}, {}
        for arm in order:
            arg = [MODES[i] for i in routes[arm]]
            t0 = perf_counter_ns()
            values = routed_batch(session, encoded[case, world], arg, bucketed=True)
            timings[arm] = perf_counter_ns() - t0
            actual = scores_as_bytes(values)
            assert actual == expected(source[case, world], routes[arm]), (tag, arm)
            digests[arm] = sha256(actual).hexdigest()
        batches.append(
            {
                "key": tag,
                "route": routes,
                "order": list(order),
                "timing": timings,
                "sha256": digests,
                "work": {
                    arm: process_cost(source[case, world], routes[arm]) for arm in ARMS
                },
            }
        )
        if world == 2 and step == 15:
            print(
                json.dumps(
                    {"round": r + 1, "catalog": case, "measurements": len(batches) * 3}
                ),
                flush=True,
            )
    trace = {"graph": GRAPH, "environment": metadata, "batches": batches}
    result = summarize(ledger, policies, trace)
    out.mkdir(parents=True, exist_ok=True)
    (out / TRACE).write_bytes(
        gzip.compress(json.dumps(trace, separators=(",", ":")).encode(), mtime=0)
    )
    (out / RESULTS).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "measurements",
                    "bitwise_scores",
                    "primary_gate",
                    "transfer_gate",
                )
            }
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for n in ("selected", "ledger", "policies", "model", "graph", "out"):
        cli.add_argument(n, type=Path)
    a = cli.parse_args()
    run(a.selected, a.ledger, a.policies, a.model, a.graph, a.out)
