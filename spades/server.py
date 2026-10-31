"""Loopback-only dashboard API and one bounded background experiment worker."""

from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
import uuid

from .corpus import build_suite
from .evaluation import run_suite, select_cases
from .report import report_csv, write_report, write_checkpoint
from .runtime import DEFAULT_MODEL, doctor
from .complex_corpus import PROFILES
from .comparison import compare_cases
from .analysis import analyze_report
from .suites import validate_suite, export_suite, plan_cases, compare_suite_revisions
from .datasets import dataset_identity
from .settings import validate_generation, validate_model, validate_retrieval
from .quality import validate_policy, assess_report
from .quality_history import compare_policies, acceptance_history

ASSETS = Path(__file__).parent / "web"


def validate_config(config):
    if not isinstance(config, dict) or set(config) - {"mode", "threshold", "k", "limit", "category", "policy", "profile", "domain", "case_ids", "concurrency", "selection_scope", "source_run_id", "model", "generation", "case_definitions", "retrieval"}:
        raise ValueError("Expected known experiment options")
    result = {"mode": "demo", "threshold": 0.7, "k": 5, "limit": 6, "category": None, "policy": "strict", "profile": "foundation",
              "domain": None, "case_ids": None, "concurrency": 2, "selection_scope": "sample", "source_run_id": None,
              "model": DEFAULT_MODEL, "generation": None, "case_definitions":None, "retrieval":None}
    result.update(config)
    if result["category"] == "":
        result["category"] = None
    if result["domain"] == "":
        result["domain"] = None
    if result["selection_scope"] not in ("sample", "all", "selected", "remaining", "errors", "failed", "attacks"):
        raise ValueError("Unknown scenario selection")
    if type(result["concurrency"]) is not int or not 1 <= result["concurrency"] <= 4:
        raise ValueError("Concurrent scenarios must be an integer from 1 to 4")
    if result["domain"] is not None and not isinstance(result["domain"], str):
        raise ValueError("Domain must be a string")
    if result["source_run_id"] is not None and (not isinstance(result["source_run_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", result["source_run_id"])):
        raise ValueError("A saved source run ID is required")
    if result["mode"] not in ("demo", "local") or result["policy"] not in ("strict", "sanitize"):
        raise ValueError("Unknown execution mode or defense policy")
    if type(result["threshold"]) not in (float, int) or not 0 <= result["threshold"] <= 1:
        raise ValueError("Trust threshold must be 0–1")
    if result["profile"] not in ("foundation", "complex"):
        raise ValueError("Unknown scenario profile")
    result["model"] = validate_model(result["model"])
    result["generation"] = validate_generation(result["generation"], result["profile"])
    result["retrieval"] = validate_retrieval(result["retrieval"],result["profile"])
    if result["case_definitions"] is not None:
        from .authoring import validate_definition
        if result["profile"] != "complex" or not isinstance(result["case_definitions"],list) or not 1 <= len(result["case_definitions"]) <= 100:
            raise ValueError("Custom evaluations require 1–100 enterprise scenario definitions")
        result["case_definitions"]=[validate_definition(definition) for definition in result["case_definitions"]]
    for key, maximum in (("k", 50), ("limit", 500)):
        if type(result[key]) is not int or not 1 <= result[key] <= maximum:
            raise ValueError(f"{key} must be an integer from 1 to {maximum}")
    if result["category"] is not None and not isinstance(result["category"], str):
        raise ValueError("Category must be a string")
    selected = result["case_ids"] if result["selection_scope"] == "selected" else None
    if result["selection_scope"] == "selected" and selected is None:
        raise ValueError("Choose at least one scenario")
    if result["case_ids"] is not None and result["selection_scope"] != "selected":
        raise ValueError("Scenario IDs require Selected scenarios mode")
    select_cases(result["category"], result["limit"], result["profile"], result["domain"], selected, case_definitions=result["case_definitions"])
    if result["selection_scope"] in ("remaining", "errors", "failed", "attacks") and not result["source_run_id"]:
        raise ValueError("Choose the previous experiment")
    return result


BUILTIN_PRESETS = [
    {"id": "quick-demo", "name": "Quick demonstration", "builtin": True,
     "config": validate_config({"mode": "demo", "limit": 6})},
    {"id": "local-sanitize", "name": "Local model · sanitize", "builtin": True,
     "config": validate_config({"mode": "local", "policy": "sanitize", "profile": "complex", "k": 20, "limit": 6})},
    {"id": "local-strict", "name": "Local model · strict baseline", "builtin": True,
     "config": validate_config({"mode": "local", "profile": "complex", "k": 20, "limit": 6})},
]


class RunManager:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.active = None
        self._campaigns = None
        self._replays = None
        self.replay_busy = False

    @property
    def replays(self):
        from .replay import ReplayManager
        with self.lock:
            if self._replays is None:self._replays=ReplayManager(self)
            return self._replays

    @property
    def campaigns(self):
        from .campaigns import CampaignManager
        with self.lock:
            if self._campaigns is None:
                self._campaigns = CampaignManager(self)
            return self._campaigns

    def snapshot(self):
        with self.lock:
            return dict(self.active) if self.active else None

    def _read_workspace(self):
        path = self.output / "workspace.json"
        if not path.exists():
            return {"presets": [], "bookmarks": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or not isinstance(data.get("presets"), list)
                or not isinstance(data.get("bookmarks"), list) or not isinstance(data.get("experiments", {}), dict)
                or not isinstance(data.get("suites", []), list) or not isinstance(data.get("quality_policies", []), list)
                or not isinstance(data.get("custom_scenarios", []), list) or not isinstance(data.get("investigations", []),list)
                or not isinstance(data.get("findings",[]),list)):
            raise ValueError("Workspace data is invalid; restore output/workspace.json from a backup")
        return data

    def _write_workspace(self, data):
        temporary = self.output / "workspace.json.tmp"
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.output / "workspace.json")

    def workspace(self):
        with self.lock:
            data = self._read_workspace()
            return {"presets": BUILTIN_PRESETS + data["presets"], "bookmarks": data["bookmarks"],
                    "experiments": data.get("experiments", {}), "suites": data.get("suites", []),
                    "quality_policy": data.get("quality_policy", {"policy":validate_policy(), "revision":0, "updated_at":None}),
                    "quality_policies":data.get("quality_policies",[]), "custom_scenarios":data.get("custom_scenarios",[]),
                    "investigations":data.get("investigations",[]),"findings":data.get("findings",[])}

    def save_finding(self,body,update=False):
        from .findings import create_finding, update_finding
        with self.lock:
            data=self._read_workspace()
            (update_finding if update else create_finding)(data,body,self.reports())
            self._write_workspace(data)
            return self.workspace()

    def save_investigation(self, body):
        from .investigations import validate_filters
        if not isinstance(body,dict) or not {"name","filters"}<=set(body) or set(body)-{"name","filters","id","revision"}:
            raise ValueError("Expected view name, filters and optional saved-view ID/revision")
        name=body["name"]
        if not isinstance(name,str) or not 1<=len(name.strip())<=100:
            raise ValueError("Investigation names must contain 1–100 characters")
        filters=validate_filters(body["filters"])
        view_id=body.get("id")
        if ("id" in body)!=("revision" in body) or ("id" in body and (
                not isinstance(view_id,str) or not re.fullmatch(r"[a-f0-9]{32}",view_id)
                or type(body["revision"]) is not int or body["revision"]<1)):
            raise ValueError("View updates require a valid saved ID and revision")
        with self.lock:
            data=self._read_workspace();views=data.setdefault("investigations",[])
            existing=next((item for item in views if item["id"]==view_id),None)
            if view_id and existing is None:raise ValueError("Saved investigation not found")
            if existing and existing["revision"]!=body["revision"]:raise RuntimeError("This view changed. Reopen it before saving.")
            if any(item["name"].casefold()==name.strip().casefold() and item["id"]!=view_id for item in views):raise ValueError("A saved investigation already uses this name")
            if not existing and len(views)>=100:raise ValueError("The workspace supports up to 100 investigation views")
            now=datetime.now(timezone.utc).isoformat()
            record={"id":view_id or uuid.uuid4().hex,"name":name.strip(),"filters":filters,
                    "revision":existing["revision"]+1 if existing else 1,"created_at":existing["created_at"] if existing else now,"updated_at":now}
            data["investigations"]=[item for item in views if item["id"]!=view_id]+[record]
            self._write_workspace(data)
            return self.workspace()

    def save_custom_scenario(self, body):
        from .authoring import save_scenario
        with self.lock:
            data=self._read_workspace()
            save_scenario(data,body)
            self._write_workspace(data)
            return self.workspace()

    def archive_quality_policy(self, body):
        if not isinstance(body,dict) or set(body)!={"policy"}:
            raise ValueError("Expected a named acceptance policy")
        policy=validate_policy(body["policy"])
        with self.lock:
            data=self._read_workspace()
            records=data.setdefault("quality_policies",[])
            if len(records)>=100:
                raise ValueError("The workspace supports up to 100 named policies")
            if any(record["policy"]["name"].casefold()==policy["name"].casefold() for record in records):
                raise ValueError("A named policy already uses this name; choose a new snapshot name")
            records.append({"id":uuid.uuid4().hex,"policy":policy,"created_at":datetime.now(timezone.utc).isoformat()})
            self._write_workspace(data)
            return self.workspace()

    def save_quality_policy(self, body):
        if not isinstance(body, dict) or set(body) != {"policy", "revision"}:
            raise ValueError("Expected quality policy and its current revision")
        policy = validate_policy(body["policy"])
        if type(body["revision"]) is not int or body["revision"] < 0:
            raise ValueError("Policy revision must be a non-negative integer")
        with self.lock:
            data = self._read_workspace()
            previous = data.get("quality_policy", {"revision":0})
            if previous["revision"] != body["revision"]:
                raise RuntimeError("The acceptance policy changed. Refresh before saving your edits.")
            data["quality_policy"] = {"policy":policy, "revision":body["revision"]+1,
                                       "updated_at":datetime.now(timezone.utc).isoformat()}
            self._write_workspace(data)
            return self.workspace()

    def save_suite(self, body, manifest=False, restored_from=None):
        validated = validate_suite(body, manifest=manifest)
        suite_id = body.get("id") if not manifest else None
        if not manifest and "id" in body and (not isinstance(suite_id, str) or not re.fullmatch(r"[a-f0-9]{32}", suite_id)):
            raise ValueError("Invalid suite ID")
        with self.lock:
            data = self._read_workspace()
            suites = data.setdefault("suites", [])
            existing = next((suite for suite in suites if suite["id"] == suite_id), None)
            if suite_id and not existing:
                raise ValueError("Saved suite not found")
            if existing and existing["revision"] != body["revision"]:
                raise RuntimeError("This suite changed since it was opened. Refresh and review the latest revision before saving.")
            if any(suite["name"].casefold() == validated["name"].casefold() and suite["id"] != suite_id for suite in suites):
                raise ValueError("A suite with this name already exists; choose a different name")
            if not existing and len(suites) >= 200:
                raise ValueError("The workspace supports up to 200 test suites")
            now = datetime.now(timezone.utc).isoformat()
            history=list(existing.get("history",[])) if existing else []
            if existing:
                if len(history)>=100:
                    raise ValueError("This suite has 100 archived revisions; export or clone it before another edit")
                history.append({key:value for key,value in existing.items() if key!="history"})
            record = {**validated, "id": suite_id or uuid.uuid4().hex,
                      "revision": existing["revision"] + 1 if existing else 1,
                      "created_at": existing["created_at"] if existing else now, "updated_at": now,"history":history}
            if restored_from is not None:
                record["restored_from_revision"]=restored_from
            data["suites"] = [suite for suite in suites if suite["id"] != suite_id] + [record]
            self._write_workspace(data)
            return self.workspace()

    def suite_history(self, suite_id):
        if not isinstance(suite_id,str) or not re.fullmatch(r"[a-f0-9]{32}",suite_id):
            raise ValueError("Invalid suite ID")
        with self.lock:
            suite=next((item for item in self._read_workspace().get("suites",[]) if item["id"]==suite_id),None)
            if suite is None:
                raise ValueError("Saved suite not found")
            return {"current":{key:value for key,value in suite.items() if key!="history"},"history":suite.get("history",[])}

    def restore_suite(self, body):
        if not isinstance(body,dict) or set(body)!={"id","revision","expected_revision"} or any(type(body[key]) is not int or body[key]<1 for key in ("revision","expected_revision")):
            raise ValueError("Expected suite ID, historical revision and current expected revision")
        with self.lock:
            revisions=self.suite_history(body["id"])
            current=revisions["current"]
            if current["revision"]!=body["expected_revision"]:
                raise RuntimeError("The suite changed. Reload its history before restoring.")
            old=next((item for item in revisions["history"] if item["revision"]==body["revision"]),None)
            if old is None:
                raise ValueError("That historical suite definition is unavailable")
            validated=validate_suite(export_suite(old),manifest=True)
            fields={key:validated[key] for key in ("name","description","profile","case_ids")}
            if validated.get("case_definitions") is not None:
                fields["case_definitions"]=validated["case_definitions"]
            return self.save_suite({**fields,"id":body["id"],"revision":current["revision"]},restored_from=old["revision"])

    def save_experiment(self, body):
        if not isinstance(body, dict) or set(body) != {"run_id", "name", "note", "pinned"}:
            raise ValueError("Expected run ID, name, note and pinned state")
        run_id, name, note, pinned = (body[key] for key in ("run_id", "name", "note", "pinned"))
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("A saved report ID is required")
        if not isinstance(name, str) or len(name.strip()) > 100:
            raise ValueError("Experiment names must contain at most 100 characters")
        if not isinstance(note, str) or len(note) > 4000 or type(pinned) is not bool:
            raise ValueError("Notes must contain at most 4000 characters and pinned must be a boolean")
        with self.lock:
            if run_id not in self.reports():
                raise ValueError("Saved experiment not found")
            data = self._read_workspace()
            metadata = data.setdefault("experiments", {})
            if run_id not in metadata and len(metadata) >= 2000:
                raise ValueError("The workspace supports up to 2000 experiment annotations")
            metadata[run_id] = {"name": name.strip(), "note": note, "pinned": pinned,
                                "updated_at": datetime.now(timezone.utc).isoformat()}
            self._write_workspace(data)
            return self.workspace()

    def save_preset(self, body):
        if not isinstance(body, dict) or set(body) != {"name", "config"}:
            raise ValueError("A preset name and configuration are required")
        name = body["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError("Preset names must contain 1–60 characters")
        config = validate_config(body["config"])
        with self.lock:
            data = self._read_workspace()
            if len(data["presets"]) >= 100:
                raise ValueError("The workspace supports up to 100 custom presets")
            if any(p["name"].casefold() == name.strip().casefold() for p in data["presets"] + BUILTIN_PRESETS):
                raise ValueError("A preset with this name already exists")
            data["presets"].append({"id": uuid.uuid4().hex, "name": name.strip(), "config": config, "builtin": False})
            self._write_workspace(data)
            return self.workspace()

    def remove_preset(self, body):
        if not isinstance(body, dict) or set(body) != {"id"} or not isinstance(body["id"], str):
            raise ValueError("A custom preset ID is required")
        with self.lock:
            data = self._read_workspace()
            if not any(p["id"] == body["id"] for p in data["presets"]):
                raise ValueError("Custom preset not found; built-in presets cannot be removed")
            data["presets"] = [p for p in data["presets"] if p["id"] != body["id"]]
            self._write_workspace(data)
            return self.workspace()

    def save_bookmark(self, body):
        if not isinstance(body, dict) or set(body) - {"run_id", "case_id", "saved", "note"}:
            raise ValueError("Unknown bookmark option")
        run_id, case_id, saved, note = (body.get(k) for k in ("run_id", "case_id", "saved", "note"))
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("A saved report ID is required")
        if not isinstance(case_id, str) or len(case_id) > 200 or type(saved) is not bool:
            raise ValueError("A case ID and saved state are required")
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ValueError("Bookmark notes must contain at most 2000 characters")
        with self.lock:
            data = self._read_workspace()
            existing = next((b for b in data["bookmarks"] if b["run_id"] == run_id and b["case_id"] == case_id), None)
            if saved:
                record = self.reports().get(run_id)
                row = next((r for r in record[1]["results"] if r["case_id"] == case_id), None) if record else None
                if row is None:
                    raise ValueError("The case does not belong to this saved report")
                if not existing and len(data["bookmarks"]) >= 1000:
                    raise ValueError("The workspace supports up to 1000 bookmarks")
                bookmark = {"run_id": run_id, "case_id": case_id, "category": row["category"],
                            "query": row["query"], "note": note if note is not None else (existing or {}).get("note", ""),
                            "updated_at": datetime.now(timezone.utc).isoformat()}
                data["bookmarks"] = [b for b in data["bookmarks"] if not (b["run_id"] == run_id and b["case_id"] == case_id)] + [bookmark]
            else:
                data["bookmarks"] = [b for b in data["bookmarks"] if not (b["run_id"] == run_id and b["case_id"] == case_id)]
            self._write_workspace(data)
            return self.workspace()

    def reports(self):
        paths = [self.output / "report.json"]
        paths += list(self.output.glob("*/report.json"))
        paths += list(self.output.glob("runs/*/report.json"))
        records = {}
        for path in paths:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                if re.fullmatch(r"[a-f0-9]{32}", data.get("run_id", "")):
                    active = self.snapshot()
                    if data.get("status") == "running" and (not active or active["run_id"] != data["run_id"] or active["status"] not in ("running", "stopping")):
                        data["status"] = "interrupted"
                    records[data["run_id"]] = (path, data)
            except (OSError, ValueError, TypeError):
                continue
        return records

    def history(self):
        reports = [{key: report.get(key) for key in (
            "run_id", "created_at", "finished_at", "mode", "model", "status", "metrics", "configuration", "planned_cases", "performance")}
                   for _, report in self.reports().values()]
        return sorted(reports, key=lambda report: report["created_at"], reverse=True)

    def resolve_selection(self, raw_config):
        config = validate_config(raw_config)
        scope = config["selection_scope"]
        excluded, source = [], None
        ids = config["case_ids"]
        if scope in ("remaining", "errors", "failed", "attacks"):
            records = self.reports()
            record = records.get(config["source_run_id"])
            if not record:
                raise ValueError("Previous experiment not found")
            source = record[1]
            prior = source["configuration"]
            compatible = (source["mode"] == config["mode"] and prior.get("profile", "foundation") == config["profile"]
                          and prior["trust_threshold"] == config["threshold"] and prior["retrieval_k"] == config["k"]
                          and prior.get("policy", "strict") == config["policy"]
                          and (config["mode"] != "local" or (source["model"] == config["model"]
                               and validate_generation(prior.get("generation"), config["profile"]) == config["generation"])))
            dataset, grading = dataset_identity(config["profile"],config["case_definitions"])
            if not compatible or prior.get("dataset_version") != dataset or prior.get("grading_version", grading) != grading:
                raise ValueError("Previous experiment must use the same profile, mode, model, generation settings, trust, retrieval depth and policy")
            # Continuations form a durable lineage. Reopening the original
            # partial run also skips cases finished by its later child batches.
            family, completed = {source["run_id"]}, set()
            changed = True
            while changed:
                changed = False
                for _, candidate in records.values():
                    c = candidate["configuration"]
                    if candidate["run_id"] not in family and c.get("source_run_id") in family:
                        same = (candidate["mode"] == source["mode"] and candidate["model"] == source["model"]
                                and c.get("profile", "foundation") == config["profile"] and c.get("dataset_version") == dataset
                                and c.get("grading_version", grading) == grading and c["trust_threshold"] == config["threshold"]
                                and c["retrieval_k"] == config["k"] and c.get("policy", "strict") == config["policy"]
                                and (config["mode"] != "local" or validate_generation(c.get("generation"), config["profile"]) == config["generation"]))
                        if same:
                            family.add(candidate["run_id"])
                            changed = True
            for _, candidate in records.values():
                if candidate["run_id"] in family:
                    completed.update(r["case_id"] for r in candidate["results"] if not r["error"])
                    completed.update(candidate["configuration"].get("previous_case_ids", []))
            if scope == "remaining":
                excluded = sorted(completed)
            elif scope == "errors":
                ids = [r["case_id"] for r in source["results"] if r["error"] and r["case_id"] not in completed]
                if not ids:
                    raise ValueError("The previous experiment has no runtime errors to retry")
            else:
                # Assessment retests intentionally revisit completed cases from
                # this exact report; they are not continuation deduplication.
                ids = [r["case_id"] for r in source["results"] if not r["error"] and
                       (not r["secured_utility"] if scope == "failed" else
                        r["category"] != "baseline" and r["secured_success"])]
                if not ids:
                    label = "failed secured tasks" if scope == "failed" else "matched secured attack objectives"
                    raise ValueError(f"The previous experiment has no {label} to retest")
        maximum = None if scope in ("all", "selected") else config["limit"]
        # Exact-ID selection preserves all IDs, so apply the batch bound after
        # domain/family filtering for report-derived retest scopes.
        if scope in ("errors", "failed", "attacks"):
            matching = {case.case_id for case in select_cases(config["category"], None, config["profile"], config["domain"],case_definitions=config["case_definitions"])}
            ids = [case_id for case_id in ids if case_id in matching]
            if not ids:
                raise ValueError("No retest scenarios match this domain or family")
            suite = select_cases(profile=config["profile"], case_ids=ids,case_definitions=config["case_definitions"])
            return config, suite[:maximum], excluded
        suite = select_cases(config["category"], maximum, config["profile"], config["domain"], ids, excluded,config["case_definitions"])
        return config, suite, excluded

    def start(self, raw_config):
        with self.lock:
            if self.replay_busy or (self.active and self.active["status"] in ("running", "stopping")):
                raise RuntimeError("An experiment is already running")
        config, suite, previous = self.resolve_selection(raw_config)
        if config["mode"] == "local":
            runtime = doctor(config["model"])
            ready=runtime["ready"] if config["retrieval"]["method"]!="bm25" else runtime.get("ollama") and config["model"] in runtime.get("models",[])
            if not ready:
                raise ValueError("The selected local model or embedding runtime is not ready. Check the Runtime page.")
            if config["source_run_id"]:
                source = self.reports()[config["source_run_id"]][1]
                previous_digest = (source.get("performance") or {}).get("model_digest")
                if previous_digest and runtime.get("model_digest") and previous_digest != runtime["model_digest"]:
                    raise ValueError("The installed model weights changed. Start a fresh experiment instead of continuing this report.")
        with self.lock:
            if self.replay_busy or (self.active and self.active["status"] in ("running", "stopping")):
                raise RuntimeError("An experiment is already running")
            run_id = uuid.uuid4().hex
            self.cancel_event.clear()
            self.active = {"run_id": run_id, "status": "running", "mode": config["mode"],
                           "completed": 0, "total": len(suite), "case_id": "Starting",
                           "concurrency": config["concurrency"], "in_flight": [],
                           "started_at": datetime.now(timezone.utc).isoformat(), "error": None}
            worker = threading.Thread(target=self._run,
                                      args=(run_id, config, [case.case_id for case in suite], previous), daemon=True)
            worker.start()
            return dict(self.active)

    def _run(self, run_id, config, selected_ids, previous):
        def progress(done, total, case_id):
            with self.lock:
                self.active.update(completed=done, total=total, case_id=case_id)
        def activity(items):
            with self.lock:
                self.active["in_flight"] = [dict(item) for item in items]
        try:
            folder = self.output / "runs" / run_id
            def checkpoint(report):
                report["configuration"]["limit"] = None if config["selection_scope"] in ("all", "selected") else config["limit"]
                write_checkpoint(report, folder)
            report = run_suite(config["mode"], config["threshold"], config["k"], folder, config["model"],
                               config["category"], None, progress, self.cancel_event.is_set, run_id, config["policy"], config["profile"],
                               concurrency=config["concurrency"], domain=config["domain"], case_ids=selected_ids,
                               checkpoint=checkpoint, activity=activity,
                               cache_path=self.output / ".cache" / "embeddings.sqlite3",
                               selection_scope=config["selection_scope"], previous_case_ids=previous,
                               source_run_id=config["source_run_id"], generation=config["generation"],case_definitions=config["case_definitions"],retrieval=config["retrieval"])
            write_report(report, folder)
            with self.lock:
                self.active["status"] = ("cancelled" if report["status"] == "cancelled" else
                                         "completed_with_errors" if report["metrics"]["error_cases"] else "completed")
        except Exception as exc:
            # Surface worker failures; never leave a job stuck in "running".
            with self.lock:
                self.active.update(status="failed", error=f"{type(exc).__name__}: {exc}")

    def stop(self):
        with self.lock:
            if not self.active or self.active["status"] not in ("running", "stopping"):
                raise ValueError("No active experiment")
            self.cancel_event.set()
            self.active["status"] = "stopping"
            return dict(self.active)


def make_handler(manager):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Spades/0.5"

        def log_message(self, fmt, *args):
            pass

        def _valid_host(self):
            port = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def _respond(self, status, body, content_type="application/json; charset=utf-8", attachment=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if attachment:
                filename = attachment if isinstance(attachment, str) else "spades-report.json"
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._valid_host():
                return self._respond(403, {"error": "Invalid local host"})
            path = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/comparison-view.js": ("comparison-view.js", "text/javascript; charset=utf-8"),
                      "/styles.css": ("styles.css", "text/css; charset=utf-8")}
            assets.update({"/authoring.js":("authoring.js","text/javascript; charset=utf-8"),
                           "/findings.js":("findings.js","text/javascript; charset=utf-8"),
                           "/portable.js":("portable.js","text/javascript; charset=utf-8"),
                           "/replay.js":("replay.js","text/javascript; charset=utf-8"),
                           "/investigations.js":("investigations.js","text/javascript; charset=utf-8"),
                           "/campaign-matrix.js":("campaign-matrix.js","text/javascript; charset=utf-8"),
                           "/coverage.js":("coverage.js","text/javascript; charset=utf-8"),
                           "/campaigns.js":("campaigns.js","text/javascript; charset=utf-8")})
            if path in assets:
                name, mime = assets[path]
                return self._respond(200, (ASSETS / name).read_bytes(), mime)
            if path == "/api/session":
                return self._respond(200, {"token": manager.token})
            if path == "/api/workspace":
                try:
                    return self._respond(200, manager.workspace())
                except (OSError, ValueError) as exc:
                    return self._respond(500, {"error": str(exc)})
            if path == "/api/runtime":
                return self._respond(200, doctor())
            if path == "/api/runs":
                return self._respond(200, {"runs": manager.history(), "active": manager.snapshot()})
            if path == "/api/progress":
                return self._respond(200, {"active": manager.snapshot()})
            if path == "/api/replays":return self._respond(200,{"replays":manager.replays.list()})
            replay_match=re.fullmatch(r"/api/replay/([a-f0-9]{32})",path)
            if replay_match:
                try:return self._respond(200,manager.replays.get(replay_match[1]))
                except ValueError as exc:return self._respond(404,{"error":str(exc)})
            if path == "/api/campaigns":
                return self._respond(200,{"campaigns":manager.campaigns.list()})
            campaign_match=re.fullmatch(r"/api/campaign/([a-f0-9]{32})",path)
            if campaign_match:
                try:
                    return self._respond(200,manager.campaigns.get(campaign_match[1]))
                except ValueError as exc:
                    return self._respond(404,{"error":str(exc)})
            if path == "/api/corpus":
                return self._respond(200, {"profiles": PROFILES, "cases": [asdict(case) for profile in PROFILES for case in build_suite(profile)]})
            match = re.fullmatch(r"/api/(report|export|csv|analysis|gate)/([a-f0-9]{32})", path)
            if match:
                record = manager.reports().get(match[2])
                if record:
                    if match[1] in ("report", "gate"):
                        policy = manager.workspace()["quality_policy"]
                        gate = {**assess_report(record[1], policy["policy"]), "policy_revision":policy["revision"]}
                        if match[1] == "gate":
                            return self._respond(200, gate)
                    if match[1] == "analysis":
                        return self._respond(200, analyze_report(record[1]))
                    if match[1] == "report":
                        return self._respond(200, {**record[1], "analysis": analyze_report(record[1]), "quality_gate":gate})
                    if match[1] == "csv":
                        return self._respond(200, "\ufeff" + report_csv(record[1]), "text/csv; charset=utf-8", "spades-report.csv")
                    return self._respond(200, record[1], attachment=match[1] == "export")
            return self._respond(404, {"error": "Not found"})

        def _reject_post(self, status, message):
            # A close with unread body bytes can reset Windows clients before
            # they receive the rejection. Drain one bounded small read only;
            # never parse rejected content or wait through a streaming upload.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 16384:
                    self.connection.settimeout(.25)
                    self.rfile.read1(length)
            except (OSError, ValueError):
                pass
            return self._respond(status, {"error": message})

        def do_POST(self):
            if not self._valid_host():
                return self._reject_post(403, "Invalid local host")
            expected_origin = "http://" + self.headers.get("Host", "")
            if self.headers.get("Origin") != expected_origin:
                return self._reject_post(403, "Same-origin request required")
            if not hmac.compare_digest(self.headers.get("X-Spades-Token", "").encode("utf-8"), manager.token.encode("utf-8")):
                return self._reject_post(403, "Invalid session token")
            if self.headers.get_content_type() != "application/json":
                return self._reject_post(415, "JSON content required")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                path = urlsplit(self.path).path
                large_routes={"/api/campaign/preview","/api/coverage","/api/ingest","/api/scenario","/api/custom/run","/api/custom/selection","/api/suite","/api/suite/import","/api/campaign/create","/api/preset"}
                maximum=24*1024*1024 if path=="/api/bundle/verify" else 65536 if path in ("/api/finding","/api/finding/update") else 8*1024*1024 if path in large_routes else 8192
                self.connection.settimeout(5)
                if not 0 < length <= maximum:
                    # Drain a small rejected body so Windows can deliver the 413
                    # instead of resetting a socket with unread inbound bytes.
                    if 8192 < length <= 16384:
                        self.rfile.read(length)
                    return self._respond(413, {"error": f"Request body must be 1–{maximum} bytes"})
                body = json.loads(self.rfile.read(length))
                if path=="/api/finding":return self._respond(200,manager.save_finding(body))
                if path=="/api/finding/update":return self._respond(200,manager.save_finding(body,update=True))
                if path=="/api/bundle/export":
                    from .bundles import build_bundle
                    content,filename=build_bundle(manager.reports(),manager.workspace(),body)
                    return self._respond(200,content,"application/zip",filename)
                if path=="/api/bundle/verify":
                    from .bundles import verify_bundle
                    return self._respond(200,verify_bundle(body))
                if path=="/api/regression-pack":
                    from .regressions import build_regression_manifest
                    return self._respond(200,manager.save_suite(build_regression_manifest(manager.reports(),body),manifest=True))
                if path=="/api/replay/inspect":
                    from .replay import inspect_request
                    return self._respond(200,inspect_request(manager.reports(),body))
                if path=="/api/replay/start":return self._respond(202,manager.replays.start(body))
                if path == "/api/investigation/search":
                    from .investigations import search_evidence
                    return self._respond(200,search_evidence([record[1] for record in manager.reports().values()],body))
                if path == "/api/investigation/view":
                    return self._respond(200,manager.save_investigation(body))
                if path == "/api/coverage":
                    from .coverage import coverage_plan
                    if not isinstance(body,dict) or set(body)!={"config","focus","budget"}:
                        raise ValueError("Expected experiment config, coverage focus and scenario budget")
                    config,cases,_=manager.resolve_selection(body["config"])
                    return self._respond(200,coverage_plan(config,cases,[record[1] for record in manager.reports().values()],focus=body["focus"],budget=body["budget"]))
                if path in ("/api/selection","/api/custom/selection"):
                    _, suite, previous = manager.resolve_selection(body)
                    return self._respond(200, {"count": len(suite), "case_ids": [case.case_id for case in suite], "previous_count": len(previous), "model_requests": plan_cases(suite)["model_responses"], "plan": plan_cases(suite)})
                if path == "/api/ingest":
                    from .ingestion import extract_document
                    if not isinstance(body,dict) or set(body)!={"filename","data"}:
                        raise ValueError("Expected a filename and base64 document data")
                    return self._respond(200,extract_document(body["filename"],body["data"]))
                if path == "/api/scenario":
                    return self._respond(200,manager.save_custom_scenario(body))
                if path == "/api/campaign/create":
                    return self._respond(202,manager.campaigns.create(body))
                if path == "/api/campaign/preview":
                    return self._respond(200,manager.campaigns.preview(body))
                if path == "/api/campaign/action":
                    if not isinstance(body,dict) or set(body)-{"id","action","job_id"} or not {"id","action"}<=set(body):
                        raise ValueError("Expected a campaign ID and known action")
                    actions={"cancel":manager.campaigns.cancel_campaign,"resume":manager.campaigns.resume,
                             "cancel_job":manager.campaigns.cancel_job,"retry_job":manager.campaigns.retry_job}
                    if not isinstance(body["action"],str) or body["action"] not in actions:
                        raise ValueError("Unknown campaign action")
                    required={"id","action","job_id"} if body["action"] in ("cancel_job","retry_job") else {"id","action"}
                    if set(body)!=required:
                        raise ValueError("Unexpected or missing campaign action fields")
                    method=actions[body["action"]]
                    if body["action"] in ("cancel_job","retry_job"):
                        return self._respond(200,method(body["id"],body.get("job_id")))
                    return self._respond(200,method(body["id"]))
                if path == "/api/suite":
                    return self._respond(200, manager.save_suite(body))
                if path == "/api/suite/import":
                    return self._respond(200, manager.save_suite(body, manifest=True))
                if path == "/api/suite/history":
                    if not isinstance(body,dict) or set(body)!={"id"}: raise ValueError("Expected suite ID")
                    return self._respond(200,manager.suite_history(body["id"]))
                if path == "/api/suite/restore":
                    return self._respond(200,manager.restore_suite(body))
                if path == "/api/suite/compare":
                    if not isinstance(body,dict) or set(body)!={"id","reference_revision","candidate_revision"}:
                        raise ValueError("Expected suite ID and two revision numbers")
                    history=manager.suite_history(body["id"])
                    versions=history["history"]+[history["current"]]
                    choices=[]
                    for key in ("reference_revision","candidate_revision"):
                        if type(body[key]) is not int: raise ValueError("Revisions must be integers")
                        item=next((version for version in versions if version["revision"]==body[key]),None)
                        if item is None: raise ValueError("Requested revision is unavailable")
                        choices.append(item)
                    return self._respond(200,compare_suite_revisions(*choices))
                if path in ("/api/suite/export", "/api/suite/resolve"):
                    if not isinstance(body, dict) or set(body) != {"id"} or not isinstance(body["id"], str):
                        raise ValueError("Choose a saved suite")
                    suite = next((item for item in manager.workspace()["suites"] if item["id"] == body["id"]), None)
                    if suite is None:
                        raise ValueError("Saved suite not found")
                    manifest = export_suite(suite)
                    return self._respond(200, validate_suite(manifest, manifest=True) if path.endswith("resolve") else manifest)
                if path == "/api/preset":
                    return self._respond(200, manager.save_preset(body))
                if path == "/api/preset/remove":
                    return self._respond(200, manager.remove_preset(body))
                if path == "/api/bookmark":
                    return self._respond(200, manager.save_bookmark(body))
                if path in ("/api/run","/api/custom/run"):
                    return self._respond(202, manager.start(body))
                if path == "/api/stop":
                    return self._respond(200, manager.stop())
                if path == "/api/experiment":
                    return self._respond(200, manager.save_experiment(body))
                if path == "/api/quality-policy":
                    return self._respond(200, manager.save_quality_policy(body))
                if path == "/api/quality-policy/archive":
                    return self._respond(200, manager.archive_quality_policy(body))
                if path in ("/api/quality/compare-policy","/api/quality/history"):
                    expected={"run_id","candidate_policy"} if path.endswith("compare-policy") else {"run_id"}
                    if not isinstance(body,dict) or set(body)!=expected or not isinstance(body["run_id"],str) or not re.fullmatch(r"[a-f0-9]{32}",body["run_id"]):
                        raise ValueError("Choose a saved experiment and valid policy options")
                    reports=manager.reports()
                    if body["run_id"] not in reports:
                        raise ValueError("Saved experiment not found")
                    policy=manager.workspace()["quality_policy"]
                    if path.endswith("compare-policy"):
                        result=compare_policies(reports[body["run_id"]][1],policy["policy"],body["candidate_policy"])
                    else:
                        result=acceptance_history([report for _,report in reports.values()],body["run_id"],policy["policy"])
                    return self._respond(200,{**result,"policy_revision":policy["revision"]})
                if path == "/api/compare":
                    if not isinstance(body, dict) or set(body) != {"reference", "candidate"}:
                        raise ValueError("Choose reference and candidate experiment IDs")
                    ids = [body["reference"], body["candidate"]]
                    if any(not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value) for value in ids):
                        raise ValueError("Invalid experiment ID")
                    if ids[0] == ids[1]:
                        raise ValueError("Choose two different experiments")
                    reports = manager.reports()
                    if any(value not in reports for value in ids):
                        raise ValueError("Saved experiment not found")
                    return self._respond(200, compare_cases(reports[ids[0]][1], reports[ids[1]][1]))
                return self._respond(404, {"error": "Not found"})
            except RuntimeError as exc:
                return self._respond(409, {"error": str(exc)})
            except (ValueError, TypeError) as exc:
                return self._respond(400, {"error": str(exc)})
    return Handler


def serve(output=Path("output"), port=8765):
    manager = RunManager(output)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(manager))
    print(f"Spades laboratory: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        manager.cancel_event.set()
    finally:
        if manager._campaigns is not None:
            manager._campaigns.close()
        server.server_close()
