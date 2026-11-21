"""Rebuild evidence using the released planner and an independent transcript oracle."""

from collections import Counter
from itertools import combinations, combinations_with_replacement, product
import json
from pathlib import Path
from random import Random
import runpy
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "stateful-identification"))
from stateful_id import ActionPlanner, Budget, Domain


def require(ok, detail):
    if not ok:
        raise RuntimeError(detail)


def make(rows, allowed, radii):
    probes = tuple((str(i),) for i in range(len(rows[0])))
    rules = {str(i): (lambda q, row=row: row[int(q[0])]) for i, row in enumerate(rows)}
    domain = Domain("binary-check/v1", rules, probes)
    return ActionPlanner(domain, dict(zip(rules, allowed)), dict(zip(rules, radii))), probes


def exclusion(n):
    return [{str(j) for j in range(n) if i != j} for i in range(n)]


def exact(rows, allowed, radii, schedule):
    for readings in product((0, 1), repeat=len(schedule)):
        live = [a for row, a, r in zip(rows, allowed, radii)
                if sum(row[q] != y for q, y in zip(schedule, readings)) <= r]
        if live and not set.intersection(*live):
            return False
    return True


def small():
    rows = list(product((0, 1), repeat=2))
    allowed = exclusion(4)
    checked = Counter()
    for radii in product(range(3), repeat=4):
        planner, (a, b) = make(rows, allowed, radii)
        for x, y in product(range(4), repeat=2):
            got = planner.assess({a: x, b: y}).guaranteed
            require(got == exact(rows, allowed, radii, (0,)*x + (1,)*y), (x, y, radii))
            checked["count_and_error_cases"] += 1
    choices = [{str(i) for i in range(3) if mask & (1 << i)} for mask in range(1, 8)]
    for allowed in product(choices, repeat=4):
        for f in (0, 1):
            radii = (f,) * 4
            planner, probes = make(rows, allowed, radii)
            require(planner.assess(probes).guaranteed == exact(rows, allowed, radii, (0, 1)), allowed)
            checked["action_cases"] += 1
    return checked


def stress():
    rng = Random(712061)
    methods = Counter()
    for _ in range(600):
        h, width = rng.randint(4, 9), rng.randint(3, 6)
        rows = [tuple(rng.randrange(2) for _ in range(width)) for _ in range(h)]
        radii = [rng.randrange(5) for _ in rows]
        allowed = exclusion(h)
        planner, probes = make(rows, allowed, radii)
        qs = tuple(rng.randrange(width) for _ in range(rng.randint(1, 9)))
        answer = planner.assess([probes[q] for q in qs])
        require(answer.guaranteed == exact(rows, allowed, radii, qs), (rows, radii, qs))
        methods.update(answer.methods)
    return methods


def cubes():
    result = []
    for d in range(1, 5):
        rows = list(product((0, 1), repeat=d))
        allowed = exclusion(len(rows))
        plan, probes = make(rows, allowed, [d-1]*len(rows))
        report = plan.assess(probes, witnesses=True)
        require(report.guaranteed and len(report.witnesses[0]) == len(rows), d)
        # With any one center removed, its complement is a transcript allowed by every other center.
        for removed in rows:
            complement = tuple(1-x for x in removed)
            require(all(sum(x != y for x, y in zip(complement, r)) <= d-1 for r in rows if r != removed), d)
        result.append({"dimensions": d, "irredundant_rows": len(rows), "method": report.methods[0]})
    return result


def grid():
    p = 3
    rows = [tuple(int(c > t) for c in (x, y) for t in range(p))
            for x, y in product(range(p + 1), repeat=2)]
    allowed = exclusion(len(rows))
    # Two paths, three splits each. Crossing graph is K3,3. Query every split once.
    results = []
    for r in (2, 3, 4):
        radii = [r]*len(rows)
        planner, probes = make(rows, allowed, radii)
        answer = planner.assess(probes, witnesses=True)
        require(answer.methods == ("two_trees",) and answer.guaranteed == exact(rows, allowed, radii, range(6)), r)
        size = len(answer.witnesses[0]) if answer.guaranteed else None
        require(size is None or size <= 4, size)
        results.append({"allowance": r, "guaranteed": answer.guaranteed, "witness_size": size})
    return results


