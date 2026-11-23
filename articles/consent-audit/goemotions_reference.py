"""Independent SQLite re-aggregation of each GoEmotions test export and split summary."""

import argparse
import csv
import json
from pathlib import Path
import sqlite3


def verify(folder, report, exported):
    vocabulary = (folder / "emotions.txt").read_text(encoding="utf8").splitlines()
    mapping = json.loads((folder / "ekman_mapping.json").read_bytes())
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE box(id, voter, marks, unclear, PRIMARY KEY(id,voter));
            CREATE TABLE hierarchy(fine PRIMARY KEY, coarse);
            CREATE TABLE released(id PRIMARY KEY, part, fine);
        """)
        for coarse, children in {**mapping, "neutral": ["neutral"]}.items():
            db.executemany("INSERT INTO hierarchy VALUES(?,?)", ((x, coarse) for x in children))
        for stem in ("train", "dev", "test"):
            with (folder / (stem + ".tsv")).open(encoding="utf8") as stream:
                for line in stream:
                    _, numbers, key = line.rstrip("\r\n").rsplit("\t", 2)
                    labels = sorted(vocabulary[int(x)] for x in numbers.split(","))
                    db.execute("INSERT INTO released VALUES(?,?,?)", (key, stem, json.dumps(labels)))
        for i in (1, 2, 3):
            with (folder / f"goemotions_{i}.csv").open(encoding="utf8", newline="") as stream:
                rows = csv.DictReader(stream)
                db.executemany("INSERT INTO box VALUES(?,?,?,?)",
                               ((r["id"], r["rater_id"], json.dumps([label for label in vocabulary if int(r[label])]),
                                 int(r["example_very_unclear"] == "True")) for r in rows))
        db.executescript("""
            CREATE TABLE keys AS SELECT DISTINCT b.id, coalesce(r.part,'unreleased') part
              FROM box b LEFT JOIN released r USING(id);
            CREATE UNIQUE INDEX keyid ON keys(id);
            CREATE TEMP TABLE mark AS SELECT b.id,b.voter,j.value fine,h.coarse
              FROM box b, json_each(b.marks) j JOIN hierarchy h ON h.fine=j.value;
            CREATE TEMP TABLE fine AS SELECT id,fine FROM mark GROUP BY id,fine HAVING count(DISTINCT voter)>=2;
            CREATE TEMP TABLE first_votes AS SELECT DISTINCT id,coarse FROM fine JOIN hierarchy USING(fine);
            CREATE TEMP TABLE last_votes AS SELECT id,coarse FROM mark GROUP BY id,coarse HAVING count(DISTINCT voter)>=2;
            CREATE TEMP TABLE original AS SELECT released.id,j.value fine FROM released,json_each(released.fine) j;
            CREATE TEMP TABLE official AS SELECT DISTINCT id,coarse FROM original JOIN hierarchy USING(fine);
            CREATE TEMP TABLE added AS SELECT * FROM last_votes EXCEPT SELECT * FROM official;
            CREATE TEMP TABLE removed AS SELECT * FROM official EXCEPT SELECT * FROM last_votes;
            CREATE TEMP TABLE order_add AS SELECT * FROM last_votes EXCEPT SELECT * FROM first_votes;
            CREATE TEMP TABLE alters AS SELECT id,coarse FROM added UNION SELECT id,coarse FROM removed;
            CREATE TEMP TABLE mismatch AS SELECT id,fine FROM original EXCEPT SELECT id,fine FROM fine;
            CREATE TEMP TABLE mismatch_reverse AS SELECT f.id,f.fine FROM fine f JOIN released USING(id)
              EXCEPT SELECT id,fine FROM original;
        """)
        # Source-specific invariants must be re-established before using matched-only counts.
        for table in ("mismatch", "mismatch_reverse", "removed"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        diag = report["diagnostics"]
        assert db.execute("SELECT count(*),count(DISTINCT id),sum(unclear) FROM box").fetchone() == (
            diag["raw_rows"], diag["raw_ids"], diag["unclear_rows"])
        assert db.execute("SELECT count(*) FROM released WHERE id NOT IN (SELECT id FROM keys)").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM box WHERE unclear != (json_array_length(marks)=0)").fetchone()[0] == 0
        for part, obs in report["subsets"].items():
            def count(sql):
                return db.execute(sql, (part,)).fetchone()[0]
            assert count("SELECT count(*) FROM keys WHERE part=?") == obs["eligible"]
            assert count("SELECT count(DISTINCT id) FROM order_add JOIN keys USING(id) WHERE part=?") == obs["order_changed"]
            assert count("""SELECT count(DISTINCT id) FROM last_votes JOIN keys USING(id) WHERE part=?
                         AND id NOT IN (SELECT id FROM fine)""") == obs["raw_fine_empty_coarse_present"]
            people = db.execute("""SELECT CAST(n AS TEXT),count(*) FROM
                      (SELECT count(*) n FROM box JOIN keys USING(id) WHERE part=? GROUP BY id) GROUP BY n""", (part,))
            assert dict(people) == obs["raw_vote_count_histogram"]
            for table, field in [("order_add", "order_added"), ("added", "release_added"), ("removed", "release_removed")]:
                if part == "unreleased" and field != "order_added":
                    continue
                observed = db.execute(f"SELECT coarse,count(*) FROM {table} JOIN keys USING(id) WHERE part=? GROUP BY coarse", (part,))
                assert dict(observed) == obs[field]
            if part != "unreleased":
                assert count("SELECT count(DISTINCT id) FROM alters JOIN keys USING(id) WHERE part=?") == obs["release_changed"]
                assert obs["fine_equal_release"] == obs["eligible"]
        test = {k: [[], []] for k, in db.execute("SELECT id FROM released WHERE part='test'")}
        for i, table in enumerate(("official", "last_votes")):
            for key, coarse in db.execute(f"SELECT v.id,v.coarse FROM {table} v JOIN keys USING(id) WHERE part='test' ORDER BY v.coarse"):
                test[key][i].append(coarse)
        observed = {}
        with exported.open(encoding="utf8") as stream:
            for row in map(json.loads, stream):
                key = row["id"]
                assert key not in observed and row["status"] == "ok" and row["fine_matches"] is True
                observed[key] = [row["published_ekman"], row["two_reporters_ekman"]]
        assert observed == test
        example = report["first_three_person_test_example"][0]
        candidates = db.execute("""SELECT k.id FROM keys k JOIN box b USING(id) WHERE k.part='test' AND
             k.id IN (SELECT id FROM alters) GROUP BY k.id HAVING count(*)=3 ORDER BY k.id LIMIT 1""")
        assert candidates.fetchone()[0] == example["id"]
        ballots = [sorted(json.loads(b)) for b, in db.execute("SELECT marks FROM box WHERE id=?", (example["id"],))]
        assert sorted(ballots) == example["anonymous_three_ballots"]
        return {"raw_votes": diag["raw_rows"], "original_split_labels_verified": sum(
            r["split_rows"] for r in report["subsets"].values()),
            "test_label_pairs_verified": len(test), "first_example_verified": example["id"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("test_comparison", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.folder, json.loads(args.result.read_bytes()), args.test_comparison), indent=2))
