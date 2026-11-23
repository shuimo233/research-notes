"""Independent explicit codeword / menu enumeration. Standard library only."""

from collections import Counter
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from consent_audit import audit


def signs(mask, low, high, consent):
    return {True} if consent else {bool(mask & (1 << (b-1))) for b in range(low,high+1)}


def history_cost(mask, history):
    errors = 0
    for row in history:
        options = signs(mask,row["low"],row["high"],row["consent"])
        fits = any((row["request"] is None or row["request"] == q) and row["effect"] == (q and row["consent"])
                   for q in options)
        errors += int(not fits)
    return errors


@lru_cache(maxsize=2048)
def reported_words(mask, intervals, errors):
    # 0,1,2,3 encode (attempt, effect). A corrupt episode may alter either or both bits.
    possible = [{2*int(q) for q in signs(mask,low,high,False)} for low,high in intervals]
    return frozenset(w for w in product(range(4),repeat=len(intervals))
                     if sum(v not in ok for v,ok in zip(w,possible)) <= errors)


def oracle(p, arbitrary):
    b, f = p["max_offer"],p["errors"]
    full = (1 << b)-1
    masks = range(full+1) if arbitrary else [full ^ ((1 << c)-1) for c in range(b+1)]
    costs = {m:history_cost(m,p["history"]) for m in masks}
    live = {m:f-c for m,c in costs.items() if c<=f}
    if not live:
        return "class_conflict", {}, []
    if 0 not in live:
        return "unsafe_somewhere", {}, live
    if len(live)==1:
        return "safe_through_bound", {}, live
    valid = {}
    for plan in product(*(range(q["capacity"]+1) for q in p["menu"])):
        intervals = tuple((item["low"],item["high"]) for n,item in zip(plan,p["menu"]) for _ in range(n))
        safe = reported_words(0, intervals,live[0])
        if all(safe.isdisjoint(reported_words(m,intervals,left)) for m,left in live.items() if m):
            valid[plan] = sum(n*q["cost"] for n,q in zip(plan,p["menu"]))
    return "unresolved",valid,live


def exercise(p, totals):
    result = audit(p)
    for arbitrary in (False,True):
        answer = result["without_monotonicity"] if arbitrary else result
        status, plans, live = oracle(p,arbitrary)
        if arbitrary and status in ("class_conflict","unsafe_somewhere"):
            assert answer["status"] == "safe_baseline_refuted"
            continue
        assert answer["status"] == status,(p,answer,status)
        if not arbitrary:
            b = p["max_offer"]
            for threshold in range(b+2):
                mask = ((1 << b)-1) ^ ((1 << min(threshold,b))-1)
                expected = history_cost(mask,p["history"])
                matching = [t for t in result["thresholds"] if t["first"]<=threshold and
                            (t["last"] is None or threshold<=t["last"])]
                assert [t["errors"] for t in matching] == ([expected] if expected<=p["errors"] else [])
            pair = result["opposing_explanations"]
            if pair:
                price = pair["separating_exact_offer"]
                assert 1 <= price <= b and price > pair["risky"]["threshold"]
                for label in ("safe","risky"):
                    c = pair[label]["threshold"]
                    m = 0 if c is None else full_mask_above(c,b)
                    assert len(pair[label]["mismatched_trials"]) == history_cost(m,p["history"]) <= p["errors"]
        if status == "unresolved":
            plan = answer["additional_plan"]
            if not plans:
                assert plan["status"] == "menu_insufficient"
            else:
                counts = tuple(plan["counts"].get(item["name"],0) for item in p["menu"])
                assert plans[counts] == plan["cost"] == min(plans.values()),(p,plan,plans)
            totals[("arbitrary" if arbitrary else "threshold")+("_optimal" if plans else "_insufficient")] += 1


def full_mask_above(c,b):
    return ((1 << b)-1)^((1 << min(c,b))-1)


