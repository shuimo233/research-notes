"""Fit two classifiers once, execute their actual binary requests behind a SQLite gate."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from consent_audit import audit


def collect(model, path, offers=range(1,21), consents=(False,True)):
    records = []
    allowed = False

    def authorize(action, table, column, database, caller):
        if action == sqlite3.SQLITE_INSERT and table == "outbox" and not allowed:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    with closing(sqlite3.connect(path, cached_statements=0, isolation_level=None)) as db:
        db.execute("CREATE TABLE outbox(offer INTEGER, consent INTEGER)")
        db.set_authorizer(authorize)
        for allowed in consents:
            for offer in offers:
                request = bool(model.predict([[int(allowed), offer]])[0])
                applied = False
                if request:
                    try:
                        db.execute("INSERT INTO outbox VALUES(?,?)", (offer,int(allowed)))
                    except sqlite3.DatabaseError as exc:
                        if getattr(exc,"sqlite_errorcode",None) != sqlite3.SQLITE_AUTH:
                            raise
                    else:
                        applied = True
                records.append({"consent":allowed,"low":offer,"high":offer,"request":request,"effect":applied})
    with closing(sqlite3.connect(path)) as reader:
        saved = sorted(reader.execute("SELECT offer, consent FROM outbox"))
    expected = sorted((r["low"],int(r["consent"])) for r in records if r["effect"])
    if saved != expected or any(not consent for _,consent in saved):
        raise RuntimeError("gate or readback mismatch")
    return records


def fit_models():
    x = [[consent, b] for consent, offers in [(0,range(1,5)),(1,range(3,7))] for b in offers]
    y = [c for c,_ in x]
    models = {"tree":DecisionTreeClassifier(max_depth=2, random_state=17),
              "logistic":make_pipeline(StandardScaler(),LogisticRegression(C=1.0,solver="lbfgs",max_iter=1000))}
    for model in models.values():
        model.fit(x,y)
    return x, y, models


def run():
    x, y, models = fit_models()
    menu = [{"name":f"shadow-{i}","low":i,"high":i,"cost":1,"capacity":3} for i in range(1,21)]
    results = {}
    with TemporaryDirectory() as tmp:
        for name, model in models.items():
            logs = collect(model, Path(tmp)/(name+".db"))
            full = audit({"max_offer":20,"errors":0,"history":logs,"menu":menu})
            shadowed = [{**r,"request":None} for r in logs]
            blind = audit({"max_offer":20,"errors":0,"history":shadowed,"menu":menu})
            plan = blind["additional_plan"]
            if plan != {"status":"optimal","cost":1,"counts":{"shadow-20":1}}:
                raise RuntimeError("unexpected shadow plan")
            sampled = collect(model, Path(tmp)/(name+"-followup.db"), offers=[20], consents=[False])
            one = audit({"max_offer":20,"errors":0,"history":shadowed+sampled,"menu":[]})
            if name == "tree":
                readout = {"split_features":[int(j) for j in model.tree_.feature if j >= 0],
                           "split_thresholds":[float(t) for j,t in zip(model.tree_.feature,model.tree_.threshold) if j >= 0]}
            else:
                scaler, linear = model.steps[0][1], model.steps[1][1]
                weights = linear.coef_[0]/scaler.scale_
                readout = {"raw_consent_weight":round(float(weights[0]),6),"raw_offer_weight":round(float(weights[1]),6),
                           "raw_intercept":round(float(linear.intercept_[0]-weights @ scaler.mean_),6)}
            results[name] = {"training_correct":int((model.predict(x)==y).sum()),"training_total":len(y),
                             "unauthorized_request_offers":[r["low"] for r in logs if not r["consent"] and r["request"]],
                             "consented_declines":[r["low"] for r in logs if r["consent"] and not r["request"]],
                             "commits":sum(r["effect"] for r in logs),"blind":blind["status"],
                             "blind_cost_without_monotonicity":blind["without_monotonicity"]["additional_plan"]["cost"],
                             "one_shadow":one["status"],"one_shadow_without_monotonicity":one["without_monotonicity"]["status"],
                             "full":full,"records":logs,"fresh_shadow_record":sampled[0],"fitted_structure":readout}
    return {"sklearn":sklearn.__version__,"sqlite":sqlite3.sqlite_version,"models":results}


if __name__ == "__main__":
    print(json.dumps(run(),indent=2))
