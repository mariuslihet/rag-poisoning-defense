"""Diagnostic replay of captured requests; never reconstruct historical prompts."""
import copy
from datetime import datetime, timezone
import json
import re
import threading
import uuid

from .core import Chunk
from .providers import DemoModel, Ollama
from .requests import request_digest
from .settings import validate_generation, validate_model


def inspect_request(reports, body):
    if not isinstance(body,dict) or set(body)-{"run_id","case_id","arm","turn"} or not {"run_id","case_id","arm"}<=set(body):
        raise ValueError("Choose an original run, case, arm and optional zero-based turn")
    run_id,case_id,arm=body["run_id"],body["case_id"],body["arm"]
    turn=body.get("turn",0)
    if not isinstance(run_id,str) or not re.fullmatch(r"[a-f0-9]{32}",run_id) or not isinstance(case_id,str) or not 1<=len(case_id)<=200 or arm not in ("vulnerable","secured") or type(turn) is not int or not 0<=turn<8:
        raise ValueError("Invalid replay evidence reference")
    source=reports.get(run_id)
    if source is None:raise ValueError("Original report not found")
    report=source[1] if isinstance(source,tuple) else source
    rows=[row for row in report["results"] if row["case_id"]==case_id]
    if len(rows)!=1:raise ValueError("Original case reference is unavailable or ambiguous")
    row=rows[0]; turns=row.get("turn_results")
    if turns:
        if turn>=len(turns):raise ValueError("That turn was not recorded")
        row=turns[turn]
    elif turn:raise ValueError("That turn was not recorded")
    record=row.get(arm+"_request")
    if not isinstance(record,dict):raise ValueError("This historical response has no captured request. Run a fresh scenario to capture it; no prompt will be reconstructed.")
    if set(record)!={"version","kind","payload","timeout_seconds","model_digest","sha256"} or type(record["version"]) is not int or record["version"]!=1 or record.get("sha256")!=request_digest(record):
        raise ValueError("Captured request fingerprint or format is invalid")
    if len(json.dumps(record,ensure_ascii=False).encode())>16*1024*1024:raise ValueError("Captured request exceeds the replay limit")
    if record["model_digest"] is not None and (not isinstance(record["model_digest"],str) or not 1<=len(record["model_digest"])<=256):raise ValueError("Invalid captured model identity")
    payload=record["payload"]
    if not isinstance(payload,dict):raise ValueError("Invalid captured payload")
    if record["kind"]=="ollama_chat":
        if not {"model","stream","options","messages"}<=set(payload) or set(payload)-{"model","stream","options","messages","keep_alive","format","think"} or payload["stream"] is not False:
            raise ValueError("Replay supports only captured non-streaming chat payloads")
        validate_model(payload["model"])
        if not isinstance(payload["options"],dict) or set(payload["options"])-{"temperature","seed","num_predict","num_ctx"}:raise ValueError("Unsupported captured generation options")
        validate_generation({**payload["options"],"think":payload.get("think"),"request_timeout":record["timeout_seconds"]})
        messages=payload["messages"]
        if not isinstance(messages,list) or not 1<=len(messages)<=20 or any(not isinstance(message,dict) or set(message)!={"role","content"} or message["role"] not in ("system","user","assistant") or not isinstance(message["content"],str) for message in messages):
            raise ValueError("Invalid captured message history")
    elif record["kind"]=="demo":
        if set(payload)!={"query","chunks","defended","schema","history"} or type(payload["defended"]) is not bool or not isinstance(payload["query"],str) or not isinstance(payload["chunks"],list) or not isinstance(payload["history"],list) or (payload["schema"] is not None and not isinstance(payload["schema"],dict)):raise ValueError("Invalid simulator request capture")
        for chunk in payload["chunks"]:Chunk(**chunk)
    else:raise ValueError("Unknown captured request kind")
    return {"source":{"run_id":run_id,"case_id":case_id,"arm":arm,"turn":turn},"record":copy.deepcopy(record),
            "original_response":row.get(arm+"_response"),
            "note":"Replay sends the captured payload unchanged and skips retrieval. Prior messages and outputs remain frozen. It creates a diagnostic artifact, not a new graded scenario result; seeds do not guarantee identical responses."}


