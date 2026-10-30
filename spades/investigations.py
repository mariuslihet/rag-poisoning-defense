"""Local cross-run evidence search. Saved views store filters, never results."""

from collections import Counter
from datetime import date, datetime, timezone
import json

from .analysis import ISSUES, diagnose_case


DEFAULT_FILTERS = {"query":"", "mode":"", "profile":"", "model":"", "policy":"", "domain":"",
                   "category":"", "issue":"", "from_date":"", "to_date":""}


def validate_filters(body):
    if not isinstance(body, dict) or set(body) - set(DEFAULT_FILTERS):
        raise ValueError("Expected known investigation filters")
    result = {**DEFAULT_FILTERS, **body}
    for key, value in result.items():
        if not isinstance(value, str) or len(value) > (200 if key in ("query","model") else 80):
            raise ValueError(f"Invalid {key} filter")
        result[key] = value.strip()
    for key, allowed in (("mode",("","demo","local")), ("profile",("","foundation","complex")),
                         ("policy",("","strict","sanitize")), ("issue",("","clear",*ISSUES))):
        if result[key] not in allowed:
            raise ValueError(f"Unknown {key} filter")
    for key in ("from_date","to_date"):
        if result[key]:
            try:
                parsed = date.fromisoformat(result[key])
                if parsed.isoformat() != result[key]: raise ValueError()
            except ValueError:
                raise ValueError("Use YYYY-MM-DD for investigation dates") from None
    if result["from_date"] and result["to_date"] and result["from_date"] > result["to_date"]:
        raise ValueError("The start date must not follow the end date")
    return result


def _time(value):
    instant = datetime.fromisoformat(value.replace("Z","+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _excerpt(text, query):
    if not text: return ""
    index = text.casefold().find(query) if query else 0
    start = max(0,index-80) if index >= 0 else 0
    return ("…" if start else "") + text[start:start+360] + ("…" if len(text)>start+360 else "")


def search_evidence(reports, body):
    if not isinstance(body,dict) or set(body)-{"filters","offset","limit"} or "filters" not in body:
        raise ValueError("Expected filters and optional page offset/limit")
    filters = validate_filters(body["filters"])
    offset, limit = body.get("offset",0), body.get("limit",25)
    if type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Page offset must be 0–1000000 and page size 1–100")
    ordered, invalid = [], 0
    for report in reports:
        try:
            ordered.append((_time(report["created_at"]),report["run_id"],report))
        except (AttributeError,ValueError,TypeError,KeyError):
            invalid += 1
    ordered.sort(key=lambda item:(item[0],item[1]),reverse=True)
    matches, counts, runs, seen = [], Counter(), set(), set()
    query = filters["query"].casefold()
    for instant, run_id, report in ordered:
        config = report.get("configuration") or {}
        if not isinstance(config,dict) or not isinstance(report.get("results"),list):
            invalid += 1
            continue
        if any(filters[key] and filters[key]!=value for key,value in (
                ("mode",report.get("mode")),("model",report.get("model")),("profile",config.get("profile","foundation")),("policy",config.get("policy","strict")))):
            continue
        day = instant.date().isoformat()
        if (filters["from_date"] and day < filters["from_date"]) or (filters["to_date"] and day > filters["to_date"]):
            continue
        for row in report.get("results",[]):
            try:
                key = (run_id,row["case_id"])
                if key in seen: continue
                seen.add(key)
                domain = row.get("domain") or row["case_id"].split("-")[0]
                if (filters["domain"] and domain!=filters["domain"]) or (filters["category"] and row["category"]!=filters["category"]):
                    continue
                sources = [f'{chunk.get("source_id","")} {chunk.get("text","")}' for chunk in (row.get("retrieved_chunks") or [])]
                searchable = [row["case_id"],row.get("query",""),row.get("secured_response",""),row.get("vulnerable_response",""),row.get("error") or "",
                              json.dumps(row.get("secured_grade") or {},ensure_ascii=False),*sources]
                if query and not any(query in text.casefold() for text in searchable): continue
                diagnostic = diagnose_case(row)
                if filters["issue"]=="clear" and diagnostic["issues"]:continue
                if filters["issue"] not in ("","clear") and filters["issue"] not in diagnostic["issues"]:continue
                excerpt_source = next((text for text in searchable if query and query in text.casefold()),row.get("secured_response") or row.get("query", ""))
                matches.append({"run_id":run_id,"case_id":row["case_id"],"created_at":report["created_at"],
                    "mode":report.get("mode"),"model":report.get("model"),"profile":config.get("profile","foundation"),
                    "policy":config.get("policy","strict"),"domain":domain,"category":row["category"],
                    "query":row.get("query",""),"excerpt":_excerpt(excerpt_source,query),
                    "issues":diagnostic["issues"],"failed_fields":diagnostic["failed_fields"],"error":row.get("error"),
                    "source_trace":diagnostic["source_trace"],"configuration":{
                        "dataset_version":config.get("dataset_version"),"grading_version":config.get("grading_version"),
                        "trust_threshold":config.get("trust_threshold"),"retrieval_k":config.get("retrieval_k"),
                        "generation":config.get("generation"),"model_digest":(report.get("performance") or {}).get("model_digest")}})
                counts.update(diagnostic["issues"])
                runs.add(run_id)
            except (TypeError,AttributeError,KeyError,ValueError):
                invalid += 1
    return {"investigation_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"filters":filters,
            "total":len(matches),"matching_runs":len(runs),"offset":offset,"limit":limit,
            "next_offset":offset+limit if offset+limit<len(matches) else None,
            "results":matches[offset:offset+limit],"issue_counts":dict(counts),"skipped_invalid_records":invalid,
            "limitations":["Each row is one saved case observation in one run. The same scenario can appear in several runs.",
                           "Issue counts cover all matches and may overlap; they are not model performance rates or proven root causes.",
                           "Different models, datasets and settings may appear together. Inspect each observation's recorded identity before comparing outcomes.",
                           "Date filters use experiment start dates in UTC. Pagination and exports describe this search snapshot; refresh may include new evidence.",
                           "Search reads tasks, both responses, grading data and retrieved source text. It uses literal text matching and makes no model calls."]}
