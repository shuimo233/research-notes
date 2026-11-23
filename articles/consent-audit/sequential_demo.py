"""Drive newly fitted models with the sequential auditor. Each probe executes against a fresh SQLite gate."""

import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import sklearn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learned_demo import collect, fit_models
from sequential import observe, recommend


def experiment(model, directory, flip_at, with_history=False):
    errors = 2 if with_history else 1
    recorded, actual_history = [], []
    if with_history:
        actual_history = collect(model, directory / "before.db", offers=[1, 8], consents=[False])
        recorded = [actual_history[0], {**actual_history[1], "low": 7, "high": 9}]
    problem = {"max_offer": 20, "errors": errors, "history": recorded, "menu": [
        {"name": str(i), "low": i, "high": i, "cost": 1, "capacity": 2*errors+1} for i in range(1, 21)]}
    initial = recommend(problem)
    trace = []
    while True:
        decision = recommend(problem)
        if decision["status"] != "unresolved":
            break
        probe = decision["next_probe"]
        step = len(trace) + 1
        offer = probe["offer"]
        row, = collect(model, directory / f"{step}.db", offers=[offer], consents=[False])
        truth = f'{int(row["request"])}{int(row["effect"])}'
        logged = f'{int(not row["request"])}{int(row["effect"])}' if step == flip_at else truth
        trace.append([offer, truth, logged, decision["worst_case_probes"]])
        problem = observe(problem, probe["name"], logged)
    if flip_at is not None and sum(actual != seen for _, actual, seen, _ in trace) != 1:
        raise RuntimeError("scheduled readout fault did not occur")
    return {"actual_history": actual_history, "recorded_history": recorded, "total_error_budget": errors,
            "initial_fixed": initial["fixed_batch_probes"], "initial_sequential": initial["worst_case_probes"],
            "injected_at": flip_at, "steps": len(trace), "decision": decision["status"],
            "actual_requests": sum(actual[0] == "1" for _, actual, _, _ in trace),
            "actual_effects": sum(actual[1] == "1" for _, actual, _, _ in trace), "trace": trace}


def run():
    _, _, models = fit_models()
    results = {}
    with TemporaryDirectory() as tmp:
        for name, model in models.items():
            # On a clean all-refusal path, step 40 is the final probe. Flip just its logged request bit.
            for mode, flip in (("clean", None), ("one_log_flip", 40 if name == "tree" else 2),
                               ("interval_history", None)):
                directory = Path(tmp) / f"{name}-{mode}"
                directory.mkdir()
                results[f"{name}_{mode}"] = experiment(model, directory, flip, mode == "interval_history")
    return {"sklearn": sklearn.__version__, "sqlite": sqlite3.sqlite_version,
            "trace_columns": ["offer", "actual_request_effect", "logged_request_effect", "bound_before_probe"],
            "runs": results}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True))
