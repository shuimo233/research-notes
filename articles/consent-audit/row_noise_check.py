"""Independent exhaustive reference using physical page strings and all opposite-world pairs."""

from copy import deepcopy
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from row_noise import Registry


def words(doc):
    ends = [p["end"] for p in doc["pages"]]
    starts = [0]+ends[:-1]
    by_group = {}
    for name,layouts in doc["groups"].items():
        classes = [set(),set()]
        for a,b in layouts:
            for x,y,z in product("01",repeat=3):
                raw = x*a+y*(b-a)+z*(ends[-1]-b)
                classes[int((x,y,z).count("1") >= 2)].add(tuple(raw[i:j] for i,j in zip(starts,ends)))
        by_group[name] = classes
    return by_group


def supports(groups):
    return {sum((a!=b)<<j for j,(a,b) in enumerate(zip(zero,one)))
            for zero_words,one_words in groups.values() for zero in zero_words for one in one_words}


def world_pages(ends,w):
    a,b = w["cuts"]
    x,y,z = w["bits"]
    raw = x*a+y*(b-a)+z*(ends[-1]-b)
    return [raw[i:j] for i,j in zip([0]+ends[:-1],ends)]


def check(doc, totals, rng):
    engine = Registry(doc)
    groups = words(doc)
    mask_family = supports(groups)
    finer = {str(i):[pair] for i,pair in enumerate(
        pair for entries in doc["groups"].values() for pair in entries)}
    fine_family = supports(words({**doc,"groups":finer}))
    same_for_every_panel = True
    # Minimal supports, using literal stored page contents; no interval assumption.
    minimal = {m for m in mask_family if not any(s != m and s & m == s for s in mask_family)}
    compiled = {sum(1<<p for p in range(a,b+1)) for a,b in engine.rules}
    assert compiled == minimal
    best = None
    P = len(engine.ends)
    for mask in range(1<<P):
        selected = {j for j in range(P) if (mask>>j)&1}
        dist = min((mask&s).bit_count() for s in mask_family)
        fine_dist = min((mask&s).bit_count() for s in fine_family)
        assert fine_dist >= dist
        same_for_every_panel &= fine_dist == dist
        actual,w = engine.limiting(selected)
        assert actual == dist
        zero,one = [world_pages(engine.ends,w[key]) for key in ("zero","one")]
        assert zero != one or dist == 0
        assert w["zero"]["bits"].count("1") <= 1 and w["one"]["bits"].count("1") >= 2
        assert all(w[key]["cuts"] in doc["groups"][w["group"]] for key in ("zero","one"))
        assert w["differing_pages"] == [j+1 for j in sorted(selected) if zero[j]!=one[j]]
        if dist >= 2*doc["errors"]+doc["erasures"]+1:
            price = sum(doc["pages"][i]["cost"] for i in selected)
            best = price if best is None else min(best,price)
        totals["panel_distances"] += 1
    value = engine.layout_value()
    assert (value["status"] == "identical_for_every_fixed_panel") == same_for_every_panel
    if not same_for_every_panel:
        example = value["zero_noise_example"]
        mask = sum(1<<(i-1) for i in example["pages"])
        assert min((mask&s).bit_count() for s in mask_family) == example["receipt_distance"] == 0
        assert min((mask&s).bit_count() for s in fine_family) == example["full_layout_distance"] > 0
    totals["equal_under_full_layout"] += int(same_for_every_panel)
    report = engine.optimize()
    engine.verify(report)
    if best is None:
        assert report["status"] == "impossible"
        totals["impossible"] += 1
    else:
        assert report["status"] == "optimal" and report["cost"] == best
        totals["optimal"] += 1
    # Probe sparse arbitrary/off-model page patterns; the decoder must also distinguish
    # excess erasures, no plausible world, and two plausible classes.
    for _ in range(6):
        selected = [j+1 for j in range(P) if rng.randrange(2)]
        observed = {str(j):(None if rng.randrange(6)==0 else
                            "".join(rng.choices("01",k=engine.ends[j-1]-engine.starts[j-1]))) for j in selected}
        group = rng.choice(list(groups))
        check_decoding(engine,group,selected,observed,groups[group],totals)
    totals["registries"] += 1


