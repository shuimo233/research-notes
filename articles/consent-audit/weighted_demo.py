"""Audit sealed synthetic trace files, counting the exact number of bytes read to verify selected segments."""

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import sklearn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learned_demo import collect, fit_models
from sequential import observe
from weighted import recommend


PAYOFFS = (1, 4, 8)
UNIT = 64


def pack(offer, bits, size):
    payload = json.dumps({"offer": offer, "bits": bits}, separators=(",", ":")).encode("ascii")
    return payload.ljust(size - 1, b" ") + b"\n"


def run_archive(model, root, flip):
    source = Path(__file__).with_name("weighted-example.json")
    problem = json.loads(source.read_text(encoding="utf-8"))
    records = collect(model, root / "history.db", offers=PAYOFFS, consents=[False])
    problem["history"] = [{**record, "low": i, "high": i} for i, record in enumerate(records, 1)]

    inventory = {}
    truth_by_name = {}
    for item in problem["menu"]:
        i, name = item["low"], item["name"]
        actual, = collect(model, root / (name + ".db"), offers=[PAYOFFS[i-1]], consents=[False])
        truth = f'{int(actual["request"])}{int(actual["effect"])}'
        seen = f'{1-int(truth[0])}{truth[1]}' if name == flip else truth
        path = root / (name + ".log")
        content = pack(i, seen, UNIT * item["cost"])
        path.write_bytes(content)
        inventory[name] = (path, sha256(content).digest())
        truth_by_name[name] = truth
        item["cost"] = path.stat().st_size

    initial = recommend(problem)
    trace = []
    while True:
        decision = recommend(problem)
        if decision["status"] != "unresolved":
            break
        probe = decision["next_probe"]
        name = probe["name"]
        path, digest = inventory[name]
        raw = path.read_bytes()
        if sha256(raw).digest() != digest or len(raw) != probe["cost"]:
            raise RuntimeError("archive manifest mismatch")
        event = json.loads(raw)
        if event["offer"] != probe["offer"]:
            raise RuntimeError("offer differs from trusted metadata")
        trace.append({"file": name, "payoff": PAYOFFS[event["offer"]-1], "bytes_read": len(raw),
                      "actual_bits": truth_by_name[name], "observed_bits": event["bits"]})
        problem = observe(problem, name, event["bits"])
    spent = sum(t["bytes_read"] for t in trace)
    if spent > initial["worst_case_cost"]:
        raise RuntimeError("observed use exceeded the certified budget")
    return {"historical_requests": [r["request"] for r in records], "flipped_file": flip, "decision": decision["status"],
            "fixed_batch_bytes": initial["fixed_batch_cost"], "worst_case_bytes": initial["worst_case_cost"],
            "actual_bytes": spent, "trace": trace}


def run():
    _, _, models = fit_models()
    results = {}
    with TemporaryDirectory() as tmp:
        for name, flip in (("tree", None), ("tree", "mid-a"), ("logistic", None)):
            label = name + ("_one_log_flip" if flip else "_clean")
            directory = Path(tmp) / label
            directory.mkdir()
            results[label] = run_archive(models[name], directory, flip)
    return {"sqlite": sqlite3.sqlite_version, "sklearn": sklearn.__version__, "payoffs": PAYOFFS, "runs": results}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
