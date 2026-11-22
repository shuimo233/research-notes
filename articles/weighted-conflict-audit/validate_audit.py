"""Differentially test the public export and verifier; enumerate the 13-row reduction."""

from collections import Counter
from itertools import product
import json
from pathlib import Path
from random import Random
import runpy

exp = runpy.run_path(str(Path(__file__).with_name("check.py")))
from stateful_id import ActionPlanner, Domain
from stateful_id.audit import fingerprint, verify

check = exp["check"]


def random_cases():
    rng = Random(321882)
    tally = Counter()
    for trial in range(320):
        width, height = rng.randrange(1, 6), rng.randrange(2, 8)
        counts = [rng.randrange(3) for _ in range(width)]
        probes = [(str(i),) for i in range(width)]
        rows = [[rng.randrange(2) for _ in probes] for _ in range(height)]
        radii = [rng.randrange(sum(counts)+2) for _ in rows]
        universe = rng.randrange(1, 5)
        actions = [rng.randrange(1, 1 << universe) for _ in rows]
        names = [str(i) for i in range(height)]
        allowed = {s: [str(j) for j in range(universe) if actions[i] >> j & 1] for i,s in enumerate(names)}
        domain = Domain("random/v1", {s: (lambda q,row=row: row[int(q[0])]) for s,row in zip(names,rows)}, probes)
        plan = ActionPlanner(domain, allowed, dict(zip(names,radii)))
        exported, claim = plan.audit(dict(zip(probes,counts)))
        trusted = {"format": "stateful-id/audit-1", "domain": "random/v1",
                   "probes": [{"trace": list(q), "count": str(c)} for q,c in zip(probes,counts)],
                   "rules": [{"name": s, "bits": rows[i], "errors": str(radii[i]), "actions": allowed[s]}
                             for i,s in enumerate(names)]}
        check(trusted == exported, trial)
        possible_live_sets = set()
        ambiguous_sets = []
        for selected in range(1 << height):
            common = (1 << universe)-1
            for i,mask in enumerate(actions):
                if selected >> i & 1:
                    common &= mask
            if not common:
                ambiguous_sets.append(selected)
        for z in product(*(range(c+1) for c in counts)):
            live = sum(1 << i for i, row in enumerate(rows)
                       if sum(abs(c*b-x) for c,b,x in zip(counts,row,z)) <= radii[i])
            possible_live_sets.add(live)
            negative = {"problem_sha256": fingerprint(trusted), "guaranteed": False, "ones": [str(x) for x in z]}
            status = verify(trusted, negative).status
            expected = live in ambiguous_sets
            check(status == ("verified" if expected else "rejected"), (trial,z,negative,status))
            tally["checked_transcripts"] += 1
        guaranteed = possible_live_sets.isdisjoint(ambiguous_sets)
        check(claim["guaranteed"] == guaranteed and verify(trusted,claim).status == "verified", trial)
        tally["guarantees" if guaranteed else "ambiguous"] += 1
        # A full-claim oracle checks row semantics against records and action coverage
        # against EVERY row subset; it does not share either verifier search.
        proposed = [claim.get("cores", []), claim.get("cores", [])[1:]]
        proposed += [[[s for s in names if bits >> int(s) & 1] for bits in
                      [rng.randrange(1, 1 << height) for _ in range(rng.randrange(1,5))]] for _ in range(3)]
        for cores in proposed:
            masks = [sum(1 << int(s) for s in core) for core in cores]
            def empty(mask):
                return not any((mask & live) == mask for live in possible_live_sets)
            valid_cores = all(empty(mask) and all(not empty(mask ^ (1 << i)) for i in range(height) if mask >> i & 1)
                              for mask in masks)
            covers = all(any((mask & selected) == mask for mask in masks) for selected in ambiguous_sets)
            forged = {"problem_sha256": fingerprint(trusted), "guaranteed": True, "cores": cores}
            check(verify(trusted,forged).status == ("verified" if valid_cores and covers else "rejected"), (trial,cores))
            tally["checked_core_collections"] += 1
    return dict(tally)


def subsets(n):
    rows, radii = exp["cycle_instance"](n)
    all_rows = (1 << 13)-1
    reachable, reduced = bytearray(1 << 13), bytearray(1 << 13)
    for active in product(range(n+1), repeat=3):
        distances = [sum(abs(n*b-z) for b,z in zip(row,active)) for row in rows[:8]]
        corner_mask = sum(1 << i for i,d in enumerate(distances) if d <= radii[i])
        reduced[corner_mask | ((31 << 8) if sum(active) <= radii[0]-1 else 0)] = 1
        for tail in product(range(n+1), repeat=5):
            t = sum(tail)
            mask = sum(1 << i for i,d in enumerate(distances) if d+t <= radii[i])
            for j in range(5):
                if sum(active) + 2*n+t-2*(tail[j]+tail[(j+1)%5]) <= radii[8+j]:
                    mask |= 1 << (8+j)
            reachable[mask] = 1
    for flags in (reachable, reduced):
        for mask in range(all_rows, 0, -1):
            if flags[mask]:
                for i in range(13):
                    flags[mask & ~(1 << i)] = 1
    check(reachable == reduced, n)
    cores = [mask for mask in range(1, all_rows+1) if not reachable[mask] and
             all(reachable[mask ^ (1 << i)] for i in range(13) if mask >> i & 1)]
    four = sum(1 << i for i in (3,5,6,7))
    check(set(cores) == {255, *(four | (1 << j) for j in range(8,13))}, cores)
    return {"repeats": n, "count_vectors": (n+1)**8, "subfamilies": len(reachable),
            "feasible_subfamilies": sum(reachable), "minimal_core_sizes": sorted(c.bit_count() for c in cores)}


def stress():
    results = []
    for n in (1, 1_000_001, 10**18+1):
        for fixture in ("cycle_instance", "tight_instance"):
            raw = exp[fixture](n)
            rows, radii = raw[0], raw[-1]
            plan, qs = exp["planner"](rows,radii)
            schedule = dict.fromkeys(qs,n)
            problem, claim = plan.audit(schedule)
            result = verify(problem,claim)
            check(claim["guaranteed"] and result.status == "verified", (fixture,n,result))
            check(verify(problem,claim,max_nodes=1).status == "inconclusive", (fixture,n))
            radii[7 if fixture == "cycle_instance" else raw[1][0]] += 1
            relaxed, _ = exp["planner"](rows,radii)
            problem, counter = relaxed.audit(schedule)
            check(not counter["guaranteed"] and verify(problem,counter).status == "verified", (fixture,n))
            results.append({"fixture": fixture, "repeats": str(n), "verified_core_size": len(claim["cores"][0]),
                            "verification_nodes": result.nodes, "counterexample_verified": True})
    return results


if __name__ == "__main__":
    print(json.dumps({"random": random_cases(), "reduction": [subsets(n) for n in (1,3)], "stress": stress()},
                     sort_keys=True, indent=2))
