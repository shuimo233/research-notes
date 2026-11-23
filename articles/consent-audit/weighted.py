"""Minimize worst-case sequential audit cost with independent, finitely stocked price tiers."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from consent_audit import audit
from sequential import observe


def cheapest(tiers, count):
    total = 0
    for cost, name, capacity in tiers:
        if count == 0:
            return total
        take = min(count, capacity)
        total += cost * take
        count -= take
    if count:
        raise ValueError("insufficient exact trial stock")
    return total


def recommend(problem):
    result = audit(problem)
    state = result["without_monotonicity"]
    status = state["status"]
    if status == "outside_comparison_domain":
        return {"status": status}
    if status == "safe_baseline_refuted":
        return {"status": status, "alternative_consistency": "unchecked", "next_probe": None}
    if status == "safe_through_bound":
        return {"status": status, "worst_case_cost": 0, "next_probe": None}
    fixed = state["additional_plan"]
    if fixed["status"] == "menu_insufficient":
        return {"status": "menu_insufficient", "witness": fixed, "next_probe": None}

    remaining = problem["errors"] - result["thresholds"][-1]["errors"]
    exact = defaultdict(list)
    for item in problem["menu"]:
        if item["low"] == item["high"] and item["capacity"]:
            exact[item["low"]].append((item["cost"], item["name"], item["capacity"]))
    order = []
    for band in state["singletons"]:
        q = band["required_each"] - remaining
        # Feasibility already implies one stocked menu entry per coordinate in these ranges.
        for i in range(band["first"], band["last"] + 1):
            tiers = sorted(exact[i])
            clean = cheapest(tiers, q)
            extra = cheapest(tiers, q + remaining) - clean
            saved = clean - cheapest(tiers, max(0, q - remaining))
            order.append({"offer": i, "clean_quota": q, "clean_cost": clean,
                          "extra_cost": extra, "avoidable_cost": saved,
                          "name": tiers[0][1], "next_cost": tiers[0][0]})
    order.sort(key=lambda entry: (-entry["extra_cost"], entry["offer"]))
    later_savings = 0
    for entry in reversed(order):
        entry["extra_less_later_savings"] = entry["extra_cost"] - later_savings
        later_savings += entry["avoidable_cost"]
    pivot = max(order, key=lambda entry: entry["extra_less_later_savings"])
    clean_total = sum(entry["clean_cost"] for entry in order)
    first = order[0]
    return {"status": status, "remaining_baseline_errors": remaining, "clean_cost": clean_total,
            "worst_case_cost": clean_total + pivot["extra_less_later_savings"],
            "fixed_batch_cost": fixed["cost"], "worst_pivot_for_order": pivot["offer"], "order": order,
            "next_probe": {"offer": first["offer"], "name": first["name"], "cost": first["next_cost"]}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path)
    parser.add_argument("--record", nargs=2, action="append", default=[], metavar=("NAME", "BITS"))
    args = parser.parse_args()
    try:
        problem = json.loads(args.problem.read_text(encoding="utf-8"))
        answer = recommend(problem)
        for name, bits in args.record:
            problem = observe(problem, name, bits)
            answer = recommend(problem)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(answer, indent=2))
