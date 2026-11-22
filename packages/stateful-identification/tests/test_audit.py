import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from stateful_id import ActionPlanner, Domain
from stateful_id import audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        names = ("a", "b", "c", "d")
        self.probes = [("first",), ("second",)]
        rules = {name: (lambda q, i=i: (i >> self.probes.index(q)) & 1) for i,name in enumerate(names)}
        self.planner = ActionPlanner(Domain("four/v1", rules, self.probes),
                                     {name: set(names)-{name} for name in names}, errors=1)

    def test_guarantee_and_counterexample_round_trip(self):
        for schedule, expected in [(iter(self.probes), True), ({self.probes[0]: 1}, False),
                                   ({self.probes[0]: 0}, False), ([], False)]:
            problem, claim = json.loads(json.dumps(self.planner.audit(schedule)))
            self.assertEqual(claim["guaranteed"], expected)
            self.assertEqual(audit.verify(problem, claim).status, "verified")
        problem, claim = self.planner.audit(self.probes)
        self.assertEqual(audit.verify(problem, claim, max_nodes=0).status, "inconclusive")
        self.assertEqual(audit.verify(problem, {**claim, "cores": []}).status, "rejected")
        self.assertEqual(audit.verify(problem, {**claim, "cores": [["a","b","c"]]}).status, "rejected")
        problem["rules"][0]["errors"] = "2"
        self.assertEqual(audit.verify(problem, claim).status, "rejected")
        self.assertEqual(audit.verify(problem, {**claim, "problem_sha256": audit.fingerprint(problem)}).status, "rejected")

    def test_global_coverage_despite_individually_valid_core(self):
        q = ("bit",)
        domain = Domain("coverage", {"a": lambda _: 0, "b": lambda _: 1, "c": lambda _: 1}, [q])
        planner = ActionPlanner(domain, {"a": ["left"], "b": ["right"], "c": ["right"]})
        problem, claim = planner.audit([q])
        self.assertEqual(len(claim["cores"]), 2)
        self.assertEqual(audit.verify(problem, claim).status, "verified")
        partial = {**claim, "cores": claim["cores"][:1]}
        self.assertIn("uncovered", audit.verify(problem, partial).detail)
        redundant = {**claim, "cores": [["a","b","c"]]}
        self.assertIn("redundant", audit.verify(problem, redundant).detail)

    def test_negative_requires_a_reachable_ambiguous_record(self):
        q = self.probes[0]
        strict = ActionPlanner(self.planner.domain, {n: [n] for n in self.planner.names})
        problem, claim = strict.audit({q: 2})
        self.assertFalse(claim["guaranteed"])
        for ones in ([1], ["3"], [True], [], ["01"], ["1"]):
            self.assertEqual(audit.verify(problem, {**claim,"ones":ones}).status, "rejected")

    def test_standalone_with_no_planner_or_site_packages(self):
        problem, claim = self.planner.audit(self.probes)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(audit.__file__, root/"audit.py")
            for filename, value in [("p",problem), ("c",claim)]:
                (root/filename).write_text(json.dumps(value), encoding="utf-8")
            cmd = [sys.executable, "-I", "-S", "audit.py", "p", "c"]
            for extra, expected in [([],0), (["--max-nodes","0"],2)]:
                result = subprocess.run(cmd+extra, cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
            raw = json.dumps(claim).replace('"guaranteed": true', '"guaranteed": false, "guaranteed": true')
            (root/"c").write_text(raw, encoding="utf-8")
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate JSON key", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "JavaScript runtime unavailable")
    def test_large_odd_counts_survive_javascript_json_transport(self):
        n = 10**18 + 1
        q = ("同步",)
        names = {"北": lambda _: 0, "南": lambda _: 1}
        domain = Domain("跨语言/v1", names, [q])
        for budget, expected in [(n//2, True), (n//2+1, False)]:
            planner = ActionPlanner(domain, {s: [s] for s in names}, budget)
            payload = json.dumps(planner.audit({q: n}))
            script = "process.stdout.write(JSON.stringify(JSON.parse(require('fs').readFileSync(0,'utf8'))))"
            output = subprocess.check_output(["node", "-e", script], input=payload.encode("ascii"))
            problem, claim = json.loads(output)
            self.assertEqual(problem["probes"][0]["count"], "1000000000000000001")
            self.assertEqual(claim["guaranteed"], expected)
            self.assertEqual(audit.verify(problem, claim).status, "verified")


if __name__ == "__main__":
    unittest.main()
