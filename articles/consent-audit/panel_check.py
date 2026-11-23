"""Compare panels and learned constraints against explicit full words and every subcatalog."""

from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from math import comb
from pathlib import Path
from random import Random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from lineage_check import language
from panel import Panels
import pysat


def load(label):
    return json.loads(Path(__file__).with_name(label+".json").read_text(encoding="utf-8"))


def subsets(n):
    for size in range(n+1):
        yield from combinations(range(n),size)


def reference(problem):
    labels, detail = language(problem)
    outputs = set().union(*labels.values())
    terminal = {frozenset():"inconsistent",frozenset({False}):"all_zero",frozenset({True}):"some_request"}
    if frozenset(outputs) in terminal:
        return terminal[frozenset(outputs)],None,[],detail
    feasible = []
    for panel in subsets(len(problem["menu"])):
        by_projection = {}
        for word,classes in labels.items():
            key = tuple(word[i] for i in panel)
            by_projection.setdefault(key,set()).update(classes)
        if all(len(v)==1 for v in by_projection.values()):
            feasible.append(panel)
    if not feasible:
        return "unidentifiable",None,[],detail
    best = min(sum(problem["menu"][i]["cost"] for i in p) for p in feasible)
    return "optimal",best,feasible,detail


def check(problem, counts):
    status, price, feasible,_ = reference(problem)
    engine = Panels(problem)
    row_counts = {}
    for mode in ("one","quota"):
        result = engine.optimize(mode)
        assert result["status"]==status,(problem,result,status)
        verified_by = engine.verify(result)
        if status=="optimal":
            row_counts[mode] = len(result["premises"])
            if mode=="quota":
                counts["verified_"+verified_by]+=1
            indices = tuple(i for i,s in enumerate(engine.names) if s in result["panel"])
            assert result["cost"]==price and indices in feasible
            for premise in result["premises"]:
                rule = engine.compile(premise)
                assert all(rule.accepts(set(p)) for p in feasible)
                counts["premise_vs_feasible_panel"] += len(feasible)
    counts[status]+=1
    return row_counts


def check_directional_family(problem):
    engine = Panels(problem)
    _,detail = language(problem)
    count = matching_count = 0
    n = len(problem["conditions"])
    for left in engine.audit.models:
        for right,rm in engine.audit.models.items():
            for chosen in subsets(n):
                if not chosen:
                    continue
                support = [problem["conditions"][i] for i in chosen]
                l,r,gates,edges = engine.components(left,right,support)
                if max(len(l),len(r))>engine.audit.f:
                    continue
                premise = dict(zero=left,opposite=right,support=support,left_bad=sorted(l),right_bad=sorted(r))
                family = []
                lm = engine.audit.models[left]
                for group in subsets(len(lm.roots)):
                    bad = {lm.roots[i] for i in group}
                    if l<=bad and len(bad)<=engine.audit.f:
                        family.append(engine.compile(dict(premise,kind="right-quota",left_bad=sorted(bad))))
                exact_matching = engine.matching([(i,a,b) for i,a,b in edges if a not in l and b not in r])
                matching = engine.compile(dict(premise,kind="matching")) if exact_matching else None
                truth = tuple(int(i in chosen) for i in range(n))
                left_words = [w for w,worlds in detail.items() if any(k==left and not any(t) for k,t,_ in worlds)]
                right_words = [w for w,worlds in detail.items() if any(k==right and t==truth for k,t,_ in worlds)]
                for p in subsets(len(problem["menu"])):
                    a = {tuple(w[i] for i in p) for w in left_words}
                    b = {tuple(w[i] for i in p) for w in right_words}
                    separated = a.isdisjoint(b)
                    assert all(rule.accepts(set(p)) for rule in family)==separated
                    count+=1
                    if matching is not None:
                        assert matching.accepts(set(p))==separated
                        matching_count+=1
    return count,matching_count


def majority_problem(n,f):
    sources = {str(i):str(i) for i in range(n)}
    return dict(conditions=["x"],history=[],relations=[],fault_budget=f,layouts={"known":sources},
                menu=[dict(kind="report",source=s,condition="x",name=s,cost=1) for s in sources])


def check_rejections(engine, valid):
    def rejects(action):
        try:
            action()
        except ValueError:
            return
        raise AssertionError("modified certificate was accepted")
    rejects(lambda: engine.verify({**valid,"cost":valid["cost"]+1}))
    rejects(lambda: engine.verify({**valid,"single_rule_bound":valid["single_rule_bound"]+1}))
    rejects(lambda: engine.verify({**valid,"panel":[]}))
    rejects(lambda: engine.verify({**valid,"premises":[]}))
    for key,value in (("support",[]),("left_bad",["unknown"]),("right_bad",[])):
        changed = deepcopy(valid)
        changed["premises"][0][key] = value
        rejects(lambda: engine.verify(changed))
    rejects(lambda: engine.optimize(reuse=[]))
    rejects(lambda: Panels(majority_problem(1,0)).optimize(reuse=valid))


