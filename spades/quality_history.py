"""Policy previews and compatible retrospective acceptance histories."""

import json
from datetime import datetime, timezone
from .quality import assess_report, validate_policy
from .settings import validate_retrieval


def compare_policies(report, reference_policy, candidate_policy):
    reference = assess_report(report, reference_policy)
    candidate = assess_report(report, candidate_policy)
    previous = {check["key"]:check for check in reference["checks"]}
    changes = []
    for check in candidate["checks"]:
        old = previous[check["key"]]
        if (old["status"],old["target"]) != (check["status"],check["target"]):
            changes.append({"key":check["key"], "label":check["label"], "observed":check["observed"],
                            "reference_target":old["target"], "candidate_target":check["target"],
                            "reference_status":old["status"], "candidate_status":check["status"],
                            "operator":check["operator"], "denominator":check["denominator"]})
    return {"comparison_version":1, "run_id":report.get("run_id"), "reference":reference, "candidate":candidate,
            "verdict_changed":reference["status"] != candidate["status"], "changes":changes,
            "note":"Both policies assess the same recorded evidence. A changed verdict is a policy effect, not a new model result. Previewing does not apply the candidate policy."}


def compatibility_key(report):
    config=report["configuration"]
    ids=report.get("planned_case_ids")
    if ids is None:
        ids=[row["case_id"] for row in report["results"]]
    if not isinstance(ids,list) or not all(isinstance(case_id,str) for case_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid planned scenario identity")
    result_ids={row["case_id"] for row in report["results"]}
    if not result_ids <= set(ids):
        raise ValueError("Saved results do not belong to the declared planned scope")
    return json.dumps({"mode":report.get("mode"), "model":report.get("model"),
        "profile":config.get("profile","foundation"), "dataset":config.get("dataset_version"),
        "grading":config.get("grading_version"), "generation":config.get("generation"),
        "model_digest":(report.get("performance") or {}).get("model_digest"), "case_ids":sorted(ids),
        "retrieval":validate_retrieval(config.get("retrieval_settings"),config.get("profile","foundation"))},sort_keys=True,allow_nan=False)


def acceptance_history(reports, anchor_id, policy):
    policy=validate_policy(policy)
    anchor=next((report for report in reports if report.get("run_id")==anchor_id),None)
    if anchor is None:
        raise ValueError("Anchor experiment not found")
    key=compatibility_key(anchor)
    compatible, invalid, excluded=[],[],0
    for report in reports:
        try:
            if compatibility_key(report) != key:
                excluded+=1
                continue
            gate=assess_report(report,policy)
            created=report.get("created_at")
            if created is not None and not isinstance(created,str):
                raise ValueError("Invalid experiment creation time")
            instant=datetime.fromisoformat(created.replace("Z","+00:00")) if created else datetime.min.replace(tzinfo=timezone.utc)
            if instant.tzinfo is None:
                instant=instant.replace(tzinfo=timezone.utc)
            compatible.append((report,gate,instant.astimezone(timezone.utc)))
        except (ValueError,TypeError,KeyError) as exc:
            invalid.append({"run_id":report.get("run_id"),"error":str(exc)})
    compatible.sort(key=lambda item:(item[2],item[0]["run_id"]))
    rows, previous=[],None
    for report,gate,_ in compatible:
        transitions=[]
        if previous:
            old_checks={check["key"]:check for check in previous["checks"]}
            for check in gate["checks"]:
                old=old_checks[check["key"]]
                pair=(old["status"],check["status"])
                kind=("regressed" if pair==("pass","fail") else "improved" if pair==("fail","pass")
                      else "newly measured" if old["status"]=="insufficient" and check["status"] in ("pass","fail")
                      else "evidence lost" if check["status"]=="insufficient" and old["status"] in ("pass","fail") else None)
                if kind:
                    transitions.append({"key":check["key"],"label":check["label"],"change":kind,
                                        "previous_status":old["status"],"status":check["status"]})
        rows.append({"run_id":report["run_id"],"created_at":report.get("created_at"),"run_status":report.get("status"),
                     "gate_status":gate["status"],"measured":gate["evidence"]["measured"],"planned":gate["evidence"]["planned"],
                     "defense":{"policy":report["configuration"].get("policy"),"trust":report["configuration"].get("trust_threshold"),"retrieval_k":report["configuration"].get("retrieval_k")},
                     "failed_checks":[check["label"] for check in gate["checks"] if check["status"]=="fail"],
                     "insufficient_checks":[check["label"] for check in gate["checks"] if check["status"]=="insufficient"],
                     "observed_metrics":{check["key"]:check["observed"] for check in gate["checks"] if check["key"] in ("task_rate","attack_rate","field_accuracy")},
                     "transitions":transitions,"previous_run_id":previous["run_id"] if previous else None})
        previous=gate
    return {"history_version":1,"anchor_run_id":anchor_id,"evaluated_at":datetime.now(timezone.utc).isoformat(),"policy":policy,"runs":rows,
            "excluded_incompatible":excluded,"invalid_reports":invalid,
            "identity":json.loads(key),
            "limitations":["All verdicts are retrospective assessments under the same policy, not the original policy at execution time.",
                           "Scenario scope, mode, model tag, dataset, grading, recorded generation settings and weight digest define compatibility; defense settings may differ.",
                           "An unrecorded weight digest or generation setting remains unknown; historical labels do not prove identical execution environments.",
                           "Newly measured criteria and lost evidence are reported separately from pass-to-fail regressions.",
                           "Chronological changes are observations, not controlled causal or statistical evidence."]}
