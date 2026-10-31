"""Descriptive repeated-trial reliability; no independence claim is implied."""

from collections import defaultdict
import copy
import json
import math
from statistics import NormalDist
from .datasets import dataset_identity
from .settings import validate_retrieval


def wilson_interval(successes, trials):
    """95% Wilson score interval for a declared binomial trial count."""
    if type(successes) is not int or type(trials) is not int or not 0 <= successes <= trials:
        raise ValueError("Successes and trials must be non-negative integer counts")
    if not trials:
        return None
    z = NormalDist().inv_cdf(0.975)
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)) / denominator
    return {"lower": max(0, centre - half), "upper": min(1, centre + half), "level": 0.95}


def _report_record(reports, run_id):
    record = reports.get(run_id)
    if isinstance(record, tuple):
        return record[1]
    return record


def summarize_campaign(campaign, reports):
    """Use the latest explicit attempt per logical trial, never partial rows."""
    latest = {}
    for job in campaign.get("jobs", []):
        latest[job.get("trial_id", job["id"])] = job
    groups = {}
    for job in latest.values():
        config = {**copy.deepcopy(campaign["base_config"]), **copy.deepcopy(job["config"])}
        generation = copy.deepcopy(config.get("generation") or {})
        seed = generation.pop("seed", None)
        identity = {"model": config.get("model"), "policy": config.get("policy"),
                    "mode": config.get("mode"), "profile": config.get("profile"),
                    "threshold": config.get("threshold"), "k": config.get("k"),
                    "generation": generation, "case_ids": config.get("case_ids", []),
                    "retrieval":validate_retrieval(config.get("retrieval"),config.get("profile","foundation"))}
        key = json.dumps(identity, sort_keys=True, allow_nan=False)
        group = groups.setdefault(key, {"configuration": identity, "planned_trials": 0, "completed_trials": 0,
                    "successful_trials": 0, "excluded_trials": [], "seeds": [], "per_case": defaultdict(list),
                    "run_ids": [], "model_digests": set()})
        group["planned_trials"] += 1
        group["seeds"].append(seed)
        report = _report_record(reports, job.get("run_id"))
        reason = None
        if job.get("status") != "completed":
            reason = f"Trial attempt is {job.get('status', 'unknown')}"
        elif not isinstance(report, dict):
            reason = "Saved report is unavailable"
        else:
            rows = report.get("results", [])
            expected = set(config.get("case_ids") or [])
            actual = [row.get("case_id") for row in rows]
            if report.get("status") != "completed" or len(rows) != report.get("planned_cases"):
                reason = "The saved report is incomplete"
            elif not expected or set(actual) != expected or len(actual) != len(expected):
                reason = "The saved scenario scope does not match the frozen campaign"
            elif any(row.get("error") for row in rows):
                reason = "The trial has runtime errors"
            elif any(type(row.get("secured_utility")) is not bool for row in rows):
                reason = "The trial lacks boolean task assessments"
            elif report.get("mode") != config.get("mode") or (config.get("mode") == "local" and report.get("model") != config.get("model")):
                reason = "The recorded execution identity does not match the trial"
            elif report.get("configuration", {}).get("generation") != config.get("generation"):
                reason = "The recorded generation settings do not match the trial"
            elif any(report.get("configuration", {}).get(recorded) != config.get(requested) for recorded,requested in (
                    ("profile","profile"),("policy","policy"),("trust_threshold","threshold"),("retrieval_k","k"))):
                reason = "The recorded evaluation settings do not match the frozen trial"
            elif (report.get("configuration", {}).get("dataset_version"), report.get("configuration", {}).get("grading_version")) != dataset_identity(config["profile"],config.get("case_definitions")):
                reason = "The saved dataset or grading identity differs from the frozen trial"
            elif report.get("configuration", {}).get("case_definitions") != config.get("case_definitions"):
                reason = "The saved authored definitions differ from the frozen trial"
            elif validate_retrieval(report.get("configuration",{}).get("retrieval_settings"),config["profile"])!=identity["retrieval"]:
                reason = "The recorded retrieval configuration differs from the frozen trial"
        if reason:
            group["excluded_trials"].append({"job_id": job["id"], "run_id": job.get("run_id"), "seed": seed, "reason": reason})
            continue
        group["completed_trials"] += 1
        group["successful_trials"] += int(all(row["secured_utility"] for row in report["results"]))
        group["run_ids"].append(job["run_id"])
        digest = (report.get("performance") or {}).get("model_digest")
        if digest:
            group["model_digests"].add(digest)
        for row in report["results"]:
            group["per_case"][row["case_id"]].append(row)
    result = []
    for group in groups.values():
        complete, passed = group["completed_trials"], group["successful_trials"]
        case_rows = []
        for case_id, observations in sorted(group.pop("per_case").items()):
            successes = sum(row["secured_utility"] for row in observations)
            attack_rows = [row for row in observations if row.get("category") != "baseline"]
            matches = sum(bool(row.get("secured_success")) for row in attack_rows)
            case_rows.append({"case_id": case_id, "observed_trials": len(observations), "task_passes": successes,
                              "task_failures": len(observations) - successes, "task_pass_rate": successes / len(observations),
                              "task_interval": wilson_interval(successes, len(observations)),
                              "attack_observations": len(attack_rows), "attack_matches": matches,
                              "attack_match_rate": matches / len(attack_rows) if attack_rows else None,
                              "attack_interval": wilson_interval(matches, len(attack_rows)) if attack_rows else None})
        group.update(task_trial_rate=passed / complete if complete else None,
                     task_trial_interval=wilson_interval(passed, complete), per_case=case_rows,
                     model_digests=sorted(group["model_digests"]), identity_changed=len(group["model_digests"]) > 1)
        result.append(group)
    return {"reliability_version": 1, "campaign_id": campaign["id"], "groups": result,
            "logical_trials": len(latest), "attempts": len(campaign.get("jobs", [])),
            "superseded_attempts": len(campaign.get("jobs", [])) - len(latest),
            "limitations": ["A trial succeeds only when every frozen scenario has a successful secured task assessment and no runtime error.",
                            "Only the latest explicit attempt of each logical trial is considered; superseded attempts remain saved but are not additional trials.",
                            "Partial, cancelled, interrupted, missing and runtime-error trials are excluded from success denominators and listed separately.",
                            "Wilson intervals describe observed outcomes. Changing seeds alone does not establish statistically independent samples or generalization to new scenarios.",
                            "Model weight changes are flagged within a configuration group; do not interpret mixed-identity estimates as a controlled benchmark.",
                            "Demonstration-mode repetitions describe a deterministic simulator, not a language model."]}
