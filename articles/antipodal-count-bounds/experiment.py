"""Deterministic fixtures, independent small-box checks and live SQLite writes."""

from collections import Counter
from contextlib import ExitStack, closing
from itertools import product
import json
from pathlib import Path
from random import Random
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/stateful-identification"))
import stateful_id as sid
from stateful_id._bounds import count_intervals, four_intervals, restrict_counts
from stateful_id.audit import verify


def check(ok, detail):
    if not ok:
        raise AssertionError(detail)


def fixture(n, parity=True):
    d = 6 if parity else 4
    rows = [r for r in product((0,1), repeat=d) if not parity or sum(r)%2 == 0]
    sizes = [n + (j%3 if n == 1 else 3*j) for j in range(d)]
    center = [size//(2+j%3) for j,size in enumerate(sizes)]
    radii = [distance(row, sizes, [x+1-bit for x,bit in zip(center,row)]) - (2 if parity else 1) for row in rows]
    return rows, sizes, radii, center


def distance(row, sizes, record):
    return sum(abs(n * b - z) for n,b,z in zip(sizes,row,record))


def columns(rows, sizes):
    return {sum(r[j] << i for i,r in enumerate(rows)): n for j,n in enumerate(sizes)}


def planner(rows, sizes, radii, api=sid):
    names = [str(i) for i in range(len(rows))]
    probes = [(str(j),) for j in range(len(sizes))]
    domain = api.Domain("busy-shard/address-v1", {s: lambda q,r=r: r[int(q[0])] for s,r in zip(names,rows)}, probes)
    return api.ActionPlanner(domain, {s:set(names)-{s} for s in names}, dict(zip(names,radii))), dict(zip(probes,sizes))


def jitter(case):
    rng = Random(715409 + case)
    rows, sizes, radii, _ = fixture(100_001, True)
    keep = sorted(rng.sample(range(len(rows)), len(rows) - 1 - case%4))
    return [rows[i] for i in keep], sizes, [radii[i]+rng.randrange(-1,4) for i in keep]


def small():
    rng = Random(657123)
    outcomes = Counter()
    visited = 0
    for trial in range(220):
        d = rng.randint(2,5)
        universe = list(product((0,1), repeat=d))
        rows = rng.sample(universe, rng.randint(3,len(universe)))
        if trial%2:
            rows.append(rows[0])
        sizes = [rng.randint(1,3) for _ in range(d)]
        radii = [rng.randint(0,sum(sizes)) for _ in rows]
        cols = columns(rows, sizes)
        if len(cols) < d:  # The public planner already merges identical types.
            continue
        p, schedule = planner(rows,sizes,radii)
        report = p.assess(schedule,witnesses=True)
        intervals = four_intervals(cols,radii)
        if intervals is not None:
            rem, budgets = restrict_counts(cols,radii,intervals)
        any_ok = False
        for z in product(*(range(n+1) for n in sizes)):
            visited += 1
            expected = all(distance(r,sizes,z) <= b for r,b in zip(rows,radii))
            mapped = intervals is not None and all(lo <= v <= hi for v,(lo,hi) in zip(z,intervals))
            if mapped:
                residual = [v-lo for v,(lo,hi) in zip(z,intervals) if hi > lo]
                mapped = all(distance([(mask >> i) & 1 for mask in rem],list(rem.values()),residual) <= b
                             for i,b in enumerate(budgets))
            check(mapped == expected, (trial,z))
            any_ok |= expected
        check(report.guaranteed != any_ok, trial)
        problem, claim = p.audit(schedule,count_hints=True)
        check(verify(problem,claim).status == "verified", trial)
        outcomes[str(any_ok)] += 1
    return {"tables_by_overlap": dict(outcomes), "raw_count_vectors": visited}


def large():
    results = []
    for family in (False,True):
        rows,sizes,radii,center = fixture(1_000_001,family)
        p,schedule = planner(rows,sizes,radii)
        problem,claim = p.audit(schedule,count_hints=True)
        check(claim["guaranteed"] and len(claim["cores"][0]) == len(rows), family)
        checked = verify(problem,claim,max_nodes=4000)
        plain = verify(problem,{k:v for k,v in claim.items() if k != "row_sums"},max_nodes=4000)
        check(checked.status == "verified", checked)
        # Construct one *different* feasible original record after removing each row.
        for i,r in enumerate(rows):
            z = [a+1-bit for a,bit in zip(center,r)]
            check(all((distance(s,sizes,z) <= limit) == (j != i) for j,(s,limit) in enumerate(zip(rows,radii))), i)
        # Relaxation by two for the parity code, by one for the full cube.
        radii[0] += (2 if family else 1)
        relaxed,schedule = planner(rows,sizes,radii)
        other,counter = relaxed.audit(schedule,count_hints=True)
        check(not counter["guaranteed"] and verify(other,counter).status == "verified", family)
        results.append({"rows":len(rows),"hints":len(claim["row_sums"]),"with_hints":checked.status,
                        "with_nodes":checked.nodes,"without_hints":plain.status,"without_nodes":plain.nodes})
    return results


def sqlite_writes():
    rows,sizes,radii,_ = fixture(1,False)
    p,schedule = planner(rows,sizes,radii)
    problem,claim = p.audit(schedule,count_hints=True)
    check(verify(problem,claim).status == "verified", "plan")
    writes, lock_checks = 0, 0
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        paths = [Path(tmp)/f"shard-{i}.db" for i in range(16)]
        conns = [stack.enter_context(closing(sqlite3.connect(path,timeout=0,isolation_level=None))) for path in paths]
        for db in conns:
            db.execute("PRAGMA synchronous=OFF")
            db.execute("CREATE TABLE jobs(origin INTEGER)")
        for i,path in enumerate(paths):
            with closing(sqlite3.connect(path,isolation_level=None,timeout=0)) as busy:
                busy.execute("BEGIN IMMEDIATE")
                locked = []
                for j,db in enumerate(conns):
                    lock_checks += 1
                    try:
                        db.execute("BEGIN IMMEDIATE")
                    except sqlite3.OperationalError as exc:
                        if str(exc) != "database is locked":
                            raise
                        locked.append(j)
                    else:
                        db.rollback()
                check(locked == [i], locked)
                for counts in product(*(range(n+1) for n in sizes)):
                    if distance(rows[locked[0]], sizes, counts) <= radii[i]:
                        result = p.decide(schedule,dict(zip(schedule,counts)))
                        check(result.status == "ready" and int(result.action) != i, (i,counts))
                        conns[int(result.action)].execute("INSERT INTO jobs VALUES(?)",(i,))
                        writes += 1
        persisted = 0
        for j,path in enumerate(paths):
            with closing(sqlite3.connect(path)) as db:
                count,bad = db.execute("SELECT COUNT(*), COUNT(CASE WHEN origin=? THEN 1 END) FROM jobs",(j,)).fetchone()
                check(bad == 0,j)
                persisted += count
    check(writes == persisted and writes > 0, writes)
    return {"sizes":sizes,"lock_checks":lock_checks,"checked_count_reports":writes,"commits_read_back":persisted}


if __name__ == "__main__":
    print(json.dumps({"small":small(),"large":large(),"sqlite":sqlite_writes()},indent=2,sort_keys=True))