def two_color_stress():
    rng = Random(727)
    counts = Counter()
    # Cross a pair of paths and a pair of branching stars. Every instance has K3,3
    # as its crossing graph; the model centers therefore exercise the parity path.
    for style in ("paths", "stars"):
        rows = [tuple(int(c > t if style == "paths" else c == t+1) for c in (x,y) for t in range(3))
                for x,y in product(range(4), repeat=2)]
        actions = exclusion(len(rows))
        for _ in range(100):
            schedule = (*range(6), *rng.choices(range(6), k=2))
            reference = tuple(rng.randrange(2) for q in schedule)
            radii = [max(0, sum(row[q] != y for q,y in zip(schedule, reference)) + rng.choice((-1,0,1)))
                     for row in rows]
            planner, probes = make(rows, actions, radii)
            result = planner.assess([probes[q] for q in schedule])
            require(result.methods == ("two_trees",), style)
            require(result.guaranteed == exact(rows, actions, radii, schedule), (style, radii, reference))
            counts["separated" if result.guaranteed else "overlap"] += 1
    return counts


def branched_product():
    # Enumerate all minimal empty families of vertex balls on a claw times an edge.
    # This direct set-intersection computation uses neither the planner nor its theorem.
    vertices = list(product(range(4), range(2)))
    def distance(p, q):
        a, b = p[0], q[0]
        return int(a != b) * (1 + int(a != 0 and b != 0)) + int(p[1] != q[1])
    balls = sorted({sum(1 << i for i, q in enumerate(vertices) if distance(p, q) <= r)
                    for p in vertices for r in range(4)})
    full = (1 << len(vertices))-1
    counts = Counter()
    def visit(start, joint, without):
        for j in range(start, len(balls)):
            b = balls[j]
            reduced = joint & b
            omitted = [x & b for x in without] + [joint]
            # Every member must still have a possible private witness.
            if not all(x & ~reduced for x in omitted):
                continue
            if not reduced:
                counts[len(omitted)] += 1
            else:
                visit(j+1, reduced, omitted)
    visit(0, full, [])
    require(max(counts) == 4, counts)
    return {"vertices": len(vertices), "different_balls": len(balls), "minimal_empty_by_size": counts}


def three_branching_factors():
    # Compare the 64 actual vertices of a product of claws with all 512 bit records.
    def encode(x):
        return sum(int(c == j+1) << (3*t+j) for t, c in enumerate(x) for j in range(3))
    points = [encode(x) for x in product(range(4), repeat=3)]
    small_full, cube_full = (1 << 64)-1, (1 << 512)-1
    def masks(space):
        return {(c,r): sum(1 << i for i,v in enumerate(space) if (v ^ c).bit_count() <= r)
                for c in points for r in range(10)}
    small, cube = masks(points), masks(range(512))
    def meet(cases, lookup, full):
        for case in cases:
            full &= lookup[case]
        return full
    tight = [(encode(x), 2) for x in product((0,1), repeat=3)]
    require(not meet(tight, small, small_full), tight)
    require(all(meet(tight[:i]+tight[i+1:], small, small_full) for i in range(8)), tight)
    rng = Random(71364)
    counts = Counter()
    max_core = 0
    for trial in range(512):
        anchor = rng.choice(points)
        centers = rng.sample(points, rng.randint(9,16))
        cases = [(c,max(0,(c ^ anchor).bit_count() + rng.choice((-1,0,1)))) for c in centers]
        direct = bool(meet(cases, small, small_full))
        require(direct == bool(meet(cases, cube, cube_full)), cases)
        counts["overlap" if direct else "empty"] += 1
        if not direct:
            core = list(cases)
            for case in cases:
                rest = [c for c in core if c != case]
                if not meet(rest, small, small_full):
                    core = rest
            max_core = max(max_core, len(core))
            require(len(core) <= 8, core)
        if trial % 16 == 0:
            rows = [tuple((c >> q) & 1 for q in range(9)) for c in centers]
            plan, qs = make(rows, exclusion(len(rows)), [r for _, r in cases])
            require(plan.assess(qs).guaranteed == (not direct), cases)
    return dict(counts, max_sampled_core=max_core, tight_core=len(tight))


