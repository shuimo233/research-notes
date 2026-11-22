"""Compare inclusion-minimal row certificates and control for vacuous input rows."""

from itertools import combinations
import json
from pathlib import Path
import platform
import runpy
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp


here = Path(__file__).resolve().parent
exp = runpy.run_path(str(here / "check.py"))
load_old = runpy.run_path(str(here / "benchmark.py"))["load_old"]


def nonredundant(n):
    # K3 and C5 are separate components of the crossing graph.
    corners = [tuple(int(b) for b in format(i, "03b")) + (0,) * 5 for i in range(8)]
    edges = [(0,) * 3 + tuple(int(j in (i, (i+1) % 5)) for j in range(5)) for i in range(5)]
    radius = 3 * ((n+1)//2) - 1
    rows, radii = corners + edges, [radius]*8 + [radius+2*n-1]*5
    for i, j in combinations(range(len(rows)), 2):
        distance = n * sum(x != y for x, y in zip(rows[i], rows[j]))
        exp["check"](abs(radii[i]-radii[j]) < distance <= radii[i]+radii[j], (n,i,j))
    # Increasing only the 111 corner's budget by one admits this complete record.
    z = [n//2]*3 + [0]*5
    distances = [sum(n-a if b else a for b,a in zip(row,z)) for row in rows]
    exp["check"](all(d <= r + (i == 7) for i,(d,r) in enumerate(zip(distances,radii))), n)
    return rows, radii


def compare(family, n, baseline):
    if family == "shards44":
        rows, _, radii = exp["tight_instance"](n)
    else:
        rows, radii = nonredundant(n)
    plan, probes = exp["planner"](rows, radii)
    schedule = dict.fromkeys(probes, n)
    size = len(probes)
    kept = tuple(i for i, r in enumerate(radii) if r < n * size)
    bits = np.asarray(rows)
    matrix, rhs = 1 - 2 * bits, np.asarray(radii) - n * bits.sum(axis=1)
    args = dict(c=np.zeros(size), integrality=np.ones(size), bounds=Bounds(0, np.full(size, n)),
                options={"time_limit": 10})

    def feasible(indices):
        idx = list(indices)
        result = milp(**args, constraints=LinearConstraint(matrix[idx], -np.inf, rhs[idx]))
        if result.status == 2:
            return False
        exp["check"](result.status == 0, (family,n,idx,result.message))
        record = [int(round(z)) for z in result.x]
        exp["check"](all(0 <= z <= n for z in record) and all(
            sum(n-z if b else z for b,z in zip(rows[i],record)) <= radii[i] for i in idx), (family,n,record))
        return True

    def highs_core():
        core = kept
        exp["check"](not feasible(core), (family,n))
        for i in kept:
            rest = tuple(j for j in core if i != j)
            if not feasible(rest):
                core = rest
        return core

    def assess(planner, schedule, row_map):
        result = planner.assess(schedule, witnesses=True)
        exp["check"](result.guaranteed and len(result.witnesses) == 1, (family,n))
        return tuple(row_map[int(i)] for i in result.witnesses[0])

    methods = {"package": lambda: assess(plan, schedule, range(len(rows))), "highs_delete": highs_core}
    if family == "shards44":
        reduced, qs = exp["planner"]([rows[i] for i in kept], [radii[i] for i in kept], baseline)
        reduced_schedule = dict.fromkeys(qs, n)
        methods["old_after_vacuous_filter"] = lambda: assess(reduced, reduced_schedule, kept)
    cores = {key: call() for key,call in methods.items()}
    for core in cores.values():
        exp["check"](not feasible(core) and all(feasible([x for x in core if x != j]) for j in core), core)
    samples = {key: [] for key in methods}
    for trial in range(5):
        order = list(methods) if trial % 2 == 0 else list(reversed(methods))
        for key in order:
            start = perf_counter()
            result = methods[key]()
            elapsed = (perf_counter()-start)*1000
            exp["check"](result == cores[key], (key, result))
            samples[key].append(round(elapsed, 4))
    return {"family": family, "repeats": n, "nonvacuous": len(kept), "core_rows": cores, "ms": samples,
            "median_ms": {key: median(values) for key,values in samples.items()}}


if __name__ == "__main__":
    with TemporaryDirectory() as tmp:
        baseline = load_old(Path(tmp))
        print(json.dumps({"python": platform.python_version(), "scipy": scipy.__version__,
                          "results": [compare(family, n, baseline) for family in ("shards44","cycles13")
                                      for n in (1,9,1_000_001)]}, indent=2))
