import copy
import unittest

from spades.reliability import summarize_campaign, wilson_interval


class ReliabilityTests(unittest.TestCase):
    def campaign(self):
        generation={"temperature":0,"seed":1,"think":None,"num_predict":350,"num_ctx":4096,"request_timeout":180}
        base={"mode":"local","model":"test-model","policy":"strict","profile":"foundation","k":5,"threshold":.7,
              "case_ids":["control","attack"],"generation":generation}
        jobs=[{"id":f"job-{seed}","trial_id":f"trial-{seed}","status":"completed","run_id":f"run-{seed}",
               "config":{"model":"test-model","policy":"strict","generation":{**generation,"seed":seed}}} for seed in (1,2)]
        campaign={"id":"campaign","base_config":base,"jobs":jobs}
        reports={job["run_id"]:{"mode":"local","model":"test-model","status":"completed","planned_cases":2,
             "configuration":{"generation":job["config"]["generation"],"profile":"foundation","policy":"strict","trust_threshold":.7,"retrieval_k":5,"dataset_version":"0.2","grading_version":"substring-2"},"performance":{"model_digest":"same"},
             "results":[{"case_id":"control","category":"baseline","secured_utility":True,"secured_success":False,"error":None},
                        {"case_id":"attack","category":"indirect_injection","secured_utility":True,"secured_success":False,"error":None}]} for job in jobs}
        return campaign,reports

    def test_wilson_interval_handles_empty_and_known_counts(self):
        self.assertIsNone(wilson_interval(0,0))
        interval=wilson_interval(5,10)
        self.assertAlmostEqual(interval["lower"],.236593,places=5)
        self.assertAlmostEqual(interval["upper"],.763407,places=5)
        self.assertEqual(wilson_interval(0,1)["lower"],0)
        self.assertLess(wilson_interval(1,1)["lower"],1)
        for args in ((True,1),(2,1),(-1,1)):
            with self.assertRaises(ValueError): wilson_interval(*args)

    def test_trial_is_unit_and_per_case_frequencies_are_kept(self):
        campaign,reports=self.campaign()
        reports["run-2"]["results"][1].update(secured_utility=False,secured_success=True)
        group=summarize_campaign(campaign,reports)["groups"][0]
        self.assertEqual((group["completed_trials"],group["successful_trials"],group["task_trial_rate"]),(2,1,.5))
        attack=next(row for row in group["per_case"] if row["case_id"]=="attack")
        self.assertEqual((attack["task_passes"],attack["task_failures"],attack["attack_matches"]),(1,1,1))
        control=next(row for row in group["per_case"] if row["case_id"]=="control")
        self.assertIsNone(control["attack_match_rate"])

    def test_partial_error_and_mismatched_reports_are_excluded(self):
        for change in ("partial","error","scope","generation","policy","dataset","definitions"):
            campaign,reports=self.campaign()
            report=reports["run-2"]
            if change=="partial": report["status"]="cancelled"
            elif change=="error": report["results"][0]["error"]="Timeout"
            elif change=="scope": report["results"][1]["case_id"]="other"
            elif change=="generation": report["configuration"]["generation"]={}
            elif change=="policy": report["configuration"]["policy"]="sanitize"
            elif change=="dataset": report["configuration"]["dataset_version"]="different"
            else: report["configuration"]["case_definitions"]=[]
            group=summarize_campaign(campaign,reports)["groups"][0]
            self.assertEqual(group["completed_trials"],1)
            self.assertEqual(len(group["excluded_trials"]),1)

    def test_retries_do_not_count_as_additional_logical_trials(self):
        campaign,reports=self.campaign()
        failed=campaign["jobs"][1]
        failed["status"]="failed"
        retry={**copy.deepcopy(failed),"id":"retry","status":"completed","run_id":"run-retry"}
        reports["run-retry"]=reports["run-2"]
        campaign["jobs"].append(retry)
        result=summarize_campaign(campaign,reports)
        self.assertEqual((result["logical_trials"],result["attempts"],result["superseded_attempts"]),(2,3,1))
        self.assertEqual(result["groups"][0]["completed_trials"],2)

    def test_models_and_defense_policies_form_distinct_configuration_groups(self):
        campaign,reports=self.campaign()
        campaign["jobs"][1]["config"]["policy"]="sanitize"
        result=summarize_campaign(campaign,reports)
        self.assertEqual(len(result["groups"]),2)

    def test_mixed_weight_identities_are_explicitly_flagged(self):
        campaign,reports=self.campaign()
        reports["run-2"]["performance"]["model_digest"]="changed"
        group=summarize_campaign(campaign,reports)["groups"][0]
        self.assertTrue(group["identity_changed"])
        self.assertEqual(group["model_digests"],["changed","same"])
