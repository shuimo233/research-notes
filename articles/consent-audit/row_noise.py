"""Choose a cheapest archive page panel and decode a noisy three-run binary record."""

import argparse
from bisect import bisect_left, bisect_right
from itertools import accumulate, product
import json
from pathlib import Path


def integer(x, minimum=0):
    if type(x) is not int or x < minimum:
        raise ValueError(f"expected an integer >= {minimum}")
    return x


def world(cuts, bits):
    return {"cuts":list(cuts), "bits":"".join(map(str,bits))}


class Registry:
    def __init__(self, doc):
        self.errors = integer(doc["errors"])
        self.erasures = integer(doc["erasures"])
        self.required = 2*self.errors + self.erasures + 1
        self.ends = [integer(p["end"], 1) for p in doc["pages"]]
        self.costs = [integer(p["cost"]) for p in doc["pages"]]
        if not self.ends or self.ends != sorted(set(self.ends)):
            raise ValueError("each page must end after the previous page")
        self.starts = [0] + self.ends[:-1]
        self.rows = self.ends[-1]
        if not isinstance(doc["groups"], dict) or not doc["groups"]:
            raise ValueError("need at least one trusted receipt group")
        self.groups = {}
        for name, layouts in doc["groups"].items():
            if not isinstance(name,str) or not isinstance(layouts,list) or not layouts:
                raise ValueError("a receipt group needs a nonempty layout list")
            cuts = set()
            for a,b in layouts:
                if not integer(a,1) < integer(b,1) < self.rows:
                    raise ValueError("cuts must define three nonempty runs")
                cuts.add((a,b))
            self.groups[name] = sorted(cuts)
        by_interval = {}
        for name, cuts in self.groups.items():
            for low, high, zero, one in self.generators(cuts):
                pages = ((bisect_right(self.ends,low),bisect_left(self.ends,high))
                         if low < high else (0,-1))
                by_interval.setdefault(pages, (name,zero,one))
        self.rules = {}
        max_left = -1
        # Empty support dominates all other inequalities.
        if (0,-1) in by_interval:
            self.rules[(0,-1)] = by_interval[(0,-1)]
        else:
            for left,right in sorted(by_interval, key=lambda p:(p[1],-p[0])):
                if left > max_left:
                    self.rules[left,right] = by_interval[left,right]
                    max_left = left

    def generators(self, cuts):
        first = {a:(a,b) for a,b in cuts}
        second = {b:(a,b) for a,b in cuts}
        shared = first.keys() & second.keys()
        if shared:
            p = min(shared)
            yield p,p,world(second[p],(0,0,1)),world(first[p],(0,1,1))
            return
        x,y = min(first),max(second)
        yield 0,x,world(first[x],(0,0,1)),world(first[x],(1,0,1))
        yield y,self.rows,world(second[y],(0,1,0)),world(second[y],(0,1,1))
        points = sorted(first.keys() | second.keys())
        for left,right in zip(points,points[1:]):
            if (left in first) != (right in first):
                a,b = (left,right) if left in first else (right,left)
                yield left,right,world(second[b],(0,0,1)),world(first[a],(0,1,1))

    def selected(self, pages):
        if not isinstance(pages,list):
            raise ValueError("pages must be a list of one-based IDs")
        ids = [integer(p,1)-1 for p in pages]
        if len(set(ids)) != len(ids) or any(p >= len(self.ends) for p in ids):
            raise ValueError("page IDs must exist and be distinct")
        return set(ids)

    def limiting(self, selected):
        counts = [0,*accumulate(i in selected for i in range(len(self.ends)))]
        def distance(interval):
            a,b = interval
            return counts[b+1]-counts[a]
        a,b = min(self.rules, key=distance)
        name,zero,one = self.rules[a,b]
        return distance((a,b)), {"group":name, "zero":zero, "one":one,
                                "differing_pages":[i+1 for i in range(a,b+1) if i in selected]}

    def layout_value(self):
        """Does full layout disclosure change the guaranteed distance of any fixed panel?"""
        partitions = sorted({pair for cuts in self.groups.values() for pair in cuts})
        fine = Registry({"errors":self.errors, "erasures":self.erasures,
                         "groups":{str(i):[pair] for i,pair in enumerate(partitions)},
                         "pages":[{"end":end,"cost":cost} for end,cost in zip(self.ends,self.costs)]})
        # Minimal intervals are in strictly increasing order of both endpoints.
        fine_rules = list(fine.rules)
        lefts = [a for a,b in fine_rules]
        for a,b in self.rules:
            j = bisect_left(lefts,a)
            if j < len(fine_rules) and fine_rules[j][1] <= b:
                continue
            outside = {i for i in range(len(self.ends)) if not a <= i <= b}
            coarse_distance,witness = self.limiting(outside)
            full_distance,_ = fine.limiting(outside)
            return {"status":"different", "zero_noise_example":{
                "pages":[i+1 for i in sorted(outside)], "receipt_distance":coarse_distance,
                "full_layout_distance":full_distance, "receipt_collision":witness}}
        return {"status":"identical_for_every_fixed_panel", "minimal_intervals":len(fine_rules)}

    def optimize(self):
        attainable,witness = self.limiting(set(range(len(self.ends))))
        if attainable < self.required:
            return {"status":"impossible", "full_distance":attainable,
                    "required":self.required, "witness":witness}
        import networkx as nx
        # Prefix counts T obey T[v]-T[u] <= cost(u,v). The dual is min-cost flow.
        graph = nx.MultiDiGraph()
        tariffs = [0,*self.costs,0]
        for i in range(len(self.ends)+1):
            graph.add_node(i,demand=tariffs[i+1]-tariffs[i])
        for i in range(len(self.ends)):
            graph.add_edge(i,i+1,key="cap",weight=1)
            graph.add_edge(i+1,i,key="floor",weight=0)
        for a,b in self.rules:
            graph.add_edge(b+1,a,key="rule",weight=-self.required)
        objective,flow = nx.network_simplex(graph)
        residual = nx.DiGraph()
        def edge(u,v,w):
            old = residual.get_edge_data(u,v)
            if old is None or w < old["weight"]:
                residual.add_edge(u,v,weight=w)
        for u,v,key,data in graph.edges(keys=True,data=True):
            edge(u,v,data["weight"])
            if flow[u][v][key]:
                edge(v,u,-data["weight"])
        prefix = nx.single_source_bellman_ford_path_length(residual,0)
        pages = [i+1 for i in range(len(self.ends)) if prefix[i+1]-prefix[i] == 1]
        dual = [[a+1,b+1,flow[b+1][a]["rule"]] for a,b in self.rules if flow[b+1][a]["rule"]]
        distance,_ = self.limiting(self.selected(pages))
        report = {"status":"optimal", "pages":pages, "cost":sum(self.costs[i-1] for i in pages),
                  "distance":distance, "required":self.required, "dual":dual}
        if -objective != report["cost"]:
            raise RuntimeError("flow and feasible archive prices differ")
        self.verify(report)
        return report

    def verify(self, report):
        if report["status"] == "impossible":
            distance,witness = self.limiting(set(range(len(self.ends))))
            if (distance >= self.required or report != {"status":"impossible","full_distance":distance,
                    "required":self.required,"witness":witness}):
                raise ValueError("invalid impossibility witness")
            return
        if report["status"] != "optimal":
            raise ValueError("unknown report status")
        selected = self.selected(report["pages"])
        price = sum(self.costs[i] for i in selected)
        distance,_ = self.limiting(selected)
        if (distance < self.required or integer(report["cost"]) != price
                or integer(report["distance"]) != distance or integer(report["required"]) != self.required):
            raise ValueError("panel, distance or price does not match")
        # Covering LP dual; the page upper-bound penalties can be recovered from multipliers.
        delta = [0]*(len(self.ends)+1)
        mass = 0
        for lo,hi,weight in report["dual"]:
            a,b = integer(lo,1)-1,integer(hi,1)-1
            integer(weight,1)
            if (a,b) not in self.rules:
                raise ValueError("dual interval is not a regenerated requirement")
            delta[a] += weight
            delta[b+1] -= weight
            mass += weight
        penalty = sum(max(0,load-price_i) for load,price_i in zip(accumulate(delta),self.costs))
        if self.required*mass - penalty != price:
            raise ValueError("dual does not certify this minimum price")

    def decode(self, group, pages, observed):
        selected = self.selected(pages)
        if group not in self.groups or not isinstance(observed,dict) or set(observed) != {str(i+1) for i in selected}:
            raise ValueError("supply the receipt and one string or null for each bought page")
        changes = {}
        lost = 0
        base = [[0],[0]]
        for i,(start,end) in enumerate(zip(self.starts,self.ends)):
            word_i = observed.get(str(i+1))
            if word_i is None:
                lost += int(i in selected)
                for b in (0,1):
                    base[b].append(base[b][-1])
                continue
            if not isinstance(word_i,str) or len(word_i) != end-start or set(word_i)-{"0","1"}:
                raise ValueError("observed page must have the declared number of binary rows")
            jumps = []
            for j in range(1,len(word_i)):
                if word_i[j] != word_i[j-1]:
                    jumps.append(start+j)
                    if len(jumps) == 3:
                        break
            pattern = (int(word_i[0]),tuple(jumps))
            changes[i] = pattern
            for b in (0,1):
                base[b].append(base[b][-1]+(pattern != (b,())))
        if lost > self.erasures:
            return {"status":"outside_erasure_budget","erased":lost}
        minima = [None,None]
        for cuts in self.groups[group]:
            a,b = cuts
            j,k = bisect_left(self.starts,a),bisect_left(self.starts,b)
            # Start with page-constant predictions. Only pages straddling a cut need correction.
            boundary = {bisect_right(self.starts,t)-1 for t in cuts}
            boundary = [i for i in boundary if i in changes and any(self.starts[i]<t<self.ends[i] for t in cuts)]
            for bits in product((0,1),repeat=3):
                x,y,z = bits
                score = base[x][j] + base[y][k]-base[y][j] + base[z][-1]-base[z][k]
                for i in boundary:
                    value = bits[bisect_right(cuts,self.starts[i])]
                    inner = tuple(t for t,p,q in ((a,x,y),(b,y,z))
                                  if p!=q and self.starts[i]<t<self.ends[i])
                    score += int(changes[i] != (value,inner)) - int(changes[i] != (value,()))
                label = int(x+y+z >= 2)
                if minima[label] is None or score < minima[label][0]:
                    minima[label] = (score,world(cuts,bits))
        compatible = [i for i,(score,_) in enumerate(minima) if score <= self.errors]
        status = ("ambiguous" if len(compatible)==2 else "inconsistent" if not compatible
                  else "some_request" if compatible[0] else "all_zero")
        return {"status":status, "erased":lost,
                "classes":[{"distance":score,"world":w} for score,w in minima]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry",type=Path)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--verify",type=Path)
    options.add_argument("--decode",type=Path)
    options.add_argument("--layout-value",action="store_true",help="compare fixed-panel distances with full provenance")
    args = parser.parse_args()
    try:
        def read(path):
            return json.loads(path.read_text(encoding="utf-8-sig"))
        engine = Registry(read(args.registry))
        if args.layout_value:
            result = engine.layout_value()
        elif args.verify:
            engine.verify(read(args.verify))
            result = {"status":"verified"}
        elif args.decode:
            case = read(args.decode)
            result = engine.decode(case["group"],case["pages"],case["observed"])
        else:
            result = engine.optimize()
        print(json.dumps(result,indent=2))
    except (ValueError, KeyError, TypeError, OSError, ImportError) as error:
        parser.exit(2,f"{error}\n")
