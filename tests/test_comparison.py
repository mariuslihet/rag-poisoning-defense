import copy
import unittest

from spades.comparison import compare_cases, numeric_delta
from spades.evaluation import run_suite


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.reference = run_suite(case_ids=["hr-baseline-concise", "hr-indirect_injection-1", "api-indirect_injection-1"])
        self.candidate = copy.deepcopy(self.reference)
        self.candidate["run_id"] = "a" * 32

    def test_task_and_attack_transitions_are_independent(self):
        old, new = self.reference["results"], self.candidate["results"]
        old[0]["secured_utility"], new[0]["secured_utility"] = True, False
        old[1]["secured_utility"], new[1]["secured_utility"] = False, True
        old[1]["secured_success"], new[1]["secured_success"] = False, True
        old[2]["secured_success"], new[2]["secured_success"] = True, False
        result = compare_cases(self.reference, self.candidate)
        self.assertEqual(result["counts"], {"task_regressions": 1, "task_improvements": 1,
                         "new_attack_matches": 1, "resolved_attack_matches": 1, "unmeasured": 0})
        self.assertEqual(result["cases"][0]["attack"], "not applicable")

    def test_runtime_errors_never_count_as_regressions_or_improvements(self):
        self.reference["results"][1]["error"] = "Provider timeout"
        self.candidate["results"][1]["secured_success"] = True
        self.candidate["results"][0]["error"] = "Provider offline"
        result = compare_cases(self.reference, self.candidate)
        self.assertEqual(result["counts"]["unmeasured"], 2)
        self.assertEqual(result["counts"]["new_attack_matches"], 0)
        self.assertEqual(result["cases"][1]["task"], "unmeasured")

    def test_row_order_does_not_change_alignment(self):
        self.candidate["results"].reverse()
        result = compare_cases(self.reference, self.candidate)
        self.assertEqual([r["case_id"] for r in result["cases"]], [r["case_id"] for r in self.reference["results"]])
        self.assertEqual(result["counts"]["task_regressions"], 0)

    def test_incompatible_evidence_is_rejected(self):
        for key in ("profile", "dataset_version", "grading_version"):
            candidate = copy.deepcopy(self.candidate)
            candidate["configuration"][key] = "different"
            with self.assertRaises(ValueError):
                compare_cases(self.reference, candidate)
        for key in ("mode", "model"):
            candidate = copy.deepcopy(self.candidate)
            candidate[key] = "different"
            with self.assertRaises(ValueError):
                compare_cases(self.reference, candidate)
        self.candidate["results"].pop()
        with self.assertRaises(ValueError):
            compare_cases(self.reference, self.candidate)

    def test_recorded_duration_and_field_score_changes(self):
        old, new = self.reference["results"][0], self.candidate["results"][0]
        old["duration_seconds"], new["duration_seconds"] = 12.5, 10.25
        old["secured_grade"], new["secured_grade"] = {"field_score": 0.25}, {"field_score": 0.75}
        row = compare_cases(self.reference, self.candidate)["cases"][0]
        self.assertEqual(row["duration_delta_seconds"], -2.25)
        self.assertEqual(row["secured_field_score_delta"], 0.5)

    def test_missing_or_failed_assessments_have_no_invented_deltas(self):
        self.candidate["results"][0]["error"] = "Timeout"
        rows = compare_cases(self.reference, self.candidate)["cases"]
        self.assertIsNone(rows[0]["duration_delta_seconds"])
        self.assertIsNone(rows[0]["secured_field_score_delta"])
        self.assertIsNone(rows[1]["secured_field_score_delta"])

    def test_numeric_delta_rejects_missing_nonfinite_and_boolean_values(self):
        for value in (None, True, "0.5", float("nan"), float("inf")):
            self.assertIsNone(numeric_delta(value, 1))
            self.assertIsNone(numeric_delta(1, value))
        self.assertEqual(numeric_delta(0.1, 0.3), 0.2)

    def test_changed_model_weights_cannot_be_compared_as_the_same_model(self):
        for report,digest in ((self.reference,"weights-old"),(self.candidate,"weights-new")):
            report["mode"] = "local"
            report["performance"]["model_digest"] = digest
        with self.assertRaisesRegex(ValueError,"weight digests"):
            compare_cases(self.reference,self.candidate)
        self.candidate["performance"]["model_digest"] = "weights-old"
        self.assertEqual(len(compare_cases(self.reference,self.candidate)["cases"]),3)
