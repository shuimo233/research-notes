"""Materialize three-run archives, damage one purchased frame and remove another, then read back."""

from collections import Counter
from itertools import combinations
import json
from pathlib import Path
from random import Random
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parent))
import networkx
import sklearn
from learned_demo import fit_models
from source_demo import capture
from row_noise import Registry
from run_receipt import RunReceipt


def init():
    codec = RunReceipt(31,[(1,15)])
    labels,groups = {},{}
    for a,b in combinations(range(1,32),2):
        receipt = codec.issue(a,b)
        label = f"{receipt['existing']}/{receipt['tag']}"
        groups.setdefault(label,[]).append([19*a,19*b])
        labels[a,b] = label
    # Four rows per stored page, four binary events per row, one byte per event.
    pages = [{"end":4*p,"cost":16} for p in range(1,153)]
    return {"errors":1,"erasures":1,"groups":groups,"pages":pages},labels


def read_pages(folder,panel):
    columns = [dict() for _ in range(4)]
    got = 0
    for p in panel:
        try:
            payload = (folder/f"p-{p}").read_bytes()
        except FileNotFoundError:
            payload = None
        else:
            if len(payload) != 16:
                raise ValueError("bad page size")
            got += len(payload)
        for event,report in enumerate(columns):
            report[str(p)] = None if payload is None else "".join(map(str,payload[event::4]))
    return columns,got


def losing_one_page(engine,panel):
    # Any deletion from this positive-price optimum must permit a collision.
    left_out = panel[0]
    remaining = panel[1:]
    distance,w = engine.limiting(engine.selected(remaining))
    def read_world(source):
        a,b = source["cuts"]
        x,y,z = source["bits"]
        word = x*a+y*(b-a)+z*(engine.rows-b)
        return {str(p):word[engine.starts[p-1]:engine.ends[p-1]] for p in remaining}
    zero = read_world(w["zero"])
    one = read_world(w["one"])
    different = list(w["differing_pages"])
    assert distance == len(different) == 3
    missing,from_one,from_zero = different
    common = {**zero,str(missing):None,str(from_one):one[str(from_one)]}
    assert engine.decode(w["group"],remaining,common)["status"] == "ambiguous"
    return {"omitted":left_out,**w, "erased":missing,
            "one_bad_page_if_zero":from_one,"one_bad_page_if_one":from_zero}


def rewrite_control(folder,roots,truth,totals):
    # A different deployment can export the three named root reports together.
    frame = b"R3v1" + b"".join(p.read_bytes() for p in roots)
    paths = [folder/f"direct-{i}" for i in range(4)]
    for p in paths:
        p.write_bytes(frame)
    paths[0].rename(folder/"direct-missing")
    paths[1].write_bytes(frame[:4]+bytes(x^1 for x in frame[4:]))
    frames = []
    for p in paths:
        try:
            payload = p.read_bytes()
        except FileNotFoundError:
            continue
        frames.append(payload)
        totals["rewritten_bytes_read"] += len(payload)
    for event,expected in enumerate(truth):
        votes = [sum(payload[4+event::4]) >= 2 for payload in frames]
        assert int(sum(votes)>=2) == expected
        totals["rewritten_correct"] += 1


def run():
    doc,labels = init()
    registry = Registry(doc)
    common = registry.optimize()
    conditioned = {g:Registry({**doc,"groups":{g:cuts}}).optimize() for g,cuts in doc["groups"].items()}
    every_layout = {str(i):[pair] for i,pair in enumerate(pair for ls in doc["groups"].values() for pair in ls)}
    known = Registry({**doc,"groups":every_layout})
    assert set(known.rules) == set(registry.rules)
    no_receipt = Registry({**doc,"groups":{"unknown":[p for ls in doc["groups"].values() for p in ls]}})
    assert no_receipt.optimize()["full_distance"] == 0
    rng = Random(10793)
    selected = Random(31871).sample(list(labels),32)
    _,_,models = fit_models()
    totals = Counter()
    with TemporaryDirectory() as temp:
        for k,(a,b) in enumerate(selected):
            folder = Path(temp)/str(k)
            folder.mkdir()
            root_names = ("app","gateway","authorizer")
            roots = [folder/name for name in root_names]
            for root in roots:
                root.touch()
            aliases = [folder/f"slot-{s}" for s in range(32)]
            for i,alias in enumerate(aliases):
                alias.hardlink_to(roots[int(i>=a)+int(i>=b)])
            actual = tuple(i for i in range(1,32) if not aliases[i-1].samefile(aliases[i]))
            assert actual == (a,b)
            group = labels[actual]
            # Keep only the previously registered printable receipt on the read side.
            meta = folder/"receipt"
            meta.write_text(group,encoding="ascii")
            group = meta.read_text(encoding="ascii")
            conditional_panel = conditioned[group]["pages"]
            totals["conditioned_pages_booked"] += len(conditional_panel)
            readings = {key:[] for key in root_names}
            for name,model in models.items():
                bits,commits = capture(model,folder/(name+".db"))
                totals["successful_inserts"] += commits
                for key in root_names:
                    readings[key].extend(bits[key])
            truth = readings["gateway"]
            for j,(key,root) in enumerate(zip(root_names,roots)):
                archived = bytes(bit ^ int(j == k%3) for bit in readings[key])
                root.write_bytes(archived)
            rewrite_control(folder,roots,truth,totals)
            # New independent files make a later frame overwrite distinct from a faulty root.
            blob = b"".join(alias.read_bytes()*19 for alias in aliases)
            for i in range(152):
                (folder/f"p-{i+1}").write_bytes(blob[16*i:16*(i+1)])
            danger = sorted(set(common["pages"]) & set(conditional_panel))
            damaged,missing = rng.sample(danger,2)
            target = folder/f"p-{damaged}"
            target.write_bytes(bytes(x ^ 1 for x in target.read_bytes()))
            (folder/f"p-{missing}").rename(folder/"quarantined")
            for name,panel in (("common",common["pages"]),("conditioned",conditional_panel)):
                columns,count = read_pages(folder,panel)
                totals[name+"_bytes_read"] += count
                for expected,obs in zip(truth,columns):
                    answer = registry.decode(group,panel,obs)
                    assert answer["status"] == ("some_request" if expected else "all_zero")
                    totals[name+"_correct"] += 1
            totals["requests"] += sum(truth)
    return {"sqlite":sqlite3.sqlite_version,"sklearn":sklearn.__version__,"networkx":networkx.__version__,
            "layouts_registered":len(labels),"groups":len(conditioned),"layouts_run":len(selected),
            "logical_pages_per_archive":152,"bytes_per_page":16,"events_per_archive":4,
            "injected_per_archive":{"faulty_root":1,"overwritten_frame":1,"missing_frame":1},
            "common_panel_pages":len(common["pages"]), "full_layout_common_pages":len(known.optimize()["pages"]),
            "common_price":common["cost"], "common_min_distance":common["distance"],
            "common_constraints":len(registry.rules),"individually_planned_pages":{
                g:len(report["pages"]) for g,report in conditioned.items()},
            "rewritten_pages_per_archive":4,
            **totals, "common_panel_minus_one":losing_one_page(registry,common["pages"])}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
