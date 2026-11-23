"""Small-instance oracle, expanding complete input vectors and all readable words independently of the planner."""

from collections import Counter
from functools import lru_cache
from itertools import combinations, product
import json
from math import inf
from pathlib import Path
from random import Random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from lineage import LineageAudit, hitting_cover, observe


def language(problem):
    coords = problem["conditions"]
    menu = problem["menu"]
    labels = {}
    detailed = {}
    for word in product((0,1),repeat=len(menu)):
        viable = set()
        for label, mapping in problem["layouts"].items():
            checks = [*problem["relations"], *(dict(q,bit=v) for q,v in zip(menu,word) if q["kind"] == "same")]
            if any((mapping[q["left"]] == mapping[q["right"]]) != q["bit"] for q in checks):
                continue
            reads = [*problem["history"], *(dict(q,bit=v) for q,v in zip(menu,word) if q["kind"] == "report")]
            for truth in product((0,1),repeat=len(coords)):
                bad = {mapping[q["source"]] for q in reads if q["bit"] != truth[coords.index(q["condition"])]}
                if len(bad) <= problem["fault_budget"]:
                    viable.add((label,truth,tuple(sorted(bad))))
        if viable:
            labels[word] = {any(t) for _,t,_ in viable}
            detailed[word] = viable
    return labels, detailed


def minimax(labels, costs):
    @lru_cache(maxsize=None)
    def solve(words, left):
        if len({v for w in words for v in labels[w]}) < 2:
            return 0
        return min((first(words,left,i) for i in left),default=inf)

    def first(words, left, i):
        rest = tuple(j for j in left if j != i)
        return costs[i] + max(solve(tuple(w for w in words if w[i]==b),rest) for b in (0,1))

    words, left = tuple(labels),tuple(range(len(costs)))
    value = solve(words,left)
    starts = [first(words,left,i) for i in left] if value != inf else []
    return value,starts


def check(problem, totals):
    labels, detailed = language(problem)
    menu = problem["menu"]
    value, starts = minimax(labels,[q["cost"] for q in menu])
    outputs = {v for values in labels.values() for v in values}
    expected = {frozenset():"inconsistent",frozenset({False}):"all_zero",frozenset({True}):"some_request"}
    status = expected.get(frozenset(outputs),"unidentifiable" if value == inf else "resolvable")
    engine = LineageAudit(problem)
    answer = engine.report()
    assert answer["status"] == status, (problem,status,answer)
    for left in engine.models:
        for right in engine.models:
            expected_pair = any(any(label==left and not any(t) for label,t,_ in states) and
                                any(label==right and any(t) for label,t,_ in states) for states in detailed.values())
            pair = engine.pair(left,right)
            assert (pair is not None) == expected_pair, (problem,left,right,pair)
            if pair:
                engine.verify(pair)
            totals["ordered_layout_pairs"] += 1
    if status == "resolvable":
        i = next(i for i,q in enumerate(menu) if q["name"]==answer["next_probe"])
        assert answer["worst_case_cost"] == value == starts[i], (problem,value,starts,answer)
    if status == "unidentifiable":
        w = answer["witness"]
        engine.verify(w)
        word = tuple(w["common_answers"][q["name"]] for q in menu)
        for target in ("all_zero","nonzero"):
            chosen = w[target]
            truth = tuple(int(c in chosen["requests_at"]) for c in problem["conditions"])
            assert any(truth) == (target=="nonzero")
            assert (chosen["layout"],truth,tuple(chosen["mismatching_roots"])) in detailed[word]
    totals[status] += 1
    totals["full_words"] += 2**len(menu)
    return answer


def graph_fixture(edges, left_count, right_count, a, b):
    f = max(a,b)+1
    graph = list(edges)
    nl,nr = left_count,right_count
    for _ in range(f-a):
        graph.extend((nl,nr+j) for j in range(2*f+1))
        nl,nr = nl+1,nr+2*f+1
    for _ in range(f-b):
        graph.extend((nl+j,nr) for j in range(2*f+1))
        nl,nr = nl+2*f+1,nr+1
    return {"conditions":["event"],"fault_budget":f,"history":[],"relations":[],
            "layouts":{"left":{str(i):str(u) for i,(u,v) in enumerate(graph)},
                       "right":{str(i):str(v) for i,(u,v) in enumerate(graph)}},
            "menu":[{"kind":"report","source":str(i),"condition":"event","name":str(i),"cost":1} for i in range(len(graph))]}


def graph_controls():
    n = 2
    all_edges = list(product(range(n),repeat=2))
    counts = Counter()
    for mask,a,b in product(range(1 << len(all_edges)),range(n+1),range(n+1)):
        edges = [e for i,e in enumerate(all_edges) if mask & (1 << i)]
        possible = any(all(u in l or v in r for u,v in edges)
                       for l in combinations(range(n),a) for r in combinations(range(n),b))
        p = graph_fixture(edges,n,n,a,b)
        claim = LineageAudit(p).report(feasibility_only=True)
        assert all(len(set(layout.values()))>2*p["fault_budget"] for layout in p["layouts"].values())
        assert (claim["status"]=="unidentifiable") == possible, (mask,a,b,claim)
        if possible:
            LineageAudit(p).verify(claim["witness"])
        counts[claim["status"]] += 1
    return dict(counts)


