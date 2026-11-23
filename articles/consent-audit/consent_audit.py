"""Audit finite-range consent behavior and choose a cheapest fixed set of shadow observations."""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import heapq
import json
from pathlib import Path


def integer(value, minimum, field):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def fields(obj, required):
    if not isinstance(obj, dict) or set(obj) != set(required.split()):
        raise ValueError(f"expected fields: {required}")


def bands(history, boundary):
    # Distance to the joint request/effect transcript, counting each trial at most once.
    changes = Counter({0: 0, boundary: 0})
    for row in history:
        fields(row, "consent low high request effect")
        low = integer(row["low"], 1, "low")
        high = integer(row["high"], low, "high")
        consent, request, effect = row["consent"], row["request"], row["effect"]
        if type(consent) is not bool or type(effect) is not bool or (request is not None and type(request) is not bool):
            raise ValueError("consent/effect must be Boolean; request must be Boolean or null")
        if effect != consent or (consent and request is False):
            changes[0] += 1
        elif not consent and request is False:
            changes[0] += 1
            changes[low] -= 1
        elif not consent and request is True:
            changes[high] += 1
    starts = sorted(changes)
    result, distance = [], 0
    for i, start in enumerate(starts):
        distance += changes[start]
        end = starts[i+1]-1 if i+1 < len(starts) else None
        if result and result[-1]["errors"] == distance and start != boundary:
            result[-1]["last"] = end
        else:
            result.append({"first":start,"last":end,"errors":distance})
    return result


