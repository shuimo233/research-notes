"""Capture the same request at three observation points and audit verified, locally archived bits."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
import sqlite3
import sys
from tempfile import TemporaryDirectory

import sklearn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from learned_demo import fit_models
from source_audit import SourceAudit, observe


def capture(model, path):
    payoffs = (8, 20)
    application, entry, authorization = [], [0,0], [0,0]
    with closing(sqlite3.connect(path, cached_statements=0, isolation_level=None)) as db:
        db.execute("CREATE TABLE outbox (payoff INTEGER)")

        def authorize(action, table, *_):
            if action == sqlite3.SQLITE_INSERT and table == "outbox":
                authorization[index] = 1
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def submit(index, payoff):
            entry[index] = 1
            try:
                db.execute("INSERT INTO outbox VALUES (?)", (payoff,))
            except sqlite3.DatabaseError as err:
                if getattr(err,"sqlite_errorcode",None) != sqlite3.SQLITE_AUTH:
                    raise

        db.set_authorizer(authorize)
        for index, payoff in enumerate(payoffs):
            decision = int(model.predict([[0,payoff]])[0])
            application.append(decision)
            if decision:
                submit(index, payoff)
    with closing(sqlite3.connect(path)) as reader:
        committed, = reader.execute("SELECT COUNT(*) FROM outbox").fetchone()
    if committed or application != entry or entry != authorization:
        raise RuntimeError("capture or gate did not behave as specified")
    return {"app":application,"gateway":entry,"authorizer":authorization}, committed


def experiment(model, directory, suppress):
    actual, committed = capture(model, directory/"gate.db")
    logged = {src: ([0,0] if src == suppress else bits) for src,bits in actual.items()}
    conditions = ["b8","b20"]
    for src in ("app","gateway"):
        (directory/src).write_text(json.dumps(dict(zip(conditions,logged[src]))),encoding="utf-8")
    copyfile(directory/"app", directory/"export")
    roots = {"app":"application","export":"application","gateway":"gateway","authorizer":"authorizer"}
    history = []
    for src in ("app","export","gateway"):
        bits = json.loads((directory/src).read_bytes())
        history.extend({"source":src,"condition":c,"bit":bits[c]} for c in conditions)
    files = {"reread":directory/"export"}
    for j,c in enumerate(conditions):
        path = directory/("verify-"+c)
        content = json.dumps({c:logged["authorizer"][j]}).encode().ljust(64 if j==0 else 128,b" ")
        path.write_bytes(content)
        files[path.name] = path
    signed = {key:sha256(path.read_bytes()).digest() for key,path in files.items()}
    menu = [{"name":key, "source":"export" if key=="reread" else "authorizer",
             "condition":"b20" if key=="verify-b20" else "b8", "cost":path.stat().st_size}
            for key,path in files.items()]
    problem = {"conditions":conditions,"sources":roots,"fault_budget":1,"history":history,"menu":menu}
    copy_only = SourceAudit({**problem,"menu":menu[:1]}).report()
    wrong_map = SourceAudit({**problem,"sources":{**roots,"export":"separate"}}).report()
    initial = SourceAudit(problem).report()
    decision = initial
    trace = []
    while decision["status"] == "resolvable":
        selected = decision["next_probe"]
        item = next(p for p in menu if p["name"] == selected)
        raw = files[selected].read_bytes()
        if sha256(raw).digest() != signed[selected] or len(raw) != item["cost"]:
            raise RuntimeError("readback mismatch")
        observed = json.loads(raw)[item["condition"]]
        trace.append({"file":selected,"bytes":len(raw),"bit":observed})
        problem = observe(problem, selected, observed)
        decision = SourceAudit(problem).report()
    return {"suppressed_reporter":suppress, "raw_channels":actual,"initial_archived_history":history,
            "committed_rows":committed,"copy_only":copy_only,"if_copy_mislabeled_as_new_root":wrong_map["status"],
            "with_third_channel":initial,"trace":trace,"final":decision["status"],
            "verification_bytes":sum(step["bytes"] for step in trace)}


def run():
    _, _, models = fit_models()
    results = {}
    with TemporaryDirectory() as tmp:
        for label, model, fault in (("tree_clean","tree",None),("logistic_clean","logistic",None),
                                   ("app_suppressed","logistic","app"),("gateway_suppressed","logistic","gateway")):
            directory = Path(tmp)/label
            directory.mkdir()
            results[label] = experiment(models[model],directory,fault)
    return {"sklearn":sklearn.__version__,"sqlite":sqlite3.sqlite_version,"conditions":[8,20],"runs":results}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
