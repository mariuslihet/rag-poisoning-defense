import copy
import unittest

from spades.findings import create_finding, update_finding


def report(run_id, *, mode="local", good=False, created="2026-10-30T12:00:00+00:00"):
    return {"run_id":run_id,"mode":mode,"model":"test-model","created_at":created,"status":"completed",
            "configuration":{"profile":"complex","dataset_version":"custom-fixed-fixture","grading_version":"typed-rubric-2"},
            "results":[{"case_id":"custom-budget","error":None,"secured_utility":good,"secured_success":False,"secured_leak":False,
                        "secured_response":"Recorded analytical answer","secured_grade":{"leakage":False}}]}


class FindingTests(unittest.TestCase):
    def setUp(self):
        self.original_id="a"*32;self.verification_id="b"*32
        self.reports={self.original_id:report(self.original_id),self.verification_id:report(self.verification_id,good=True,created="2026-10-31T12:00:00+00:00")}
        self.workspace={"bookmarks":[]}
        self.body={"title":"Incorrect annual cost","run_id":self.original_id,"case_id":"custom-budget","severity":"high","note":"Expected arithmetic differs from the secured answer.","tags":["procurement"]}

    def create(self):return create_finding(self.workspace,self.body,self.reports)
    def update(self,record,**change):return update_finding(self.workspace,{"id":record["id"],"revision":record["revision"],"status":record["status"],**change},self.reports)

    def test_creation_captures_exact_source_and_does_not_mutate_reports(self):
        before=copy.deepcopy(self.reports);record=self.create()
        self.assertEqual(record["source"]["run_id"],self.original_id)
        self.assertEqual(len(record["source"]["row_sha256"]),64)
        self.assertEqual(record["status"],"open")
        self.assertEqual(len(record["history"]),1)
        self.assertEqual(self.reports,before)
        record["history"][0]["note"]="Client mutation"
        self.assertNotEqual(record,self.workspace["findings"][0])

    def test_revisions_preserve_events_and_stale_writes_are_rejected(self):
        first=self.create();original=copy.deepcopy(first)
        second=self.update(first,status="investigating",assignee="Retrieval team",note="Review the admitted source records.")
        self.assertEqual(second["revision"],2)
        self.assertEqual(second["source"],first["source"])
        self.assertEqual(second["history"][0],original["history"][0])
        self.assertEqual(first,original)
        with self.assertRaises(RuntimeError):self.update(first,note="Stale write")
        self.assertEqual(self.workspace["findings"][0],second)

    def test_fix_requires_later_compatible_measured_verification(self):
        first=self.create()
        with self.assertRaises(ValueError):self.update(first,status="fixed")
        reference={"run_id":self.verification_id,"case_id":"custom-budget"}
        fixed=self.update(first,status="fixed",verification=reference,note="Verified a revised defense policy.")
        self.assertEqual(fixed["verification"]["run_id"],self.verification_id)
        self.assertEqual(fixed["history"][-1]["status"],"fixed")
        reopened=self.update(fixed,status="investigating",note="Additional adversarial coverage is needed.")
        self.assertEqual(reopened["verification"],fixed["verification"])
        self.assertEqual(reopened["history"][-2]["status"],"fixed")

    def test_verification_rejects_wrong_case_identity_modes_times_and_error_outcomes(self):
        for key,value in (("error","timeout"),("secured_utility",False),("secured_utility",None),("secured_success",True),("secured_success",None),("secured_leak",True)):
            with self.subTest(key=key,value=value):
                workspace={};first=create_finding(workspace,self.body,self.reports);bad=copy.deepcopy(self.reports);bad[self.verification_id]["results"][0][key]=value
                with self.assertRaises(ValueError):update_finding(workspace,{"id":first["id"],"revision":1,"status":"fixed","verification":{"run_id":self.verification_id,"case_id":"custom-budget"}},bad)
                self.assertEqual(workspace["findings"][0],first)
        changes=({"mode":"demo"},{"created_at":"2026-10-29T00:00:00+00:00"},{"status":"cancelled"})
        for change in changes:
            bad=copy.deepcopy(self.reports);bad[self.verification_id].update(change);first=self.create()
            with self.assertRaises(ValueError):update_finding(self.workspace,{"id":first["id"],"revision":1,"status":"fixed","verification":{"run_id":self.verification_id,"case_id":"custom-budget"}},bad)
        for key in ("profile","dataset_version","grading_version"):
            bad=copy.deepcopy(self.reports);bad[self.verification_id]["configuration"][key]="changed";first=self.create()
            with self.assertRaises(ValueError):update_finding(self.workspace,{"id":first["id"],"revision":1,"status":"fixed","verification":{"run_id":self.verification_id,"case_id":"custom-budget"}},bad)

    def test_changes_to_model_or_defense_are_allowed_but_identity_is_preserved(self):
        first=self.create();self.reports[self.verification_id]["model"]="revised-local-model"
        self.reports[self.verification_id]["configuration"]["policy"]="sanitize"
        fixed=self.update(first,status="fixed",verification={"run_id":self.verification_id,"case_id":"custom-budget"})
        self.assertEqual(fixed["source"]["identity"]["model"],"test-model")
        self.assertEqual(fixed["verification"]["identity"]["model"],"revised-local-model")
        self.assertEqual(fixed["verification"]["identity"]["policy"],"sanitize")

    def test_accepted_risk_requires_a_rationale_and_does_not_invent_verification(self):
        first=self.create()
        with self.assertRaises(ValueError):self.update(first,status="accepted",note=" ")
        accepted=self.update(first,status="accepted",note="Retain this bounded limitation for the current internal benchmark.")
        self.assertIsNone(accepted["verification"])
        self.assertEqual(accepted["history"][-1]["status"],"accepted")

    def test_source_or_verification_tampering_prevents_silent_fix_reuse(self):
        first=self.create();reference={"run_id":self.verification_id,"case_id":"custom-budget"}
        fixed=self.update(first,status="fixed",verification=reference)
        self.reports[self.verification_id]["results"][0]["secured_response"]="Different response"
        with self.assertRaises(ValueError):self.update(fixed,note="Do not reuse changed verification silently")
        self.reports[self.original_id]["results"][0]["secured_response"]="Altered original evidence"
        with self.assertRaises(ValueError):self.update(fixed,verification=reference)

    def test_invalid_bodies_and_metadata_leave_workspace_untouched(self):
        for change in ({"severity":"urgent"},{"tags":["one","ONE"]},{"assignee":None},{"run_id":"../outside"},{"source":{}},{"case_id":"missing"}):
            with self.assertRaises(ValueError):create_finding(self.workspace,{**self.body,**change},self.reports)
            self.assertNotIn("findings",self.workspace)
        first=self.create()
        for change in ({"revision":True},{"status":"closed"},{"source":{}},{"history":[]},{"verification":{"run_id":self.verification_id,"case_id":"custom-budget"}}):
            with self.assertRaises(ValueError):update_finding(self.workspace,{"id":first["id"],"revision":1,"status":"open",**change},self.reports)

    def test_tuple_report_mapping_and_duplicate_case_rejection(self):
        reports={key:(None,value) for key,value in self.reports.items()}
        record=create_finding(self.workspace,self.body,reports)
        self.assertEqual(record["source"]["case_id"],"custom-budget")
        bad=copy.deepcopy(self.reports);bad[self.original_id]["results"]*=2
        with self.assertRaises(ValueError):create_finding({},self.body,bad)

    def test_limits_fail_without_pruning_existing_history(self):
        first=self.create();self.workspace["findings"][0]["revision"]=100
        before=copy.deepcopy(self.workspace)
        with self.assertRaises(ValueError):update_finding(self.workspace,{"id":first["id"],"revision":100,"status":"investigating"},self.reports)
        self.assertEqual(self.workspace,before)
