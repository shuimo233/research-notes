"""Compare every receipt with raw three-ballot truth tables, without assuming the quotient."""

from collections import defaultdict
from itertools import combinations,combinations_with_replacement
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parent))
from mqm_receipt import Receipt, ballot_rows, issue
from mqm_wmt import bag_bounds
import mqm_archive


def exercise(cap,n,relaxed=False):
    ordinary=tuple((("major" if i%2==0 else "minor"),f"test-{i}") for i in range(n))
    no=("no-error","No-error")
    nt=("major","Non-translation!")
    types=ordinary+(nt,)
    queries=[set(q) for k in range(len(types)+1) for q in combinations(types,k)]
    allowed=[(no,),(nt,)]+[b for k in range(1,cap+1) for b in combinations_with_replacement(ordinary,k)]
    if relaxed:
        # Three nonempty ballots with at most six total rows can have at most four each.
        allowed=[b for k in range(1,5) for b in combinations_with_replacement(types+(no,),k)]
    truth_by_margin=defaultdict(set)
    rank_to_truth=defaultdict(dict)
    bag_tallies=defaultdict(set)
    checks = count = 0
    max_states=0
    for ballots in combinations_with_replacement(allowed,3):
        if relaxed and sum(map(len,ballots))>6:
            continue
        count+=1
        sets=list(map(set,ballots))
        table=tuple(sum(bool(s&q) for s in sets)>=2 for q in queries)
        pack=issue(list(ballots),cap,relaxed)
        m=tuple(map(tuple,pack["margins"]))
        codec=Receipt(m,cap,relaxed)
        rank=pack["rank"]
        view=tuple(codec.answer(q,rank) for q in queries)
        assert view==table
        assert rank_to_truth[m].setdefault(rank,view)==view
        truth_by_margin[m].add(table)
        bag=tuple(row[:3] for row in m)
        bag_tallies[bag].add(sum(any(t[0]=="major" for t in s) for s in sets))
        checks+=len(queries)
    for m,distinct in truth_by_margin.items():
        codec=Receipt(m,cap,relaxed)
        assert len(distinct)==codec.states
        assert set(rank_to_truth[m])==set(range(codec.states))
        assert set(rank_to_truth[m].values())==distinct
        for i,q in enumerate(queries):
            assert codec.possible(q)==sorted({v[i] for v in distinct})
        if not relaxed:
            lo,hi=bag_bounds(m,cap)
            assert bag_tallies[tuple(row[:3] for row in m)]==set(range(lo,hi+1))
        max_states=max(max_states,codec.states)
    return {"cap":None if relaxed else cap,"relaxed":relaxed,"ordinary_types":n,"three_ballot_tables":count,"margins":len(truth_by_margin),
            "reference_query_answers":checks,"largest_function_set":max_states}


def run():
    checks=[exercise(2,3),exercise(3,3),exercise(2,4),exercise(5,2,True)]
    a=("major","Accuracy/A"); b=("major","Accuracy/B"); c=("minor","Fluency/C"); d=("minor","Style/D")
    linked1=issue([[a,b],[c],[d]])
    linked2=issue([[a,c],[b],[d]])
    assert linked1["margins"]==linked2["margins"] and linked1["rank"]!=linked2["rank"]
    codec=Receipt(linked1["margins"])
    assert codec.possible([a,b])==[False,True]
    assert [codec.answer([a,b],x["rank"]) for x in (linked1,linked2)]==[False,True]
    trivial=issue([[a],[a],[a]])
    assert trivial["extra_bits"]==0
    with TemporaryDirectory() as tmp:
        folder=Path(tmp)/"store"
        parts=[linked1,trivial,linked2,linked1,linked2,trivial]
        rows=[(("s",i),p["margins"],p["rank"],False) for i,p in enumerate(parts)]
        mqm_archive.write(folder,rows)
        assert [rank for _,_,rank in mqm_archive.read(folder)]==[p["rank"] for p in parts]
        (folder/"owners.bin").write_bytes(b"")
        try:
            list(mqm_archive.read(folder))
        except ValueError:
            pass
        else:
            raise AssertionError("corrupt archive accepted")
    return {"exhaustive":checks,"example_ranks":[linked1["rank"],linked2["rank"]],"example_states":codec.states}


if __name__=="__main__":
    print(json.dumps(run(),indent=2))
