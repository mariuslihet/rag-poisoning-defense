import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
import uuid

from spades.campaigns import CampaignManager
from spades.settings import validate_generation


class FakeRunner:
    def __init__(self,output,delay=.02):
        self.output=Path(output); self.active=None; self.saved={}; self.calls=[]; self.delay=delay; self.stop_calls=[]
        self.lock=threading.RLock(); self.fail_models=set()
        self.start_gate=None
    def resolve_selection(self,config):
        result={"mode":"demo","profile":"foundation","model":"test-model","policy":"strict","generation":validate_generation(),
                "limit":2,"threshold":.7,"k":5,"concurrency":1,"selection_scope":"sample",**copy.deepcopy(config)}
        ids=result.get("case_ids") or ["control","attack"][:result["limit"]]
        return result,[SimpleNamespace(case_id=case_id) for case_id in ids],[]
    def snapshot(self):
        with self.lock: return copy.deepcopy(self.active)
    def start(self,config):
        if self.start_gate is not None: self.start_gate.wait(timeout=2)
        with self.lock:
            if self.active and self.active["status"] in ("running","stopping"): raise RuntimeError("busy")
            if config["model"] in self.fail_models: raise ValueError("model unavailable")
            run_id=uuid.uuid4().hex; self.calls.append(copy.deepcopy(config)); self.active={"run_id":run_id,"status":"running","error":None}
        def finish():
            time.sleep(self.delay)
            with self.lock:
                cancelled=self.active["status"]=="stopping"
                ids=config["case_ids"][:1] if cancelled else config["case_ids"]
                report={"status":"cancelled" if cancelled else "completed","mode":config["mode"],"model":config["model"],"planned_cases":len(config["case_ids"]),
                        "configuration":{"generation":config["generation"],"profile":config["profile"],"policy":config["policy"],"trust_threshold":config.get("threshold",.7),"retrieval_k":config.get("k",5),"dataset_version":"0.2","grading_version":"substring-2","retrieval_settings":config.get("retrieval")},"metrics":{"error_cases":0},
                        "results":[{"case_id":case_id,"category":"baseline" if case_id=="control" else "indirect_injection","secured_utility":True,"secured_success":False,"error":None} for case_id in ids]}
                self.saved[run_id]=(self.output/"report.json",report); self.active["status"]=report["status"]
        threading.Thread(target=finish,daemon=True).start()
        return copy.deepcopy(self.active)
    def stop(self):
        with self.lock:
            self.stop_calls.append(self.active["run_id"]); self.active["status"]="stopping"; return copy.deepcopy(self.active)
    def reports(self):
        with self.lock: return copy.deepcopy(self.saved)


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.runner=FakeRunner(self.folder.name)
        self.campaigns=CampaignManager(self.runner,poll_interval=.005)
        self.body={"name":"Repeated check","base_config":{"limit":2},"models":["test-model"],"policies":["strict","sanitize"],"seeds":[1,2]}
    def tearDown(self):
        self.campaigns.close(); time.sleep(self.runner.delay+.01); self.folder.cleanup()
    def wait(self,campaign_id,predicate=None):
        predicate=predicate or (lambda item:item["status"] not in ("queued","running","stopping"))
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            value=self.campaigns.get(campaign_id)
            if predicate(value): return value
            time.sleep(.005)
        self.fail("campaign did not reach expected state")

    def test_matrix_freezes_scope_runs_serially_and_produces_reliability(self):
        created=self.campaigns.create(self.body); result=self.wait(created["id"])
        self.assertEqual(result["status"],"completed")
        self.assertEqual(len(result["jobs"]),4)
        self.assertEqual(len(self.runner.calls),4)
        self.assertTrue(all(config["selection_scope"]=="selected" and config["case_ids"]==["control","attack"] for config in self.runner.calls))
        self.assertEqual(len(result["reliability"]["groups"]),2)
        self.assertTrue(all(group["completed_trials"]==2 for group in result["reliability"]["groups"]))

    def test_custom_definitions_are_captured_once_in_the_frozen_base(self):
        body={**self.body,"base_config":{"case_definitions":[{"case_id":"custom-case","query":"task"}],"case_ids":["custom-case"]},"seeds":[1],"policies":["strict"]}
        result=self.wait(self.campaigns.create(body)["id"])
        self.assertEqual(result["base_config"]["case_definitions"],body["base_config"]["case_definitions"])
        self.assertNotIn("case_definitions",result["jobs"][0]["config"])
        self.assertEqual(self.runner.calls[0]["case_definitions"],body["base_config"]["case_definitions"])

    def test_readiness_failure_is_local_to_job_and_queue_continues(self):
        self.runner.fail_models.add("missing")
        body={**self.body,"models":["missing","test-model"],"policies":["strict"],"seeds":[1]}
        result=self.wait(self.campaigns.create(body)["id"])
        self.assertEqual([job["status"] for job in result["jobs"]],["failed","completed"])
        self.assertEqual(result["status"],"completed_with_errors")

    def test_queued_cancellation_and_active_stop_are_individual(self):
        self.runner.delay=.15
        result=self.campaigns.create(self.body); active=self.wait(result["id"],lambda item:item["jobs"][0]["status"]=="running")
        self.campaigns.cancel_job(result["id"],active["jobs"][-1]["id"])
        self.campaigns.cancel_job(result["id"],active["jobs"][0]["id"])
        finished=self.wait(result["id"])
        self.assertEqual(finished["jobs"][0]["status"],"cancelled")
        self.assertEqual(finished["jobs"][-1]["status"],"cancelled")
        self.assertEqual(len(self.runner.calls),3)
        self.assertEqual(len(self.runner.stop_calls),1)

    def test_manual_run_is_not_stopped_when_campaign_waiting_is_cancelled(self):
        self.runner.active={"run_id":"manual","status":"running","error":None}
        result=self.campaigns.create(self.body)
        self.campaigns.cancel_campaign(result["id"])
        self.assertEqual(self.campaigns.get(result["id"])["status"],"cancelled")
        self.assertEqual(self.runner.stop_calls,[])
        self.assertEqual(self.runner.calls,[])

    def test_restart_does_not_execute_queued_or_interrupted_trials(self):
        self.campaigns.close()
        campaign_id=uuid.uuid4().hex; job_id=uuid.uuid4().hex
        record={"id":campaign_id,"name":"Interrupted","status":"running","created_at":"2026-10-30T00:00:00+00:00","updated_at":"x",
                "base_config":{"mode":"demo","profile":"foundation","case_ids":["control"],"generation":validate_generation()},
                "scenario_count":1,"original_job_count":2,"cancel_requested":False,
                "jobs":[{"id":job_id,"trial_id":job_id,"attempt":1,"config":{"model":"test-model","policy":"strict","generation":validate_generation()},
                         "status":"running","run_id":"saved-run","cancel_requested":False},
                        {"id":"q"*32,"trial_id":"q"*32,"attempt":1,"config":{"model":"test-model","policy":"strict","generation":validate_generation()},
                         "status":"queued","run_id":None,"cancel_requested":False}]}
        path=Path(self.folder.name)/"campaigns"/(campaign_id+".json"); path.write_text(json.dumps(record))
        self.campaigns=CampaignManager(self.runner,poll_interval=.005)
        recovered=self.campaigns.get(campaign_id)
        self.assertEqual(recovered["status"],"interrupted")
        self.assertEqual(recovered["jobs"][0]["status"],"interrupted")
        self.assertEqual(recovered["jobs"][0]["run_id"],"saved-run")
        time.sleep(.02); self.assertEqual(self.runner.calls,[])
        self.campaigns.resume(campaign_id)
        finished=self.wait(campaign_id)
        self.assertEqual(len(self.runner.calls),1)
        self.assertEqual(finished["jobs"][0]["status"],"interrupted")

    def test_explicit_retry_appends_attempt_without_double_counting(self):
        self.runner.fail_models.add("test-model")
        body={**self.body,"policies":["strict"],"seeds":[1]}
        failed=self.wait(self.campaigns.create(body)["id"])
        self.runner.fail_models.clear()
        retried=self.campaigns.retry_job(failed["id"],failed["jobs"][0]["id"])
        finished=self.wait(retried["id"])
        self.assertEqual(len(finished["jobs"]),2)
        self.assertEqual(finished["jobs"][1]["retry_of"],failed["jobs"][0]["id"])
        self.assertEqual(finished["reliability"]["logical_trials"],1)
        self.assertEqual(finished["reliability"]["superseded_attempts"],1)
        with self.assertRaises(ValueError): self.campaigns.retry_job(failed["id"],failed["jobs"][0]["id"])

    def test_invalid_matrices_are_rejected_before_scheduling(self):
        for change in ({"seeds":[True]},{"seeds":[1,1]},{"models":["x","x"]},{"policies":["unknown"]},{"name":" "},
                       {"models":[f"model-{n}" for n in range(10)],"seeds":list(range(20))}):
            with self.assertRaises(ValueError): self.campaigns.create({**self.body,**change})
        self.assertEqual(self.runner.calls,[])

    def test_sweep_axes_propagate_to_execution_and_reliability_groups(self):
        body={**self.body,"policies":["strict"],"seeds":[1,2],"thresholds":[.5,.9],"retrieval_depths":[5,10],"temperatures":[0,.5]}
        result=self.wait(self.campaigns.create(body)["id"])
        self.assertEqual(len(self.runner.calls),16)
        actual={(c["threshold"],c["k"],c["generation"]["temperature"],c["generation"]["seed"]) for c in self.runner.calls}
        self.assertEqual(len(actual),16)
        self.assertEqual(len(result["reliability"]["groups"]),8)
        self.assertTrue(all(group["completed_trials"]==2 for group in result["reliability"]["groups"]))
        self.assertEqual(result["axes"]["thresholds"],[.5,.9])

    def test_invalid_sweep_values_reject_without_saved_campaigns(self):
        for values in ([],[True],[float("nan")],[float("inf")],[0,.0],[-.1],[1.1],[10**400],".5"):
            with self.assertRaises(ValueError):self.campaigns.create({**self.body,"thresholds":values})
        for change in ({"retrieval_depths":[1.5]},{"retrieval_depths":[51]},{"temperatures":[2.1]},{"temperatures":None}):
            with self.assertRaises(ValueError):self.campaigns.create({**self.body,**change})
        self.assertEqual(self.campaigns.list(),[])
        self.assertFalse(list(self.campaigns.output.glob("*.json")))

    def test_cartesian_limit_counts_all_axes_before_starting(self):
        with self.assertRaisesRegex(ValueError,"160 trial jobs"):
            self.campaigns.create({**self.body,"seeds":list(range(10)),"thresholds":[.5,.9],"retrieval_depths":[5,10],"temperatures":[0,.5]})
        self.assertEqual(self.runner.calls,[])

    def test_closed_scheduler_rejects_creation_without_persisting_jobs(self):
        self.campaigns.close()
        with self.assertRaises(RuntimeError):self.campaigns.create(self.body)
        self.assertEqual(self.campaigns.list(),[])
        self.assertFalse(list(self.campaigns.output.glob("*.json")))

    def test_retrieval_variants_inherit_base_and_form_separate_groups(self):
        body={**self.body,"seeds":[1],"base_config":{"limit":2,"retrieval":{"method":"dense","chunk_size":900,"overlap":100,"rerank":"none"}},
              "retrieval_variants":[{"method":"dense"},{"method":"bm25"},{"method":"hybrid","rerank":"term_coverage"}]}
        result=self.wait(self.campaigns.create(body)["id"])
        self.assertEqual(len(result["jobs"]),6)
        self.assertTrue(all(job["config"]["retrieval"]["chunk_size"]==900 for job in result["jobs"]))
        self.assertEqual(len(result["reliability"]["groups"]),6)
        self.assertTrue(all(group["completed_trials"]==1 for group in result["reliability"]["groups"]))

    def test_invalid_or_duplicate_retrieval_variants_do_not_start(self):
        for variants in ([],[None],[{},{}],[{"method":"unknown"}],[{"chunk_size":256,"overlap":256}]):
            with self.assertRaises(ValueError):self.campaigns.create({**self.body,"retrieval_variants":variants})
        self.assertEqual(self.runner.calls,[])

    def test_shutdown_during_readiness_start_cannot_leave_uncancelled_work(self):
        self.runner.start_gate=threading.Event()
        created=self.campaigns.create(self.body)
        self.wait(created["id"],lambda item:item["jobs"][0]["status"]=="starting")
        threading.Timer(.03,self.runner.start_gate.set).start()
        self.campaigns.close()
        saved=self.campaigns.get(created["id"])
        self.assertEqual(saved["status"],"interrupted")
        self.assertEqual(saved["jobs"][0]["status"],"interrupted")
        self.assertEqual(len(self.runner.calls),1)
        self.assertEqual(len(self.runner.stop_calls),1)
