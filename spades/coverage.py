"""Read-only coverage planning from comparable, saved case observations."""

from collections import Counter
from datetime import datetime, timezone
import copy

from .datasets import dataset_identity
from .settings import validate_generation
from .suites import plan_cases


def _instant(value):
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def _generation(options, profile):
    result = validate_generation(options, profile)
    result.pop("seed")
    return result


def coverage_plan(config, cases, reports, *, focus="unseen", budget=6):
    if not isinstance(focus, str) or focus not in ("unseen", "review", "all"):
        raise ValueError("Choose unseen, review or all coverage")
    if type(budget) is not int or not 1 <= budget <= 100:
        raise ValueError("The scenario budget must be an integer from 1 to 100")
    dataset, grading = dataset_identity(config["profile"], config.get("case_definitions"))
    target_ids = {case.case_id for case in cases}
    compatible, excluded = [], Counter()
    for report in reports:
        recorded = report.get("configuration") or {}
        reason = None
        try:
            if report.get("mode") != config["mode"] or (config["mode"] == "local" and report.get("model") != config["model"]):
                reason = "execution identity"
            elif (recorded.get("profile", "foundation"), recorded.get("dataset_version"), recorded.get("grading_version")) != (config["profile"], dataset, grading):
                reason = "dataset or grading"
            elif any(recorded.get(saved) != config[requested] for saved, requested in (
                    ("policy", "policy"), ("trust_threshold", "threshold"), ("retrieval_k", "k"))):
                reason = "defense or retrieval settings"
            elif config["mode"] == "local" and (not recorded.get("generation") or _generation(recorded["generation"], config["profile"]) != _generation(config["generation"], config["profile"])):
                reason = "generation settings missing or different"
            elif not _instant(report.get("created_at")):
                reason = "invalid evidence time"
            elif not any(row.get("case_id") in target_ids for row in report.get("results", [])):
                reason = "no selected scenarios"
        except (TypeError, ValueError, KeyError):
            reason = "invalid report settings"
        if reason:
            excluded[reason] += 1
        else:
            compatible.append(report)
    compatible.sort(key=lambda report: (_instant(report["created_at"]), report["run_id"]), reverse=True)
    # Pin the newest observed identity; historical unknown weights cannot fill
    # gaps for a known model identity, nor can known weights fill an unknown one.
    digest = (compatible[0].get("performance") or {}).get("model_digest") if compatible and config["mode"] == "local" else None
    latest, used_runs = {}, set()
    for report in compatible:
        if config["mode"] == "local" and (report.get("performance") or {}).get("model_digest") != digest:
            excluded["different or unrecorded model weights"] += 1
            continue
        seen = set()
        for row in report.get("results", []):
            case_id = row.get("case_id")
            if case_id not in target_ids or case_id in seen:
                continue
            seen.add(case_id)
            if case_id not in latest:
                latest[case_id] = (row, report)
                used_runs.add(report["run_id"])
    entries = []
    for case in cases:
        row, report = latest.get(case.case_id, ({}, {}))
        grade = row.get("secured_grade") or {}
        issues = []
        if not row:
            status = "unseen"
        elif row.get("error"):
            status = "runtime_error"
        elif type(row.get("secured_utility")) is not bool:
            status = "unmeasured"
        else:
            if row.get("secured_leak") or grade.get("leakage"):
                issues.append("restricted data disclosed")
            if case.category != "baseline" and row.get("secured_success"):
                issues.append("attack objective matched")
            if not row["secured_utility"]:
                issues.append("secured task failed")
            status = "review" if issues else "passed"
        failed = [check["field"] for check in grade.get("checks", []) if not check.get("passed")]
        entries.append({"case_id": case.case_id, "domain": case.domain or case.case_id.split("-")[0],
                        "category": case.category, "status": status, "issues": issues, "failed_fields": failed,
                        "missing_citations": grade.get("missing_citations", []), "error": row.get("error"),
                        "run_id": report.get("run_id"), "observed_at": report.get("created_at"),
                        "duration_seconds": row.get("duration_seconds")})
    priority = {"review": 0, "runtime_error": 1, "unmeasured": 2, "unseen": 3, "passed": 4}
    ranked = sorted(entries, key=lambda item: (priority[item["status"]],
                    -int("restricted data disclosed" in item["issues"]),
                    -int("attack objective matched" in item["issues"]), item["case_id"]))
    candidates = [item for item in ranked if focus == "all" or (focus == "unseen" and item["status"] == "unseen")
                  or (focus == "review" and item["status"] in ("review", "runtime_error", "unmeasured"))]
    # Preserve risk tiers, then spread equally ranked work across domains and
    # families. The budget is a scenario bound, not a statistical sampling claim.
    selected, remaining = [], list(candidates)
    domain_counts, family_counts = Counter(), Counter()
    while remaining and len(selected) < budget:
        item = min(remaining, key=lambda entry: (
            priority[entry["status"]], -int("restricted data disclosed" in entry["issues"]),
            -int("attack objective matched" in entry["issues"]), domain_counts[entry["domain"]],
            family_counts[entry["category"]], entry["case_id"]))
        selected.append(item)
        remaining.remove(item)
        domain_counts[item["domain"]] += 1
        family_counts[item["category"]] += 1
    chosen = {item["case_id"] for item in selected}
    selected_cases = [case for case in cases if case.case_id in chosen]
    planned_config = copy.deepcopy(config)
    planned_config.update(selection_scope="selected", case_ids=[item["case_id"] for item in selected],
                          source_run_id=None, domain=None, category=None, limit=max(1, len(selected)))
    def groups(key):
        result = []
        for name in sorted({item[key] for item in entries}):
            members = [item for item in entries if item[key] == name]
            counts = Counter(item["status"] for item in members)
            result.append({"name": name, "scenarios": len(members), "states": dict(counts),
                           "measured": counts["passed"] + counts["review"]})
        return result
    return {"coverage_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "focus": focus, "budget": budget, "scope_count": len(cases),
            "states": dict(Counter(item["status"] for item in entries)), "cases": ranked,
            "domains": groups("domain"), "families": groups("category"),
            "eligible_count": len(candidates), "selected_ids": planned_config["case_ids"],
            "config": planned_config, "plan": plan_cases(selected_cases),
            "identity": {"dataset_version": dataset, "grading_version": grading, "model_digest": digest,
                         "mode": config["mode"], "model": config["model"] if config["mode"] == "local" else "deterministic simulator"},
            "evidence_run_ids": sorted(used_runs), "excluded_reports": dict(excluded),
            "limitations": ["Coverage uses the latest saved observation per scenario under matching execution, defense, retrieval and grading settings; seed differences are allowed.",
                            "Local observations require matching recorded generation settings and the newest observed weight identity. This does not verify the currently installed model weights.",
                            "Unseen means no compatible saved observation, not that the scenario has never run under another configuration.",
                            "Completed cases in partial runs are retained. Runtime errors and unmeasured outcomes do not count as measured coverage.",
                            "The scenario budget bounds selected scenarios and paired responses; it is not a time or token guarantee. Planning makes no model calls.",
                            "Suggestions prioritize disclosure/attack findings, other failed tasks, errors, unmeasured cases, unseen cases and passes; equally ranked work is spread across domains and families.",
                            "Latest observations are a planning aid, not an aggregate benchmark or a reliability estimate."]}