def quota_control():
    # Independent optimization over every subset and every exact-price multiplicity, with f=1.
    b, f = 3, 1
    row_types = [{"low":l,"high":h,"consent":False,"effect":False,"request":q}
                 for l in range(1,4) for h in range(l,4) for q in (False,True)]
    n = 0
    for x,y in product(row_types,repeat=2):
        history = [x,y]
        d = [history_cost(mask,history) for mask in range(1 << b)]
        if d[0]>f:
            continue
        menu = [{"name":str(i+1),"low":i+1,"high":i+1,"capacity":3,"cost":i+1} for i in range(b)]
        report = audit({"max_offer":b,"history":history,"errors":f,"menu":menu})["without_monotonicity"]
        valid = []
        for counts in product(range(4),repeat=b):
            if all(sum(counts[i] for i in range(b) if mask >> i & 1)>2*f-d[mask]-d[0]
                   for mask in range(1,1 << b) if d[mask]<=f):
                valid.append(sum((i+1)*v for i,v in enumerate(counts)))
        opt = report["additional_plan"]
        assert min(valid) == (0 if opt is None else opt["cost"]), (report,history)
        n += 1
    return n


def run():
    rng = Random(729114)
    totals = Counter()
    for trial in range(480):
        b = rng.randint(2,4)
        history = []
        for _ in range(rng.randint(0,5)):
            low = rng.randint(1,b)
            c = rng.randrange(4)==0
            history.append({"consent":c,"low":low,"high":rng.randint(low,b),"request":rng.choice([None,False,True]),
                            "effect":c if rng.randrange(6) else not c})
        menu = []
        for j in range(rng.randint(1,4)):
            low = rng.randint(1,b)
            menu.append({"name":str(j),"low":low,"high":rng.randint(low,b),"cost":rng.randint(0,5),"capacity":1})
        exercise({"max_offer":b,"errors":rng.randrange(3),"history":history,"menu":menu},totals)
    # Exact two-price menu, all joint history log bits, with repeated and imprecise menu entries.
    menu = [{"name":str(i),"low":lo,"high":hi,"cost":cost,"capacity":count}
            for i,(lo,hi,cost,count) in enumerate([(1,1,2,1),(2,2,3,2),(1,2,1,1)])]
    grid = 0
    for a,b,f in product(range(4),range(4),range(3)):
        rows = [{"low":i,"high":i,"consent":False,"request":bool(x&2),"effect":bool(x&1)}
                for i,x in ((1,a),(2,b))]
        exercise({"max_offer":2,"history":rows,"menu":menu,"errors":f},totals)
        grid += 1
    # Noncontiguous version space, mixed-cost optimum, and a domain too large to expand.
    def row(b, q):
        return {"consent":False,"low":b,"high":b,"request":q,"effect":False}
    split = audit({"max_offer":9,"history":[row(2,True),row(7,False)],"errors":1,"menu":[]})
    assert [(r["first"],r["last"]) for r in split["thresholds"]] == [(0,1),(7,8),(9,None)]
    impossible = audit({"max_offer":9,"history":[row(2,True),row(7,False)],"errors":0,"menu":[]})
    assert impossible["status"] == "class_conflict"
    # A rule safe through 5 can fit the historical request at 10 better than the absolute veto.
    top = {"name":"top","low":5,"high":5,"cost":1,"capacity":3}
    wider = audit({"max_offer":5,"history":[row(10,True)],"errors":1,"menu":[top]})
    assert wider["additional_plan"] == {"status":"optimal","cost":3,"counts":{"top":3}}
    assert wider["without_monotonicity"]["status"] == "outside_comparison_domain"
    all_prices = [{"name":str(i),"low":i,"high":i,"cost":1,"capacity":3} for i in range(1,21)]
    unobserved = audit({"max_offer":20,"history":[],"errors":1,"menu":all_prices})
    assert unobserved["additional_plan"]["cost"] == 3
    assert unobserved["without_monotonicity"]["additional_plan"]["cost"] == 60
    sample = json.loads(Path(__file__).with_name("example.json").read_text(encoding="utf-8"))
    ex = audit(sample)
    assert ex["additional_plan"] == {"status":"optimal","cost":6,"counts":{"low":1,"high":1}}
    huge = audit({"max_offer":10**18,"history":[],"errors":2,"menu":[]})
    assert huge["without_monotonicity"]["necessary_observations"] == 5*10**18
    return {"seed":729114,"random_problems":480,"joint_log_grid":grid,"arbitrary_quota_control":quota_control(),
            "compared_designs":dict(totals),
            "large_domain":"1000000000000000000","mixed_plan":ex["additional_plan"]}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2,sort_keys=True))
