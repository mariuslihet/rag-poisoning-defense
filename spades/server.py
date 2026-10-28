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

ASSETS = Path(__file__).parent / "web"


def validate_config(config):
    if not isinstance(config, dict) or set(config) - {"mode", "threshold", "k", "limit", "category", "policy", "profile", "domain", "case_ids", "concurrency", "selection_scope", "source_run_id"}:
        raise ValueError("Expected known experiment options")
    result = {"mode": "demo", "threshold": 0.7, "k": 5, "limit": 6, "category": None, "policy": "strict", "profile": "foundation",
              "domain": None, "case_ids": None, "concurrency": 2, "selection_scope": "sample", "source_run_id": None}
    result.update(config)
    if result["category"] == "":
        result["category"] = None
    if result["domain"] == "":
        result["domain"] = None
    if result["selection_scope"] not in ("sample", "all", "selected", "remaining", "errors"):
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
    select_cases(result["category"], result["limit"], result["profile"], result["domain"], selected)
    if result["selection_scope"] in ("remaining", "errors") and not result["source_run_id"]:
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

    def snapshot(self):
        with self.lock:
            return dict(self.active) if self.active else None

    def _read_workspace(self):
        path = self.output / "workspace.json"
        if not path.exists():
            return {"presets": [], "bookmarks": []}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("presets"), list) or not isinstance(data.get("bookmarks"), list):
            raise ValueError("Workspace data is invalid; restore output/workspace.json from a backup")
        return data

    def _write_workspace(self, data):
        temporary = self.output / "workspace.json.tmp"
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.output / "workspace.json")

    def workspace(self):
        with self.lock:
            data = self._read_workspace()
            return {"presets": BUILTIN_PRESETS + data["presets"], "bookmarks": data["bookmarks"]}

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
        if scope in ("remaining", "errors"):
            records = self.reports()
            record = records.get(config["source_run_id"])
            if not record:
                raise ValueError("Previous experiment not found")
            source = record[1]
            prior = source["configuration"]
            compatible = (source["mode"] == config["mode"] and prior.get("profile", "foundation") == config["profile"]
                          and prior["trust_threshold"] == config["threshold"] and prior["retrieval_k"] == config["k"]
                          and prior.get("policy", "strict") == config["policy"]
                          and (config["mode"] != "local" or source["model"] == DEFAULT_MODEL))
            dataset = "enterprise-1.1" if config["profile"] == "complex" else "0.2"
            grading = "typed-rubric-2" if config["profile"] == "complex" else "substring-2"
            if not compatible or prior.get("dataset_version") != dataset or prior.get("grading_version", grading) != grading:
                raise ValueError("Previous experiment must use the same profile, mode, model, trust, retrieval depth and policy")
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
                                and c["retrieval_k"] == config["k"] and c.get("policy", "strict") == config["policy"])
                        if same:
                            family.add(candidate["run_id"])
                            changed = True
            for _, candidate in records.values():
                if candidate["run_id"] in family:
                    completed.update(r["case_id"] for r in candidate["results"] if not r["error"])
                    completed.update(candidate["configuration"].get("previous_case_ids", []))
            if scope == "remaining":
                excluded = sorted(completed)
            else:
                ids = [r["case_id"] for r in source["results"] if r["error"] and r["case_id"] not in completed]
                if not ids:
                    raise ValueError("The previous experiment has no runtime errors to retry")
        maximum = None if scope in ("all", "selected") else config["limit"]
        suite = select_cases(config["category"], maximum, config["profile"], config["domain"], ids, excluded)
        return config, suite, excluded

    def start(self, raw_config):
        with self.lock:
            if self.active and self.active["status"] in ("running", "stopping"):
                raise RuntimeError("An experiment is already running")
        config, suite, previous = self.resolve_selection(raw_config)
        if config["mode"] == "local" and not doctor()["ready"]:
            raise ValueError("Local runtime is not ready. Check the Runtime page.")
        with self.lock:
            if self.active and self.active["status"] in ("running", "stopping"):
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
            report = run_suite(config["mode"], config["threshold"], config["k"], folder, DEFAULT_MODEL,
                               config["category"], None, progress, self.cancel_event.is_set, run_id, config["policy"], config["profile"],
                               concurrency=config["concurrency"], domain=config["domain"], case_ids=selected_ids,
                               checkpoint=checkpoint, activity=activity,
                               cache_path=self.output / ".cache" / "embeddings.sqlite3",
                               selection_scope=config["selection_scope"], previous_case_ids=previous,
                               source_run_id=config["source_run_id"])
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
                      "/styles.css": ("styles.css", "text/css; charset=utf-8")}
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
            if path == "/api/corpus":
                return self._respond(200, {"profiles": PROFILES, "cases": [asdict(case) for profile in PROFILES for case in build_suite(profile)]})
            match = re.fullmatch(r"/api/(report|export|csv)/([a-f0-9]{32})", path)
            if match:
                record = manager.reports().get(match[2])
                if record:
                    if match[1] == "csv":
                        return self._respond(200, "\ufeff" + report_csv(record[1]), "text/csv; charset=utf-8", "spades-report.csv")
                    return self._respond(200, record[1], attachment=match[1] == "export")
            return self._respond(404, {"error": "Not found"})

        def do_POST(self):
            if not self._valid_host():
                return self._respond(403, {"error": "Invalid local host"})
            expected_origin = "http://" + self.headers.get("Host", "")
            if self.headers.get("Origin") != expected_origin:
                return self._respond(403, {"error": "Same-origin request required"})
            if not hmac.compare_digest(self.headers.get("X-Spades-Token", "").encode("utf-8"), manager.token.encode("utf-8")):
                return self._respond(403, {"error": "Invalid session token"})
            if self.headers.get_content_type() != "application/json":
                return self._respond(415, {"error": "JSON content required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                self.connection.settimeout(5)
                if not 0 < length <= 8192:
                    # Drain a small rejected body so Windows can deliver the 413
                    # instead of resetting a socket with unread inbound bytes.
                    if 8192 < length <= 16384:
                        self.rfile.read(length)
                    return self._respond(413, {"error": "Request body must be 1–8192 bytes"})
                body = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/selection":
                    _, suite, previous = manager.resolve_selection(body)
                    return self._respond(200, {"count": len(suite), "case_ids": [case.case_id for case in suite], "previous_count": len(previous), "model_requests": len(suite) * 2})
                if path == "/api/preset":
                    return self._respond(200, manager.save_preset(body))
                if path == "/api/preset/remove":
                    return self._respond(200, manager.remove_preset(body))
                if path == "/api/bookmark":
                    return self._respond(200, manager.save_bookmark(body))
                if path == "/api/run":
                    return self._respond(202, manager.start(body))
                if path == "/api/stop":
                    return self._respond(200, manager.stop())
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
        server.server_close()
