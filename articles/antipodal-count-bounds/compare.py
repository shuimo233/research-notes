"""Optional SciPy comparison and time-limited paired measurements against the actual 0.4.0."""

import importlib.util
import json
import multiprocessing as mp
from pathlib import Path
import platform
import runpy
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

exp = runpy.run_path(str(Path(__file__).with_name("experiment.py")))


def old_api(directory):
    folder = Path(directory)
    for f in ("__init__.py","core.py","action.py","_layer.py","audit.py"):
        ref = "621f118:packages/stateful-identification/stateful_id/" + f
        (folder/f).write_bytes(subprocess.check_output(["git","show",ref],cwd=exp["ROOT"]))
    spec = importlib.util.spec_from_file_location("old_sid",folder/"__init__.py",submodule_search_locations=[str(folder)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def planted(rows,sizes,radii):
    """Recognize the complete even-parity fixture from the input, without its hidden center."""
    d, h = len(sizes),len(rows)
    if len(set(rows)) != h or h != 2**(d-1) or any(sum(row)%2 for row in rows):
        return None
    center = []
    for j,n in enumerate(sizes):
        diff = sum(r if row[j] else -r for r,row in zip(radii,rows))
        slope, rem = divmod(2*diff,h)
        a = (n-slope-1)//2
        if rem or n-slope != 2*a+1 or not 0 <= a < n:
            return None
        center.append(a)
    if any(exp["distance"](row,sizes,[a+1-b for a,b in zip(center,row)])-2 != r for row,r in zip(rows,radii)):
        return None
    return tuple(range(h))


def worker(pipe, n, method, extract, folder):
    rows,sizes,radii,_ = exp["fixture"](n)
    api = old_api(folder) if method == "0.4" else exp["sid"]
    if method == "two_only":
        api.action.four_intervals = lambda cols, _: [(0,v) for v in cols.values()]
    p,schedule = exp["planner"](rows,sizes,radii,api)
    pipe.send("ready")
    for _ in range(3):
        start = perf_counter()
        if method == "planted":
            success = planted(rows,sizes,radii) == tuple(range(len(rows)))
        else:
            result = p.assess(schedule,witnesses=extract)
            success = result.guaranteed and (not extract or len(result.witnesses[0]) == len(rows))
        elapsed = (perf_counter()-start)*1000
        exp["check"](success,method)
        pipe.send(round(elapsed,4))
    pipe.close()


def timed(n,method,extract):
    with TemporaryDirectory() as tmp:
        rx,tx = mp.Pipe(duplex=False)
        proc = mp.Process(target=worker,args=(tx,n,method,extract,tmp))
        proc.start()
        tx.close()
        data = []
        try:
            exp["check"](rx.poll(45) and rx.recv() == "ready", "setup")
            for _ in range(3):
                if not rx.poll(2):
                    break
                data.append(rx.recv())
        finally:
            if len(data)<3 and proc.is_alive():
                proc.terminate()
            proc.join()
            rx.close()
        return {"ms":data,"median_ms":median(data) if len(data)==3 else None}


def irregular(*, minimal_control=False):
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy import __version__ as version
    cases = []
    for case in range(18):
        rows,sizes,radii = exp["jitter"](case)
        p,schedule = exp["planner"](rows,sizes,radii)
        a = np.asarray(rows)
        directions, rhs = 1-2*a, np.array(radii)-a @ np.asarray(sizes)
        affine = np.column_stack([np.ones(len(rows)),a])
        is_affine = np.linalg.matrix_rank(affine) == np.linalg.matrix_rank(np.column_stack([affine,radii]))
        def solve(ids):
            idx = list(ids)
            result = milp(c=np.zeros(len(sizes)),integrality=np.ones(len(sizes)),bounds=Bounds(0,sizes),
                          constraints=LinearConstraint(directions[idx],-np.inf,rhs[idx]),options={"time_limit":5})
            if result.status == 2:
                return False
            exp["check"](result.status == 0,(case,result.message))
            z = [round(float(x)) for x in result.x]
            exp["check"](all(0<=x<=n for x,n in zip(z,sizes)) and all(
                exp["distance"](rows[i],sizes,z)<=radii[i] for i in idx),(case,z))
            return True
        if minimal_control:
            ids = list(range(len(rows)))
            if solve(ids):
                continue
            samples = []
            for _ in range(3):
                start = perf_counter()
                core = ids[:]
                for i in ids:
                    smaller = [j for j in core if j != i]
                    if not solve(smaller):
                        core = smaller
                samples.append(round((perf_counter()-start)*1000,4))
            exp["check"](not solve(core) and all(solve([j for j in core if j!=i]) for i in core),case)
            cases.append({"case":case,"core_rows":core,"highs_deletion_ms":samples})
            continue
        # Paired microtimes on the same fixed table; model data prepared above.
        timings = {"framework":[],"highs":[]}
        all_ids = list(range(len(rows)))
        for trial in range(4):
            order = list(timings) if trial%2 == 0 else list(reversed(timings))
            for method in order:
                start = perf_counter()
                result = p.assess(schedule) if method == "framework" else solve(all_ids)
                dt = (perf_counter()-start)*1000
                if trial:
                    timings[method].append(round(dt,4))
                if method == "framework":
                    assessment = result
                else:
                    feasible = result
            exp["check"](assessment.guaranteed != feasible,case)
        start = perf_counter()
        cert = p.assess(schedule,witnesses=True)
        extract = (perf_counter()-start)*1000
        if cert.guaranteed:
            core = [int(s) for s in cert.witnesses[0]]
            exp["check"](not solve(core) and all(solve([v for v in core if v!=i]) for i in core), case)
        else:
            z = list(dict(cert.counterexample_ones).values())
            exp["check"](all(exp["distance"](r,sizes,z)<=lim for r,lim in zip(rows,radii)),case)
        start = perf_counter()
        prob,claim = p.audit(schedule,count_hints=True,minimal=False)
        made = (perf_counter()-start)*1000
        start = perf_counter()
        checked = exp["verify"](prob,claim,max_nodes=4000)
        verified_ms = (perf_counter()-start)*1000
        exp["check"](checked.status == "verified" and claim["guaranteed"] == (not feasible), case)
        cases.append({"case":case,"rows":len(rows),"affine":bool(is_affine),"feasible":feasible,
                      "core_size":len(core) if cert.guaranteed else None,"methods":cert.methods,"ms":timings,
                      "framework_witness_ms":round(extract,4),"guarantee_export_ms":round(made,4),
                      "independent_check_ms":round(verified_ms,4),"independent_nodes":checked.nodes})
    return version,cases


if __name__ == "__main__":
    if sys.argv[1:] == ["--minimal-control"]:
        version, controls = irregular(minimal_control=True)
        print(json.dumps({"scipy":version,"cases":controls},indent=2))
        raise SystemExit
    scipy, cases = irregular()
    measurements = []
    for n in (9,100_001):
        for extract in (False,True):
            measurements.append({"n":n,"witnesses":extract,
                                 "times":{m:timed(n,m,extract) for m in ("0.4","two_only","0.5","planted")}})
    print(json.dumps({"python":platform.python_version(),"scipy":scipy,"machine":platform.machine(),
                      "per_sample_timeout_seconds":2,"parity":measurements,"irregular":cases},indent=2))
