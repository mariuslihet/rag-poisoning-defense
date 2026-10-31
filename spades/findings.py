"""Local remediation records tied to immutable saved-case fingerprints."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

STATUSES = ("open", "investigating", "fixed", "accepted")
SEVERITIES = ("low", "medium", "high", "critical")
MAX_FINDINGS_BYTES = 32 * 1024 * 1024


def _text(value, name, maximum, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f"{name} must contain {'1' if required else '0'}–{maximum} characters")
    return value.strip()


def _metadata(body, previous=None):
    previous = previous or {"title":"", "severity":"medium", "assignee":"", "tags":[], "note":""}
    result = {key: deepcopy(body.get(key, previous[key])) for key in ("title","severity","assignee","tags","note")}
    result["title"] = _text(result["title"], "Finding title", 160, required=True)
    result["note"] = _text(result["note"], "Finding note", 4000)
    result["assignee"] = _text(result["assignee"], "Local assignee label", 100)
    if not isinstance(result["severity"], str) or result["severity"] not in SEVERITIES:
        raise ValueError("Choose low, medium, high or critical severity")
    if not isinstance(result["tags"], list) or len(result["tags"]) > 12:
        raise ValueError("Use at most twelve finding tags")
    tags = [_text(tag,"Tag",40,required=True) for tag in result["tags"]]
    if len({tag.casefold() for tag in tags}) != len(tags):
        raise ValueError("Finding tags must be unique")
    result["tags"] = tags
    return result


def _instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Evidence requires a valid timezone-aware experiment start time") from None


def _evidence(reports, body):
    if not isinstance(body,dict) or set(body) != {"run_id","case_id"}:
        raise ValueError("Evidence references require exactly run_id and case_id")
    run_id, case_id = body["run_id"], body["case_id"]
    if not isinstance(run_id,str) or not re.fullmatch(r"[a-f0-9]{32}",run_id):
        raise ValueError("Choose a saved experiment ID")
    if not isinstance(case_id,str) or not 1 <= len(case_id) <= 200:
        raise ValueError("Choose an exact saved scenario ID")
    report = reports.get(run_id)
    if isinstance(report, tuple):
        report = report[1]
    if not isinstance(report,dict) or report.get("run_id") != run_id:
        raise ValueError("Saved evidence report is unavailable")
    if not isinstance(report.get("results"),list) or not isinstance(report.get("configuration"),dict):
        raise ValueError("Saved evidence report has an invalid structure")
    rows = [row for row in report["results"] if isinstance(row,dict) and row.get("case_id")==case_id]
    if len(rows) != 1:
        raise ValueError("The selected case must appear exactly once in the saved report")
    row = rows[0]
    config = report.get("configuration") or {}
    identity = {"mode":report.get("mode"), "model":report.get("model"), "profile":config.get("profile","foundation"),
                "dataset_version":config.get("dataset_version"), "grading_version":config.get("grading_version"),
                "policy":config.get("policy","strict"),"trust_threshold":config.get("trust_threshold"),
                "retrieval_k":config.get("retrieval_k"),"generation":deepcopy(config.get("generation")),
                "retrieval_settings":deepcopy(config.get("retrieval_settings")),
                "model_digest":(report.get("performance") or {}).get("model_digest")}
    if identity["mode"] not in ("demo","local") or identity["profile"] not in ("foundation","complex"):
        raise ValueError("The saved evidence execution identity is unavailable")
    _instant(report.get("created_at"))
    digest = hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")).hexdigest()
    return {"run_id":run_id,"case_id":case_id,"row_sha256":digest,"identity":identity,
            "created_at":report["created_at"]}, report, row


def _verify(reports, source, reference):
    current_source, _, _ = _evidence(reports,{key:source[key] for key in ("run_id","case_id")})
    if current_source != source:
        raise ValueError("The original finding evidence changed; review its preserved fingerprint before verification")
    evidence, report, row = _evidence(reports,reference)
    if evidence["run_id"] == source["run_id"]:
        raise ValueError("A fix requires a different verification experiment")
    if evidence["case_id"] != source["case_id"]:
        raise ValueError("Verification must assess the original exact scenario ID")
    if _instant(evidence["created_at"]) <= _instant(source["created_at"]):
        raise ValueError("Verification must come from an experiment started after the original finding evidence")
    if report.get("status") != "completed":
        raise ValueError("Verification requires a completed experiment")
    identity = evidence["identity"]
    for key in ("profile","dataset_version","grading_version"):
        if not source["identity"].get(key) or identity[key] != source["identity"][key]:
            raise ValueError("Verification must retain the original profile, dataset and grading identity")
    if source["identity"]["mode"] == "local" and identity["mode"] != "local":
        raise ValueError("A local-model finding cannot be fixed using demonstration responses")
    grade = row.get("secured_grade") or {}
    if (row.get("error") or row.get("secured_utility") is not True or row.get("secured_success") is not False
            or row.get("secured_leak") or grade.get("leakage")):
        raise ValueError("Verification must pass the secured task with no runtime error, attack match or restricted-data disclosure")
    return evidence


def _event(record, action):
    return {key:deepcopy(record[key]) for key in ("revision","status","title","severity","assignee","tags","note","verification","updated_at")} | {"action":action}


def _store(workspace, records, record):
    updated = [item for item in records if item["id"] != record["id"]] + [record]
    if len(json.dumps(updated,allow_nan=False,ensure_ascii=False).encode("utf-8")) > MAX_FINDINGS_BYTES:
        raise ValueError("Finding history exceeds the 32 MiB workspace limit; export existing records before adding more")
    workspace["findings"] = updated
    return deepcopy(record)


def create_finding(workspace, body, reports):
    if not isinstance(body,dict) or not {"title","run_id","case_id"} <= set(body) or set(body)-{"title","run_id","case_id","severity","note","assignee","tags"}:
        raise ValueError("Expected finding title, source run/case and optional severity, note, assignee and tags")
    metadata = _metadata(body)
    source, _, _ = _evidence(reports,{"run_id":body["run_id"],"case_id":body["case_id"]})
    records = workspace.get("findings",[])
    if not isinstance(records,list):
        raise ValueError("Finding workspace data is invalid")
    if len(records) >= 500:
        raise ValueError("The workspace supports up to 500 findings")
    now = datetime.now(timezone.utc).isoformat()
    record = {"id":uuid.uuid4().hex,**metadata,"status":"open","revision":1,"source":source,"verification":None,
              "created_at":now,"updated_at":now}
    record["history"] = [_event(record,"created")]
    return _store(workspace,records,record)


def update_finding(workspace, body, reports):
    if not isinstance(body,dict) or not {"id","revision","status"} <= set(body) or set(body)-{"id","revision","status","title","severity","note","assignee","tags","verification"}:
        raise ValueError("Expected finding ID, revision, status and known update fields")
    finding_id = body["id"]
    if not isinstance(finding_id,str) or not re.fullmatch(r"[a-f0-9]{32}",finding_id):
        raise ValueError("Invalid finding ID")
    if type(body["revision"]) is not int or body["revision"] < 1:
        raise ValueError("Finding revisions must be positive integers")
    if not isinstance(body["status"],str) or body["status"] not in STATUSES:
        raise ValueError("Choose open, investigating, fixed or accepted status")
    records = workspace.get("findings",[])
    existing = next((item for item in records if item["id"]==finding_id),None)
    if existing is None:
        raise ValueError("Saved finding not found")
    if existing["revision"] != body["revision"]:
        raise RuntimeError("This finding changed. Reload the latest revision before saving.")
    if existing["revision"] >= 100:
        raise ValueError("This finding reached its 100-revision limit; export its history before further work")
    metadata = _metadata(body,existing)
    verification = deepcopy(existing["verification"])
    if "verification" in body and body["status"] != "fixed":
        raise ValueError("Verification evidence is attached when marking a finding fixed")
    if body["status"] == "accepted" and not metadata["note"]:
        raise ValueError("Accepted findings require a written acceptance rationale")
    if body["status"] == "fixed":
        reference = body.get("verification")
        if reference is None and verification:
            reference = {key:verification[key] for key in ("run_id","case_id")}
        if reference is None:
            raise ValueError("Choose an explicit verification experiment and scenario before marking this finding fixed")
        checked = _verify(reports,existing["source"],reference)
        if "verification" not in body and checked["row_sha256"] != verification["row_sha256"]:
            raise ValueError("The prior verification evidence changed; review and explicitly attach it again")
        verification = checked
    now = datetime.now(timezone.utc).isoformat()
    record = {**deepcopy(existing),**metadata,"status":body["status"],"verification":verification,
              "revision":existing["revision"]+1,"updated_at":now}
    record["history"].append(_event(record,"updated"))
    return _store(workspace,records,record)