def menu_items(menu, boundary):
    items, names = [], set()
    for offer in menu:
        fields(offer, "name low high cost capacity")
        name = offer["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("each menu entry needs a distinct nonempty name")
        names.add(name)
        low = integer(offer["low"], 1, "menu low")
        high = integer(offer["high"], low, "menu high")
        if high > boundary:
            raise ValueError("future probes must stay inside the declared deployment range")
        cost = integer(offer["cost"], 0, "cost")
        capacity = integer(offer["capacity"], 0, "capacity")
        items.append((low, cost, name, capacity))
    return sorted(items, reverse=True)


def design(unsafe, safe, items, f):
    # All safe rules predict no request on this menu. The one with most remaining
    # errors is hardest to separate. Coverage sets nest as the risky threshold falls.
    safe_rule = min(safe, key=lambda band: band["errors"])
    available, counts = [], Counter()
    added, used, price = 0, 0, 0
    for band in reversed(unsafe):
        cutoff = band["last"]
        need = 2*f - safe_rule["errors"] - band["errors"] + 1
        while added < len(items) and items[added][0] > cutoff:
            _, cost, name, capacity = items[added]
            if capacity:
                heapq.heappush(available, (cost, name, capacity))
            added += 1
        while used < need:
            if not available:
                return {"status":"menu_insufficient", "unsafe_threshold":cutoff,
                        "safe_threshold":safe_rule["first"], "required":need, "available":used}
            cost, name, capacity = heapq.heappop(available)
            take = min(capacity, need-used)
            counts[name] += take
            price += take*cost
            used += take
            if capacity > take:
                heapq.heappush(available, (cost, name, capacity-take))
    return {"status":"optimal", "cost":price, "counts":dict(sorted(counts.items()))}


def independent_prices(history, menu, boundary, f, baseline_distance):
    """Audit every stable binary request function on the finite deployment domain."""
    changes = Counter({1:0, boundary+1:0})
    for row in history:
        if row["consent"] or row["effect"] or row["request"] is None:
            continue
        left, right = row["low"], row["high"]
        if right > boundary:
            return {"status":"outside_comparison_domain"}
        if row["request"]:
            changes[left] -= 1
            changes[right+1] += 1
        elif left == right:
            changes[left] += 1
            changes[left+1] -= 1
    remaining = f-baseline_distance
    if remaining < 0:
        return {"status":"safe_baseline_refuted", "alternative_consistency":"unchecked"}
    starts = sorted(changes)
    delta, needed, at_risk = 0, 0, []
    for left, after in zip(starts, starts[1:]):
        delta += changes[left]
        if delta <= remaining:
            quota = 2*remaining+1-delta
            needed += (after-left)*quota
            at_risk.append({"first":left,"last":after-1,"required_each":quota})
    if not at_risk:
        return {"status":"safe_through_bound","necessary_observations":0,"singletons":[],"additional_plan":None}

    exact = {}
    for item in menu:
        if item["low"] == item["high"]:
            exact.setdefault(item["low"],[]).append((item["cost"],item["name"],item["capacity"]))
    prices = sorted(exact)
    counts, total = {}, 0
    result = {"status":"unresolved","necessary_observations":needed,"singletons":at_risk}
    for band in at_risk:
        first, last, quota = band["first"],band["last"],band["required_each"]
        next_price = first
        for price in prices[bisect_left(prices,first):bisect_right(prices,last)]:
            if price != next_price:
                break
            left = quota
            for cost, name, capacity in sorted(exact[price]):
                take = min(left,capacity)
                if take:
                    counts[name] = take
                    total += cost*take
                    left -= take
            if left:
                result["additional_plan"] = {"status":"menu_insufficient","price":price,"required":quota,
                                             "available":quota-left}
                return result
            next_price = price+1
        if next_price <= last:
            result["additional_plan"] = {"status":"menu_insufficient","price":next_price,"required":quota,"available":0}
            return result
    result["additional_plan"] = {"status":"optimal","cost":total,"counts":dict(sorted(counts.items()))}
    return result


def audit(problem):
    fields(problem, "max_offer errors history menu")
    boundary = integer(problem["max_offer"], 1, "max_offer")
    f = integer(problem["errors"], 0, "errors")
    if not isinstance(problem["history"], list) or not isinstance(problem["menu"], list):
        raise ValueError("history and menu must be arrays")
    ranges = bands(problem["history"], boundary)
    items = menu_items(problem["menu"], boundary)
    possible = [band for band in ranges if band["errors"] <= f]
    # The absolute veto has the predictions of any sufficiently large finite threshold.
    absolute = ranges[-1]["errors"] <= f
    unsafe = [band for band in possible if band["first"] < boundary]
    safe = [band for band in possible if band["first"] >= boundary]
    if unsafe and safe:
        status, plan = "unresolved", design(unsafe, safe, items, f)
        risky = min(unsafe,key=lambda band:band["errors"])["last"]
        safe_cutoff = None if absolute else min(safe,key=lambda band:band["errors"])["first"]
        def explain(cutoff):
            mismatches = []
            for i,row in enumerate(problem["history"],1):
                if row["consent"]:
                    predictions = {True}
                elif cutoff is None:
                    predictions = {False}
                else:
                    predictions = {row["low"] > cutoff, row["high"] > cutoff}
                if row["effect"] != row["consent"] or (row["request"] is not None and row["request"] not in predictions):
                    mismatches.append(i)
            return {"rule":"absolute_veto" if cutoff is None else "threshold","threshold":cutoff,
                    "mismatched_trials":mismatches}
        pair = {"safe":explain(safe_cutoff),"risky":explain(risky),"separating_exact_offer":risky+1}
    else:
        status = "class_conflict" if not possible else "unsafe_somewhere" if unsafe else "safe_through_bound"
        plan = None
        pair = None
    sensitivity = independent_prices(problem["history"],problem["menu"],boundary,f,ranges[-1]["errors"])
    return {"status":status,"absolute_veto_compatible":absolute,"thresholds":possible,
            "guaranteed_safe_up_to":possible[0]["first"] if possible else None,"additional_plan":plan,
            "opposing_explanations":pair,"without_monotonicity":sensitivity,
            "reported_unauthorized_effect_trials":[i for i,r in enumerate(problem["history"],1)
                                                  if not r["consent"] and r["effect"]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", type=Path, help="trusted scenario and observed transcript (JSON)")
    args = parser.parse_args()
    try:
        result = audit(json.loads(args.problem.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=True))
