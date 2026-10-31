import base64
import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile

from spades.evaluation import run_suite
from spades.report import write_report
from spades.server import RunManager, make_handler


class ExpansionAPITests(unittest.TestCase):
    def test_replay_findings_regression_and_verified_bundle_preserve_original_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=RunManager(Path(folder))
            source=run_suite(case_ids=["hr-baseline-concise"]);source["created_at"]="2026-10-30T12:00:00+00:00"
            verification=run_suite(case_ids=["hr-baseline-concise"]);verification["created_at"]="2026-10-31T12:00:00+00:00"
            write_report(source,manager.output/"source");write_report(verification,manager.output/"verified")
            original=(manager.output/"source"/"report.json").read_bytes()
            server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(manager));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            def post(path,body):
                connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=10)
                connection.request("POST",path,json.dumps(body),{"Content-Type":"application/json","Origin":f"http://127.0.0.1:{server.server_port}","X-Spades-Token":manager.token})
                response=connection.getresponse();status=response.status;data=response.read();kind=response.getheader("Content-Type");connection.close()
                return status,json.loads(data) if kind.startswith("application/json") else data
            ref={"run_id":source["run_id"],"case_id":"hr-baseline-concise","arm":"secured","turn":0}
            try:
                status,capture=post("/api/replay/inspect",ref);self.assertEqual(status,200);self.assertEqual(capture["record"]["kind"],"demo")
                status,replay=post("/api/replay/start",ref);self.assertEqual(status,202)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline and manager.replay_busy:threading.Event().wait(.01)
                self.assertEqual(manager.replays.get(replay["id"])["status"],"completed")
                status,workspace=post("/api/finding",{"title":"Verify control handling","run_id":source["run_id"],"case_id":"hr-baseline-concise","note":"Independent control observation."})
                self.assertEqual(status,200);finding=workspace["findings"][0]
                status,workspace=post("/api/finding/update",{"id":finding["id"],"revision":1,"status":"fixed","verification":{"run_id":verification["run_id"],"case_id":"hr-baseline-concise"}})
                self.assertEqual(status,200);self.assertEqual(workspace["findings"][0]["status"],"fixed")
                status,workspace=post("/api/regression-pack",{"run_id":source["run_id"],"case_ids":["hr-baseline-concise"],"name":"API frozen regression"})
                self.assertEqual(status,200);self.assertEqual(workspace["suites"][0]["case_ids"],["hr-baseline-concise"])
                status,data=post("/api/bundle/export",{"run_ids":[source["run_id"]],"include_findings":True});self.assertEqual(status,200)
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    metadata=json.loads(archive.read("metadata.json"));self.assertEqual(metadata["unbundled_finding_run_ids"],[verification["run_id"]])
                status,verified=post("/api/bundle/verify",{"data":base64.b64encode(data).decode()});self.assertEqual(status,200)
                self.assertTrue(verified["valid"])
                self.assertFalse(verified["authenticity_verified"])
                self.assertEqual((manager.output/"source"/"report.json").read_bytes(),original)
                self.assertIsNone(manager.snapshot())
            finally:
                server.shutdown();server.server_close();thread.join(2)
