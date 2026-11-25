"""Calibrate marginal row cost, then run the isolated CPU comparisons."""

import argparse
from contextlib import nullcontext
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import product
import json
from math import ceil
from pathlib import Path
from random import Random
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from audit_runtime_calibration import CalibratedPlanner
from audit_runtime_calibration_check import (
    CASES,
    GRAPH,
    MODEL,
    ORDERS,
    RESULTS,
    TRACE,
    calibration,
    records,
    sources,
    summarize,
    task_layout,
)
from audit_runtime_latency import balanced, encoded_rows, scores_as_bytes
from audit_runtime_latency_check import MODES, expected
from audit_runtime_pack import _one_call, routed_batch
from audit_runtime_parallel import CpuExecutor, cpu_session
from audit_runtime_strata import balanced_strata
from go_model_fetch import verify
from point_runtime import make_session


def routes(groups):
    rng = Random(7765387)
    for rep, c, w in product(range(2), CASES, range(3)):
        independent = balanced([[i] for i in range(8)], rng)
        alternate = balanced_strata(groups[c], rng)
        for i, z in enumerate(independent + alternate):
            yield [rep, c, w, i], z


def profile(rows, tokens, graph):
    anchors, widths = sources(rows)
    session = cpu_session(graph, 1)
    report = {}
    for w in widths:
        _c, _s, i = anchors[0]
        warm = tokens[_c, _s][i][:w]
        for n in (2, 4):
            _one_call(session, [warm] * n, [w] * n, 0)
        pairs = []
        for a, (c, x, i) in enumerate(anchors):
            ids = tokens[c, x][i][:w]
            for k in range(4):
                first = 2 if (a + k + w) % 2 == 0 else 4
                ns = {}
                for n in (first, 6 - first):
                    batch = [ids] * n
                    floors = [w] * n
                    t = perf_counter_ns()
                    scored = _one_call(session, batch, floors, 0)
                    ns[n] = perf_counter_ns() - t
                    assert all(z.tobytes() == scored[0].tobytes() for z in scored)
                pairs.append([a, k, first, ns[2], ns[4]])
        cost = max(1, ceil(median(F(four - two, 2) for _, _, _, two, four in pairs)))
        report[str(w)] = {"pairs": pairs, "marginal_ns": cost}
    return {"graph": GRAPH, "anchors": anchors, "widths": report}


def experiment(rows, groups, tokens, graph, arm, rep, measured):
    plan = CalibratedPlanner(calibration(rows, measured))
    planning = 0

    def watched(widths, k):
        nonlocal planning
        t = perf_counter_ns()
        a = plan(widths, k)
        planning = perf_counter_ns() - t
        return a

    backend = (
        nullcontext(make_session(graph)) if arm == "default" else CpuExecutor(graph)
    )
    result = []
    with backend as service:

        def invoke(tokens, floors):
            if arm == "default":
                output = routed_batch(service, tokens, floors, bucketed=True)
                return output, None
            return service.execute(
                tokens,
                floors,
                "balanced",
                planner=watched if arm == "calibrated" else None,
            )

        invoke(tokens[CASES[0], 0], list(MODES))
        for key, z in routes(groups):
            r, c, w, _ = key
            if r != rep:
                continue
            planning = 0
            floors = [MODES[i] for i in z]
            start = perf_counter_ns()
            values, jobs = invoke(tokens[c, w], floors)
            ns = perf_counter_ns() - start
            if jobs is None:
                jobs = task_layout(
                    [max(len(t), m) for t, m in zip(tokens[c, w], floors, strict=True)]
                )[0]
            computed = scores_as_bytes(values)
            assert computed == expected(rows[c, w], z), (key, arm)
            result.append(
                dict(
                    key=key,
                    route=z,
                    jobs=jobs,
                    ns=ns,
                    planner_ns=planning,
                    sha256=sha256(computed).hexdigest(),
                )
            )
    return {"arm": arm, "batches": result}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def invoke_child(a):
    verify(a.graph, GRAPH)
    rows, groups = records(a.ledger, a.plans)
    tokens = encoded_rows(a.selected, a.model, rows)
    out = a.output
    if a.arm == "profile":
        save(out, profile(rows, tokens, a.graph))
    else:
        out.write_bytes(
            json.dumps(
                experiment(
                    rows,
                    groups,
                    tokens,
                    a.graph,
                    a.arm,
                    a.rep,
                    json.loads(a.profile.read_bytes()),
                )
            ).encode()
        )


def all_runs(a):
    path = a.output
    path.mkdir(parents=True, exist_ok=True)
    measured = path / MODEL
    common = [
        sys.executable,
        "-B",
        __file__,
        *(
            str(getattr(a, x))
            for x in ("selected", "ledger", "plans", "model", "graph")
        ),
    ]
    subprocess.run([*common, str(measured), "--arm", "profile"], check=True)
    frozen = json.loads(measured.read_bytes())
    print(
        json.dumps(
            {
                "calibrated_widths": len(frozen["widths"]),
                "pairs": 12 * len(frozen["widths"]),
            }
        ),
        flush=True,
    )
    output = []
    with TemporaryDirectory(prefix="calibrated-tail-") as tmp:
        stage = Path(tmp) / "stage.json"
        for i, order in enumerate(ORDERS):
            collected = []
            for arm in order:
                subprocess.run(
                    [
                        *common,
                        str(stage),
                        "--arm",
                        arm,
                        "--rep",
                        str(i),
                        "--profile",
                        str(measured),
                    ],
                    check=True,
                )
                collected.append(json.loads(stage.read_bytes()))
                print(
                    json.dumps(
                        {
                            "round": i + 1,
                            "arm": arm,
                            "batches": len(collected[-1]["batches"]),
                        }
                    ),
                    flush=True,
                )
            output.append(collected)
    report = summarize(a.ledger, a.plans, frozen, output)
    (path / TRACE).write_bytes(
        gzip.compress(json.dumps(output, separators=(",", ":")).encode(), mtime=0)
    )
    save(path / RESULTS, report)
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
    cli.add_argument("--arm", choices=("profile", *ORDERS[0]))
    cli.add_argument("--rep", type=int, choices=(0, 1))
    cli.add_argument("--profile", type=Path)
    a = cli.parse_args()
    if a.arm:
        invoke_child(a)
    else:
        all_runs(a)
