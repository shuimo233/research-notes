"""Independent small-instance oracle: enumerate every true vector and complete future report word."""

from collections import Counter
from functools import lru_cache
from itertools import product
import json
from math import inf
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_audit import SourceAudit


def check(problem, totals):
    conditions, menu = problem["conditions"], problem["menu"]
    names = problem["sources"]
    f = problem["fault_budget"]
    initial = [(names[r["source"]], conditions.index(r["condition"]), r["bit"]) for r in problem["history"]]
    cells = [(names[p["source"]], conditions.index(p["condition"])) for p in menu]
    inputs = tuple(product((0, 1), repeat=len(conditions)))

    def bad(truth, readings):
        return {source for source, condition, value in readings if truth[condition] != value}

    engine = SourceAudit(problem)
    if len(bad((0,)*len(conditions), initial)) <= f:
        candidates = [tuple((s >> j) & 1 for j in range(len(conditions))) for s in engine.risk_supports(engine.ones)]
        positive_roots = {r for r,i,v in initial if v}
        assert len(candidates) <= len(conditions) + 2**len(positive_roots) - 1
        for truth in inputs:
            forced = bad(truth, initial)
            if any(truth) and len(forced) <= f:
                assert any(all(a <= b for a,b in zip(y,truth)) and bad(y,initial) <= forced for y in candidates)
                totals["risk_worlds_with_subwitness"] += 1

    # Store the feasible labels for *every* full future word, including inconsistent rows from a bad source.
    labels = {}
    for word in product((0, 1), repeat=len(menu)):
        transcript = initial + [(root, i, value) for (root, i), value in zip(cells, word)]
        classes = frozenset(any(t) for t in inputs if len(bad(t, transcript)) <= f)
        if classes:
            labels[word] = classes
    root_words = tuple(labels)

    @lru_cache(maxsize=None)
    def solve(words, left):
        outputs = {o for word in words for o in labels[word]}
        if len(outputs) < 2:
            return 0
        if not left:
            return inf
        return min(first_cost(words, left, i) for i in left)

    def first_cost(words, left, i):
        rest = tuple(j for j in left if j != i)
        return menu[i]["cost"] + max(solve(tuple(w for w in words if w[i] == a), rest) for a in (0,1))

    outputs = {o for word in labels for o in labels[word]}
    expected = {frozenset(): "inconsistent", frozenset({False}): "all_zero", frozenset({True}): "some_request"}
    left = tuple(range(len(menu)))
    value = solve(root_words, left)
    status = expected.get(frozenset(outputs), "unidentifiable" if value == inf else "resolvable")
    report = engine.report()
    assert report["status"] == status, (problem, status, report)
    if status == "resolvable":
        idx = next(i for i in left if menu[i]["name"] == report["next_probe"])
        assert report["worst_case_cost"] == value == first_cost(root_words, left, idx), (problem, report, value)
    if status == "unidentifiable":
        witness = report["witness"]
        engine.verify_witness(witness)
        word = tuple(witness["common_future_bits"][p["name"]] for p in menu)
        assert labels[word] == {True, False}
        full = initial + [(r, i, v) for (r, i), v in zip(cells, word)]
        for label in ("all_zero", "nonzero"):
            world = witness[label]
            truth = tuple(int(c in world["requests_at"]) for c in conditions)
            assert bool(any(truth)) == (label == "nonzero")
            assert bad(truth, full) == set(world["mismatching_roots"])
            assert len(world["mismatching_roots"]) <= f
    totals[status] += 1
    totals["full_words_checked"] += 2 ** len(menu)
    totals["decision_tree_states"] += solve.cache_info().currsize
    return report


