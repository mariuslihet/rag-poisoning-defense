"""Immutable request envelopes shared by capture and diagnostic replay."""
import copy
import hashlib
import json


def request_digest(record):
    return hashlib.sha256(json.dumps({key:value for key,value in record.items() if key!="sha256"},
        sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")).hexdigest()


def capture_request(kind, payload, timeout=None, model_digest=None):
    record={"version":1,"kind":kind,"payload":copy.deepcopy(payload),"timeout_seconds":timeout,"model_digest":model_digest}
    record["sha256"]=request_digest(record)
    return record


def user_message(query,chunks):
    context=json.dumps([{"source":c.source_id,"chunk":c.chunk_id,"text":c.text} for c in chunks])
    return {"role":"user","content":f"Documents (JSON):\n{context}\nQuestion: {query}"}