def run():
    counts = Counter()
    mixed, sample, double_star = [load(f) for f in ("lineage-mixed","lineage-example","lineage-ambiguous")]
    gate = dict(kind="same",left="a",right="b",cost=4,name="origin")
    crossing = {**double_star, "menu":[*double_star["menu"],gate]}
    parallel = majority_problem(3,1)
    parallel["menu"] += [{**parallel["menu"][0],"name":"copy","cost":0}]
    history = {**crossing,"conditions":["event","other"],
               "history":[dict(source="a",condition="other",bit=1),dict(source="d",condition="event",bit=0)]}
    history["menu"] = [*history["menu"],dict(kind="report",source="c",condition="other",name="other",cost=2)]
    for p in (mixed,sample,double_star,crossing,parallel,history):
        check(p,counts)
    pair_checks = [check_directional_family(p) for p in (mixed,sample,double_star,crossing,parallel,history)]
    topology_comparison = Counter()
    for left_pair in combinations("abcd",2):
        for right_pair in combinations("abcd",2):
            maps = {k:{s:("pair" if s in pair else s) for s in "abcd"}
                    for k,pair in (("L",left_pair),("R",right_pair))}
            receipt = {**gate,"left":left_pair[0],"right":left_pair[1]}
            for bridge_price in (0,3,9):
                menu = [*double_star["menu"],{**receipt,"cost":bridge_price}]
                rows = check({**double_star,"layouts":maps,"menu":menu},counts)
                diff = rows["quota"]-rows["one"]
                topology_comparison["fewer" if diff<0 else "more" if diff>0 else "equal"]+=1
    rng = Random(57709)
    for _ in range(160):
        cs = list("xy")[:rng.randint(1,2)]
        ss = list("abcd")[:rng.randint(2,4)]
        layouts = {str(i):{s:str(rng.randrange(len(ss))) for s in ss} for i in range(rng.randint(1,3))}
        def cell():
            return dict(source=rng.choice(ss),condition=rng.choice(cs))
        def relation():
            a,b = rng.sample(ss,2)
            return dict(left=a,right=b)
        menu = [dict(dict(kind="same",**relation()) if rng.randrange(4)==0 else dict(kind="report",**cell()),
                     name=str(i),cost=rng.randint(0,7)) for i in range(rng.randint(0,6))]
        p = dict(conditions=cs,layouts=layouts,menu=menu,fault_budget=rng.randrange(3),
                 history=[dict(**cell(),bit=rng.randrange(2)) for _ in range(rng.randrange(5))],
                 relations=[dict(**relation(),bit=rng.randrange(2)) for _ in range(rng.randrange(2))])
        check(p,counts)
    # Systematic cost changes keep the evidence structure fixed and exercise exact minimum selection.
    reprice_cases = 0
    initial = Panels(mixed).optimize()
    for i in range(len(mixed["menu"])):
        for price in (0,2,11,10**20):
            q = {**mixed,"menu":[{**p,"cost":price} if j==i else p for j,p in enumerate(mixed["menu"])]}
            check(q,counts)
            engine = Panels(q)
            reused = engine.optimize(reuse=initial)
            engine.verify(reused)
            assert reused["cost"] == reference(q)[1]
            reprice_cases+=1
    # A single expensive indispensable query tests exact arithmetic above 2**53.
    huge = majority_problem(1,0)
    huge["menu"][0]["cost"]=10**20+3
    check(huge,counts)
    controls = []
    for n,f in ((6,1),(8,2),(10,2)):
        engine = Panels(majority_problem(n,f))
        ordinary = engine.optimize("one")
        compact = engine.optimize()
        engine.verify(ordinary)
        engine.verify(compact)
        assert ordinary["cost"]==compact["cost"]==2*f+1
        assert len(ordinary["premises"])==comb(n,2*f) and len(compact["premises"])==1
        controls.append(dict(roots=n,f=f,minimum_cost=2*f+1,one_hit_rows=len(ordinary["premises"]),
                             cardinality_rows=len(compact["premises"])))
    clean = Panels(sample).optimize()
    check_rejections(Panels(sample),clean)
    switched = {**sample,"menu":[{**q,"cost":192 if q["kind"]=="same" else 32} for q in sample["menu"]]}
    after = Panels(switched).optimize(reuse=clean)
    Panels(switched).verify(after)
    assert (clean["panel"],after["panel"],after["candidate_checks"])==(["receipt"],["extra"],1)
    return {"pysat":pysat.__version__,"seed":57709,"oracle_scenarios":sum(counts[k] for k in
            ("optimal","unidentifiable","inconsistent","all_zero","some_request")),"oracle":dict(counts),
            "reprice_cases":reprice_cases,"directional_pair_panel_checks":sum(v for v,w in pair_checks),
            "matching_pair_panel_checks":sum(w for v,w in pair_checks),"majority_controls":controls,
            "four_alias_layout_price_grid":dict(topology_comparison),
            "repriced_fixture":{"initial":clean["panel"],"initial_cost":clean["cost"],"after":after["panel"],
                                "after_cost":after["cost"],"new_rows":len(after["premises"])-after["reused_constraints"]},
            "mixed_fixed":initial["cost"],"mixed_panel":initial["panel"]}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
