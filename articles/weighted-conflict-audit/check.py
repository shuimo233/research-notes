"""Reproduce the correctness and live-lock experiments; no external dependencies."""

from collections import Counter
from contextlib import ExitStack, closing
from itertools import combinations, product
import json
from pathlib import Path
from random import Random
import sqlite3
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages/stateful-identification"))
import stateful_id as sid


def check(ok, detail):
    if not ok:
        raise RuntimeError(detail)


def shards():
    tags = [(), *((i,) for i in range(5)), *((i,(i+1)%5) for i in range(5))]
    return [tuple(int(i in tag) for i in range(5)) + tuple(int(site == j) for j in (1,2,3))
            for tag, site in product(tags, range(4))]


def planner(rows, radii, api=sid):
    qs = tuple((str(i),) for i in range(len(rows[0])))
    rules = {str(i): (lambda q, row=row: row[int(q[0])]) for i,row in enumerate(rows)}
    actions = {i: set(rules)-{i} for i in rules}
    domain = api.Domain("queued-writes/v1", rules, qs)
    return api.ActionPlanner(domain, actions, dict(zip(rules, radii))), qs


def tight_instance(n):
    rows = shards()
    # Square on tag bits 0,1 times the edge for location bit 5.
    corners = [i for i,r in enumerate(rows) if not any(r[q] for q in (2,3,4,6,7))]
    radius = 3 * ((n+1)//2) - 1
    check(n % 2 == 1 and len(corners) == 8, n)
    return rows, corners, [radius if i in corners else 8*n for i in range(len(rows))]


def cycle_instance(n):
    # K3 and C5 are separate components of the crossing graph.
    corners = [tuple(int(b) for b in format(i, "03b")) + (0,) * 5 for i in range(8)]
    edges = [(0,) * 3 + tuple(int(j in (i, (i+1) % 5)) for j in range(5)) for i in range(5)]
    radius = 3 * ((n+1)//2) - 1
    rows, radii = corners + edges, [radius]*8 + [radius+2*n-1]*5
    for i, j in combinations(range(len(rows)), 2):
        distance = n * sum(x != y for x, y in zip(rows[i], rows[j]))
        check(abs(radii[i]-radii[j]) < distance <= radii[i]+radii[j], (n,i,j))
    # Increasing only the 111 corner's budget by one admits this complete record.
    z = [n//2]*3 + [0]*5
    distances = [sum(n-a if b else a for b,a in zip(row,z)) for row in rows]
    check(all(d <= r + (i == 7) for i,(d,r) in enumerate(zip(distances,radii))), n)
    # The proof gives eight candidate records, one of which works for any four rows.
    live_sets = []
    for offset in product((0, 1), repeat=3):
        record = [n//2+b for b in offset] + [0]*5
        live_sets.append({i for i,row in enumerate(rows)
                          if sum(n-z if b else z for b,z in zip(row,record)) <= radii[i]})
    check(all(any(set(four) <= live for live in live_sets)
              for four in combinations(range(len(rows)), 4)), n)
    return rows, radii


def compressed():
    results = []
    for n in (1, 3, 9, 27, 1_000_001):
        rows, corners, radii = tight_instance(n)
        p, qs = planner(rows, radii)
        schedule = dict.fromkeys(qs, n)
        a = p.assess(schedule, witnesses=True)
        check(a.guaranteed and set(map(int,a.witnesses[0])) == set(corners), (n,a))
        check(a.methods == ("two_columns",), a.methods)
        radii[corners[0]] += 1
        p, _ = planner(rows, radii)
        b = p.assess(schedule, witnesses=True)
        ones = dict(b.counterexample_ones)
        check(not b.guaranteed and p.decide(schedule, ones).status == "ambiguous", n)
        for i,row in enumerate(rows):
            check(sum(n-ones[q] if y else ones[q] for q,y in zip(qs,row)) <= radii[i], (i,n))
        cycle_rows, cycle_radii = cycle_instance(n)
        cp, cq = planner(cycle_rows, cycle_radii)
        cycle_schedule = dict.fromkeys(cq, n)
        proven = cp.assess(cycle_schedule, witnesses=True)
        check(proven.guaranteed and proven.methods == ("halfball_tree",), (n, proven))
        if n == 1:
            core = [int(i) for i in proven.witnesses[0]]
            def overlaps(ids):
                return any(all(sum(x != y for x,y in zip(bits,cycle_rows[i])) <= cycle_radii[i] for i in ids)
                           for bits in product((0, 1),repeat=8))
            check(not overlaps(core) and all(overlaps([i for i in core if i != j]) for j in core), core)
        cycle_radii[7] += 1
        cp, _ = planner(cycle_rows, cycle_radii)
        example = cp.assess(cycle_schedule, witnesses=True)
        check(cp.decide(cycle_schedule, dict(example.counterexample_ones)).status == "ambiguous", n)
        results.append({"repeats_each": n, "core_size": len(a.witnesses[0]), "counterexample_verified": True,
                        "cycle_core_size": len(proven.witnesses[0]), "cycle_counterexample_verified": True})
    return results


def random_tables():
    rng = Random(822341)
    histogram = Counter()
    for trial in range(512):
        indices = rng.sample(shards(), rng.randint(10,36))
        flip = [rng.randrange(2) for _ in range(8)]
        rows = [tuple(x ^ y for x,y in zip(r,flip)) for r in indices]
        # Add a complementary probe and a duplicate rule on alternating trials.
        rows = [r + (1-r[0],) for r in rows]
        if trial % 2:
            rows.append(rows[0])
        radii = [rng.randint(2,7) for _ in rows]
        p, qs = planner(rows, radii)
        schedule = [*qs, qs[rng.randrange(len(qs))]]
        case = p.assess(schedule, witnesses=True)
        expected = [sum(row[int(q[0])] << i for i,q in enumerate(schedule)) for row in rows]
        def overlaps(subset):
            return any(all((y ^ expected[i]).bit_count() <= radii[i] for i in subset)
                       for y in range(1 << len(schedule)))
        check(case.guaranteed != overlaps(range(len(rows))), trial)
        if case.guaranteed:
            core = tuple(map(int, case.witnesses[0]))
            check(not overlaps(core) and all(overlaps([j for j in core if j != k]) for k in core), trial)
        else:
            check(p.decide(schedule, dict(case.counterexample_ones)).status == "ambiguous", trial)
        histogram[case.methods[0]] += 1
    return histogram


def sqlite():
    rows = shards()
    p, qs = planner(rows, [2]*len(rows))
    check(p.assess(qs).guaranteed, "two faults")
    relaxed, _ = planner(rows, [3]*len(rows))
    check(not relaxed.assess(qs).guaranteed, "three faults")
    _, corners, radii = tight_instance(1)
    joint, _ = planner(rows, radii)
    check(joint.assess(qs).guaranteed, corners)
    for i,j in combinations(range(len(rows)), 2):
        check(sum(a != b for a,b in zip(rows[i],rows[j])) <= radii[i]+radii[j], (i,j))
    writes, mixed_writes, scans = Counter(), 0, 0
    persisted = 0
    with TemporaryDirectory(prefix="queue-proof-") as tmp, ExitStack() as stack:
        def connect(path):
            return stack.enter_context(closing(sqlite3.connect(path, isolation_level=None, timeout=0)))
        paths = [Path(tmp)/f"queue{i}.db" for i in range(len(rows))]
        dbs = [connect(path) for path in paths]
        for db in dbs:
            db.execute("PRAGMA synchronous=OFF")  # Timing durability is outside this fixture.
            db.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, origin INT)")
        for busy,path in enumerate(paths):
            with closing(sqlite3.connect(path, isolation_level=None, timeout=0)) as writer:
                writer.execute("BEGIN IMMEDIATE")
                locked = []
                for i,db in enumerate(dbs):
                    scans += 1
                    try:
                        db.execute("BEGIN IMMEDIATE")
                    except sqlite3.OperationalError as err:
                        code = getattr(err, "sqlite_errorcode", None)
                        busy_error = code == 5 if code is not None else str(err) == "database is locked"
                        if not busy_error:
                            raise
                        locked.append(i)
                    else:
                        db.rollback()
                check(locked == [busy], (locked,busy))
                bits = tuple(int(any(rows[i][j] for i in locked)) for j in range(8))
                for count in range(3):
                    for errors in combinations(range(8), count):
                        report = {q: y ^ (j in errors) for j,(q,y) in enumerate(zip(qs,bits))}
                        verdict = p.decide(qs, report)
                        check(verdict.status == "ready" and str(busy) in verdict.candidates, (busy,errors))
                        dbs[int(verdict.action)].execute("INSERT INTO jobs(origin) VALUES(?)", (busy,))
                        writes[count] += 1
                for mask in range(256):
                    if mask.bit_count() <= radii[busy]:
                        report = {q: y ^ ((mask >> j) & 1) for j,(q,y) in enumerate(zip(qs,bits))}
                        verdict = joint.decide(qs, report)
                        check(verdict.status == "ready" and str(busy) in verdict.candidates, (busy,mask))
                        dbs[int(verdict.action)].execute("INSERT INTO jobs(origin) VALUES(?)", (busy,))
                        mixed_writes += 1
                writer.rollback()
        for path in paths:
            with closing(sqlite3.connect(path)) as independent:
                persisted += independent.execute("SELECT count(*) FROM jobs").fetchone()[0]
    check(sum(writes.values()) == 1628 and mixed_writes == 9512 and persisted == 11140, persisted)
    return {"shards": len(rows), "lock_checks": scans, "uniform_writes_by_flip_count": writes,
            "mixed_writes": mixed_writes, "persisted": persisted}


if __name__ == "__main__":
    print(json.dumps({"compressed": compressed(), "oracle": random_tables(), "sqlite": sqlite()},
                     indent=2, sort_keys=True))
