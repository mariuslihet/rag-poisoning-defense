"""Portable, validated scenario suites and inference-free run planning."""

from .evaluation import select_cases

VERSIONS = {"foundation": ("0.2", "substring-2"), "complex": ("enterprise-1.1", "typed-rubric-2")}


def validate_suite(body, manifest=False):
    required = {"name", "description", "profile", "case_ids"}
    if manifest:
        required |= {"format", "version", "dataset_version", "grading_version"}
    allowed = required if manifest else required | {"id", "revision"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
        raise ValueError("Expected a suite name, description, profile and exact scenario IDs")
    name, description, profile = body["name"], body["description"], body["profile"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Suite names must contain 1–100 characters")
    if not isinstance(description, str) or len(description) > 1000:
        raise ValueError("Suite descriptions must contain at most 1000 characters")
    if not isinstance(profile, str) or profile not in VERSIONS:
        raise ValueError("Unknown suite profile")
    if manifest and (body["format"] != "spades-test-suite" or type(body["version"]) is not int or body["version"] != 1
                     or (body["dataset_version"], body["grading_version"]) != VERSIONS[profile]):
        raise ValueError("Suite format, dataset or grading version is incompatible")
    cases = select_cases(profile=profile, case_ids=body["case_ids"])
    if not manifest and (("id" in body) != ("revision" in body)):
        raise ValueError("Suite updates require both ID and revision")
    if "revision" in body and (type(body["revision"]) is not int or body["revision"] < 1):
        raise ValueError("Suite revision must be a positive integer")
    dataset, grading = VERSIONS[profile]
    return {"name": name.strip(), "description": description, "profile": profile,
            "case_ids": [case.case_id for case in cases], "dataset_version": dataset,
            "grading_version": grading, "plan": plan_cases(cases)}


def plan_cases(cases):
    domains, families = {}, {}
    records, characters, assertions = 0, 0, 0
    for case in cases:
        domain = case.domain or case.case_id.split("-")[0]
        domains[domain] = domains.get(domain, 0) + 1
        families[case.category] = families.get(case.category, 0) + 1
        documents = [case.legitimate] + case.supporting + case.distractors + ([case.poison] if case.poison else [])
        records += len(documents) + 1  # Runtime adds the restricted synthetic appendix.
        characters += sum(len(document.text) for document in documents)
        assertions += len(case.rubric)
    return {"scenarios": len(cases), "model_responses": len(cases) * 2,
            "domains": domains, "families": families, "source_records": records,
            "fixture_characters": characters, "typed_assertions_per_arm": assertions,
            "paired_typed_assertions": assertions * 2,
            "foundation_fact_checks": sum(case.profile == "foundation" for case in cases) * 2,
            "note": "Source volume precedes chunking and retrieval; fixture characters exclude the runtime appendix. Assessment counts describe the selected fixtures, not expected successes or runtime."}


def export_suite(suite):
    return {"format": "spades-test-suite", "version": 1,
            **{key: suite[key] for key in ("name", "description", "profile", "case_ids", "dataset_version", "grading_version")}}
