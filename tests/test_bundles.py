import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import unittest
import zipfile

from spades.bundles import build_bundle,verify_bundle
from spades.evaluation import run_suite


def encoded(data):return {"data":base64.b64encode(data).decode("ascii")}


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.report=run_suite(case_ids=["hr-baseline-concise"])
        self.reports={self.report["run_id"]:(Path("D:/private-machine-path/report.json"),self.report)}

    def build(self,**options):return build_bundle(self.reports,{}, {"run_ids":[self.report["run_id"]],**options})[0]

    def rewrite(self,data,change):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:files={name:archive.read(name) for name in archive.namelist()}
        change(files)
        memory=io.BytesIO()
        with zipfile.ZipFile(memory,"w",compression=zipfile.ZIP_STORED) as archive:
            for path,payload in files.items():archive.writestr(path,payload)
        return memory.getvalue()

    def test_bundle_has_exact_manifest_fingerprints_and_verifies_without_extraction(self):
        original=copy.deepcopy(self.report);data=self.build()
        result=verify_bundle(encoded(data))
        self.assertTrue(result["valid"])
        self.assertFalse(result["authenticity_verified"])
        self.assertEqual(result["archive_sha256"],hashlib.sha256(data).hexdigest())
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            manifest=json.loads(archive.read("manifest.json"))
            for entry in manifest["files"]:
                payload=archive.read(entry["path"])
                self.assertEqual(entry["bytes"],len(payload))
                self.assertEqual(entry["sha256"],hashlib.sha256(payload).hexdigest())
            self.assertNotIn(b"private-machine-path",b"".join(archive.read(path) for path in archive.namelist()))
            self.assertEqual(json.loads(archive.read(f"reports/{self.report['run_id']}.json")),original)
        self.assertEqual(original,self.report)

    def test_html_escapes_recorded_strings_and_has_no_executable_scripts(self):
        self.report["model"]='<script>alert("model")</script>'
        self.report["results"][0]["error"]='<img src=x onerror="bad()">'
        with zipfile.ZipFile(io.BytesIO(self.build())) as archive:
            index=archive.read("index.html").decode()
        self.assertNotIn("<script",index)
        self.assertNotIn("<img",index)
        self.assertIn("&lt;script&gt;",index)
        self.assertIn("Content-Security-Policy",index)

    def test_changed_payload_extra_file_and_removed_payload_are_rejected(self):
        data=self.build();path=f"reports/{self.report['run_id']}.json"
        for change in (lambda files:files.__setitem__(path,b"tampered"),lambda files:files.__setitem__("extra.txt",b"extra"),lambda files:files.pop(path)):
            with self.assertRaises(ValueError):verify_bundle(encoded(self.rewrite(data,change)))

    def test_unsafe_paths_symlinks_and_high_expansion_are_rejected(self):
        for path,kind in (("../outside.txt","normal"),("folder\\outside.txt","normal"),("link.txt","symlink"),("huge.txt","bomb")):
            memory=io.BytesIO()
            with zipfile.ZipFile(memory,"w") as archive:
                archive.writestr("manifest.json",b"{}")
                info=zipfile.ZipInfo(path)
                if kind=="symlink":info.external_attr=(stat.S_IFLNK|0o777)<<16
                if kind=="bomb":info.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(info,b"x"*200000 if kind=="bomb" else b"outside")
            with self.assertRaises(ValueError):verify_bundle(encoded(memory.getvalue()))

    def test_stale_definition_is_marked_unavailable_instead_of_substituted(self):
        self.report["configuration"]["dataset_version"]="unrecoverable-old-version"
        with zipfile.ZipFile(io.BytesIO(self.build())) as archive:
            snapshot=json.loads(archive.read(f"scenarios/{self.report['run_id']}.json"))
        self.assertEqual(snapshot["availability"],"unavailable")
        self.assertNotIn("cases",snapshot)

    def test_only_findings_linked_to_selected_runs_are_included(self):
        findings=[{"id":"one","source":{"run_id":self.report["run_id"]},"verification":None,"history":[]},
                  {"id":"two","source":{"run_id":"f"*32},"verification":{"run_id":self.report["run_id"]},"history":[]},
                  {"id":"other","source":{"run_id":"e"*32},"history":[]}]
        data,_=build_bundle(self.reports,{"findings":findings},{"run_ids":[self.report["run_id"]]})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:self.assertEqual([item["id"] for item in json.loads(archive.read("findings.json"))],["one","two"])
        with zipfile.ZipFile(io.BytesIO(self.build(include_findings=False))) as archive:self.assertNotIn("findings.json",archive.namelist())

    def test_duplicate_manifest_keys_and_invalid_inputs_are_rejected(self):
        data=self.build()
        duplicate=self.rewrite(data,lambda files:files.__setitem__("manifest.json",b'{"format":"x","format":"spades-evidence-bundle"}'))
        with self.assertRaises(ValueError):verify_bundle(encoded(duplicate))
        for body in ({"data":"not base64"},{"data":base64.b64encode(b"not zip").decode()},{"data":None},{"url":"https://example.invalid/archive.zip"}):
            with self.assertRaises(ValueError):verify_bundle(body)
        for body in ({"run_ids":[]},{"run_ids":[self.report["run_id"]]*2},{"run_ids":["../outside"]},{"run_ids":[self.report["run_id"]],"include_findings":1}):
            with self.assertRaises(ValueError):build_bundle(self.reports,{},body)