def replicas():
    rows = list(product((0, 1), repeat=2))
    plan, probes = make(rows, exclusion(4), [1]*4)
    schedule = plan.plan(Budget(2, 2))
    require(schedule == probes and plan.plan(Budget(1, 2)) is None, schedule)
    checked = 0
    for i, row in enumerate(rows):
        for error in (None, 0, 1):
            stream = iter(row[j] ^ int(j == error) for j in range(2))
            out = plan.run(lambda q: next(stream), Budget(2, 2))
            require(out.status == "ready" and out.action != str(i) and out.spent == Budget(2, 2), (row, error))
            checked += 1
    identity, _ = make(rows, [{str(i)} for i in range(4)], [1]*4)
    full = identity.plan(Budget(6, 6))
    require(full is not None and len(full) == 6, full)
    n = 1_000_001
    big, _ = make(rows, exclusion(4), [n]*4)
    report = big.assess(dict.fromkeys(probes, n), witnesses=True)
    require(report.guaranteed and len(report.witnesses[0]) == 4, report)
    require(big.assess({probes[0]: n, probes[1]: n-1}).guaranteed is False, n)
    pair_depth = next(n for n in range(7) if any(
        any(sum(a[q] != b[q] for q in s) > 2 for a, b in combinations(rows, 2))
        for s in combinations_with_replacement(range(2), n)))
    require(pair_depth == 3, pair_depth)
    return {"joint": len(schedule), "pair_only": pair_depth, "identify": len(full),
            "executed_worlds_and_errors": checked, "compact_rechecks": 2*n}


def sqlite_trials():
    sql = runpy.run_path(str(HERE.parent / "action-before-identification" / "verify.py"))
    modes = sql["POLICIES"]
    rows = [tuple(sql["read"](m, q) for q in range(4)) for m in modes]
    allowed = [{a for a in sql["CONTINUATIONS"] if sql["action_rows"](m, a) == sql["GOAL"]} for m in modes]
    require(not set.intersection(*allowed), modes)
    runs = []
    for f in (0, 1):
        radii = [f]*5
        planner, probes = make(rows, allowed, radii)
        limit = Budget(12, 12)
        chosen = planner.plan(limit)
        depth = len(chosen)
        brute = next(n for n in range(depth+1) if any(exact(rows, allowed, radii, s)
                     for s in combinations_with_replacement(range(4), n)))
        require(brute == depth, (f, depth, brute))
        identity, _ = make(rows, [{m} for m in modes], radii)
        ids = identity.plan(limit)
        require(len(ids) == 4*(2*f+1), ids)
        executed = 0
        for m in modes:
            for flip in (None, *range(depth)) if f else (None,):
                calls = []
                def observe(q):
                    y = sql["read"](m, probes.index(q)) ^ int(len(calls) == flip)
                    calls.append(q)
                    return y
                out = planner.run(observe, Budget(depth, depth))
                require(out.status == "ready" and sql["action_rows"](m, out.action) == sql["GOAL"], (m, flip))
                executed += 1
        runs.append({"f": f, "fixed_action": depth, "fixed_identity": len(ids),
                     "outcomes_executed": executed, "prefix_rechecks": 0})
    return runs


if __name__ == "__main__":
    print(json.dumps({"small": small(), "random_methods": stress(), "sharp": cubes(), "grid": grid(),
                      "branched": branched_product(), "two_color_checks": two_color_stress(),
                      "three_branching_factors": three_branching_factors(),
                      "replicas": replicas(), "sqlite": sqlite_trials()}, sort_keys=True, indent=2))
