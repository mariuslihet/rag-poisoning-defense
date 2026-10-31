"""Bounded local model settings shared by the dashboard, CLI and runner."""

import math
import re

DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"


def validate_retrieval(options=None, profile="foundation"):
    defaults={"method":"hybrid" if profile=="complex" else "dense", "chunk_size":1400 if profile=="complex" else 700,
              "overlap":180 if profile=="complex" else 100, "rerank":"none"}
    if options is not None and (not isinstance(options,dict) or set(options)-set(defaults)):
        raise ValueError("Unknown retrieval setting")
    result={**defaults,**(options or {})}
    if result["method"] not in ("dense","bm25","hybrid") or result["rerank"] not in ("none","term_coverage"):
        raise ValueError("Select dense, bm25 or hybrid retrieval and none/term_coverage reranking")
    if type(result["chunk_size"]) is not int or not 256<=result["chunk_size"]<=4000:
        raise ValueError("Chunk size must be an integer from 256 to 4000")
    if type(result["overlap"]) is not int or not 0<=result["overlap"]<result["chunk_size"]:
        raise ValueError("Overlap must be nonnegative and smaller than chunk size")
    return result


def validate_model(model):
    if (not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)
            or "://" in model):
        raise ValueError("Choose a local Ollama model name, not a URL or command")
    return model


def validate_generation(options=None, profile="foundation"):
    defaults = {"temperature": 0, "seed": None, "think": None, "num_predict": 1400 if profile == "complex" else 350,
                "num_ctx": 16384 if profile == "complex" else 4096, "request_timeout": 180}
    if options is not None and (not isinstance(options, dict) or set(options) - set(defaults)):
        raise ValueError("Unknown generation setting")
    result = {**defaults, **(options or {})}
    temperature = result["temperature"]
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("Temperature must be a finite number from 0 to 2")
    seed = result["seed"]
    if result["think"] is not None and type(result["think"]) is not bool:
        raise ValueError("Thinking mode must be model default, enabled or disabled")
    if seed is not None and (type(seed) is not int or not 0 <= seed <= 2147483647):
        raise ValueError("Seed must be blank or an integer from 0 to 2147483647")
    for key, low, high in (("num_predict", 128, 8192), ("num_ctx", 2048, 32768), ("request_timeout", 30, 600)):
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"{key} must be an integer from {low} to {high}")
    if result["num_predict"] >= result["num_ctx"]:
        raise ValueError("Response token limit must be smaller than the context window")
    return result
