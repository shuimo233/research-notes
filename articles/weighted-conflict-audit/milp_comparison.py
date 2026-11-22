"""Compare decisions with an eight-variable integer program; optional SciPy dependency."""

import json
from pathlib import Path
import platform
import runpy
from statistics import median
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp


experiment = runpy.run_path(str(Path(__file__).with_name("check.py")))


def compare(n, relaxed):
    rows, corners, radii = experiment["tight_instance"](n)
    if relaxed:
        radii[corners[0]] += 1
    planner, probes = experiment["planner"](rows, radii)
    schedule = dict.fromkeys(probes, n)
    bits = np.asarray(rows)
    size = len(probes)
    constraint = LinearConstraint(1 - 2 * bits, -np.inf, np.asarray(radii) - n * bits.sum(axis=1))
    arguments = dict(c=np.zeros(size), integrality=np.ones(size), bounds=Bounds(np.zeros(size), np.full(size, n)),
                     constraints=constraint, options={"time_limit": 10})

    def run_highs():
        return milp(**arguments)

    def run_layer():
        return planner.assess(schedule)

    def validate(method, result):
        if method == "package":
            return "verified" if result.guaranteed == (not relaxed) else "wrong_verdict"
        if result.status == 2:
            return "verified" if not relaxed else "wrong_infeasible"
        if result.status != 0 or result.x is None:
            return "unresolved_status_" + str(result.status)
        record = [int(round(v)) for v in result.x]
        valid = all(0 <= z <= n for z in record) and all(
            sum(n-z if bit else z for bit, z in zip(row, record)) <= r for row, r in zip(rows, radii))
        return "verified" if valid and relaxed else "invalid_feasible"

    methods = {"package": run_layer, "highs": run_highs}
    times = {key: [] for key in methods}
    outcomes = {key: validate(key, call()) for key, call in methods.items()}
    for trial in range(7):
        order = list(methods) if trial % 2 == 0 else list(reversed(methods))
        for key in order:
            if outcomes[key] != "verified":
                continue
            start = perf_counter()
            result = methods[key]()
            duration = (perf_counter() - start) * 1000
            outcomes[key] = validate(key, result)
            if outcomes[key] == "verified":
                times[key].append(round(duration, 4))
    return {"repeats": n, "relaxed": relaxed, "outcomes": outcomes, "ms": times,
            "median_ms": {key: round(median(values), 4) if len(values) == 7 else None
                          for key, values in times.items()}}


if __name__ == "__main__":
    print(json.dumps({"python": platform.python_version(), "scipy": scipy.__version__,
                      "numpy": np.__version__, "platform": platform.system(), "machine": platform.machine(),
                      "results": [compare(n, relaxed) for n in (1, 3, 9, 27, 1_000_001)
                                  for relaxed in (False, True)]}, indent=2))
