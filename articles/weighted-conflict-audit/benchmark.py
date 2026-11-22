"""Paired benchmark against the published source at 28b6109 (full git history needed)."""

import importlib.util
import json
import multiprocessing
from pathlib import Path
import platform
import runpy
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).resolve().parent
exp = runpy.run_path(str(HERE/"check.py"))


def load_old(directory):
    for name in ("__init__.py", "core.py", "action.py"):
        ref = f"28b6109:packages/stateful-identification/stateful_id/{name}"
        (directory/name).write_bytes(subprocess.check_output(["git", "show", ref], cwd=HERE))
    spec = importlib.util.spec_from_file_location("stateful_baseline", directory/"__init__.py",
                                                   submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def worker(conn, version, n, extract, temp):
    api = load_old(Path(temp)) if version == "0.2.0" else exp["sid"]
    rows, core, radii = exp["tight_instance"](n)
    plan, qs = exp["planner"](rows, radii, api)
    counts = dict.fromkeys(qs,n)
    conn.send("ready")
    for _ in range(3):
        start = perf_counter()
        decision = plan.assess(counts, witnesses=extract)
        elapsed = (perf_counter()-start)*1000
        exp["check"](decision.guaranteed, (version,n))
        if extract:
            exp["check"](set(map(int,decision.witnesses[0])) == set(core), (version,n))
        conn.send(round(elapsed, 4))
    conn.close()


def measure(version, n, extract, temp):
    rx, tx = multiprocessing.Pipe(duplex=False)
    proc = multiprocessing.Process(target=worker, args=(tx, version, n, extract, temp))
    proc.start()
    tx.close()
    times = []
    try:
        exp["check"](rx.poll(30) and rx.recv() == "ready", "benchmark setup failed")
        for _ in range(3):
            if not rx.poll(10):
                break
            times.append(rx.recv())
    finally:
        if len(times) < 3 and proc.is_alive():
            proc.terminate()
        proc.join()
        rx.close()
    return times


def run():
    results = []
    for n in (1, 3, 9, 27):
        for extract in (False, True):
            with TemporaryDirectory() as temp:
                times = {v: measure(v, n, extract, temp) for v in ("0.2.0","0.3.0")}
            ratio = None
            if all(len(s) == 3 for s in times.values()):
                ratio = round(statistics.median(times["0.2.0"]) / statistics.median(times["0.3.0"]), 2)
            results.append({"repeats": n, "witnesses": extract, "ms": times, "median_ratio": ratio})
    return {"baseline": "28b6109", "python": platform.python_version(), "platform": platform.system(),
            "machine": platform.machine(), "sample_cutoff_seconds": 10, "results": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