class ReplayManager:
    def __init__(self,manager):
        self.manager=manager;self.output=manager.output/"replays";self.output.mkdir(parents=True,exist_ok=True)
        self.records={}
        for path in self.output.glob("*.json"):
            try:
                record=json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record,dict) or not re.fullmatch(r"[a-f0-9]{32}",record.get("id","")) or not isinstance(record.get("source"),dict) or not isinstance(record.get("created_at"),str):continue
                changed=record.get("status")=="running"
                if changed:record.update(status="interrupted",error="Replay process stopped; inference is never resumed automatically.")
                self.records[record["id"]]=record
                if changed:self._save(record)
            except (ValueError,OSError,TypeError):continue

    def get(self,identifier):
        with self.manager.lock:
            if identifier not in self.records:raise ValueError("Saved replay not found")
            return copy.deepcopy(self.records[identifier])

    def list(self):
        with self.manager.lock:return [{key:item.get(key) for key in ("id","status","created_at","source","error")} for item in sorted(self.records.values(),key=lambda item:item["created_at"],reverse=True)]

    def _save(self,record):
        path=self.output/(record["id"]+".json");temporary=path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record,indent=2,allow_nan=False),encoding="utf-8");temporary.replace(path)

    def start(self,body):
        request=inspect_request(self.manager.reports(),body)
        with self.manager.lock:
            active=self.manager.snapshot()
            if self.manager.replay_busy or (active and active["status"] in ("running","stopping")):raise RuntimeError("Wait for the current experiment or replay to finish")
            if len(self.records)>=100:raise ValueError("This workspace supports 100 saved diagnostic replays")
            record={"id":uuid.uuid4().hex,"created_at":datetime.now(timezone.utc).isoformat(),"status":"running","error":None,**request}
            self._save(record);self.records[record["id"]]=record;self.manager.replay_busy=True
            threading.Thread(target=self._run,args=(record,),daemon=True).start()
            return copy.deepcopy(record)

    def _run(self,record):
        # Publish terminal state only after its durable artifact is written.
        # Readers must not observe completion while a worker is still saving.
        record=copy.deepcopy(record)
        try:
            capture=record["record"];payload=copy.deepcopy(capture["payload"])
            if capture["kind"]=="demo":
                answer=DemoModel().answer(payload["query"],[Chunk(**chunk) for chunk in payload["chunks"]],payload["defended"],schema=payload["schema"],history=payload["history"])
                metadata={"simulation":True}
            else:
                provider=Ollama(model=payload["model"],generation={"request_timeout":capture["timeout_seconds"]})
                provider._require_local_weights(payload["model"])
                digest=provider.statistics()["model_digest"]
                if capture["model_digest"] and digest!=capture["model_digest"]:raise ValueError("Installed model weights differ from the captured request; exact-identity replay is unavailable")
                response=provider.request("/api/chat",payload);answer=response["message"]["content"]
                metadata={"done_reason":response.get("done_reason"),"model_digest":digest,"weights_verified":bool(capture["model_digest"] and digest==capture["model_digest"]),"generated_tokens":response.get("eval_count")}
            record.update(status="completed",response=answer,response_changed=answer!=record["original_response"],metadata=metadata)
        except Exception as exc:record.update(status="failed",error=f"{type(exc).__name__}: {exc}")
        finally:
            with self.manager.lock:
                record["finished_at"]=datetime.now(timezone.utc).isoformat()
                try:self._save(record)
                except (OSError,ValueError) as exc:record.update(status="failed",error=f"Could not save replay artifact: {exc}")
                finally:
                    self.records[record["id"]]=record
                    self.manager.replay_busy=False
