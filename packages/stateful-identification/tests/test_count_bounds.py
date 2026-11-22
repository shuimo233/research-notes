from itertools import product
import unittest

from stateful_id import ActionPlanner, Domain
from stateful_id._bounds import count_intervals, four_intervals
from stateful_id.audit import verify


class CountBoundTests(unittest.TestCase):
    def test_parity_fixture_and_original_row_hints(self):
        rows = [r for r in product((0,1),repeat=6) if sum(r)%2 == 0]
        n = 100_001
        probes = [(str(j),) for j in range(6)]
        columns = {sum(r[j] << i for i,r in enumerate(rows)): n for j in range(6)}
        radii = [6 * ((n+1)//2)-2]*len(rows)
        self.assertEqual(count_intervals(columns,radii), [(0,n)]*6)
        self.assertEqual(four_intervals(columns,radii), [(n//2,n//2+1)]*6)
        rules = {str(i):lambda q,r=r: r[int(q[0])] for i,r in enumerate(rows)}
        p = ActionPlanner(Domain("six-bit/check",rules,probes), {s:set(rules)-{s} for s in rules},radii[0])
        schedule = dict.fromkeys(probes,n)
        problem,claim = p.audit(schedule,count_hints=True)
        self.assertEqual(len(claim["cores"][0]),32)
        self.assertTrue(claim["row_sums"])
        self.assertEqual(verify(problem,claim,max_nodes=4000,require_minimal=True).status,"verified")
        wrong = {**claim,"row_sums":[["absent"]]}
        self.assertEqual(verify(problem,wrong).status,"rejected")
        # Even a true aggregate referencing a removed rule cannot be applied to that deletion.
        wrong = {**claim,"cores":[claim["cores"][0][1:]]}
        self.assertEqual(verify(problem,wrong).status,"rejected")

    def test_guarantee_only_is_an_explicitly_weaker_evidence_request(self):
        q = ("q",)
        rules = {"a":lambda _:0,"b":lambda _:1,"c":lambda _:1}
        domain = Domain("scope",rules,[q])
        p = ActionPlanner(domain,{s:set(rules)-{s} for s in rules})
        problem,claim = p.audit([q],count_hints=True,minimal=False)
        self.assertEqual(verify(problem,claim).detail,"guarantee only checked")
        self.assertEqual(verify(problem,claim,require_minimal=True).status,"rejected")
        self.assertEqual(verify(problem,{**claim,"minimal":True}).status,"rejected")
        problem,claim = p.audit([],minimal=False)
        self.assertFalse(claim["guaranteed"])
        self.assertEqual(verify(problem,claim).status,"verified")

    def test_record_keeps_original_complement_duplicate_and_zero_count(self):
        rows = [r+(1-r[0],r[1],0) for r in product((0,1),repeat=4)]
        qs = [(str(j),) for j in range(7)]
        sizes = (101,102,103,104,19,20,0)
        z = (32,55,34,22,9,8,0)
        rules = {str(i):lambda q,r=r:r[int(q[0])] for i,r in enumerate(rows)}
        radii = {str(i):sum(abs(n*b-v) for n,b,v in zip(sizes,row,z)) for i,row in enumerate(rows)}
        planner = ActionPlanner(Domain("raw-order",rules,qs),{s:set(rules)-{s} for s in rules},radii)
        schedule = dict(zip(qs,sizes))
        report = planner.assess(schedule,witnesses=True)
        self.assertIn("count_bounds",report.methods)
        actual = dict(report.counterexample_ones)
        self.assertEqual(list(actual),qs)
        self.assertEqual(actual[qs[-1]],0)
        self.assertTrue(all(sum(abs(n*b-actual[q]) for n,b,q in zip(sizes,row,qs)) <= radii[str(i)]
                            for i,row in enumerate(rows)))


if __name__ == "__main__":
    unittest.main()
