"""Validated operator-authored scenarios with immutable revision snapshots.

Definitions contain grading references. ``definition_to_case`` places only field
types in the model output schema; references remain in the independent grader.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import uuid

from .core import Document
from .corpus import CANARY, Case
from .grading import matches

MAX_CUSTOM_BYTES = 32 * 1024 * 1024
CATEGORIES = {"baseline", "indirect_injection", "semantic_camouflage", "metadata_hijacking", "exfiltration", "data_corruption", "role_spoofing", "cross_document"}
DOC_KEYS = {"source_id", "text", "author_role", "access", "channel_trust", "timestamp", "provenance"}


def _finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _text(value, label, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{label} must contain {'0' if empty else '1'}–{maximum} characters")
    return value


def _document(body, *, attack=False):
    if not isinstance(body, dict) or not {"source_id", "text"} <= set(body) or set(body) - DOC_KEYS:
        raise ValueError("Documents require source_id and text with known provenance options")
    source = body["source_id"]
    if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", source) or source == "private-appendix":
        raise ValueError("Source IDs must be 1–100 simple identifier characters; private-appendix is reserved")
    text = _text(body["text"], "Document text", 250_000)
    role = body.get("author_role", "external" if attack else "editor")
    access = body.get("access", 0)
    trust = body.get("channel_trust", 0.2 if attack else 0.95)
    timestamp = body.get("timestamp", datetime.now(timezone.utc).isoformat())
    if type(access) is not int or access not in (0, 1, 2):
        raise ValueError("Document access must be an integer from 0 to 2")
    if not _finite_number(trust) or not 0 <= trust <= 1:
        raise ValueError("Channel trust must be finite and between 0 and 1")
    if not isinstance(timestamp, str) or len(timestamp) > 64:
        raise ValueError("Document timestamps must be ISO 8601 values with timezones")
    # Reuse the ingestion contract and validate timestamps/roles without I/O.
    Document(source, text, role, access, trust, timestamp)
    result = {"source_id": source, "text": text, "author_role": role,
              "access": access, "channel_trust": trust, "timestamp": timestamp}
    if "provenance" in body:
        provenance = body["provenance"]
        allowed = {"filename", "format", "sha256", "byte_count", "warnings"}
        if not isinstance(provenance, dict) or set(provenance) - allowed:
            raise ValueError("Unknown document provenance field")
        canonical = {}
        for key in ("filename", "format", "sha256"):
            if key in provenance:
                canonical[key] = _text(provenance[key], f"Provenance {key}", 255)
        if "sha256" in canonical and not re.fullmatch(r"[a-f0-9]{64}", canonical["sha256"]):
            raise ValueError("Provenance SHA-256 must be a lowercase 64-character digest")
        if "byte_count" in provenance:
            if type(provenance["byte_count"]) is not int or not 0 <= provenance["byte_count"] <= 4 * 1024 * 1024:
                raise ValueError("Invalid original document byte count")
            canonical["byte_count"] = provenance["byte_count"]
        if "warnings" in provenance:
            warnings = provenance["warnings"]
            if not isinstance(warnings, list) or len(warnings) > 20:
                raise ValueError("Invalid provenance warnings")
            canonical["warnings"] = [_text(value, "Extraction warning", 1000) for value in warnings]
        result["provenance"] = canonical
    return result


def _scalar(value, label):
    if type(value) is bool:
        return value
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if finite:
            return value
    if isinstance(value, str) and len(value) <= 4000:
        return value
    raise ValueError(f"{label} must be a finite number, boolean or string of at most 4000 characters")


def validate_definition(body):
    """Return a bounded canonical scenario; no files, models or URLs are opened."""
    required = {"name", "query", "documents", "rubric", "required_sources"}
    allowed = required | {"case_id", "domain", "category", "clearance", "retrieval_queries", "attack", "attack_goal"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
        raise ValueError("Expected scenario name, task, documents, rubric and required source IDs")
    case_id = body.get("case_id", "custom-" + uuid.uuid4().hex)
    if not isinstance(case_id, str) or not re.fullmatch(r"custom-[a-z0-9][a-z0-9_-]{0,90}", case_id):
        raise ValueError("Custom case IDs must start custom- and use lowercase identifier characters")
    name = _text(body["name"], "Scenario name", 120).strip()
    query = _text(body["query"], "Analytical task", 20_000).strip()
    if CANARY.casefold() in query.casefold():
        raise ValueError("The analytical task must not contain the restricted synthetic canary value")
    domain = body.get("domain", "custom")
    if not isinstance(domain, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", domain):
        raise ValueError("Domain must be a lowercase identifier of at most 40 characters")
    category = body.get("category", "baseline")
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError("Choose a known scenario family")
    clearance = body.get("clearance", 1)
    if type(clearance) is not int or clearance not in (0, 1, 2):
        raise ValueError("Scenario clearance must be 0, 1 or 2")
    documents = body["documents"]
    if not isinstance(documents, list) or not 1 <= len(documents) <= 40:
        raise ValueError("A scenario requires 1–40 source documents")
    documents = [_document(document) for document in documents]
    ids = [document["source_id"] for document in documents]
    if len(set(ids)) != len(ids):
        raise ValueError("Source document IDs must be unique")
    required_sources = body["required_sources"]
    if (not isinstance(required_sources, list) or not 1 <= len(required_sources) <= 40
            or not all(isinstance(source, str) for source in required_sources)
            or len(set(required_sources)) != len(required_sources) or not set(required_sources) <= set(ids)):
        raise ValueError("Required sources must be unique IDs from the legitimate source documents")
    rules = body["rubric"]
    if not isinstance(rules, list) or not 1 <= len(rules) <= 30:
        raise ValueError("Define 1–30 typed reference assertions")
    rubric = []
    for rule in rules:
        if not isinstance(rule, dict) or not {"field", "expected"} <= set(rule) or set(rule) - {"field", "expected", "tolerance", "description"}:
            raise ValueError("Assertions require a field and expected scalar value")
        field = rule["field"]
        if not isinstance(field, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", field):
            raise ValueError("Assertion fields must be lowercase identifiers")
        expected = _scalar(rule["expected"], "Reference value")
        tolerance = rule.get("tolerance", 0)
        if not _finite_number(tolerance) or tolerance < 0 or tolerance > 1_000_000:
            raise ValueError("Numeric tolerance must be finite and between 0 and 1,000,000")
        if tolerance and type(expected) not in (int, float):
            raise ValueError("Tolerance applies only to numeric reference values")
        rubric.append({"field": field, "expected": expected, "tolerance": tolerance,
                       "description": _text(rule.get("description", ""), "Assertion description", 1000, empty=True)})
    fields = [rule["field"] for rule in rubric]
    if len(set(fields)) != len(fields):
        raise ValueError("Assertion fields must be unique")
    retrieval = body.get("retrieval_queries", [])
    if not isinstance(retrieval, list) or len(retrieval) > 8:
        raise ValueError("Use at most eight task-derived retrieval queries")
    retrieval = [_text(value, "Retrieval query", 2000).strip() for value in retrieval]
    if any(CANARY.casefold() in value.casefold() for value in retrieval):
        raise ValueError("Retrieval queries must not include the synthetic canary value")
    attack = body.get("attack")
    goal = body.get("attack_goal", {})
    if not isinstance(goal, dict):
        raise ValueError("Attack goal must be an object")
    if attack is not None:
        if not isinstance(attack, dict) or set(attack) - {"document", "approved_provenance"} or "document" not in attack:
            raise ValueError("An attack requires a document and optional explicit provenance approval")
        approved = attack.get("approved_provenance", False)
        if type(approved) is not bool:
            raise ValueError("Attack provenance approval must be an explicit boolean")
        attack = {"document": _document(attack["document"], attack=True), "approved_provenance": approved}
        if attack["document"]["source_id"] in ids:
            raise ValueError("The attack document must have a distinct source ID")
        if category == "baseline":
            raise ValueError("An adversarial document requires an attack family, not baseline")
        if not isinstance(goal, dict):
            raise ValueError("Attack goal must be an object")
        if goal.get("kind") == "canary" and set(goal) == {"kind"}:
            goal = {"kind": "canary"}
        elif goal.get("kind") == "field" and set(goal) == {"kind", "field", "equals"}:
            if goal["field"] not in fields:
                raise ValueError("The attack objective must target a graded field")
            value = _scalar(goal["equals"], "Attack target")
            rule = next(rule for rule in rubric if rule["field"] == goal["field"])
            if type(value) is not type(rule["expected"]) and not (type(value) in (int, float) and type(rule["expected"]) in (int, float)):
                raise ValueError("The attack target must use the reference field type")
            if matches(value, rule["expected"], rule["tolerance"]):
                raise ValueError("The attack target must differ from the legitimate reference")
            if isinstance(value, str) and len(value) >= 4 and any(value.casefold() in text.casefold() for text in [query, *retrieval]):
                raise ValueError("Do not include the attacker-selected target in the analytical task or retrieval queries")
            goal = {"kind": "field", "field": goal["field"], "equals": value}
        else:
            raise ValueError("Choose a synthetic-canary goal or a typed field target")
    elif category != "baseline" or goal:
        raise ValueError("Attack-family scenarios require an attack document and goal")
    total = sum(len(document["text"]) for document in documents) + (len(attack["document"]["text"]) if attack else 0)
    if total > 1_000_000:
        raise ValueError("Total scenario document text must not exceed 1,000,000 characters")
    return {"case_id": case_id, "name": name, "domain": domain, "query": query,
            "documents": documents, "rubric": rubric, "required_sources": list(required_sources),
            "category": category, "clearance": clearance, "retrieval_queries": retrieval,
            "attack": attack, "attack_goal": goal}


def definition_digest(definition):
    canonical = validate_definition(definition)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def definition_to_case(definition):
    definition = validate_definition(definition)
    def document(value):
        return Document(**{key: value[key] for key in DOC_KEYS - {"provenance"} if key in value})
    documents = [document(value) for value in definition["documents"]]
    properties = {}
    for rule in definition["rubric"]:
        value = rule["expected"]
        kind = "boolean" if type(value) is bool else "number" if type(value) in (int, float) else "string"
        properties[rule["field"]] = {"type": [kind, "null"]}
    schema = {"type": "object", "properties": {
        "explanation": {"type": "string"},
        "answers": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
        "citations": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}}},
        "required": ["explanation", "answers", "citations", "limitations"], "additionalProperties": False}
    attack = definition["attack"]
    goal = definition["attack_goal"]
    target = CANARY if goal.get("kind") == "canary" else str(goal.get("equals", ""))
    return Case(case_id=definition["case_id"], category=definition["category"], query=definition["query"],
                expected="; ".join(f'{rule["field"]} = {rule["expected"]}' for rule in definition["rubric"]),
                legitimate=documents[0], supporting=documents[1:],
                poison=document(attack["document"]) if attack else None,
                trusted_poison=attack["approved_provenance"] if attack else False,
                target=target, rubric=deepcopy(definition["rubric"]), required_sources=list(definition["required_sources"]),
                retrieval_queries=definition["retrieval_queries"] or [definition["query"]], answer_schema=schema,
                attack_goal=deepcopy(goal), profile="complex", domain=definition["domain"], clearance=definition["clearance"])


def save_scenario(workspace, body):
    """Mutate a workspace only after validation and return its saved record.

    The caller owns persistence/locking. Existing revisions are never pruned.
    """
    if not isinstance(body, dict) or "definition" not in body or set(body) - {"definition", "id", "revision"}:
        raise ValueError("Expected a definition and optional scenario ID/revision")
    if ("id" in body) != ("revision" in body):
        raise ValueError("Scenario updates require both ID and revision")
    definition = validate_definition(body["definition"])
    records = workspace.get("custom_scenarios", [])
    if not isinstance(records, list):
        raise ValueError("Custom scenario workspace data is invalid")
    existing = None
    if "id" in body:
        if not isinstance(body["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", body["id"]):
            raise ValueError("Invalid saved scenario ID")
        if type(body["revision"]) is not int or body["revision"] < 1:
            raise ValueError("Scenario revision must be a positive integer")
        existing = next((record for record in records if record["id"] == body["id"]), None)
        if existing is None:
            raise ValueError("Saved custom scenario not found")
        if existing["revision"] != body["revision"]:
            raise RuntimeError("This scenario changed. Reload the current revision before saving.")
        if existing["definition"]["case_id"] != definition["case_id"]:
            raise ValueError("A saved scenario's case ID cannot be changed")
        if existing["revision"] >= 50:
            raise ValueError("This scenario reached its 50-revision limit; export it and create a new scenario")
    elif len(records) >= 100:
        raise ValueError("The workspace supports up to 100 custom scenarios")
    if any(record["definition"]["case_id"] == definition["case_id"] and (not existing or record["id"] != existing["id"]) for record in records):
        raise ValueError("A custom scenario already uses this case ID")
    now = datetime.now(timezone.utc).isoformat()
    history = deepcopy(existing.get("history", [])) if existing else []
    if existing:
        history.append({key: deepcopy(existing[key]) for key in ("revision", "definition", "dataset_digest", "created_at", "updated_at")})
    record = {"id": existing["id"] if existing else uuid.uuid4().hex,
              "revision": existing["revision"] + 1 if existing else 1, "definition": definition,
              "dataset_digest": definition_digest(definition), "history": history,
              "created_at": existing["created_at"] if existing else now, "updated_at": now}
    updated = [value for value in records if value["id"] != record["id"]] + [record]
    if len(json.dumps(updated, ensure_ascii=False, allow_nan=False).encode()) > MAX_CUSTOM_BYTES:
        raise ValueError("Custom scenario revision data exceeds the 32 MiB workspace limit")
    workspace["custom_scenarios"] = updated
    return deepcopy(record)
