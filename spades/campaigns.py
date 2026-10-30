"""Durable, explicitly started campaigns over the existing single-run manager."""

import copy
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

from .reliability import summarize_campaign
from .settings import validate_generation, validate_model
from .suites import plan_cases

ACTIVE = {"starting", "running", "stopping"}
TERMINAL = {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class CampaignManager:
    def __init__(self, run_manager, poll_interval=0.2):
        self.manager = run_manager
        self.output = Path(run_manager.output) / "campaigns"
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.poll_interval = poll_interval
        self.records = {}
        self.thread = None
        self.closed = threading.Event()
        for path in self.output.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or not re.fullmatch(r"[a-f0-9]{32}", record.get("id", "")) or not isinstance(record.get("jobs"), list):
                    continue
                changed = record.get("status") in ("queued", "running", "stopping")
                if changed:
                    record["status"] = "interrupted"
                    for job in record["jobs"]:
                        if job.get("status") in ACTIVE:
                            job.update(status="interrupted", error="The campaign process stopped. Review its saved report before explicitly retrying this trial.", finished_at=_now())
                self.records[record["id"]] = record
                if changed:
                    self._save(record)
            except (OSError, ValueError, TypeError, KeyError):
                continue

    def _save(self, record):
        record["updated_at"] = _now()
        path = self.output / (record["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(path)

    def _record(self, campaign_id):
        if not isinstance(campaign_id, str) or not re.fullmatch(r"[a-f0-9]{32}", campaign_id) or campaign_id not in self.records:
            raise ValueError("Saved campaign not found")
        return self.records[campaign_id]

    def _plan(self, body):
        required = {"name", "base_config", "models", "policies", "seeds"}
        optional = {"thresholds", "retrieval_depths", "temperatures"}
        if not isinstance(body, dict) or not required <= set(body) or set(body) - required - optional:
            raise ValueError("Expected campaign name, base configuration, models, policies, seeds and optional parameter sweeps")
        name = body["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Campaign names must contain 1–100 characters")
        models, policies, seeds = (body[key] for key in ("models", "policies", "seeds"))
        if not isinstance(models, list) or not 1 <= len(models) <= 10 or not all(isinstance(model, str) for model in models) or len(set(models)) != len(models):
            raise ValueError("Choose 1–10 unique local model names")
        models = [validate_model(model) for model in models]
        if not isinstance(policies, list) or not 1 <= len(policies) <= 2 or not all(policy in ("strict", "sanitize") for policy in policies) or len(set(policies)) != len(policies):
            raise ValueError("Choose unique strict/sanitize defense policies")
        if not isinstance(seeds, list) or not 1 <= len(seeds) <= 20 or not all(type(seed) is int and 0 <= seed <= 2147483647 for seed in seeds) or len(set(seeds)) != len(seeds):
            raise ValueError("Choose 1–20 unique integer seeds from 0 to 2147483647")
        axes = {}
        for key, low, high, integer in (("thresholds", 0, 1, False), ("retrieval_depths", 1, 50, True), ("temperatures", 0, 2, False)):
            if key not in body:
                continue
            values = body[key]
            if (not isinstance(values, list) or not 1 <= len(values) <= 10
                    or any(type(value) not in ((int,) if integer else (int, float))
                           or not low <= value <= high or not math.isfinite(value) for value in values)
                    or len(set(values)) != len(values)):
                raise ValueError(f"{key} requires 1–10 unique {'integer ' if integer else ''}values from {low} to {high}")
            axes[key] = list(values)
        count = len(models) * len(policies) * len(seeds)
        for values in axes.values():
            count *= len(values)
        if count > 100:
            raise ValueError(f"This matrix contains {count} trial jobs; a campaign supports at most 100")
        config, cases, _ = self.manager.resolve_selection(body["base_config"])
        if not cases:
            raise ValueError("Choose at least one scenario for a campaign")
        frozen = copy.deepcopy(config)
        frozen.update(case_ids=[case.case_id for case in cases], selection_scope="selected", category=None,
                      domain=None, source_run_id=None, limit=len(cases))
        axes.setdefault("thresholds", [frozen["threshold"]])
        axes.setdefault("retrieval_depths", [frozen["k"]])
        axes.setdefault("temperatures", [frozen["generation"]["temperature"]])
        configurations = []
        for model, policy, threshold, depth, temperature, seed in itertools.product(
                models, policies, axes["thresholds"], axes["retrieval_depths"], axes["temperatures"], seeds):
            generation = validate_generation({**frozen["generation"], "seed": seed, "temperature": temperature}, frozen["profile"])
            configurations.append({"model": model, "policy": policy, "threshold": threshold, "k": depth, "generation": generation})
        return name.strip(), frozen, cases, axes, configurations

    def preview(self, body):
        name, frozen, cases, axes, configurations = self._plan(body)
        return {"name": name, "base_config": frozen, "axes": axes, "trial_jobs": len(configurations),
                "scenario_evaluations": len(configurations) * len(cases),
                "model_responses": len(configurations) * len(cases) * 2,
                "scenario_plan": plan_cases(cases), "configurations": configurations,
                "generation_applied": frozen["mode"] == "local",
                "note": "Preview validates the full matrix and freezes this snapshot only. Creation resolves the submitted selection again; no inference or queue mutation occurs during preview."}

    def create(self, body):
        name, frozen, cases, axes, configurations = self._plan(body)
        jobs = []
        for config in configurations:
            job_id = uuid.uuid4().hex
            jobs.append({"id": job_id, "trial_id": job_id, "attempt": 1, "retry_of": None,
                         "config": config,
                         "status": "queued", "run_id": None, "cancel_requested": False,
                         "created_at": _now(), "started_at": None, "finished_at": None, "error": None})
        record = {"campaign_version": 1, "id": uuid.uuid4().hex, "name": name, "status": "queued", "axes": axes,
                  "created_at": _now(), "updated_at": _now(), "base_config": frozen, "jobs": jobs,
                  "cancel_requested": False, "scenario_count": len(cases), "original_job_count": len(jobs)}
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError("Campaign scheduler is closed")
            if len(self.records) >= 200:
                raise ValueError("The workspace supports up to 200 saved campaigns")
            self.records[record["id"]] = record
            self._save(record)
            self._ensure_scheduler()
        return self.get(record["id"])

    def list(self):
        with self.lock:
            result = []
            for record in self.records.values():
                counts = {}
                for job in record["jobs"]:
                    counts[job["status"]] = counts.get(job["status"], 0) + 1
                result.append({key: copy.deepcopy(record[key]) for key in ("id", "name", "status", "created_at", "updated_at", "scenario_count", "original_job_count")})
                result[-1].update(job_counts=counts, attempts=len(record["jobs"]))
            return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def get(self, campaign_id):
        with self.lock:
            result = copy.deepcopy(self._record(campaign_id))
        result["reliability"] = summarize_campaign(result, self.manager.reports())
        return result

    def _ensure_scheduler(self):
        if self.closed.is_set():
            raise RuntimeError("Campaign scheduler is closed")
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._schedule, daemon=True)
            self.thread.start()

    def _job(self, record, job_id):
        job = next((item for item in record["jobs"] if item["id"] == job_id), None)
        if job is None:
            raise ValueError("Campaign trial job not found")
        return job

    def cancel_job(self, campaign_id, job_id):
        run_id = None
        with self.lock:
            record = self._record(campaign_id)
            job = self._job(record, job_id)
            if job["status"] in TERMINAL:
                raise ValueError("This trial is already finished")
            job["cancel_requested"] = True
            if job["status"] == "queued":
                job.update(status="cancelled", finished_at=_now())
            else:
                job["status"] = "stopping"
                run_id = job.get("run_id")
            self._refresh_status(record)
            self._save(record)
        if run_id:
            self._stop_own_run(run_id)
        return self.get(campaign_id)

    def cancel_campaign(self, campaign_id):
        run_ids = []
        with self.lock:
            record = self._record(campaign_id)
            record["cancel_requested"] = True
            for job in record["jobs"]:
                if job["status"] not in TERMINAL:
                    job["cancel_requested"] = True
                    if job["status"] == "queued":
                        job.update(status="cancelled", finished_at=_now())
                    else:
                        job["status"] = "stopping"
                        if job.get("run_id"):
                            run_ids.append(job["run_id"])
            self._refresh_status(record)
            self._save(record)
        for run_id in run_ids:
            self._stop_own_run(run_id)
        return self.get(campaign_id)

    def resume(self, campaign_id):
        with self.lock:
            record = self._record(campaign_id)
            if not any(job["status"] == "queued" for job in record["jobs"]):
                raise ValueError("No queued trials remain; interrupted or failed trials need an explicit retry")
            if record.get("cancel_requested"):
                raise ValueError("Cancelled campaigns require explicit retries of individual trials")
            record["status"] = "queued"
            self._save(record)
            self._ensure_scheduler()
        return self.get(campaign_id)

    def retry_job(self, campaign_id, job_id):
        with self.lock:
            record = self._record(campaign_id)
            job = self._job(record, job_id)
            if job["status"] not in ("failed", "cancelled", "interrupted", "completed_with_errors"):
                raise ValueError("Only failed, cancelled, interrupted or runtime-error trials can be retried")
            latest = [item for item in record["jobs"] if item["trial_id"] == job["trial_id"]][-1]
            if latest["id"] != job["id"]:
                raise ValueError("Retry the latest attempt of this logical trial")
            if any(item["trial_id"] == job["trial_id"] and item["status"] not in TERMINAL for item in record["jobs"]):
                raise ValueError("This logical trial already has an active or queued retry")
            if len(record["jobs"]) >= 300:
                raise ValueError("A campaign supports at most 300 attempts including retries")
            attempt = {**copy.deepcopy(job), "id": uuid.uuid4().hex, "retry_of": job["id"],
                       "attempt": max(item["attempt"] for item in record["jobs"] if item["trial_id"] == job["trial_id"]) + 1,
                       "status": "queued", "run_id": None, "cancel_requested": False,
                       "created_at": _now(), "started_at": None, "finished_at": None, "error": None}
            record["jobs"].append(attempt)
            record.update(cancel_requested=False, status="queued")
            self._save(record)
            self._ensure_scheduler()
        return self.get(campaign_id)

    def _stop_own_run(self, run_id):
        active = self.manager.snapshot()
        if active and active.get("run_id") == run_id and active.get("status") in ("running", "stopping"):
            try:
                self.manager.stop()
            except ValueError:
                pass

    def _refresh_status(self, record):
        states = [job["status"] for job in record["jobs"]]
        if any(state in ACTIVE for state in states):
            record["status"] = "stopping" if record.get("cancel_requested") else "running"
        elif any(state == "queued" for state in states):
            record["status"] = "queued"
        elif record.get("cancel_requested"):
            record["status"] = "cancelled"
        elif any(state in ("failed", "completed_with_errors", "interrupted") for state in states):
            record["status"] = "completed_with_errors"
        else:
            record["status"] = "completed"

    def _schedule(self):
        while not self.closed.is_set():
            with self.lock:
                candidate = next(((record, job) for record in sorted(self.records.values(), key=lambda item: item["created_at"])
                                  if record["status"] in ("queued", "running") and not record.get("cancel_requested")
                                  for job in record["jobs"] if job["status"] == "queued"), None)
                if candidate is None:
                    self.thread = None
                    return
                record, job = candidate
            active = self.manager.snapshot()
            if active and active.get("status") in ("running", "stopping"):
                self.closed.wait(self.poll_interval)
                continue
            with self.lock:
                if job["status"] != "queued" or record.get("cancel_requested"):
                    continue
                job.update(status="starting", started_at=_now())
                record["status"] = "running"
                self._save(record)
                config = {**copy.deepcopy(record["base_config"]), **copy.deepcopy(job["config"])}
            try:
                result = self.manager.start(config)
            except Exception as exc:
                active = self.manager.snapshot()
                with self.lock:
                    if isinstance(exc, RuntimeError) and active and active.get("status") in ("running", "stopping") and not job.get("cancel_requested"):
                        job.update(status="queued", started_at=None)
                    else:
                        job.update(status="cancelled" if job.get("cancel_requested") else "failed", error=f"{type(exc).__name__}: {exc}", finished_at=_now())
                    self._refresh_status(record)
                    self._save(record)
                self.closed.wait(self.poll_interval)
                continue
            with self.lock:
                job["run_id"] = result["run_id"]
                job["status"] = "stopping" if job.get("cancel_requested") else "running"
                self._save(record)
            if self.closed.is_set():
                self._stop_own_run(job["run_id"])
                with self.lock:
                    job.update(status="interrupted",error="The scheduler closed while this trial was starting. Review its saved evidence before retrying.",finished_at=_now())
                    record["status"]="interrupted"
                    self._save(record)
                return
            if job.get("cancel_requested"):
                self._stop_own_run(job["run_id"])
            while not self.closed.is_set():
                active = self.manager.snapshot()
                if active and active.get("run_id") == job["run_id"]:
                    if active.get("status") in ("running", "stopping"):
                        self.closed.wait(self.poll_interval)
                        continue
                    state = active.get("status", "failed")
                    error = active.get("error")
                else:
                    saved = self.manager.reports().get(job["run_id"])
                    report = saved[1] if saved else None
                    state = (report or {}).get("status", "interrupted")
                    if state == "completed" and (report or {}).get("metrics", {}).get("error_cases"):
                        state = "completed_with_errors"
                    error = "The runner no longer owns this trial" if state not in TERMINAL else None
                    if state not in TERMINAL:
                        state = "interrupted"
                with self.lock:
                    job.update(status="cancelled" if job.get("cancel_requested") else state, error=error, finished_at=_now())
                    self._refresh_status(record)
                    self._save(record)
                break

    def close(self):
        """Stop scheduling; do not cancel manual work or silently retry on restart."""
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)
