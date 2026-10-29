"""Local runtime inspection and explicit model preparation."""

import importlib.util
import json
import urllib.request

from .providers import Ollama

DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
EMBEDDING_MODEL = "nomic-embed-text"


def doctor(model=DEFAULT_MODEL):
    result = {"ollama": False, "chromadb": importlib.util.find_spec("chromadb") is not None,
              "models": [], "required_model": model, "embedding_model": EMBEDDING_MODEL,
              "ready": False, "error": None}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(Ollama.base_url + "/api/tags", timeout=4) as response:
            records = json.load(response)["models"]
            result["models"] = [m["name"] for m in records if not m.get("remote_host") and not m.get("remote_model")]
            result["model_digest"] = next((m.get("digest") for m in records if m["name"] == model
                                           and not m.get("remote_host") and not m.get("remote_model")), None)
        result["ollama"] = True
        names = result["models"]
        result["ready"] = result["chromadb"] and model in names and any(
            name in (EMBEDDING_MODEL, EMBEDDING_MODEL + ":latest") for name in names)
    except (OSError, ValueError, KeyError) as exc:
        result["error"] = str(exc)
    return result


def prepare_models():
    """Download only the two explicitly required public model artifacts."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for model in (DEFAULT_MODEL, EMBEDDING_MODEL):
        print(f"Preparing {model}", flush=True)
        request = urllib.request.Request(Ollama.base_url + "/api/pull",
                                         json.dumps({"model": model, "stream": True}).encode(),
                                         {"Content-Type": "application/json"})
        previous = None
        with opener.open(request, timeout=180) as response:
            for line in response:
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError(event["error"])
                total = event.get("total", 0)
                progress = int(event.get("completed", 0) / total * 100) if total else None
                state = (event.get("status", ""), progress // 10 if progress is not None else None)
                if state != previous:
                    print(f'{model}: {event.get("status", "")} {str(progress) + "%" if progress is not None else ""}', flush=True)
                    previous = state
