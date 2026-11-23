"""Audit a stable Boolean claim under explicitly enumerated source layouts and priced lineage checks."""

import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_audit import SourceAudit, bit, fields, name, number, positions


def hitting_cover(clauses, left_mask, f):
    """Find at most f chosen roots per world hitting each clause, or return None."""
    ordered = sorted(set(clauses), key=lambda c: (c.bit_count(), c))
    forced = 0
    for c in ordered:
        if c.bit_count() == 1:
            forced |= c
    remaining = [c for c in ordered if not c & forced]

    @lru_cache(maxsize=None)
    def find(chosen):
        if (chosen & left_mask).bit_count() > f or (chosen & ~left_mask).bit_count() > f:
            return None
        for c in remaining:
            if not c & chosen:
                for r in positions(c):
                    answer = find(chosen | (1 << r))
                    if answer is not None:
                        return answer
                return None
        return chosen
    return find(forced)


class LineageAudit:
    def __init__(self, problem):
        fields(problem, "conditions", "layouts", "history", "relations", "fault_budget", "menu")
        self.f = number(problem["fault_budget"])
        mappings = problem["layouts"]
        if not isinstance(mappings, dict) or not mappings:
            raise ValueError("give at least one possible layout")
        if not isinstance(problem["relations"], list) or not isinstance(problem["menu"], list):
            raise ValueError("relations and menu must be arrays")
        self.menu = problem["menu"]
        behaviors = []
        for q in self.menu:
            if not isinstance(q, dict):
                raise ValueError("invalid menu entry")
            if q.get("kind") == "report":
                fields(q, "kind", "name", "cost", "source", "condition")
                behaviors.append({k:v for k,v in q.items() if k != "kind"})
            elif q.get("kind") == "same":
                fields(q, "kind", "name", "cost", "left", "right")
            else:
                raise ValueError("kind must be report or same")
            name(q["name"])
            number(q["cost"])
        if len({q["name"] for q in self.menu}) != len(self.menu):
            raise ValueError("menu names must be unique")
        for obs in problem["relations"]:
            fields(obs, "left", "right", "bit")
            bit(obs["bit"])
        shared_keys = None
        self.models = {}
        self.cells = {}
        self.labels = {}
        self.conditions = problem["conditions"]
        for label, mapping in mappings.items():
            name(label)
            model = SourceAudit({"conditions":self.conditions, "sources":mapping, "fault_budget":self.f,
                                 "history":problem["history"], "menu":behaviors})
            if shared_keys is not None and set(mapping) != shared_keys:
                raise ValueError("all layouts must assign the same report names")
            shared_keys = set(mapping)

            def same(q):
                x, y = name(q["left"]), name(q["right"])
                if x not in mapping or y not in mapping:
                    raise ValueError("unknown source in relation")
                return int(mapping[x] == mapping[y])

            relations = {i:same(q) for i,q in enumerate(self.menu) if q["kind"] == "same"}
            previous = [same(q) == q["bit"] for q in problem["relations"]]
            if all(previous):
                self.models[label] = model
                report_items = iter(model.menu)
                self.cells[label] = {i:next(report_items) for i,q in enumerate(self.menu) if q["kind"] == "report"}
                self.labels[label] = relations

    def current(self, answers):
        safe = risky = False
        for label, model in self.models.items():
            if any(i in answers and answers[i] != v for i,v in self.labels[label].items()):
                continue
            zeros, ones = model.zeros.copy(), model.ones.copy()
            for i, value in answers.items():
                if i in self.cells[label]:
                    q = self.cells[label][i]
                    (ones if value else zeros)[q.root] |= 1 << q.condition
            s, r = model.classes(zeros, ones)
            safe, risky = safe or s, risky or r
            if safe and risky:
                break
        return {(False,False):"inconsistent",(True,False):"all_zero",
                (False,True):"some_request",(True,True):"ambiguous"}[safe,risky]

    def pair(self, left, right):
        if self.labels[left] != self.labels[right]:
            return None
        base, alt = self.models[left], self.models[right]
        shift = len(base.roots)
        left_mask = (1 << shift)-1
        forced_base = [1 << r for r,v in enumerate(base.ones) if v]
        if len(forced_base) > self.f:
            return None
        n = len(self.conditions)
        pos, neg, edges = ([[] for _ in range(n)] for _ in range(3))
        for r, (z,o) in enumerate(zip(alt.zeros, alt.ones)):
            flag = 1 << (shift+r)
            for c in positions(o):
                pos[c].append(flag)
            for c in positions(z):
                neg[c].append(flag)
        for i,p in self.cells[left].items():
            other = self.cells[right][i]
            edges[p.condition].append((1 << p.root) | (1 << (shift+other.root)))
        common = set(forced_base)
        for c in range(n):
            common.update(p | z for p in pos[c] for z in neg[c])
            common.update(p | edge for p in pos[c] for edge in edges[c])
        for seed in range(n):
            taken = hitting_cover(common.union(neg[seed], edges[seed]), left_mask, self.f)
            if taken is None:
                continue
            support = 1 << seed
            for r,o in enumerate(alt.ones):
                if not taken & (1 << (shift+r)):
                    support |= o
            future = dict(self.labels[left])
            for i,p in self.cells[left].items():
                other = self.cells[right][i]
                future[i] = int(bool(taken & (1 << p.root)) and
                                not taken & (1 << (shift+other.root)) and bool(support & (1 << p.condition)))
            named = {q["name"]:future[i] for i,q in enumerate(self.menu)}
            return {"common_answers":named,"all_zero":self.world(left, 0, named),
                    "nonzero":self.world(right, support, named)}
        return None

    def world(self, label, support, named):
        model = self.models[label]
        bad = model.mismatches(model.zeros, model.ones, support)
        for i,p in self.cells[label].items():
            if named[self.menu[i]["name"]] != ((support >> p.condition) & 1):
                bad |= 1 << p.root
        return {"layout":label,"requests_at":[self.conditions[c] for c in positions(support)],
                "mismatching_roots":[model.roots[r] for r in positions(bad)]}

    def verify(self, witness):
        fields(witness,"common_answers","all_zero","nonzero")
        named = witness["common_answers"]
        if not isinstance(named, dict) or set(named) != {q["name"] for q in self.menu}:
            raise ValueError("certificate must cover the entire menu")
        for v in named.values():
            bit(v)
        for label in ("all_zero","nonzero"):
            w = witness[label]
            fields(w,"layout","requests_at","mismatching_roots")
            layout = name(w["layout"])
            if layout not in self.models or not isinstance(w["requests_at"],list):
                raise ValueError("incompatible layout or support")
            if any(c not in self.conditions for c in w["requests_at"]):
                raise ValueError("unknown condition")
            support = sum(1 << i for i,c in enumerate(self.conditions) if c in w["requests_at"])
            if (bool(support) != (label == "nonzero") or self.world(layout,support,named) != w or
                    len(w["mismatching_roots"]) > self.f):
                raise ValueError("world fails raw evidence or fault budget")
            if any(named[self.menu[i]["name"]] != v for i,v in self.labels[layout].items()):
                raise ValueError("world contradicts a trusted lineage check")

    def plan(self):
        order = sorted(range(len(self.menu)), key=lambda i:(self.menu[i]["cost"],self.menu[i]["name"]))
        @lru_cache(maxsize=None)
        def solve(unread, ones):
            answers = {i:(ones >> i) & 1 for i in range(len(self.menu)) if not (unread >> i) & 1}
            if self.current(answers) != "ambiguous":
                return 0, None
            best = chosen = None
            for i in order:
                if not unread & (1 << i):
                    continue
                q = self.menu[i]
                if best is not None and q["cost"] >= best:
                    break
                left = unread ^ (1 << i)
                low = solve(left, ones)[0]
                if best is not None and q["cost"]+low >= best:
                    continue
                high = solve(left, ones | (1 << i))[0]
                total = q["cost"]+max(low, high)
                if best is None or total < best:
                    best, chosen = total, q["name"]
            if best is None:
                raise RuntimeError("ambiguous leaf in a separating menu")
            return best, chosen
        return solve((1 << len(self.menu))-1, 0)

    def report(self, feasibility_only=False):
        status = self.current({})
        if status != "ambiguous":
            return {"status":status,"worst_case_cost":None if status=="inconsistent" else 0,"next_probe":None}
        for left in self.models:
            for right in self.models:
                witness = self.pair(left,right)
                if witness:
                    return {"status":"unidentifiable","witness":witness}
        if feasibility_only:
            return {"status":"resolvable"}
        cost, action = self.plan()
        return {"status":"resolvable","worst_case_cost":cost,"next_probe":action}


