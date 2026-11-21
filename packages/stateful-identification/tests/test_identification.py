import json
from pathlib import Path
import tempfile
import unittest

from stateful_id import Budget, Domain, Journal, identify, replay, traces
from stateful_id.examples import publish, sqlite_policy


class IdentificationTests(unittest.TestCase):
    def setUp(self):
        self.domain = Domain("switch/v1", {"off": lambda q: False, "on": lambda q: True},
                             [("try",)], checks=[("check",)])
        self.limit = Budget(2, 2)

    def test_no_queries_reports_next_probe_and_no_model(self):
        result = identify(self.domain, self.fail, Budget(0, 0))
        self.assertEqual((result.status, result.reason, result.spent), ("ambiguous", "budget", Budget(0, 0)))
        self.assertEqual(result.next_probe.actions, ("try",))
        self.assertIsNone(result.model)

    def test_resumed_budget_is_cumulative_and_never_repeats_query(self):
        calls = []

        def observe(actions):
            calls.append(actions)
            return True

        first = identify(self.domain, observe, Budget(1, 1), strategy="fixed")
        self.assertEqual((first.status, first.next_probe.phase), ("unverified", "check"))
        self.assertIsNone(first.model)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "observations.json"
            first.journal.save(path)
            journal = Journal.load(path)
        self.assertEqual(first, replay(self.domain, journal))
        self.assertEqual(replay(self.domain, journal, self.limit).reason, "ready")
        result = identify(self.domain, observe, self.limit, journal=journal)
        self.assertEqual(calls, [("try",), ("check",)])
        self.assertEqual((result.status, result.spent, result.journal.strategy),
                         ("identified", self.limit, "fixed"))
        self.assertTrue(result.model(("new",)))
        self.assertEqual(result, replay(self.domain, result.journal))
        self.assertEqual(result, identify(self.domain, self.fail, self.limit, journal=result.journal))

    def test_heldout_contradiction_suppresses_previously_unique_model(self):
        result = identify(self.domain, lambda q: q == ("try",), self.limit)
        self.assertEqual((result.status, result.spent), ("conflict", self.limit))
        self.assertEqual((result.steps[-1].before, result.steps[-1].after), (("on",), ()))
        self.assertEqual(result.conflict_predictions, {"on": True})
        self.assertIsNone(result.model)
        self.assertEqual(result, replay(self.domain, result.journal))

    def test_single_survivor_still_needs_actual_observation(self):
        d = Domain("singleton", {"only": lambda q: None}, [], checks=[()])
        self.assertEqual(identify(d, self.fail, Budget(0, 0)).status, "unverified")
        result = identify(d, lambda q: None, Budget(1, 0))
        self.assertEqual(result.status, "identified")
        self.assertEqual(result.steps[0].entry.record()["observation"], None)
        empty = Domain("empty", d.rules, [])
        self.assertEqual(identify(empty, self.fail, self.limit).reason, "no_observation")

    def test_equivalent_rules_stop_ambiguous_even_if_budget_remains(self):
        d = Domain("equivalent", {"a": lambda q: 1, "b": lambda q: 1}, [("inspect",)])
        result = identify(d, self.fail, self.limit)
        self.assertEqual((result.status, result.reason, result.candidates),
                         ("ambiguous", "probe_set_exhausted", ("a", "b")))
        self.assertIsNone(result.next_probe)

    def test_cost_limit_uses_affordable_split(self):
        rules = {str(i): (lambda q, i=i: i if q[0] == "full" else int(i == 0)) for i in range(5)}
        d = Domain("cost", rules, [("full",), ("partial",)], cost=lambda q: 3 if q[0] == "full" else 1)
        result = identify(d, rules["1"], Budget(2, 1))
        self.assertEqual(result.steps[0].entry.actions, ("partial",))
        self.assertEqual(result.next_probe.actions, ("full",))
        self.assertEqual((result.status, result.spent), ("ambiguous", Budget(1, 1)))

    def test_transport_error_is_charged_and_replays_without_retry(self):
        def broken(q):
            raise OSError("fixture offline")

        result = identify(self.domain, broken, self.limit)
        self.assertEqual((result.status, result.reason), ("error", "observation_failed"))
        self.assertEqual(result.spent, Budget(1, 1))
        self.assertEqual(result.candidates, ("off", "on"))
        self.assertIn("fixture offline", result.steps[-1].entry.error)
        self.assertEqual(result, identify(self.domain, self.fail, self.limit, journal=result.journal))

    def test_canonical_json_treats_true_and_one_as_different_observations(self):
        d = Domain("typed", {"bool": lambda q: True, "int": lambda q: 1}, [()])
        self.assertEqual(identify(d, lambda q: 1, self.limit).candidates, ("int",))
        self.assertEqual(identify(d, lambda q: float("nan"), self.limit).status, "error")

    def test_journal_rejects_wrong_version_cost_order_duplicate_and_budget(self):
        result = identify(self.domain, lambda q: True, self.limit)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            result.journal.save(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            start, check = data["entries"]
            for changes in ({"domain": "other"}, {"entries": [dict(start, cost=2)]},
                            {"entries": [check, start]}, {"entries": [start, start]},
                            {"budget": {"queries": 0, "cost": 0}},
                            {"entries": [dict(start, error="a")]}, {"entries": [dict(start, actions=["other"])]}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    path.write_text(json.dumps(dict(data, **changes)), encoding="utf-8")
                    replay(self.domain, Journal.load(path))

    def test_domain_requires_disjoint_checks_and_valid_prices(self):
        with self.assertRaises(ValueError):
            Domain("overlap", self.domain.rules, [()], checks=[()])
        with self.assertRaises(ValueError):
            Domain("bad-cost", self.domain.rules, [()], cost=lambda q: -1)
        self.assertEqual(list(traces(["a", "b"], 2))[-1], ("b", "b"))

    def test_interruption_reserves_inflight_query_and_checks_source_on_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            def observe(actions):
                if actions == ("check",):
                    raise KeyboardInterrupt
                return True
            with self.assertRaises(KeyboardInterrupt):
                identify(self.domain, observe, self.limit, checkpoint=path, source_id="sandbox-A")
            journal = Journal.load(path)
            self.assertEqual((len(journal.entries), journal.entries[0].answer_json), (2, "true"))
            with self.assertRaisesRegex(ValueError, "source mismatch"):
                identify(self.domain, self.fail, self.limit, journal=journal, source_id="sandbox-B")
            result = identify(self.domain, self.fail, self.limit, journal=journal, source_id="sandbox-A")
            self.assertEqual((result.status, result.reason, result.spent), ("error", "outcome_unknown", self.limit))

    def test_real_sqlite_matches_five_distinct_row_sets(self):
        observed = {k: sqlite_policy.adapter(k)(("seed", "batch")) for k in sqlite_policy.POLICIES}
        self.assertEqual(observed["ROLLBACK"], [])
        self.assertEqual(observed["ABORT"], [[1, "old"]])
        self.assertEqual(observed["FAIL"], [[1, "old"], [2, "prefix"]])
        self.assertEqual(observed["IGNORE"], [[1, "old"], [2, "prefix"], [3, "suffix"]])
        self.assertEqual(observed["REPLACE"], [[1, "new"], [2, "prefix"], [3, "suffix"]])

    def test_real_sqlite_finds_missing_candidate_on_the_first_probe(self):
        full = sqlite_policy.domain()
        rules = {k: v for k, v in full.rules.items() if k != "FAIL"}
        domain = Domain("sqlite/without-fail-v1", rules, full.probes, checks=full.checks)
        result = identify(domain, sqlite_policy.adapter("FAIL"), Budget(3, 8))
        self.assertEqual((result.status, result.spent, result.model), ("conflict", Budget(1, 2), None))
        self.assertEqual(result.steps[-1].entry.record()["observation"], [[1, "old"], [2, "prefix"]])
        self.assertEqual(set(result.conflict_predictions), set(rules))

    def test_demo_domains_identify_all_policies_and_run_separate_validation(self):
        for module in (publish, sqlite_policy):
            domain = module.domain()
            for name in module.POLICIES:
                with self.subTest(domain=domain.id, name=name):
                    result = identify(domain, module.adapter(name), Budget(10, 25))
                    self.assertEqual((result.status, result.candidates), ("identified", (name,)))
                    self.assertEqual([s.phase for s in result.steps], ["probe", "check", "check"])
                    self.assertEqual(result.model(()), module.adapter(name)(()))


if __name__ == "__main__":
    unittest.main()
