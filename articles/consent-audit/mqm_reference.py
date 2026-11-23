"""Independent SQLite re-aggregation of the original TSV and the reported collision examples."""

import argparse
from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3


def compare(folder,report):
    lang=report["direction"]
    stem=f"mqm_newstest2020_{lang}"
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript("""
            CREATE TABLE mark(sys TEXT, seg INTEGER, person TEXT, level TEXT, cat TEXT);
            CREATE TABLE official(sys TEXT, seg INTEGER, score TEXT, PRIMARY KEY(sys,seg));
        """)
        with (folder/(stem+".tsv")).open(encoding="utf8",newline="") as stream:
            reader=csv.DictReader(stream,delimiter="\t",quoting=csv.QUOTE_NONE)
            db.executemany("INSERT INTO mark VALUES (?,?,?,?,?)",
                ((r["system"],int(r["seg_id"]),r["rater"],r["severity"].strip().lower(),r["category"].strip()) for r in reader))
        with (folder/(stem+".avg_seg_scores.tsv")).open(encoding="utf8") as stream:
            next(stream)
            db.executemany("INSERT INTO official VALUES (?,?,?)",
                           ((s,int(i),v) for s,v,i in (line.split() for line in stream)))
        db.executescript("""
            CREATE INDEX mark_segment ON mark(sys,seg);
            CREATE TEMP VIEW target AS SELECT * FROM mark
             WHERE lower(replace(cat,'-',' ')) NOT LIKE 'source error%';
            CREATE TEMP TABLE truth AS
             WITH per_person AS (
               SELECT sys,seg,person,MAX(level='major' AND lower(cat)!='no-error') m
               FROM target GROUP BY sys,seg,person
             ) SELECT sys,seg,COUNT(*) persons,SUM(m) endorsers FROM per_person GROUP BY sys,seg;
            CREATE TEMP TABLE marg AS
             SELECT sys,seg,level,cat,COUNT(*) nr,COUNT(DISTINCT person) np
             FROM target GROUP BY sys,seg,level,cat;
            CREATE INDEX marg_seg ON marg(sys,seg);
            CREATE TEMP TABLE observation AS
             SELECT t.sys,t.seg,t.endorsers,o.score,
               (SELECT json_group_array(json_array(level,cat,nr)) FROM
                 (SELECT * FROM marg m WHERE m.sys=t.sys AND m.seg=t.seg ORDER BY level,cat)) bag,
               (SELECT json_group_array(json_array(level,cat,nr,np)) FROM
                 (SELECT * FROM marg m WHERE m.sys=t.sys AND m.seg=t.seg ORDER BY level,cat)) detail
             FROM truth t JOIN official o USING(sys,seg) WHERE t.persons=3;
        """)
        n,yes=db.execute("SELECT COUNT(*),SUM(endorsers>=2) FROM observation").fetchone()
        assert [n,yes]==[report["three_people"],report["major_consensus"]]
        pair = ((name,cols) for name,cols in
                (("public_average","CAST(score AS REAL)"),("rows_by_type","bag"),
                 ("average_and_rows","CAST(score AS REAL),bag"),("average_rows_and_people","CAST(score AS REAL),detail")))
        for name,cols in pair:
            row=db.execute(f"""WITH freq AS (SELECT SUM(endorsers<2) f,SUM(endorsers>=2) t
                              FROM observation GROUP BY {cols})
                              SELECT COUNT(*),SUM(f*t>0),SUM(CASE WHEN f*t>0 THEN f+t ELSE 0 END),
                              SUM(MIN(f,t)) FROM freq""").fetchone()
            got=report["same_summary_opposite_majority"][name]
            assert list(row)==[got[v] for v in ("observed_summaries","mixed_summaries","segments_with_mixed_summary",
                                                "minimum_errors_on_observed_corpus")]
        for name,e in report["natural_collisions"].items():
            fields=[]
            for sys,seg in e["keys"]:
                row=db.execute("SELECT score,bag,detail,endorsers FROM observation WHERE sys=? AND seg=?",(sys,seg)).fetchone()
                assert float(row[0])==float(e["score"])
                fields.append(row)
            assert fields[0][1]==fields[1][1]
            if name!="bag_major":
                assert fields[0][2]==fields[1][2]
            if "major_reporters" in e:
                assert e["major_reporters"]==[r[3] for r in fields]
            if "query" in e:
                q={tuple(v) for v in e["query"]}
                answers=[]
                for sys,seg in e["keys"]:
                    marks=db.execute("SELECT person,level,cat FROM target WHERE sys=? AND seg=?",(sys,seg))
                    answers.append(len({p for p,l,c in marks if (l,c) in q})>=2)
                assert answers==e["answers"]
        return {"direction":lang,"segments_with_three":n,"expert_majorities":yes,
                "summary_baselines_verified":4,"raw_collision_pairs_verified":len(report["natural_collisions"])}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data",type=Path)
    parser.add_argument("result",type=Path)
    args=parser.parse_args()
    print(json.dumps(compare(args.data,json.loads(args.result.read_bytes())),indent=2))
