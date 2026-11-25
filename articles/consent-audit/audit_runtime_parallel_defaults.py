"""Isolated-process follow-up against the original ONNX threading defaults."""

import argparse
from contextlib import nullcontext
from fractions import Fraction as F
import gzip
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from audit_runtime_latency_check import GRAPH, MODES, comparison, expected, p95
from audit_runtime_parallel_check import records, task_layout

CASES = (0, 1, 12, 22, 34, 58)
TRACE = "audit-runtime-parallel-defaults-trace.json.gz"
RESULTS = "audit-runtime-parallel-defaults-results.json"
ORDERS = (("default", "balanced"), ("balanced", "default"))


def summary(ledger, plans, experiments):
    rows, _ = records(ledger, plans)
    reports = []
    for rep, pair in enumerate(experiments):
        assert [x["arm"] for x in pair] == list(ORDERS[rep])
        by_arm = {x["arm"]: x["batches"] for x in pair}
        times = {"default": [], "balanced": []}
        calls = {"default": 0, "balanced": 0}
        for (c, w, k), old, new in zip(
            product(CASES, range(3), range(16)),
            by_arm["default"],
            by_arm["balanced"],
            strict=True,
        ):
            key = [rep, c, w, k]
            assert old["key"] == new["key"] == key and old["route"] == new["route"]
            route = old["route"]
            want = sha256(expected(rows[c, w], route)).hexdigest()
            widths = [
                max(int(r["length"]), MODES[m])
                for r, m in zip(rows[c, w], route, strict=True)
            ]
            buckets, packed = task_layout(widths)
            for arm, data, groups in (
                ("default", old, buckets),
                ("balanced", new, packed),
            ):
                assert data["sha256"] == want and data["calls"] == len(groups)
                assert type(data["ns"]) is int and data["ns"] > 0
                times[arm].append(data["ns"])
                calls[arm] += data["calls"]
        data = comparison(times["balanced"], times["default"])
        data["call_ratio"] = str(F(calls["balanced"], calls["default"]))
        reports.append(
            {
                "comparison": data,
                "arms": {
                    arm: {
                        "p95_ns": p95(clock),
                        "median_ns": str(median(map(F, clock))),
                        "mean_calls": str(F(calls[arm], len(clock))),
                    }
                    for arm, clock in times.items()
                },
            }
        )
    assert len(reports) == 2
    passed = all(
        F(r["comparison"]["p95_ratio"]) <= F(19, 20)
        and F(r["comparison"]["paired_median_ratio"]) <= F(21, 20)
        and F(r["comparison"]["call_ratio"]) <= F(19, 20)
        for r in reports
    )
    return {
        "rounds": reports,
        "measurements": 1152,
        "bitwise_scores": 27648,
        "passed": passed,
    }


def child(selected, ledger, plans, model, graph, arm, rep):
    from audit_runtime_latency import encoded_rows, scores_as_bytes
    from audit_runtime_pack import routed_batch
    from audit_runtime_parallel import CpuExecutor
    from audit_runtime_parallel_run import replay_routes
    from go_model_fetch import verify
    from point_runtime import make_session

    verify(graph, GRAPH)
    rows, groups = records(ledger, plans)
    tokens = encoded_rows(selected, model, rows)
    run = []
    backend = (
        nullcontext(make_session(graph)) if arm == "default" else CpuExecutor(graph)
    )
    with backend as service:

        def infer(w, x):
            if arm == "default":
                z = routed_batch(service, w, x, bucketed=True)
                return z, len(set(max(len(r), n) for r, n in zip(w, x, strict=True)))
            z, jobs = service.execute(w, x, "balanced")
            return z, len(jobs)

        infer(tokens[CASES[0], 0], list(MODES))
        for key, route in replay_routes(groups):
            r, c, w, _ = key
            if r != rep or c not in CASES:
                continue
            z = route["stratified"]
            floors = [MODES[i] for i in z]
            instant = perf_counter_ns()
            scored, calls = infer(tokens[c, w], floors)
            ns = perf_counter_ns() - instant
            actual = scores_as_bytes(scored)
            assert actual == expected(rows[c, w], z)
            run.append(
                dict(
                    key=key,
                    route=z,
                    ns=ns,
                    calls=calls,
                    sha256=sha256(actual).hexdigest(),
                )
            )
    return {"arm": arm, "batches": run}


def run(arguments):
    sequences = []
    with TemporaryDirectory(prefix="parallel-defaults-") as folder:
        temp = Path(folder) / "child.json"
        for r, order in enumerate(ORDERS):
            pair = []
            for engine in order:
                cmd = [
                    sys.executable,
                    "-B",
                    __file__,
                    *(
                        str(getattr(arguments, x))
                        for x in ("selected", "ledger", "plans", "model", "graph")
                    ),
                    str(temp),
                    "--arm",
                    engine,
                    "--rep",
                    str(r),
                ]
                subprocess.run(cmd, check=True)
                pair.append(json.loads(temp.read_bytes()))
                print(json.dumps({"rep": r + 1, "completed": engine}), flush=True)
            sequences.append(pair)
    out = arguments.output
    out.mkdir(parents=True, exist_ok=True)
    (out / TRACE).write_bytes(
        gzip.compress(json.dumps(sequences, separators=(",", ":")).encode(), mtime=0)
    )
    report = summary(arguments.ledger, arguments.plans, sequences)
    (out / RESULTS).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {
                "verified": True,
                "passed": report["passed"],
                "measurements": report["measurements"],
            }
        )
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for k in ("selected", "ledger", "plans", "model", "graph", "output"):
        cli.add_argument(k, type=Path)
    cli.add_argument("--arm", choices=("default", "balanced"))
    cli.add_argument("--rep", type=int, choices=(0, 1))
    cli.add_argument(
        "--check",
        action="store_true",
        help="recompute the report from the stored raw clocks",
    )
    a = cli.parse_args()
    if a.arm:
        a.output.write_bytes(
            json.dumps(
                child(a.selected, a.ledger, a.plans, a.model, a.graph, a.arm, a.rep)
            ).encode()
        )
    elif a.check:
        report = summary(
            a.ledger,
            a.plans,
            json.loads(gzip.decompress((a.output / TRACE).read_bytes())),
        )
        assert report == json.loads((a.output / RESULTS).read_bytes())
        print(
            json.dumps(
                {
                    "verified": True,
                    "passed": report["passed"],
                    "measurements": report["measurements"],
                }
            )
        )
    else:
        run(a)
