"""Minimum-cost fixed audit panels. Implicit hitting set with a PySAT RC2 master."""

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lineage import LineageAudit


@dataclass(frozen=True)
class Rule:
    gates: tuple
    groups: tuple
    need: int

    def accepts(self, items):
        return not items.isdisjoint(self.gates) or sum(not items.isdisjoint(g) for g in self.groups) >= self.need

    def price_bound(self, costs):
        # Each action belongs to at most one report group; trusted checks are separate purchases.
        options = [costs[i] for i in self.gates]
        if len(self.groups) >= self.need:
            first = sorted(min(costs[i] for i in group) for group in self.groups)
            options.append(sum(first[:self.need]))
        if not options:
            raise ValueError("even the full catalog cannot meet this constraint")
        return min(options)


def minimum_panel(costs, rules):
    if not rules:
        return ()
    from pysat.card import CardEnc, EncType
    from pysat.examples.rc2 import RC2
    from pysat.formula import IDPool, WCNF

    form = WCNF()
    pool = IDPool(start_from=len(costs)+1)
    for i,cost in enumerate(costs,1):
        # Secondary objective avoids buying unnecessary free items.
        form.append([-i], weight=cost*(len(costs)+1)+1)
    for rule in rules:
        gates = [i+1 for i in rule.gates]
        if rule.need == 1:
            form.append(gates+[i+1 for g in rule.groups for i in g])
            continue
        if len(rule.groups) < rule.need:
            form.append(gates)
            continue
        flags = []
        for group in rule.groups:
            lits = [i+1 for i in group]
            if len(lits)==1:
                flags.append(lits[0])
            else:
                active = pool.id()
                flags.append(active)
                form.append([-active,*lits])
                for lit in lits:
                    form.append([-lit,active])
        counter = CardEnc.atleast(lits=flags,bound=rule.need,vpool=pool,encoding=EncType.seqcounter)
        for clause in counter.clauses:
            form.append(gates+clause)
    with RC2(form,solver="g3") as solver:
        model = solver.compute()
    if model is None:
        raise ValueError("constraints have no purchasing solution")
    return tuple(sorted(lit-1 for lit in model if 1<=lit<=len(costs)))


