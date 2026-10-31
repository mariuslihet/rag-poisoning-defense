"""Bounded in-memory evidence archives with explicit integrity manifests."""

import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import re
import stat
import zipfile
import zlib

from .datasets import dataset_identity
from .evaluation import select_cases
from .regressions import report_record

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_UNCOMPRESSED = 32 * 1024 * 1024
MAX_ENTRIES = 128
MAX_RATIO = 100


def _json(value):
    return json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(value):
    if (not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,159}",value)
            or any(part in ("",".","..") for part in value.split("/"))):
        raise ValueError("Bundle entries must use safe relative paths")
    return value


def _definition_snapshot(report):
    config = report.get("configuration") or {}
    profile = config.get("profile","foundation")
    definitions = config.get("case_definitions")
    try:
        identity = dataset_identity(profile,definitions)
        if identity != (config.get("dataset_version"),config.get("grading_version")):
            raise ValueError()
        ids = report.get("planned_case_ids") or [row["case_id"] for row in report.get("results",[])]
        if definitions is not None:
            cases = select_cases(profile=profile,case_ids=ids,case_definitions=definitions)
            return {"availability":"frozen authored definitions","dataset_version":identity[0],"grading_version":identity[1],
                    "planned_case_ids":ids,"case_definitions":definitions}
        cases = select_cases(profile=profile,case_ids=ids)
        return {"availability":"compatible built-in definitions","dataset_version":identity[0],"grading_version":identity[1],"cases":[asdict(case) for case in cases]}
    except (ValueError,KeyError,TypeError):
        return {"availability":"unavailable","note":"The original dataset identity could not be recovered. Saved report evidence is included unchanged; current fixtures were not substituted."}


def build_bundle(reports, workspace, body):
    if not isinstance(body,dict) or not {"run_ids"} <= set(body) or set(body)-{"run_ids","include_findings"}:
        raise ValueError("Expected saved experiment IDs and optional include_findings flag")
    ids = body["run_ids"]
    if not isinstance(ids,list) or not 1 <= len(ids) <= 10 or any(not isinstance(item,str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Choose 1–10 unique saved experiments")
    include_findings = body.get("include_findings",True)
    if type(include_findings) is not bool:
        raise ValueError("Finding inclusion must be an explicit boolean")
    selected = [report_record(reports,run_id) for run_id in ids]
    files, unavailable = {}, []
    cards = []
    for report in selected:
        run_id = report["run_id"]
        files[f"reports/{run_id}.json"] = _json(report)
        snapshot = _definition_snapshot(report)
        files[f"scenarios/{run_id}.json"] = _json(snapshot)
        if snapshot["availability"] == "unavailable":unavailable.append(run_id)
        config = report.get("configuration") or {}
        rows = report.get("results",[])
        cards.append(f'<article><h2>{html.escape(run_id)}</h2><p>{html.escape(str(report.get("mode")))} · {html.escape(str(report.get("model")))} · {html.escape(str(config.get("policy","strict")))} · {len(rows)} recorded observations</p><p><a href="reports/{run_id}.json">Original report JSON</a> · <a href="scenarios/{run_id}.json">Scenario definitions and availability</a></p><ul>' + ''.join(f'<li>{html.escape(str(row.get("case_id","unknown")))} · {html.escape(str(row.get("error") or ("secured task passed" if row.get("secured_utility") else "review required")))}</li>' for row in rows) + '</ul></article>')
    findings, unbundled_finding_runs = [], set()
    if include_findings:
        for finding in workspace.get("findings",[]):
            refs = [finding.get("source"),finding.get("verification")]
            refs += [event.get("verification") for event in finding.get("history",[])]
            if any(isinstance(ref,dict) and ref.get("run_id") in ids for ref in refs):
                findings.append(finding)
                unbundled_finding_runs.update(ref["run_id"] for ref in refs if isinstance(ref,dict) and isinstance(ref.get("run_id"),str) and ref["run_id"] not in ids)
        files["findings.json"] = _json(findings)
    files["index.html"] = ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\"><title>Spades evidence bundle</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#172b44;background:#f3f6fa}article{background:white;border:1px solid #b5c4d5;padding:20px;margin:20px 0;overflow-wrap:anywhere}a{color:#2458a9}</style><h1>Spades evidence bundle</h1><p>Offline evidence snapshot. Each observation retains its original model, dataset and configuration. Different experiments are not a combined performance benchmark.</p><p>Manifest fingerprints detect file changes when the manifest is trusted. They do not authenticate the publisher or establish that recorded model claims are true. No inference, installation or network request runs when this page is opened.</p>"+''.join(cards)+("<p><a href='findings.json'>Linked findings and verification references</a></p>" if include_findings else "")+"<p>Inspect <a href='manifest.json'>manifest.json</a> for file sizes and SHA-256 fingerprints, and <a href='metadata.json'>metadata.json</a> for recovery limits.</p></html>").encode("utf-8")
    if unbundled_finding_runs:
        warning="<p>Some linked findings reference experiments outside this selected bundle: "+html.escape(", ".join(sorted(unbundled_finding_runs)))+". Their evidence is not included; export those experiments as well to review complete verification history.</p>"
        files["index.html"] = files["index.html"].replace(b"</html>",warning.encode("utf-8")+b"</html>")
    files["metadata.json"] = _json({"format":"spades-evidence-metadata","version":1,"run_ids":ids,"included_findings":len(findings),"unavailable_definitions":unavailable,"unbundled_finding_run_ids":sorted(unbundled_finding_runs),
                                  "note":"Reports preserve recorded evidence, including any operator-authored text or paths appearing inside original errors. Host report-file locations are not added to the archive."})
    if sum(len(data) for data in files.values()) > MAX_UNCOMPRESSED:
        raise ValueError("Selected evidence exceeds the 32 MiB uncompressed bundle limit; choose fewer experiments")
    manifest = {"format":"spades-evidence-bundle","version":1,"created_at":datetime.now(timezone.utc).isoformat(),"run_ids":ids,
                "files":[{"path":path,"bytes":len(data),"sha256":_sha(data)} for path,data in sorted(files.items())],
                "integrity_note":"Fingerprints cover every payload file; manifest authenticity is not verified."}
    files["manifest.json"] = _json(manifest)
    if sum(len(data) for data in files.values()) > MAX_UNCOMPRESSED:
        raise ValueError("Selected evidence and manifest exceed the 32 MiB expanded bundle limit")
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,"w") as archive:
        for path,data in sorted(files.items()):
            # Highly compressible synthetic fixture text is stored, preventing
            # our own archive from violating the verifier's ratio bounds.
            compressed = zlib.compress(data)
            method = zipfile.ZIP_STORED if len(data) > MAX_RATIO*max(1,len(compressed)) else zipfile.ZIP_DEFLATED
            info = zipfile.ZipInfo(path,date_time=(2026,1,1,0,0,0));info.compress_type=method;info.external_attr=0o100600 << 16
            archive.writestr(info,data)
    data = memory.getvalue()
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Selected evidence exceeds the 16 MiB archive limit; choose fewer experiments")
    return data,"spades-evidence-bundle.zip"


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:raise ValueError("Duplicate JSON key in bundle manifest")
        result[key] = value
    return result


