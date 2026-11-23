"""Anonymous, exact two-of-three consensus for arbitrary unions of issue types.

An atom is a (severity, category) pair. Public margins give its row count and
number of reporting people. Each of the three raters supplies 1..cap rows.
"""

import argparse
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path


def atom(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2 or any(not isinstance(s,str) or not s.strip() for s in value):
        raise ValueError("an atom requires a severity and a category")
    return value[0].strip().casefold(), value[1].strip()


def silent(t):
    return t[1].casefold()=="no-error"


def exclusive(t):
    return silent(t) or t[1].casefold().rstrip("!")=="non-translation"


def integer(x,lower=0):
    if type(x) is not int or x<lower:
        raise ValueError(f"expected an integer >= {lower}")
    return x


class PartitionSpace:
    def __init__(self, single, fillers, cap, open_coverage):
        self.single = single
        self.cap = cap
        self.open_coverage = open_coverage
        self.fills = []
        for k,d,sealed in fillers:
            increments = []
            for x in range(min(k,cap)+1):
                for y in range(min(k-x,cap)+1):
                    vals = (x,y,k-x-y)
                    if max(vals)<=cap and sum(bool(v) for v in vals)==d:
                        if not sealed or k==d:
                            increments.append(tuple(cap if sealed and v else v for v in vals))
            self.fills.append(increments)
        self.count = lru_cache(None)(self._count)
        self.fillable = lru_cache(None)(self._fillable)

    def _fillable(self, i, loads):
        if i==len(self.fills):
            return all(loads)
        next_states = {tuple(sorted(a+b for a,b in zip(loads,delta))) for delta in self.fills[i]}
        return any(s[-1]<=self.cap and self.fillable(i+1,s) for s in next_states)

    def moves(self, i, loads):
        k,sealed = self.single[i]
        used = self.cap if sealed else k
        for seat in range(min(3,len(loads)+1)):
            after = list(loads)
            if seat==len(after):
                after.append(0)
            if after[seat]+used<=self.cap:
                after[seat] += used
                yield seat,tuple(after)

    def _count(self,i,loads):
        if i==len(self.single):
            if self.open_coverage is not None:
                return int(len(loads)+self.open_coverage>=3)
            padded = tuple(sorted(loads+(0,)*(3-len(loads))))
            return int(self.fillable(0,padded))
        return sum(self.count(i+1,s) for _,s in self.moves(i,loads))

    def rank(self, owners):
        if len(owners)!=len(self.single):
            raise ValueError("incomplete owner partition")
        rank,loads = 0,()
        for i,chosen in enumerate(owners):
            for seat,after in self.moves(i,loads):
                if seat==chosen:
                    loads = after
                    break
                rank += self.count(i+1,after)
            else:
                raise ValueError("unrealizable owner partition")
        if not self.count(len(owners),loads):
            raise ValueError("common types cannot complete the three ballots")
        return rank

    def unrank(self,rank):
        if integer(rank)>=self.count(0,()):
            raise ValueError("receipt rank outside this margin's feasible states")
        owners,loads = [],()
        for i in range(len(self.single)):
            for seat,after in self.moves(i,loads):
                size = self.count(i+1,after)
                if rank<size:
                    owners.append(seat)
                    loads = after
                    break
                rank -= size
        return tuple(owners)

    def possible_votes(self, hits):
        # Memoize only within this particular policy. False and True are independent
        # possibilities, not numbers of equally likely assignments.
        @lru_cache(None)
        def visit(i,loads,voters):
            if self.count(i,loads)==0:
                return 0
            if voters.bit_count()>=2:
                return 2
            if i==len(self.single):
                return 1
            result = 0
            for seat,after in self.moves(i,loads):
                result |= visit(i+1,after,voters | ((1<<seat) if hits[i] else 0))
                if result==3:
                    break
            return result
        return visit(0,(),0)


@lru_cache(512)
def space(single,fillers,cap,open_coverage=None):
    return PartitionSpace(single,fillers,cap,open_coverage)


class Receipt:
    def __init__(self,margins,cap=5,relaxed=False):
        self.cap = integer(cap,1)
        if type(relaxed) is not bool:
            raise ValueError("relaxed must be a boolean")
        self.relaxed = relaxed
        self.margins = {}
        for row in margins:
            if not isinstance(row,(list,tuple)) or len(row)!=4:
                raise ValueError("margin requires severity, category, row count, person count")
            t = atom(row[:2])
            k,d = integer(row[2],1),integer(row[3],1)
            if (t in self.margins or d>3 or d>k or
                    (not relaxed and (k>d*cap or (exclusive(t) and k!=d)))):
                raise ValueError("inconsistent atom margin")
            self.margins[t] = (k,d)
        total=sum(k for k,d in self.margins.values())
        if total<3 or (not relaxed and total>3*cap):
            raise ValueError("the three ballot sizes cannot match")
        self.common = {t for t,(_,d) in self.margins.items() if d>=2 and not silent(t)}
        self.single = tuple(sorted(t for t,(_,d) in self.margins.items() if d==1 and not silent(t)))
        single = tuple((self.margins[t][0],exclusive(t)) for t in self.single)
        fillers = tuple(sorted((k,d,exclusive(t)) for t,(k,d) in self.margins.items() if t not in self.single))
        if relaxed:
            # Without capacity/exclusivity constraints, remaining types can cover the
            # unused seats whenever their total person-incidence reaches that count.
            coverage=sum(d for _,d,_ in fillers)
            self.space=space(((1,False),)*len(single),(),max(1,len(single)),min(3,coverage))
        else:
            self.space=space(single,fillers,cap)
        self.states = self.space.count(0,())
        if not self.states:
            raise ValueError("no three ballots satisfy all public margins")
        self.bits = (self.states-1).bit_length()

    def answer(self,query,rank):
        query = {atom(t) for t in query}
        owners = self.space.unrank(rank)
        return self.with_partition(query,owners)

    def with_partition(self,query,owners):
        return bool(self.common & query) or len({s for t,s in zip(self.single,owners) if t in query})>=2

    def possible(self,query):
        query = {atom(t) for t in query}
        if self.common & query:
            return [True]
        mask = self.space.possible_votes(tuple(t in query for t in self.single))
        return [v for v in (False,True) if mask & (1<<int(v))]


def ballot_rows(ballots):
    return [[*t,k,sum(t in b for b in ballots)] for t,k in sorted(sum((Counter(b) for b in ballots),Counter()).items())]


def partition(ballots,single):
    seat_names = {}
    owners = []
    for t in single:
        seat = next(i for i,b in enumerate(ballots) if t in b)
        owners.append(seat_names.setdefault(seat,len(seat_names)))
    return tuple(owners)


def issue(ballots,cap=5,relaxed=False):
    if not isinstance(ballots,(list,tuple)) or len(ballots)!=3:
        raise ValueError("need three local ballots")
    ballots = [tuple(atom(t) for t in b) for b in ballots]
    if any(not b or (not relaxed and (len(b)>cap or (len(b)>1 and any(exclusive(t) for t in b)))) for b in ballots):
        raise ValueError("ballot outside cap or singleton rule")
    margins = ballot_rows(ballots)
    receipt = Receipt(margins,cap,relaxed)
    rank = receipt.space.rank(partition(ballots,receipt.single))
    return {"cap":cap,"relaxed":relaxed,"margins":margins,"rank":rank,"states":receipt.states,"extra_bits":receipt.bits}


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request",type=Path)
    args = parser.parse_args()
    try:
        req = json.loads(args.request.read_text(encoding="utf-8-sig"))
        if "ballots" in req:
            result = issue(req["ballots"],req.get("cap",5),req.get("relaxed",False))
        else:
            receipt = Receipt(req["margins"],req.get("cap",5),req.get("relaxed",False))
            result = {"states":receipt.states,"extra_bits":receipt.bits}
            if "query" in req:
                result["possible_without_rank"] = receipt.possible(req["query"])
                if "rank" in req:
                    result["answer"] = receipt.answer(req["query"],req["rank"])
        print(json.dumps(result,indent=2,ensure_ascii=False))
    except (ValueError,TypeError,KeyError,OSError) as exc:
        parser.exit(2,f"{exc}\n")
