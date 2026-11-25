"""Run the frozen matched comparison of CPU execution strategies."""

import argparse
import gzip
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
import platform
from random import Random
from time import perf_counter_ns, process_time_ns

import numpy as np
import onnxruntime as ort

from audit_runtime_latency import balanced, encoded_rows, scores_as_bytes
from audit_runtime_latency_check import MODES, expected
from audit_runtime_parallel import CpuExecutor
from audit_runtime_parallel_check import (
    ARMS,
    CASES,
    GRAPH,
    RESULTS,
    TRACE,
    records,
    summarize,
)
from audit_runtime_strata import balanced_strata
from go_model_fetch import verify


def replay_routes(groups):
    rng = Random(7655548)
    single = [[i] for i in range(8)]
    for r, c, w in product(range(2), CASES, range(3)):
        common = balanced(single, rng)
        separate = common + balanced(single, rng)
        stratified = common + balanced_strata(groups[c], rng)
        for k, (a, b) in enumerate(zip(separate, stratified, strict=True)):
            yield [r, c, w, k], {"independent": a, "stratified": b}


def run(selected, ledger, plans, model, graph, output):
    verify(graph, GRAPH)
    rows, groups = records(ledger, plans)
    tokens = encoded_rows(selected, model, rows)
    captured = []
    env = {
        "os": platform.system(),
        "os_release": platform.release(),
        "cpu": platform.processor(),
        "python": platform.python_version(),
        "runtime": ort.__version__,
        "numpy": np.__version__,
        "provider": "CPUExecutionProvider",
        "requested_graph_threads": 4,
        "spinning": False,
    }
    with CpuExecutor(graph) as service:
        for name in ARMS:
            seen, _ = service.execute(
                tokens[CASES[0], 0], list(MODES), name.split("_")[1]
            )
            assert scores_as_bytes(seen) == expected(rows[CASES[0], 0], list(range(8)))
        print(json.dumps({"preflight_bitwise_scores": 24 * len(ARMS)}), flush=True)
        for key, route in replay_routes(groups):
            r, c, w, k = key
            shift = (r + c + w + k) % 6
            order = ARMS[shift:] + ARMS[:shift]
            elapsed, cpu, jobs, digest, peak = {}, {}, {}, {}, {}
            for arm in order:
                selected_route, engine = arm.split("_")
                modes = route[selected_route]
                floors = [MODES[i] for i in modes]
                proc0 = process_time_ns()
                wall = perf_counter_ns()
                scores, assigned = service.execute(tokens[c, w], floors, engine)
                elapsed[arm] = perf_counter_ns() - wall
                cpu[arm] = process_time_ns() - proc0
                actual = scores_as_bytes(scores)
                assert actual == expected(rows[c, w], modes), (key, arm)
                digest[arm] = sha256(actual).hexdigest()
                jobs[arm] = assigned
                work = [
                    max(len(v), f) ** 2
                    for v, f in zip(tokens[c, w], floors, strict=True)
                ]
                peak[arm] = (
                    sum(work)
                    if engine == "operator"
                    else max(sum(work[i] for i in a) for a in assigned)
                )
            captured.append(
                {
                    "key": key,
                    "route": route,
                    "order": list(order),
                    "elapsed": elapsed,
                    "cpu": cpu,
                    "jobs": jobs,
                    "sha256": digest,
                    "peak_work": peak,
                }
            )
            if w == 2 and k == 15:
                print(
                    json.dumps(
                        {
                            "round": r + 1,
                            "catalog": c,
                            "measurements": len(captured) * len(ARMS),
                        }
                    ),
                    flush=True,
                )
    trace = {"graph": GRAPH, "environment": env, "batches": captured}
    report = summarize(ledger, plans, trace)
    output.mkdir(parents=True, exist_ok=True)
    (output / TRACE).write_bytes(
        gzip.compress(json.dumps(trace, separators=(",", ":")).encode(), mtime=0)
    )
    (output / RESULTS).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
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
    for k in ("selected", "ledger", "plans", "model", "graph", "output"):
        cli.add_argument(k, type=Path)
    a = cli.parse_args()
    run(a.selected, a.ledger, a.plans, a.model, a.graph, a.output)
