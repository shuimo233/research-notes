"""Bounded CPU task execution for per-row-width ONNX inference."""

from concurrent.futures import ThreadPoolExecutor, wait
from threading import Lock

import numpy as np
import onnxruntime as ort

from audit_runtime_pack import _one_call


def schedule(widths, engine, workers=4):
    buckets = {}
    for i, w in enumerate(widths):
        buckets.setdefault(w, []).append(i)
    if engine in ("operator", "bucket"):
        return list(buckets.values())
    if engine != "balanced":
        raise ValueError("unknown CPU execution strategy")
    n = min(workers, len(buckets))
    tasks = [[] for _ in range(n)]
    loads = [0] * n
    for i in sorted(range(len(widths)), key=lambda i: (-widths[i], i)):
        k = min(range(n), key=lambda j: (loads[j], j))
        tasks[k].append(i)
        loads[k] += widths[i] ** 2
    return [sorted(t) for t in tasks if t]


def cpu_session(graph, threads):
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(graph), options, providers=["CPUExecutionProvider"])


class CpuExecutor:
    """A fixed worker budget and one admitted batch at a time."""

    def __init__(self, graph, workers=4):
        if type(workers) is not int or workers < 1:
            raise ValueError("expected a positive worker budget")
        self.workers = workers
        self.operator = cpu_session(graph, workers)
        self.parallel = cpu_session(graph, 1)
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self._admission = Lock()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        with self._admission:
            self.pool.shutdown(wait=True, cancel_futures=True)

    def execute(self, rows, floors, engine):
        if (
            len(rows) == 0
            or len(rows) != len(floors)
            or any(not 0 < len(row) <= 512 for row in rows)
        ):
            raise ValueError("expected one to 512 tokens per nonempty input row")
        if any(type(w) is not int or not 0 <= w <= 512 for w in floors):
            raise ValueError("expected one integer width floor in [0,512] per request")
        widths = [max(len(row), w) for row, w in zip(rows, floors, strict=True)]
        jobs = schedule(widths, engine, self.workers)

        def call(session, indices):
            return _one_call(
                session, [rows[i] for i in indices], [floors[i] for i in indices], 0
            )

        out = np.empty((len(rows), 3), dtype=np.float32)
        with self._admission:
            if engine == "operator":
                for indices in jobs:
                    out[indices] = call(self.operator, indices)
            else:
                futures = [
                    self.pool.submit(call, self.parallel, indices) for indices in jobs
                ]
                # Do not admit a subsequent batch while an unsuccessful job is still running.
                wait(futures)
                for indices, future in zip(jobs, futures, strict=True):
                    out[indices] = future.result()
        return out, jobs
