"""Measure bytes read from synthetic behavior reports or from a separately trusted route receipt."""

from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
import sqlite3
import sys
from tempfile import TemporaryDirectory

import sklearn

sys.path.insert(0,str(Path(__file__).resolve().parent))
from learned_demo import fit_models
from source_demo import capture
from lineage import LineageAudit, observe


def packed(payload, size):
    raw = json.dumps(payload,separators=(",",":")).encode("ascii")
    if len(raw)>size:
        raise ValueError("fixture content exceeds the declared file size")
    return raw.ljust(size,b" ")


def trial(model, layout, folder, receipt_size, extra_size):
    fixture = json.loads(Path(__file__).with_name("lineage-example.json").read_text(encoding="utf-8"))
    raw, commits = capture(model,folder/"gate.db")
    bits = {"app":raw["app"][0],"gateway":raw["gateway"][0],"auth":raw["authorizer"][0]}
    changed = "app" if layout=="app-pair" else "auth"
    stored = {r:(1-v if r==changed else v) for r,v in bits.items()}
    # Capture also exercises payoff 20; only the first, payoff-8 event enters this audit.
    for channel,v in stored.items():
        (folder/(channel+".raw")).write_bytes(packed({"bit":v},24))
    mapping = fixture["layouts"][layout]
    bindings = {}
    for alias in "abcde":
        origin = folder/(mapping[alias]+".raw")
        target = folder/(alias+".report")
        copyfile(origin,target)
        bindings[alias] = origin.stem
    history = [dict(source=s,condition="b8",bit=json.loads((folder/(s+".report")).read_bytes())["bit"]) for s in "abcd"]
    assert history==fixture["history"]
    receipt = packed({"a_root":bindings["a"],"b_root":bindings["b"]},receipt_size)
    extra = packed(json.loads((folder/"e.report").read_bytes()),extra_size)
    checksums = {}
    paths = {}
    for label,data in (("receipt",receipt),("extra",extra)):
        path = folder/(label+".archive")
        path.write_bytes(data)
        paths[label] = path
        checksums[label] = sha256(data).digest()
    menu = [{**q,"cost":paths[q["name"]].stat().st_size} for q in fixture["menu"]]
    problem = {**fixture,"menu":menu,"history":history}
    shared = LineageAudit({**problem,"menu":[]}).report()
    plan = LineageAudit(problem).report()
    selected = plan["next_probe"]
    readback = paths[selected].read_bytes()
    if sha256(readback).digest() != checksums[selected]:
        raise RuntimeError("archive integrity mismatch")
    payload = json.loads(readback)
    answer = int(payload["a_root"]==payload["b_root"]) if selected=="receipt" else payload["bit"]
    conclusion = LineageAudit(observe(problem,selected,answer)).report()
    assert conclusion["status"] == ("some_request" if bits["gateway"] else "all_zero")
    assert len(readback)==plan["worst_case_cost"]
    return {"layout":layout,"payoff":8,"actual_channels":bits,"flipped_logger":changed,"observed_abcd":[r["bit"] for r in history],
            "successful_writes":commits,"history_only":shared["status"],"purchased":selected,"answer":answer,
            "receipt_bytes":receipt_size,"extra_report_bytes":extra_size,"bytes_read":len(readback),
            "conclusion":conclusion["status"]}


def run():
    _,_,models = fit_models()
    tests = []
    with TemporaryDirectory() as temp:
        for layout, model in (("app-pair","tree"),("auth-pair","logistic")):
            for size,other in ((64,128),(192,32)):
                path = Path(temp)/(layout+str(size))
                path.mkdir()
                tests.append(trial(models[model],layout,path,size,other))
    return {"sqlite":sqlite3.sqlite_version,"sklearn":sklearn.__version__,"runs":tests}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
