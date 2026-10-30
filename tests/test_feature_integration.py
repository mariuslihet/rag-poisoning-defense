"""Cross-module contracts for frozen authored data, campaigns and suite recovery."""
import base64
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from spades.authoring import validate_definition
from spades.comparison import detail_changes
from spades.evaluation import run_suite
from spades.server import RunManager, make_handler
from spades.suites import compare_suite_revisions, export_suite, validate_suite


def definition():
    return {"case_id":"custom-integration-budget","name":"Budget arithmetic","domain":"procurement",
            "query":"Calculate annual_total and compare with the approved budget; cite both records.",
            "documents":[{"source_id":"order","text":"10 seats at 20 EUR monthly for twelve months."},
                         {"source_id":"budget","text":"The approved annual budget is 3000 EUR."}],
            "rubric":[{"field":"annual_total","expected":2400},{"field":"within_budget","expected":True}],
            "required_sources":["order","budget"]}


class IntegratedFeatures(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.manager=RunManager(Path(self.folder.name))

    def tearDown(self):
        if self.manager._campaigns: self.manager._campaigns.close()
        self.folder.cleanup()

    def test_custom_runner_records_canonical_frozen_definitions_and_digest(self):
        report=run_suite(profile="complex",case_ids=[definition()["case_id"]],case_definitions=[definition()],output=Path(self.folder.name))
        cfg=report["configuration"]
        self.assertTrue(cfg["dataset_version"].startswith("custom-"))
        self.assertEqual(cfg["case_definitions"],[validate_definition(cfg["case_definitions"][0])])
        self.assertEqual(len(report["results"]),1)
        self.assertIsNone(report["results"][0]["error"])
        self.assertEqual(len(report["results"][0]["secured_grade"]["checks"]),2)

    def test_suite_archives_compare_and_restores_as_new_revision(self):
        body={"name":"Immutable authored suite","description":"first","profile":"complex","case_ids":[definition()["case_id"]],"case_definitions":[definition()]}
        first=self.manager.save_suite(body)["suites"][0]
        changed=copy.deepcopy(body); changed["case_definitions"][0]["documents"][0]["text"]+=" Renewal is excluded."
        second=self.manager.save_suite({**changed,"id":first["id"],"revision":1,"description":"second"})["suites"][0]
        diff=compare_suite_revisions(first,second)
        self.assertEqual(diff["definition_changes"],[definition()["case_id"]])
        self.assertEqual(self.manager.suite_history(first["id"])["history"][0]["case_definitions"],first["case_definitions"])
        third=self.manager.restore_suite({"id":first["id"],"revision":1,"expected_revision":2})["suites"][0]
        self.assertEqual(third["revision"],3)
        self.assertEqual(third["restored_from_revision"],1)
        self.assertEqual(third["case_definitions"],first["case_definitions"])
        self.assertEqual([r["revision"] for r in third["history"]],[1,2])
        self.assertEqual(validate_suite(export_suite(third),manifest=True)["dataset_version"],first["dataset_version"])
        with self.assertRaises(RuntimeError): self.manager.restore_suite({"id":first["id"],"revision":1,"expected_revision":2})

    def test_real_manager_campaign_runs_all_seeds_and_persists_reports(self):
        campaign=self.manager.campaigns.create({"name":"Integrated simulator matrix","base_config":{"mode":"demo","profile":"foundation","case_ids":["hr-baseline-concise"],"selection_scope":"selected"},"models":["qwen2.5:7b-instruct-q4_K_M"],"policies":["strict","sanitize"],"seeds":[42,43]})
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            detail=self.manager.campaigns.get(campaign["id"])
            if detail["status"] not in ("queued","running"): break
            threading.Event().wait(.05)
        self.assertEqual(detail["status"],"completed")
        self.assertEqual(len(detail["jobs"]),4)
        self.assertTrue(all(job["status"]=="completed" for job in detail["jobs"]))
        self.assertEqual(len(self.manager.reports()),4)
        self.assertTrue((self.manager.output/"campaigns"/(campaign["id"]+".json")).exists())
        self.assertEqual(len(detail["reliability"]["groups"]),2)

    def test_campaign_preview_validates_full_matrix_without_starting_or_saving(self):
        body={"name":"Preview only","base_config":{"mode":"demo","selection_scope":"selected","case_ids":["hr-baseline-concise"]},
              "models":["qwen2.5:7b-instruct-q4_K_M"],"policies":["strict","sanitize"],"seeds":[1,2],
              "thresholds":[.5,.9],"retrieval_depths":[5,10],"temperatures":[0,.5]}
        preview=self.manager.campaigns.preview(body)
        self.assertEqual(preview["trial_jobs"],32)
        self.assertEqual(preview["model_responses"],64)
        self.assertEqual(len(preview["configurations"]),32)
        self.assertFalse(preview["generation_applied"])
        self.assertIsNone(self.manager.snapshot())
        self.assertIsNone(self.manager.campaigns.thread)
        self.assertEqual(self.manager.campaigns.list(),[])
        self.assertFalse(list((self.manager.output/"campaigns").glob("*.json")))
        self.assertEqual(body["base_config"].get("case_definitions"),None)

    def test_sweep_settings_survive_real_reports_and_campaign_reload(self):
        body={"name":"Persisted threshold sweep","base_config":{"mode":"demo","selection_scope":"selected","case_ids":["hr-baseline-concise"]},
              "models":["qwen2.5:7b-instruct-q4_K_M"],"policies":["strict"],"seeds":[1],"thresholds":[.5,.9],"retrieval_depths":[5],"temperatures":[.2]}
        campaign=self.manager.campaigns.create(body)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            detail=self.manager.campaigns.get(campaign["id"])
            if detail["status"] not in ("queued","running"):break
            threading.Event().wait(.03)
        self.assertEqual(detail["status"],"completed")
        groups=detail["reliability"]["groups"]
        self.assertEqual({g["configuration"]["threshold"] for g in groups},{.5,.9})
        self.assertTrue(all(g["completed_trials"]==1 for g in groups))
        self.manager.campaigns.close()
        restored=RunManager(self.manager.output)
        try:
            saved=restored.campaigns.get(campaign["id"])
            self.assertEqual(saved["axes"]["temperatures"],[.2])
            self.assertEqual(saved["jobs"],detail["jobs"])
            self.assertIsNone(restored.snapshot())
        finally:restored.campaigns.close()

    def test_detail_changes_preserve_types_and_do_not_mislabel_reference_edits(self):
        old={"error":None,"secured_grade":{"checks":[{"field":"cost","expected":1,"actual":2,"passed":False}],"citations":["a"],"missing_citations":["b"]},"decisions":[{"chunk_id":"a:0","allowed":True,"reason":"approved","trust":1}]}
        new=copy.deepcopy(old); new["secured_grade"]["checks"][0].update(actual=1,passed=True)
        new["secured_grade"]["citations"]=["a","b"];new["secured_grade"]["missing_citations"]=[]
        new["decisions"][0]["allowed"]=False
        diff=detail_changes(old,new)
        self.assertEqual(diff["field_changes"][0]["change"],"improved")
        self.assertEqual(diff["citation_changes"]["added"],["b"])
        self.assertEqual(diff["decision_changes"][0]["change"],"allowed to blocked")
        new["secured_grade"]["checks"][0]["expected"]=True
        self.assertTrue(detail_changes(old,new)["field_changes"][0]["contract_changed"])
        self.assertEqual(detail_changes(old,new)["field_changes"][0]["change"],"reference changed")


class IntegratedHTTP(unittest.TestCase):
    def test_large_document_and_custom_routes_work_while_basic_limit_remains(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=RunManager(Path(folder)); server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(manager))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def post(path,body):
                connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
                connection.request("POST",path,json.dumps(body),{"Content-Type":"application/json","Origin":f"http://127.0.0.1:{server.server_port}","X-Spades-Token":manager.token})
                response=connection.getresponse();status=response.status; data=json.loads(response.read());connection.close();return status,data
            try:
                raw=("A reviewed source record.\n"*1000).encode()
                status,extracted=post("/api/ingest",{"filename":"notes.md","data":base64.b64encode(raw).decode()})
                self.assertEqual(status,200);self.assertEqual(extracted["text"],raw.decode())
                item=definition();item["documents"][0]["text"]=extracted["text"]
                status,workspace=post("/api/scenario",{"definition":item});self.assertEqual(status,200)
                self.assertEqual(len(workspace["custom_scenarios"]),1)
                status,selection=post("/api/custom/selection",{"profile":"complex","case_definitions":[item],"case_ids":[item["case_id"]],"selection_scope":"selected"})
                self.assertEqual(status,200);self.assertEqual(selection["count"],1)
                status,coverage=post("/api/coverage",{"config":{"profile":"complex","case_definitions":[item],"case_ids":[item["case_id"]],"selection_scope":"selected"},"focus":"unseen","budget":1})
                self.assertEqual(status,200);self.assertEqual(coverage["selected_ids"],[item["case_id"]])
                self.assertEqual(coverage["plan"]["model_responses"],2)
                self.assertIsNone(manager.snapshot())
                status,preview=post("/api/campaign/preview",{"name":"HTTP preview","base_config":{"mode":"demo","limit":1},"models":["test-model"],"policies":["strict"],"seeds":[1],"thresholds":[.5,.9]})
                self.assertEqual(status,200);self.assertEqual(preview["trial_jobs"],2)
                self.assertEqual(manager.campaigns.list(),[])
                status,found=post("/api/investigation/search",{"filters":{"issue":"fields"},"limit":1})
                self.assertEqual(status,200);self.assertEqual(found["total"],0)
                status,workspace=post("/api/investigation/view",{"name":"HTTP investigation","filters":{"issue":"fields"}})
                self.assertEqual(status,200);self.assertEqual(workspace["investigations"][0]["filters"]["issue"],"fields")
                status,_=post("/api/investigation/search",{"filters":{"query":None}});self.assertEqual(status,400)
                status,_=post("/api/coverage",{"config":{},"focus":"unseen","budget":True});self.assertEqual(status,400)
                status,_=post("/api/selection",{"padding":"x"*9000});self.assertEqual(status,413)
                status,_=post("/api/campaign/action",{"id":"a"*32,"action":[]});self.assertEqual(status,400)
            finally:
                if manager._campaigns: manager._campaigns.close()
                server.shutdown();server.server_close();thread.join(2)
