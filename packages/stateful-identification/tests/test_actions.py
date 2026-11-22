import unittest

from stateful_id import ActionPlanner, Budget, Domain


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.x, self.y, self.expensive = ("x",), ("y",), ("expensive_x",)
        rules = {name: (lambda q, name=name: int(name[1 if q == self.y else 0]))
                 for name in ("00", "01", "10", "11")}
        self.domain = Domain("replica/v1", rules, [self.expensive, self.x, self.y],
                             cost=lambda q: 9 if q == self.expensive else 1)
        self.actions = {name: set(rules) - {name} for name in rules}
        self.planner = ActionPlanner(self.domain, self.actions, errors=1)

    def test_collective_certificate_and_inadequate_budget(self):
        schedule = self.planner.plan(Budget(2, 2))
        self.assertEqual(schedule, (self.x, self.y))
        report = self.planner.assess(schedule, witnesses=True)
        self.assertTrue(report.guaranteed)
        self.assertEqual(report.witnesses, (tuple(self.domain.rules),))
        missing = self.planner.assess([self.x])
        self.assertFalse(missing.guaranteed)
        self.assertEqual(missing.obstruction, tuple(self.domain.rules))
        result = self.planner.run(self.fail, Budget(2, 1))
        self.assertEqual((result.status, result.spent), ("no_guaranteed_plan", Budget(0, 0)))

    def test_action_still_valid_with_a_flipped_observation(self):
        result = self.planner.run(lambda q: int(q == self.y), Budget(2, 2))
        self.assertEqual(result.action, "10")
        self.assertIn("00", result.candidates)
        self.assertEqual(result.spent, Budget(2, 2))

    def test_positive_count_report_matches_observe(self):
        result = self.planner.decide([self.x, self.y], {self.x: 0, self.y: 1})
        self.assertEqual((result.status, result.action, result.candidates),
                         ("ready", "10", ("00", "01", "11")))
        strict = ActionPlanner(self.domain, self.actions)
        conflict = strict.decide([self.x, self.x], {self.x: 1})
        self.assertEqual((conflict.status, conflict.action, conflict.candidates), ("conflict", None, ()))
        for invalid in ({}, {self.x: 2}, {self.x: -1}, {self.x: True}):
            with self.assertRaises(ValueError):
                self.planner.decide([self.x], invalid)

    def test_actual_ambiguous_record_for_complementary_and_repeated_probes(self):
        domain = Domain("complements", {"a": lambda q: int(q == self.x), "b": lambda q: int(q != self.x)},
                        [self.x, self.y])
        p = ActionPlanner(domain, {"a": ["a"], "b": ["b"]}, {"a": 3, "b": 1})
        schedule = {self.x: 2, self.y: 2}
        cert = p.assess(schedule, witnesses=True)
        self.assertEqual(cert.obstruction, ("a", "b"))
        decoded = p.decide(schedule, dict(cert.counterexample_ones))
        self.assertEqual((decoded.status, decoded.candidates), ("ambiguous", cert.obstruction))
        self.assertIsNone(p.assess(schedule).counterexample_ones)
        self.assertEqual(p.assess([], witnesses=True).counterexample_ones, ())

    def test_invalid_reading_is_charged(self):
        result = self.planner.run(lambda q: 2, Budget(2, 2))
        self.assertEqual((result.status, result.action, result.spent), ("error", None, Budget(1, 1)))

    def test_compressed_eight_row_boundary_and_four_way_crossing_fallback(self):
        # A triangle and an independent edge require three vertices to cover the edges.
        corners = [format(value, "03b") + "00" for value in range(8)]
        signatures = corners + ["00001", "00010", "00011"]
        repeats = 100_001
        qs = [(str(i),) for i in range(5)]
        rules = {s: (lambda q, s=s: int(s[int(q[0])])) for s in signatures}
        allowed = {s: set(signatures) - {s} for s in signatures}
        domain = Domain("weighted-cube", rules, qs)
        budgets = {s: 3 * ((repeats + 1) // 2) - 1 if s in corners else 5 * repeats for s in rules}
        schedule = dict.fromkeys(qs, repeats)
        report = ActionPlanner(domain, allowed, budgets).assess(schedule, witnesses=True)
        self.assertEqual(report.methods, ("two_columns",))
        self.assertEqual(set(report.witnesses[0]), set(corners))
        budgets[corners[0]] += 1
        relaxed = ActionPlanner(domain, allowed, budgets)
        example = relaxed.assess(schedule, witnesses=True).counterexample_ones
        self.assertEqual(set(relaxed.decide(schedule, dict(example)).candidates), set(signatures))

        qs = qs[:4]
        cube = [format(value, "04b") for value in range(16)]
        rules = {s: (lambda q, s=s: int(s[int(q[0])])) for s in cube}
        domain = Domain("four-crossing-columns", rules, qs)
        planner = ActionPlanner(domain, {s: set(cube) - {s} for s in cube}, errors=3)
        report = planner.assess(qs, witnesses=True)
        self.assertEqual(report.methods, ("count_search",))
        self.assertEqual(set(report.witnesses[0]), set(cube))

    def test_pairwise_feasible_table_uses_joint_five_row_witness(self):
        corners = [format(i, "03b") + "00000" for i in range(8)]
        edge_rows = ["00011000", "00001100", "00000110", "00000011", "00010001"]
        signatures = corners + edge_rows
        qs = [(str(i),) for i in range(8)]
        rules = {s: (lambda q, s=s: int(s[int(q[0])])) for s in signatures}
        allowed = {s: set(signatures) - {s} for s in signatures}
        radii = {s: 2 if s in corners else 3 for s in signatures}
        planner = ActionPlanner(Domain("pairwise-overlap", rules, qs), allowed, radii)
        result = planner.assess(qs, witnesses=True)
        self.assertEqual(result.methods, ("halfball_tree",))
        self.assertEqual(len(result.witnesses[0]), 5)

    def test_common_action_without_probing(self):
        actions = {n: {"available"} for n in self.domain.rules}
        plan = ActionPlanner(self.domain, actions)
        self.assertEqual(plan.run(self.fail, Budget(0, 0)).action, "available")

    def test_unobservable_conflict_rejected(self):
        domain = Domain("aliases", {"a": lambda q: 0, "b": lambda q: 0}, [()])
        planner = ActionPlanner(domain, {"a": ["x"], "b": ["y"]}, 1)
        self.assertIsNone(planner.plan(Budget(10, 100)))

    def test_invalid_specifications(self):
        with self.assertRaises(ValueError):
            ActionPlanner(self.domain, self.actions, {"00": 1})
        for bad in ({self.x: -1}, {("z",): 1}):
            with self.assertRaises(ValueError):
                self.planner.assess(bad)


if __name__ == "__main__":
    unittest.main()