def verify_bundle(body):
    if not isinstance(body,dict) or set(body)!={"data"} or not isinstance(body["data"],str) or len(body["data"]) > 4*((MAX_ARCHIVE+2)//3):
        raise ValueError("Expected base64 archive data no larger than 16 MiB")
    try:data=base64.b64decode(body["data"],validate=True)
    except (ValueError,TypeError):raise ValueError("The archive is not valid base64") from None
    if not data or len(data)>MAX_ARCHIVE:raise ValueError("The archive must contain 1–16 MiB of ZIP data")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not 2 <= len(infos) <= MAX_ENTRIES or len({item.filename for item in infos}) != len(infos):raise ValueError("Invalid or duplicate bundle entries")
            if sum(item.file_size for item in infos) > MAX_UNCOMPRESSED:raise ValueError("Expanded archive exceeds 32 MiB")
            for item in infos:
                _path(item.filename)
                mode = item.external_attr >> 16
                if item.is_dir() or item.flag_bits & 1 or stat.S_IFMT(mode) not in (0,stat.S_IFREG) or item.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError("Unsupported, encrypted or symbolic-link bundle entry")
                if item.file_size > MAX_RATIO*max(1,item.compress_size):raise ValueError("Bundle entry compression ratio exceeds the safety limit")
            manifest_info=next((item for item in infos if item.filename=="manifest.json"),None)
            if manifest_info is None or manifest_info.file_size>1024*1024:raise ValueError("A bounded manifest.json is required")
            manifest=json.loads(archive.read(manifest_info).decode("utf-8"),object_pairs_hook=_unique_object)
            if not isinstance(manifest,dict) or manifest.get("format")!="spades-evidence-bundle" or type(manifest.get("version")) is not int or manifest["version"]!=1:raise ValueError("Unsupported evidence bundle format")
            entries=manifest.get("files")
            run_ids=manifest.get("run_ids")
            if not isinstance(run_ids,list) or not 1<=len(run_ids)<=10 or any(not isinstance(run_id,str) or not re.fullmatch(r"[a-f0-9]{32}",run_id) for run_id in run_ids) or len(set(run_ids))!=len(run_ids):raise ValueError("Invalid manifest experiment IDs")
            if not isinstance(entries,list) or not entries or len(entries)>MAX_ENTRIES-1:raise ValueError("Invalid manifest file list")
            expected={}
            for entry in entries:
                if not isinstance(entry,dict) or set(entry)!={"path","bytes","sha256"}:raise ValueError("Invalid manifest entry")
                path=_path(entry["path"])
                if path in expected or path=="manifest.json" or type(entry["bytes"]) is not int or not 0<=entry["bytes"]<=MAX_UNCOMPRESSED or not isinstance(entry["sha256"],str) or not re.fullmatch(r"[a-f0-9]{64}",entry["sha256"]):raise ValueError("Invalid manifest identity, size or fingerprint")
                expected[path]=entry
            if set(expected)!={item.filename for item in infos if item.filename!="manifest.json"}:raise ValueError("Archive contents do not exactly match the manifest")
            required={"index.html","metadata.json"}|{f"{folder}/{run_id}.json" for folder in ("reports","scenarios") for run_id in run_ids}
            if not required<=set(expected) or set(expected)-required-{"findings.json"}:raise ValueError("Bundle structure does not match the declared experiments")
            for path,entry in expected.items():
                payload=archive.read(path)
                if len(payload)!=entry["bytes"] or _sha(payload)!=entry["sha256"]:raise ValueError(f"Integrity mismatch for {path}")
            return {"valid":True,"format":manifest["format"],"version":manifest["version"],"files_verified":len(expected),"archive_bytes":len(data),
                    "uncompressed_bytes":sum(item.file_size for item in infos),"archive_sha256":_sha(data),"run_ids":manifest.get("run_ids",[]),
                    "authenticity_verified":False,"note":"All payload sizes and SHA-256 fingerprints match the manifest. This is an integrity check, not publisher authentication, safety certification or model-result validation. Nothing was extracted or executed."}
    except (zipfile.BadZipFile,UnicodeDecodeError,KeyError,RuntimeError,RecursionError,zlib.error) as exc:
        raise ValueError("Invalid or unreadable evidence archive") from exc