def sharp_lists():
    results = []
    for f in range(1,6):
        n = 2*f
        coords = [str(i) for i in range(n)]
        roots = [f"A{i}" for i in range(f)] + [f"B{i}" for i in range(f+1)]
        rows = [{"source":f"A{i//2}","condition":c,"bit":1} for i,c in enumerate(coords)]
        targets = [{i} for i in range(n)] + [
            {i for i in range(n) if mask & (1 << (i//2))} for mask in range(1,1 << f)]
        for target in targets:
            inner = 0 if len(target)==1 else len(target)//2
            queries = [(j,i) for i in range(n) for j in range(inner if i in target else f+1)]
            menu = [{"source":f"B{j}","name":f"{j}:{i}","condition":str(i),"cost":1} for j,i in queries]
            valid = []
            for x in product((0,1),repeat=n):
                # In the baseline all A roots are used up, so the only shared future word is all zeros.
                faulty = {f"A{i//2}" for i in range(n) if not x[i]} | {f"B{j}" for j,i in queries if x[i]}
                if len(faulty)<=f and any(x):
                    valid.append({i for i in range(n) if x[i]})
            assert valid == [target]
            p = {"sources":{r:r for r in roots},"conditions":coords,"menu":menu,"history":rows,"fault_budget":f}
            witness = SourceAudit(p).report(feasibility_only=True)["witness"]
            assert set(witness["nonzero"]["requests_at"]) == {str(i) for i in target}
            assert not any(witness["common_future_bits"].values())
        results.append({"fault_budget":f,"conditions":n,"individually_necessary_supports":len(targets)})
    return results


def run():
    totals = Counter()
    sample = json.loads(Path(__file__).with_name("source-example.json").read_text(encoding="utf-8"))
    resolved = check(sample, totals)
    assert (resolved["next_probe"], resolved["worst_case_cost"]) == ("verify-low",3)
    ambiguous = {**sample, "menu": sample["menu"][:1]}
    witness = check(ambiguous, totals)["witness"]
    assert witness["nonzero"]["requests_at"] == sample["conditions"]
    for forged in ({**witness,"common_future_bits":{}},
                   {**witness,"nonzero":{**witness["nonzero"],"mismatching_roots":[]}}):
        try:
            SourceAudit(ambiguous).verify_witness(forged)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid witness accepted")
    third = {**ambiguous, "conditions": [*sample["conditions"],"extra"],
             "menu": [*ambiguous["menu"],{**sample["menu"][1],"condition":"extra"}]}
    assert check(third, totals)["status"] == "unidentifiable"
    # One prior vote and two available votes. The old vote's root alone changes identifiability.
    one = {**sample, "conditions":["one"], "menu":[{"name":s,"source":s,"condition":"one","cost":v}
           for s,v in (("export",1),("authorization",3))]}
    prior_pair = {}
    for old in ("application","gateway"):
        p = {**one, "history":[{"condition":"one","source":old,"bit":0}]}
        prior_pair[old] = check(p, totals)["status"]
    assert prior_pair == {"application":"unidentifiable","gateway":"resolvable"}
    grid = 0
    for a,b,s,t,f in product((None,0,1),(None,0,1),("application","gateway"),
                             ("export","gateway","authorization"),(0,1,2)):
        past = [{"condition":"one","source":source,"bit":v} for v,source in ((a,"application"),(b,s)) if v is not None]
        menu = [{**one["menu"][0],"source":t},one["menu"][1]]
        check({**one,"history":past,"menu":menu,"fault_budget":f}, totals)
        grid += 1
    rng = Random(136913)
    for _ in range(240):
        conditions = [str(i) for i in range(rng.randint(1,4))]
        sources = {str(i):str(i) for i in range(rng.randint(1,5))}
        sources["copy"] = "0"
        def cell():
            return {"source":rng.choice(list(sources)), "condition":rng.choice(conditions)}
        p = {"conditions":conditions, "sources":sources, "fault_budget":rng.randrange(3),
             "history":[{**cell(),"bit":rng.randrange(2)} for _ in range(rng.randrange(8))],
             "menu":[{**cell(),"name":str(j),"cost":rng.randrange(8)} for j in range(rng.randrange(7))]}
        check(p, totals)
    # Random catalogs above can be insufficient; also force resolvable partially overlapping catalogs.
    for _ in range(70):
        c = rng.choice(sample["conditions"])
        h = [{"source":"application","condition":i,"bit":rng.randrange(2)} for i in sample["conditions"]]
        rows = [*h, {"source":"gateway","condition":c,"bit":rng.randrange(2)}]
        menu = [{"name":f"{s}-{i}","source":s,"condition":i,"cost":rng.randrange(8)}
                for s in ("gateway","authorization") for i in sample["conditions"]]
        check({**sample,"history":rows,"menu":menu}, totals)
    # Each alternative below requires all n bits. No enumeration of the 2**n input vectors here.
    n = 512
    conditions = [str(i) for i in range(n)]
    history = [{"condition":i,"source":s,"bit":v} for i in conditions for s,v in (("application",1),("gateway",0))]
    large = {**sample, "conditions":conditions, "history":history, "menu":[]}
    proof = SourceAudit(large).report()["witness"]
    assert proof["nonzero"]["requests_at"] == conditions
    large["menu"] = [{**sample["menu"][1],"condition":conditions[-1]}]
    assert SourceAudit(large).report()["worst_case_cost"] == 3
    return {"seed":136913, "one_condition_grid":grid, "random_cases":240, "overlap_cases":70,
            "targeted_oracle_cases":5, "totals":dict(sorted(totals.items())),
            "prior_root_only":prior_pair, "large_minimum_nonzero_support":n, "sharp_lists":sharp_lists()}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