class Panels:
    def __init__(self, problem):
        self.problem = problem
        self.audit = LineageAudit(problem)
        self.menu = self.audit.menu
        self.costs = [q["cost"] for q in self.menu]
        self.names = [q["name"] for q in self.menu]
        structure = {**problem,"menu":[{k:v for k,v in q.items() if k!="cost"} for q in self.menu]}
        self.fingerprint = sha256(json.dumps(structure,sort_keys=True,separators=(",",":")).encode()).hexdigest()

    def assess(self, items):
        partial = {**self.problem,"menu":[self.menu[i] for i in items]}
        return LineageAudit(partial).report(feasibility_only=True)

    def components(self, left, right, support):
        if left not in self.audit.models or right not in self.audit.models:
            raise ValueError("incompatible source layout in explanation")
        if not isinstance(support,list) or not support or any(c not in self.audit.conditions for c in support):
            raise ValueError("invalid nonzero support")
        selected = set(support)
        if len(selected)!=len(support):
            raise ValueError("duplicate condition in explanation")
        mask = sum(1<<i for i,c in enumerate(self.audit.conditions) if c in selected)
        lm, rm = self.audit.models[left], self.audit.models[right]
        def forced(model, truth):
            bad = model.mismatches(model.zeros,model.ones,truth)
            return {r for j,r in enumerate(model.roots) if bad & (1<<j)}
        base, other = forced(lm,0), forced(rm,mask)
        gates = tuple(i for i,v in self.audit.labels[left].items() if self.audit.labels[right][i]!=v)
        edges = []
        for i,lp in self.audit.cells[left].items():
            if mask & (1<<lp.condition):
                rp = self.audit.cells[right][i]
                edges.append((i,lm.roots[lp.root],rm.roots[rp.root]))
        return base, other, gates, edges

    @staticmethod
    def matching(edges):
        pairs = {(a,b) for _,a,b in edges}
        return len(pairs)==len({a for a,b in pairs})==len({b for a,b in pairs})

    def compile(self, fact):
        keys = {"kind","zero","opposite","support","left_bad","right_bad"}
        if not isinstance(fact,dict) or set(fact)!=keys:
            raise ValueError("malformed constraint premise")
        left,right = fact["zero"],fact["opposite"]
        base,other,gates,edges = self.components(left,right,fact["support"])
        def allowed(key, layout, forced):
            raw = fact[key]
            if not isinstance(raw,list) or any(not isinstance(r,str) for r in raw):
                raise ValueError("invalid list of potentially faulty roots")
            roots = set(raw)
            if (len(roots)!=len(raw) or len(roots)>self.audit.f or not forced<=roots or
                    not roots<=set(self.audit.models[layout].roots)):
                raise ValueError("inadmissible root assignment")
            return roots
        lbad,rbad = allowed("left_bad",left,base),allowed("right_bad",right,other)
        clean = [(i,a,b) for i,a,b in edges if a not in lbad and b not in rbad]
        kind = fact["kind"]
        if kind=="one":
            return Rule(gates,tuple((i,) for i,_,_ in clean),1)
        groups = defaultdict(list)
        if kind=="matching" and base==lbad and other==rbad and self.matching(clean):
            need = 2*self.audit.f-len(lbad)-len(rbad)+1
            for i,a,b in clean:
                groups[(a,b)].append(i)
        elif kind=="right-quota" and other==rbad:
            need = self.audit.f-len(rbad)+1
            for i,a,b in clean:
                groups[b].append(i)
        elif kind=="left-quota" and base==lbad:
            need = self.audit.f-len(lbad)+1
            for i,a,b in clean:
                groups[a].append(i)
        else:
            raise ValueError("constraint type does not meet its assumptions")
        return Rule(gates,tuple(sorted(tuple(g) for g in groups.values())),need)

    def explain(self, witness, mode):
        first,second = witness["all_zero"],witness["nonzero"]
        left,right,support = first["layout"],second["layout"],second["requests_at"]
        base,other,_,edges = self.components(left,right,support)
        lbad,rbad = set(first["mismatching_roots"]),set(second["mismatching_roots"])
        def fact(kind,l,r):
            return {"kind":kind,"zero":left,"opposite":right,"support":support,
                    "left_bad":sorted(l),"right_bad":sorted(r)}
        if mode=="one":
            # Extend the already compatible pair greedily. This makes the one-hit control stronger.
            while True:
                counts = Counter()
                for _,a,b in edges:
                    if a in lbad or b in rbad:
                        continue
                    if len(lbad)<self.audit.f:
                        counts[("L",a)]+=1
                    if len(rbad)<self.audit.f:
                        counts[("R",b)]+=1
                if not counts:
                    break
                side,r = min(counts,key=lambda k:(-counts[k],k))
                (lbad if side=="L" else rbad).add(r)
            return [fact("one",lbad,rbad)]
        if self.matching([(i,a,b) for i,a,b in edges if a not in base and b not in other]):
            return [fact("matching",base,other)]
        return [fact("right-quota",lbad,other),fact("left-quota",base,rbad)]

    def optimize(self, mode="quota", reuse=None):
        if mode not in ("one","quota"):
            raise ValueError("mode must be one or quota")
        if reuse is not None and (not isinstance(reuse,dict) or reuse.get("status")!="optimal"
                                  or reuse.get("structure")!=self.fingerprint):
            raise ValueError("reuse requires the same scenario apart from menu prices")
        full = self.audit.report(feasibility_only=True)
        if full["status"]!="resolvable":
            return full
        facts, ordered, seen = [], [], set()
        if reuse is not None:
            for fact in reuse["premises"]:
                rule = self.compile(fact)
                if rule not in seen:
                    seen.add(rule)
                    ordered.append(rule)
                    facts.append(fact)
        reused = len(facts)
        iterations = 0
        while True:
            items = minimum_panel(self.costs,ordered)
            answer = self.assess(items)
            iterations += 1
            if answer["status"]=="resolvable":
                return {"status":"optimal","structure":self.fingerprint,"mode":mode,
                        "panel":[self.names[i] for i in items],"cost":sum(self.costs[i] for i in items),
                        "single_rule_bound":max((r.price_bound(self.costs) for r in ordered),default=0),
                        "candidate_checks":iterations,"reused_constraints":reused,"premises":facts}
            if answer["status"]!="unidentifiable":
                raise RuntimeError("history decision changed without any new observations")
            count = len(facts)
            for fact in self.explain(answer["witness"],mode):
                rule = self.compile(fact)
                if rule.accepts(set(items)):
                    raise RuntimeError("proposed cut does not exclude the counterexample panel")
                if rule not in seen:
                    facts.append(fact)
                    seen.add(rule)
                    ordered.append(rule)
            if count==len(facts):
                raise RuntimeError("no new constraint")

    def verify(self, report):
        if report["status"]!="optimal":
            if report["status"]=="unidentifiable":
                self.audit.verify(report["witness"])
            elif report!=self.audit.report(feasibility_only=True):
                raise ValueError("incorrect history status")
            elif report["status"]=="resolvable":
                raise ValueError("missing fixed-panel result")
            return "raw_evidence"
        if report["structure"]!=self.fingerprint:
            raise ValueError("scenario mismatch")
        panel = report["panel"]
        if not isinstance(panel,list) or len(set(panel))!=len(panel) or not set(panel)<=set(self.names):
            raise ValueError("unknown or repeated purchase")
        indices = [self.names.index(s) for s in panel]
        if self.assess(indices)["status"]!="resolvable" or self.audit.current({})!="ambiguous":
            raise ValueError("purchased items do not certify the requested distinction")
        price = sum(self.costs[i] for i in indices)
        rules = [self.compile(f) for f in report["premises"]]
        simple = max((rule.price_bound(self.costs) for rule in rules),default=0)
        if (type(report["cost"]) is not int or report["cost"]!=price or
                type(report["single_rule_bound"]) is not int or report["single_rule_bound"]!=simple):
            raise ValueError("price or single-rule lower bound does not match")
        if simple==price:
            return "single_rule_arithmetic"
        bound = sum(self.costs[i] for i in minimum_panel(self.costs,rules))
        if bound!=price:
            raise ValueError("price or certified lower bound does not match")
        return "weighted_maxsat"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem",type=Path)
    parser.add_argument("--mode",choices=("one","quota"),default="quota")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--reuse",type=Path)
    options.add_argument("--verify",type=Path)
    args = parser.parse_args()
    try:
        def read(path):
            return json.loads(path.read_text(encoding="utf-8-sig"))
        engine = Panels(read(args.problem))
        if args.verify:
            result = {"status":"verified","method":engine.verify(read(args.verify))}
        else:
            result = engine.optimize(args.mode,read(args.reuse) if args.reuse else None)
        print(json.dumps(result,indent=2))
    except (ValueError,KeyError,TypeError,OSError,ImportError) as error:
        parser.exit(2,f"{error}\n")
