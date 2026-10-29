"""Case-level transitions for comparable saved experiment evidence."""

import math


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
                      "secured_field_score_delta": numeric_delta(old_grade.get("field_score"), new_grade.get("field_score")) if measured else None})
    return {"reference_run_id": reference["run_id"], "candidate_run_id": candidate["run_id"],
            "counts": counts, "cases": cases}
