"""Case-level transitions for comparable saved experiment evidence."""

import math
import json


def _same(left, right):
    return json.dumps(left,sort_keys=True,allow_nan=False)==json.dumps(right,sort_keys=True,allow_nan=False)


def detail_changes(old, new):
    if old.get("error") or new.get("error"):
        return {"field_changes":[],"citation_changes":None,"decision_changes":[],"details_measured":False}
    a,b=old.get("secured_grade") or {},new.get("secured_grade") or {}
    old_fields={check["field"]:check for check in a.get("checks",[])}
    new_fields={check["field"]:check for check in b.get("checks",[])}
    changes=[]
    for field in dict.fromkeys([*old_fields,*new_fields]):
        before,after=old_fields.get(field),new_fields.get(field)
        if _same(before,after): continue
        contract_changed=bool(before and after and (not _same(before.get("expected"),after.get("expected")) or before.get("tolerance",0)!=after.get("tolerance",0)))
        change="added assertion" if before is None else "removed assertion" if after is None else "reference changed" if contract_changed else (
            "regressed" if before["passed"] and not after["passed"] else "improved" if not before["passed"] and after["passed"] else "value changed" if not _same(before.get("actual"),after.get("actual")) else "assertion metadata changed")
        changes.append({"field":field,"change":change,"reference":before,"candidate":after,"contract_changed":contract_changed})
    citations=None
    if a or b:
        old_cited,new_cited=set(a.get("citations",[])),set(b.get("citations",[]))
        citations={"added":sorted(new_cited-old_cited),"removed":sorted(old_cited-new_cited),
                   "reference_missing":a.get("missing_citations",[]),"candidate_missing":b.get("missing_citations",[]),
                   "reference_invalid":a.get("invalid_citations",[]),"candidate_invalid":b.get("invalid_citations",[])}
        citations["changed"]=bool(citations["added"] or citations["removed"] or citations["reference_missing"]!=citations["candidate_missing"] or citations["reference_invalid"]!=citations["candidate_invalid"])
    old_decisions={decision["chunk_id"]:decision for decision in old.get("decisions",[])}
    new_decisions={decision["chunk_id"]:decision for decision in new.get("decisions",[])}
    decisions=[]
    for chunk in dict.fromkeys([*old_decisions,*new_decisions]):
        before,after=old_decisions.get(chunk),new_decisions.get(chunk)
        if _same(before,after): continue
        kind="newly retrieved" if before is None else "not retrieved in candidate" if after is None else (
            "allowed to blocked" if before["allowed"] and not after["allowed"] else "blocked to allowed" if not before["allowed"] and after["allowed"] else "decision details changed")
        summarize=lambda decision: {key:decision.get(key) for key in ("allowed","reason","trust")} if decision else None
        decisions.append({"chunk_id":chunk,"change":kind,"reference":summarize(before),"candidate":summarize(after),
                          "sanitization_changed":bool(before and after and before.get("sanitized_text")!=after.get("sanitized_text"))})
    return {"field_changes":changes,"citation_changes":citations,"decision_changes":decisions,"details_measured":True}


def numeric_delta(old, new):
    """Return candidate minus reference only for recorded finite numbers."""
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (old, new)):
        return None
    return round(new - old, 6)


def compare_cases(reference, candidate):
    a, b = reference["configuration"], candidate["configuration"]
    reference_rows = {row["case_id"]: row for row in reference["results"]}
    candidate_rows = {row["case_id"]: row for row in candidate["results"]}
    if (reference["mode"] != candidate["mode"] or reference["model"] != candidate["model"]
            or set(reference_rows) != set(candidate_rows)
            or a.get("profile", "foundation") != b.get("profile", "foundation")
            or a.get("dataset_version") != b.get("dataset_version")
            or a.get("grading_version") != b.get("grading_version")):
        raise ValueError("Case comparisons require the same mode, model, profile, dataset, grading and scenario IDs")
    digests = [(report.get("performance") or {}).get("model_digest") for report in (reference, candidate)]
    if reference["mode"] == "local" and all(digests) and digests[0] != digests[1]:
        raise ValueError("Case comparisons require matching model weight digests when both runs record them")
    counts = {"task_regressions": 0, "task_improvements": 0,
              "new_attack_matches": 0, "resolved_attack_matches": 0, "unmeasured": 0}
    cases = []
    for case_id, old in reference_rows.items():
        new = candidate_rows[case_id]
        task, attack = "unchanged", "not applicable"
        if old["error"] or new["error"]:
            task = attack = "unmeasured"
            counts["unmeasured"] += 1
        else:
            if old["secured_utility"] and not new["secured_utility"]:
                task = "regressed"
                counts["task_regressions"] += 1
            elif not old["secured_utility"] and new["secured_utility"]:
                task = "improved"
                counts["task_improvements"] += 1
            if old["category"] != "baseline":
                attack = "unchanged"
                if not old["secured_success"] and new["secured_success"]:
                    attack = "new match"
                    counts["new_attack_matches"] += 1
                elif old["secured_success"] and not new["secured_success"]:
                    attack = "resolved match"
                    counts["resolved_attack_matches"] += 1
        measured = not old["error"] and not new["error"]
        old_grade, new_grade = old.get("secured_grade") or {}, new.get("secured_grade") or {}
        cases.append({"case_id": case_id, "task": task, "attack": attack,
                      "reference_error": old["error"], "candidate_error": new["error"],
                      "duration_delta_seconds": numeric_delta(old.get("duration_seconds"), new.get("duration_seconds")) if measured else None,
                      "secured_field_score_delta": numeric_delta(old_grade.get("field_score"), new_grade.get("field_score")) if measured else None,
                      **detail_changes(old,new)})
    return {"reference_run_id": reference["run_id"], "candidate_run_id": candidate["run_id"],
            "counts": counts, "cases": cases,
            "field_summary":{"regressed":sum(change["change"]=="regressed" for case in cases for change in case["field_changes"]),
                             "improved":sum(change["change"]=="improved" for case in cases for change in case["field_changes"]),
                             "reference_changes":sum(change["contract_changed"] for case in cases for change in case["field_changes"])}}