def run():
    totals = Counter()
    sample = json.loads(Path(__file__).with_name("lineage-example.json").read_text(encoding="utf-8"))
    report = check(sample,totals)
    assert (report["worst_case_cost"],report["next_probe"]) == (64,"receipt")
    empty = {**sample,"menu":[]}
    assert check(empty,totals)["status"]=="unidentifiable"
    for answer,status in [(1,"all_zero"),(0,"some_request")]:
        assert check(observe(sample,"receipt",answer),totals)["status"]==status
    alternate = {**sample,"menu":[{**q,"cost":192 if q["kind"]=="same" else 32} for q in sample["menu"]]}
    assert check(alternate,totals)["next_probe"]=="extra"
    mixed = json.loads(Path(__file__).with_name("lineage-mixed.json").read_text(encoding="utf-8"))
    labels,_ = language(mixed)
    mixed_value, starts = minimax(labels,[q["cost"] for q in mixed["menu"]])
    all_reports = check({**mixed,"menu":mixed["menu"][:-1]},totals)["worst_case_cost"]
    assert (mixed_value,starts,all_reports)==(8,[12,8,12,9],12)
    assert check(mixed,totals)["next_probe"]=="b"
    branch = [check(observe(mixed,"b",v),totals)["next_probe"] for v in (0,1)]
    assert branch==["receipt","a"]
    for prices in product((0,1,7),repeat=4):
        catalog = [{**q,"cost":c} for q,c in zip(mixed["menu"],prices)]
        check({**mixed,"menu":catalog},totals)
    # Independent semantic check for a forced-positive history at an optional coordinate, with the
    # forced bad root on the all-zero side already accounted for. Test all eight assignments.
    ternary = []
    for p,l,r in product((0,1),repeat=3):
        feasible = any((p or truth==1) and (l or common==0) and (r or common==truth)
                       for truth,common in product((0,1),repeat=2))
        assert bool(p or l or r)==feasible
        ternary.append(int(feasible))
    assert hitting_cover([7],1,0) is None
    rng = Random(110237)
    for _ in range(340):
        cs = list("xyz")[:rng.randint(1,3)]
        sources = list("abcd")[:rng.randint(2,4)]
        maps = {str(k):{s:str(rng.randrange(len(sources))) for s in sources} for k in range(rng.randint(1,3))}
        def entry():
            return {"source":rng.choice(sources),"condition":rng.choice(cs)}
        def same():
            x,y=rng.sample(sources,2)
            return {"left":x,"right":y}
        rel = [dict(same(),bit=rng.randrange(2)) for _ in range(rng.randrange(2))]
        history = [dict(entry(),bit=rng.randrange(2)) for _ in range(rng.randrange(7))]
        menu = [dict(dict(kind="same",**same()) if rng.randrange(3)==0 else dict(kind="report",**entry()),
                     name=str(i),cost=rng.randrange(6)) for i in range(rng.randrange(6))]
        check(dict(conditions=cs,layouts=maps,history=history,relations=rel,menu=menu,fault_budget=rng.randrange(3)),totals)
    for history_bits, checks in product(product((0,1),repeat=3),(False,True)):
        history = [dict(source=s,condition="b8",bit=b) for s,b in zip("abc",history_bits)]
        reports = [dict(kind="report",source=s,condition="b8",name=s,cost=i+1) for i,s in enumerate("ade")]
        check({**sample,"history":history,"menu":[*reports,*([sample["menu"][0]] if checks else [])]},totals)
    coords = [str(c) for c in range(256)]
    large = {**empty,"conditions":coords,"history":[{**q,"condition":c} for q in empty["history"] for c in coords]}
    engine = LineageAudit(large)
    w = engine.report(feasibility_only=True)["witness"]
    engine.verify(w)
    assert w["nonzero"]["requests_at"]==coords
    # A misattributed layout or an altered receipt response must fail standalone raw-witness verification.
    forged = {**w,"nonzero":{**w["nonzero"],"layout":w["all_zero"]["layout"]}}
    try:
        engine.verify(forged)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a false layout assignment")
    return {"seed":110237,"random_cases":340,"targeted_cases":9,"history_grid":16,"mixed_price_grid":81,
            "mixed":{"minimax":mixed_value,"receipt_first":starts[-1],"reports_only":all_reports,"after_b":branch},
            "local_ternary_truth_table":ternary,"large_witness_size":len(w["nonzero"]["requests_at"]),
            "oracle":dict(sorted(totals.items())),
            "two_by_two_reduction_controls":graph_controls()}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