def check_decoding(engine,group,selected,observed,classes,totals):
    got = engine.decode(group,selected,observed)
    if list(observed.values()).count(None) > engine.erasures:
        assert got["status"] == "outside_erasure_budget"
    else:
        def mismatch(raw):
            return sum(observed[str(p)] is not None and observed[str(p)] != raw[p-1] for p in selected)
        scores = [min(map(mismatch, side)) for side in classes]
        statuses = {(True,True):"ambiguous", (False,False):"inconsistent",
                    (True,False):"all_zero", (False,True):"some_request"}
        assert got["status"] == statuses[tuple(v<=engine.errors for v in scores)]
        assert scores == [entry["distance"] for entry in got["classes"]]
        assert scores == [mismatch(world_pages(engine.ends,entry["world"])) for entry in got["classes"]]
    totals["decoded_statuses"][got["status"]] = totals["decoded_statuses"].get(got["status"],0)+1


def run():
    rng = Random(28317)
    totals = dict(registries=0,panel_distances=0,optimal=0,impossible=0,equal_under_full_layout=0,decoded_statuses={})
    for n in range(3,8):
        layouts = list(combinations(range(1,n),2))
        for a,b in layouts:
            for ends in ([n], list(range(1,n+1))):
                for e,s in ((0,0),(1,0),(0,1)):
                    p = {"pages":[{"end":k,"cost":k%4} for k in ends], "groups":{"x":[[a,b]]},
                         "errors":e,"erasures":s}
                    check(p,totals,rng)
    for _ in range(210):
        n = rng.randrange(4,13)
        ends = sorted(rng.sample(range(1,n),rng.randrange(min(6,n-1))))+[n]
        layouts = list(combinations(range(1,n),2))
        groups = {}
        for i,(a,b) in enumerate(rng.sample(layouts,rng.randint(1,min(6,len(layouts))))):
            groups.setdefault(str(rng.randrange(3)),[]).append([a,b])
        p = {"groups":groups, "pages":[{"end":j,"cost":rng.choice([0,1,4,7,10**20+3])} for j in ends],
             "errors":rng.randrange(2),"erasures":rng.randrange(3)}
        check(p,totals,rng)
    wide = {"groups":{"A":[[7,18],[8,19]],"B":[[8,17],[9,18]]},
            "pages":[{"end":j,"cost":(7*j)%13} for j in [*range(2,27,2),27]],
            "errors":1,"erasures":1}
    check(wide,totals,rng)
    robust = Registry(wide)
    panel = robust.optimize()["pages"]
    targeted = 0
    for group,classes in words(wide).items():
        for truth,side in enumerate(classes):
            for ideal in side:
                base = {str(p):ideal[p-1] for p in panel}
                for missing in panel:
                    for damaged in panel:
                        if damaged == missing:
                            continue
                        for bits in product("01",repeat=len(ideal[damaged-1])):
                            substitute = "".join(bits)
                            if substitute == ideal[damaged-1]:
                                continue
                            observed = {**base,str(missing):None,str(damaged):substitute}
                            got = robust.decode(group,panel,observed)
                            assert got["status"] == ("some_request" if truth else "all_zero")
                            targeted += 1
    # An omitted adjacent layout can make even full-archive recovery depend on the receipt.
    sparse = dict(errors=1,erasures=0,pages=[dict(end=i,cost=1) for i in range(1,16)],
                  groups={"same":[[3,7],[8,12]]})
    complete = {**sparse,"groups":{"left":[[3,7]],"right":[[8,12]]}}
    coarse_distance = Registry(sparse).optimize()["full_distance"]
    fine_distance = Registry(complete).limiting(set(range(15)))[0]
    prices = [Registry({**s,"errors":0}).optimize()["cost"] for s in (sparse,complete)]
    assert (coarse_distance,fine_distance,prices) == (1,3,[5,4])
    # Independently exhaust every possible corrupted or erased 2-row page, including invalid words.
    p = {"groups":{"same":[[1,3],[3,5]]},"pages":[{"end":k,"cost":1} for k in (2,4,6)],
         "errors":1,"erasures":1}
    engine = Registry(p)
    classes = words(p)["same"]
    for panel in ([],[1,3],[1,2,3]):
        for received in product((None,"00","01","10","11"),repeat=len(panel)):
            check_decoding(engine,"same",panel,dict(zip(map(str,panel),received)),classes,totals)
    sample = json.loads(Path(__file__).with_name("row-noise-example.json").read_bytes())
    ref = Registry(sample)
    result = ref.optimize()
    for field,value in (("cost",result["cost"]+1),("distance",0),("dual",[]),("pages",[]),
                        ("dual",[[1,18,10**30]])):
        corrupt = deepcopy(result)
        corrupt[field] = value
        try:
            ref.verify(corrupt)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted tampered {field}")
    return {"seed":28317,**totals, "targeted_error_plus_erasure_decodes":targeted, "missing_adjacent_layout":{
        "receipt_full_distance":coarse_distance,"known_full_distance":fine_distance,"zero_error_prices":prices}}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
