"""Choose the next unit-cost consent probe and certify the exact worst-case depth."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from consent_audit import audit


def recommend(problem):
    result = audit(problem)
    if any(item["cost"] != 1 for item in problem["menu"]):
        raise ValueError("sequential minimax probe counts require unit cost for every menu entry")
    state = result["without_monotonicity"]
    status = state["status"]
    if status == "outside_comparison_domain":
        return {"status": status}
    if status == "safe_baseline_refuted":
        return {"status": status, "alternative_consistency": "unchecked", "next_probe": None}
    if status == "safe_through_bound":
        return {"status": status, "worst_case_probes": 0, "next_probe": None}

    batch = state["additional_plan"]
    if batch["status"] == "menu_insufficient":
        return {"status": "menu_insufficient", "witness": batch, "next_probe": None}

    # When the all-refusal baseline survives, the unbounded tail agrees with it on all past rows.
    remaining = problem["errors"] - result["thresholds"][-1]["errors"]
    points = sum(band["last"] - band["first"] + 1 for band in state["singletons"])
    fixed = state["necessary_observations"]
    clean = fixed - points * remaining
    price = state["singletons"][-1]["last"]
    probe = next(item for item in problem["menu"]
                 if item["low"] == item["high"] == price and item["capacity"] > 0)
    quotas = []
    for band in state["singletons"]:
        each = band["required_each"] - remaining
        if quotas and quotas[-1]["each"] == each and quotas[-1]["last"] + 1 == band["first"]:
            quotas[-1]["last"] = band["last"]
        else:
            quotas.append({"first": band["first"], "last": band["last"], "each": each})
    return {
        "status": "unresolved",
        "remaining_baseline_errors": remaining,
        "live_singletons": points,
        "clean_refusal_quotas": quotas,
        "clean_refusal_probes": clean,
        "worst_case_probes": clean + remaining,
        "fixed_batch_probes": fixed,
        "next_probe": {"name": probe["name"], "offer": price},
    }


def observe(problem, name, bits):
    """Return a new input after one named menu trial. The caller supplies the joint log."""
    if bits not in ("00", "01", "10", "11"):
        raise ValueError("expected request and effect as two bits, e.g. 10")
    item = next((entry for entry in problem["menu"] if entry["name"] == name), None)
    if item is None or item["capacity"] == 0:
        raise ValueError(f"unknown or exhausted menu entry: {name}")
    row = {"consent": False, "low": item["low"], "high": item["high"],
           "request": bits[0] == "1", "effect": bits[1] == "1"}
    menu = [{**entry, "capacity": entry["capacity"] - 1} if entry["name"] == name else entry
            for entry in problem["menu"]]
    return {**problem, "history": [*problem["history"], row], "menu": menu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("--record", nargs=2, action="append", default=[], metavar=("NAME", "BITS"),
                        help="append a past menu probe; repeat in chronological order")
    args = parser.parse_args()
    try:
        current = json.loads(args.problem.read_text(encoding="utf-8"))
        answer = recommend(current)
        for probe_name, reading in args.record:
            current = observe(current, probe_name, reading)
            answer = recommend(current)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(answer, indent=2))
