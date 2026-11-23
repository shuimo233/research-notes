"""Post-holdout comparison of three ways to combine recorded Major judgments."""

import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mqm_wmt import load, positive


def outcomes(ballots):
    leaves = [{category for level, category in ballot if positive((level, category))}
              for ballot in ballots]
    families = [{category.partition("/")[0] for category in ballot} for ballot in leaves]

    def has_shared(sets):
        return any(a & b for i, a in enumerate(sets) for b in sets[i + 1:])

    return has_shared(leaves), has_shared(families), sum(bool(s) for s in leaves) >= 2


def sql_counts(path):
    # A separate TSV parser and independent SQL aggregation validate every segment.
    with path.open(encoding="utf8", newline="") as stream, sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE marks(sys,seg INTEGER,rater,category,level)")
        rows = csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE)
        db.executemany("INSERT INTO marks VALUES(?,?,?,?,?)",
                       ((r["system"], int(r["seg_id"]), r["rater"], r["category"].strip(),
                         r["severity"].strip().lower()) for r in rows))
        values = db.execute("""
            WITH hits AS (
                SELECT sys,seg,rater,category,substr(category,1,instr(category||'/','/')-1) AS family
                FROM marks WHERE level='major' AND lower(category)!='no-error'
                AND lower(replace(category,'-',' ')) NOT LIKE 'source error%'
            ), flags AS (
                SELECT sys,seg,1 AS kind FROM hits GROUP BY sys,seg,category HAVING count(DISTINCT rater)>=2
                UNION ALL
                SELECT sys,seg,2 FROM hits GROUP BY sys,seg,family HAVING count(DISTINCT rater)>=2
                UNION ALL
                SELECT sys,seg,3 FROM hits GROUP BY sys,seg HAVING count(DISTINCT rater)>=2
            ), keys AS (SELECT DISTINCT sys,seg FROM marks)
            SELECT sys,seg,max(CASE WHEN kind=1 THEN 1 ELSE 0 END),
                           max(CASE WHEN kind=2 THEN 1 ELSE 0 END),
                           max(CASE WHEN kind=3 THEN 1 ELSE 0 END)
            FROM keys LEFT JOIN flags USING(sys,seg) GROUP BY sys,seg
        """)
        return {(system, seg): (bool(leaf), bool(family), bool(any_major))
                for system, seg, leaf, family, any_major in values}


def run(folder, lang):
    ratings, _, _ = load(folder, lang)
    reference = sql_counts(folder / f"mqm_newstest2020_{lang}.tsv")
    if reference.keys() != ratings.keys():
        raise ValueError("the two imports disagree on segment keys")
    fields = ("segments", "same_leaf", "same_family", "any_major",
              "same_family_only", "across_families_only")
    systems = {}
    for key, group in ratings.items():
        if len(group) != 3:
            raise ValueError(f"expected three ballots for {key}")
        flags = outcomes(group.values())
        leaf, family, any_major = flags
        if flags != reference[key] or not (leaf <= family <= any_major):
            raise ValueError(f"aggregation mismatch for {key}")
        counts = systems.setdefault(key[0], dict.fromkeys(fields, 0))
        for field, value in zip(fields, (1, leaf, family, any_major,
                                         family and not leaf, any_major and not family)):
            counts[field] += int(value)
    return {"direction": lang,
            "total": {field: sum(c[field] for c in systems.values()) for field in fields},
            "by_system": systems}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    print(json.dumps([run(args.folder, lang) for lang in ("ende", "zhen")],
                     indent=2, sort_keys=True))
