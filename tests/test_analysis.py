import copy
import unittest

from spades.analysis import analyze_report, diagnose_case


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.row = {"case_id": "enterprise-procurement-1-baseline", "category": "baseline", "domain": "procurement",
                    "error": None, "secured_success": False, "secured_utility": True,
                    "required_sources": ["price"], "retrieved_chunks": [{"chunk_id": "price:0", "source_id": "price"}],
                    "decisions": [{"chunk_id": "price:0", "allowed": True, "reason": "Verified"}],
                    "secured_context_ids": ["price:0"],
                    "secured_grade": {"format_valid": True, "citations": ["price"], "missing_citations": [],
                                      "invalid_citations": [], "leakage": False,
                                      "checks": [{"field": "cost", "passed": True, "actual": 20, "expected": 20}]}}

    def test_complete_evidence_has_a_verified_delivery_trace(self):
        case = diagnose_case(self.row)
        self.assertEqual(case["issues"], [])
        trace = case["source_trace"][0]
        self.assertTrue(all(trace[key] for key in ("retrieved", "allowed", "supplied", "cited")))
        self.assertEqual(case["status"], "no recorded issues")

    def test_retrieval_defense_and_context_omissions_are_distinct(self):
        for expected in ("retrieval", "defense", "budget"):
            row = copy.deepcopy(self.row)
            if expected == "retrieval":
                row["retrieved_chunks"] = []
            elif expected == "defense":
                row["decisions"][0].update(allowed=False, reason="Trust below threshold")
            row["secured_context_ids"] = []
            self.assertEqual(diagnose_case(row)["issues"], [expected])

    def test_legacy_missing_context_trace_does_not_invent_budget_exclusion(self):
        self.row.pop("secured_context_ids")
        case = diagnose_case(self.row)
        self.assertIsNone(case["source_trace"][0]["supplied"])
        self.assertNotIn("budget", case["issues"])

    def test_overlapping_observations_retain_failed_field_detail(self):
        self.row.update(category="data_corruption", secured_success=True, secured_leak=True, secured_utility=False)
        self.row["secured_grade"].update(format_valid=False, missing_citations=["price"], invalid_citations=["invented"])
        self.row["secured_grade"]["checks"][0].update(passed=False, actual=999)
        result = diagnose_case(self.row)
        self.assertEqual(result["issues"], ["leakage", "attack", "format", "fields", "citations"])
        self.assertEqual(result["failed_fields"][0]["actual"], 999)
        self.assertTrue(all(item["next_step"] for item in result["observations"]))

    def test_runtime_error_has_no_invented_model_assessment(self):
        self.row.update(error="Connection refused", secured_success=True, secured_leak=True)
        self.row["secured_grade"]["checks"][0]["passed"] = False
        result = diagnose_case(self.row)
        self.assertEqual(result["issues"], ["runtime"])
        self.assertEqual(result["failed_fields"], [])
        self.assertEqual(result["source_trace"], [])

    def test_foundation_controls_are_not_counted_as_attacks(self):
        row = {"case_id": "hr-baseline", "category": "baseline", "error": None,
               "secured_success": True, "secured_utility": False}
        self.assertEqual(diagnose_case(row)["issues"], ["utility"])
        report = analyze_report({"run_id": "a" * 32, "results": [row]})
        self.assertIsNone(report["domains"][0]["attack_rate"])
        self.assertIsNone(report["domains"][0]["field_accuracy"])
        self.assertEqual(report["domains"][0]["name"], "hr")

    def test_scorecards_exclude_errors_and_weight_fields_by_assertion_count(self):
        attack = copy.deepcopy(self.row)
        attack.update(case_id="enterprise-procurement-1-attack", category="data_corruption", secured_success=True, secured_utility=False)
        attack["secured_grade"]["checks"] = [{"field": "cost", "passed": False}, {"field": "vat", "passed": False}]
        error = {**self.row, "case_id": "enterprise-procurement-error", "error": "Timeout"}
        analysis = analyze_report({"run_id": "a" * 32, "planned_cases": 6, "results": [self.row, attack, error]})
        group = analysis["domains"][0]
        self.assertEqual((group["attempted"], group["measured"], group["runtime_errors"]), (3, 2, 1))
        self.assertEqual((group["task_passed"], group["task_rate"]), (1, 0.5))
        self.assertEqual((group["attack_cases"], group["attack_rate"]), (1, 1))
        self.assertEqual((group["fields_passed"], group["fields_total"]), (1, 3))
        self.assertAlmostEqual(group["field_accuracy"], 1/3)
        self.assertEqual((analysis["attempted"], analysis["planned"]), (3, 6))

    def test_error_only_and_empty_reports_have_no_fake_rates(self):
        self.row["error"] = "Timeout"
        group = analyze_report({"run_id": "a" * 32, "results": [self.row]})["domains"][0]
        self.assertIsNone(group["task_rate"])
        self.assertIsNone(group["attack_rate"])
        self.assertIsNone(group["field_accuracy"])
        empty = analyze_report({"run_id": "a" * 32, "results": [], "planned_cases": 6})
        self.assertEqual(empty["issues"], [])
        self.assertEqual(empty["domains"], [])

    def test_analysis_does_not_mutate_original_evidence(self):
        report = {"run_id": "a" * 32, "results": [self.row]}
        original = copy.deepcopy(report)
        analyze_report(report)
        self.assertEqual(report, original)

    def test_response_exhaustion_and_empty_answers_are_independent_observations(self):
        self.row.update(secured_response="",secured_generation={"done_reason":"length"})
        self.assertEqual(diagnose_case(self.row)["issues"],["generation_limit","empty_answer"])
        self.row["secured_generation"] = {}
        self.assertEqual(diagnose_case(self.row)["issues"],["empty_answer"])
