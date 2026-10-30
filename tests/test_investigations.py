import copy
from pathlib import Path
import tempfile
import unittest

from spades.evaluation import run_suite
from spades.investigations import search_evidence, validate_filters
from spades.server import RunManager


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.report=run_suite(case_ids=["hr-baseline-concise","hr-indirect_injection-1"])
        self.report["created_at"]="2026-10-29T01:00:00+02:00"

    def search(self,filters=None,**page):
        return search_evidence([self.report],{"filters":filters or {},**page})

    def test_run_observations_remain_separate_and_pages_have_full_match_counts(self):
        newer=copy.deepcopy(self.report);newer.update(run_id="a"*32,created_at="2026-10-30T12:00:00Z",mode="local",model="other")
        result=search_evidence([self.report,newer],{"filters":{},"limit":1})
        self.assertEqual((result["total"],result["matching_runs"],result["next_offset"]),(4,2,1))
        self.assertEqual(result["results"][0]["run_id"],newer["run_id"])
        self.assertEqual(self.search({"mode":"local"})["total"],0)

    def test_literal_queries_match_responses_fields_and_retrieved_text(self):
        row=self.report["results"][0]
        row["secured_response"]="Unique-response-marker"
        self.assertEqual(self.search({"query":"UNIQUE-response"})["total"],1)
        row["secured_grade"]={"checks":[{"field":"net_total","expected":12,"actual":10,"passed":False}],"format_valid":True}
        self.assertEqual(self.search({"query":"net_total","issue":"fields"})["total"],1)
        row["retrieved_chunks"][0]["text"]="Unique-source-marker"
        self.assertEqual(self.search({"query":"Unique-source-marker"})["total"],1)
        self.assertEqual(self.search({"query":".*"})["total"],0)

    def test_dates_use_utc_day_and_other_filters_are_exact(self):
        self.assertEqual(self.search({"from_date":"2026-10-29"})["total"],0)
        self.assertEqual(self.search({"to_date":"2026-10-28"})["total"],2)
        self.assertEqual(self.search({"domain":"hr","category":"baseline","policy":"strict","profile":"foundation"})["total"],1)
        self.assertEqual(self.search({"model":"different"})["total"],0)

    def test_errors_and_clear_cases_are_not_conflated(self):
        self.report["results"][0]["error"]="timeout"
        result=self.search({"issue":"runtime"})
        self.assertEqual(result["total"],1)
        self.assertEqual(result["issue_counts"]["runtime"],1)
        self.assertEqual(self.search({"issue":"clear"})["total"],1)

    def test_search_does_not_mutate_reports_and_skips_invalid_records(self):
        old=copy.deepcopy(self.report)
        self.search();self.assertEqual(old,self.report)
        invalid=copy.deepcopy(self.report);invalid["results"]=None
        result=search_evidence([invalid,{"created_at":"invalid"},self.report],{"filters":{}})
        self.assertEqual(result["total"],2)
        self.assertEqual(result["skipped_invalid_records"],2)

    def test_invalid_filters_and_pages_are_rejected(self):
        for filters in ({"unknown":"x"},{"issue":"bogus"},{"query":"x"*201},{"query":None},{"mode":True},{"from_date":"20261028"},{"from_date":"2026-11-01","to_date":"2026-10-01"}):
            with self.assertRaises(ValueError):validate_filters(filters)
        for page in ({"offset":True},{"limit":0},{"offset":-1},{"limit":101}):
            with self.assertRaises(ValueError):self.search(**page)


class SavedInvestigationTests(unittest.TestCase):
    def test_views_persist_filters_only_and_reject_stale_or_duplicate_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=RunManager(Path(folder))
            first=manager.save_investigation({"name":"Field review","filters":{"issue":"fields"}})["investigations"][0]
            self.assertNotIn("results",first)
            self.assertEqual(RunManager(Path(folder)).workspace()["investigations"][0],first)
            second=manager.save_investigation({"name":"Field review","filters":{"issue":"citations"},"id":first["id"],"revision":1})["investigations"][0]
            self.assertEqual(second["revision"],2)
            with self.assertRaises(RuntimeError):manager.save_investigation({"name":"Old edit","filters":{},"id":first["id"],"revision":1})
            with self.assertRaises(ValueError):manager.save_investigation({"name":"field review","filters":{}})
            self.assertIsNone(manager.snapshot())

    def test_bad_view_changes_never_write_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=RunManager(Path(folder))
            for body in ({"name":" ","filters":{}},{"name":"x","filters":{"issue":"bogus"}},{"name":"x","filters":{},"id":"../outside","revision":1}):
                with self.assertRaises(ValueError):manager.save_investigation(body)
            self.assertFalse((Path(folder)/"workspace.json").exists())
