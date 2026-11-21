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

    def test_invalid_reading_is_charged(self):
        result = self.planner.run(lambda q: 2, Budget(2, 2))
        self.assertEqual((result.status, result.action, result.spent), ("error", None, Budget(1, 1)))

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