def observe(problem, label, answer):
    action = next((q for q in problem["menu"] if q["name"]==label), None)
    if action is None:
        raise ValueError("unknown or spent menu item")
    value = bit(answer)
    remainder = [q for q in problem["menu"] if q["name"] != label]
    if action["kind"] == "same":
        key, attrs = "relations", ("left","right")
    else:
        key, attrs = "history", ("source","condition")
    row = {attr:action[attr] for attr in attrs}
    return {**problem, "menu":remainder, key:[*problem[key],{**row,"bit":value}]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem",type=Path)
    parser.add_argument("--record",nargs=2,action="append",default=[],metavar=("NAME","BIT"))
    parser.add_argument("--feasibility-only",action="store_true")
    parser.add_argument("--verify-witness",type=Path)
    args = parser.parse_args()
    try:
        problem = json.loads(args.problem.read_text(encoding="utf-8-sig"))
        audit = LineageAudit(problem)
        for label, value in args.record:
            problem = observe(problem,label,int(value))
            audit = LineageAudit(problem)
        if args.verify_witness:
            saved = json.loads(args.verify_witness.read_text(encoding="utf-8-sig"))
            if not isinstance(saved,dict) or saved.get("status")!="unidentifiable" or "witness" not in saved:
                raise ValueError("expected an unidentifiable report")
            audit.verify(saved["witness"])
            result = {"status":"verified"}
        else:
            result = audit.report(args.feasibility_only)
        print(json.dumps(result,indent=2))
    except (ValueError,OSError) as exc:
        parser.exit(2,f"{exc}\n")
