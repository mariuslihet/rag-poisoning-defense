import json
from pathlib import Path
import tempfile
import unittest

from spades.evaluation import select_cases
from spades.server import RunManager
from spades.suites import export_suite, plan_cases, validate_suite


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.manager = RunManager(Path(self.folder.name))
        self.body = {"name": "  Procurement controls  ", "description": "Two independent procurement variants.",
                     "profile": "complex", "case_ids": ["enterprise-procurement-1-baseline", "enterprise-procurement-2-baseline"]}

    def tearDown(self):
        self.folder.cleanup()

    def test_suites_persist_exact_order_and_portable_manifest_roundtrip(self):
        suite = self.manager.save_suite(self.body)["suites"][0]
        self.assertEqual(suite["name"], "Procurement controls")
        self.assertEqual(suite["revision"], 1)
        self.assertEqual(suite["case_ids"], self.body["case_ids"])
        self.assertEqual(RunManager(self.manager.output).workspace()["suites"][0], suite)
        manifest = export_suite(suite)
        self.assertNotIn("id", manifest)
        self.assertNotIn("plan", manifest)
        self.assertEqual(validate_suite(json.loads(json.dumps(manifest)), manifest=True)["case_ids"], self.body["case_ids"])

    def test_edits_increment_revision_and_stale_edits_cannot_overwrite(self):
        suite = self.manager.save_suite(self.body)["suites"][0]
        update = {**self.body, "id": suite["id"], "revision": 1, "case_ids": self.body["case_ids"][:1]}
        revised = self.manager.save_suite(update)["suites"][0]
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["created_at"], suite["created_at"])
        self.assertEqual(len(revised["case_ids"]), 1)
        with self.assertRaises(RuntimeError):
            self.manager.save_suite(update)
        self.assertEqual(self.manager.workspace()["suites"][0], revised)

    def test_incompatible_imports_and_unknown_fields_do_not_mutate_workspace(self):
        suite = self.manager.save_suite(self.body)["suites"][0]
        original = (self.manager.output / "workspace.json").read_bytes()
        manifest = export_suite(suite)
        for change in ({"version": True}, {"version": 2}, {"dataset_version": "old"}, {"grading_version": "old"}, {"format": "other"}, {"script": "execute nothing"}):
            with self.assertRaises(ValueError):
                self.manager.save_suite({**manifest, **change}, manifest=True)
            self.assertEqual((self.manager.output / "workspace.json").read_bytes(), original)

    def test_ids_and_metadata_are_strictly_validated(self):
        for change in ({"case_ids": []}, {"case_ids": [self.body["case_ids"][0]] * 2}, {"case_ids": ["unknown"]},
                       {"case_ids": ["hr-baseline-concise"]}, {"name": " "}, {"description": "x" * 1001},
                       {"profile": []}, {"id": None, "revision": 1}, {"id": "../outside", "revision": 1},
                       {"id": "a" * 32}, {"id": "a" * 32, "revision": True}):
            with self.assertRaises(ValueError):
                self.manager.save_suite({**self.body, **change})

    def test_duplicate_names_are_rejected_but_import_can_be_renamed(self):
        suite = self.manager.save_suite(self.body)["suites"][0]
        with self.assertRaises(ValueError):
            self.manager.save_suite({**self.body, "name": "procurement controls"})
        imported = self.manager.save_suite({**export_suite(suite), "name": "Imported controls"}, manifest=True)
        self.assertEqual(len(imported["suites"]), 2)
        self.assertIsNone(self.manager.snapshot())

    def test_run_plan_counts_enterprise_assertions_and_source_records(self):
        plan = plan_cases(select_cases(profile="complex", case_ids=self.body["case_ids"]))
        self.assertEqual((plan["scenarios"], plan["model_responses"]), (2, 4))
        self.assertEqual((plan["typed_assertions_per_arm"], plan["paired_typed_assertions"]), (8, 16))
        self.assertEqual(plan["source_records"], 42)
        self.assertEqual(plan["domains"], {"procurement": 2})
        self.assertEqual(plan["families"], {"baseline": 2})
        self.assertEqual(plan["foundation_fact_checks"], 0)
        self.assertGreater(plan["fixture_characters"], 80000)

    def test_foundation_plan_and_empty_plan_never_claim_typed_assessments(self):
        plan = plan_cases(select_cases(case_ids=["hr-baseline-concise"]))
        self.assertEqual(plan["foundation_fact_checks"], 2)
        self.assertEqual(plan["paired_typed_assertions"], 0)
        empty = plan_cases([])
        self.assertEqual(empty["model_responses"], 0)
        self.assertEqual(empty["domains"], {})

    def test_complete_enterprise_manifest_remains_portable(self):
        body = {**self.body, "case_ids": [case.case_id for case in select_cases(profile="complex")]}
        validated = validate_suite(body)
        manifest = export_suite(validated)
        self.assertEqual(len(validate_suite(manifest, manifest=True)["case_ids"]), 96)
        self.assertLess(len(json.dumps(manifest).encode("utf-8")), 8192)
