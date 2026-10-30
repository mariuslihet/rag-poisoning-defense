"""Portable, validated scenario suites and inference-free run planning."""

from .evaluation import select_cases
from .datasets import VERSIONS, dataset_identity


def validate_suite(body, manifest=False):
    required = {"name", "description", "profile", "case_ids"}
    if manifest:
        required |= {"format", "version", "dataset_version", "grading_version"}
    allowed = (required if manifest else required | {"id", "revision"}) | {"case_definitions"}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - allowed:
        raise ValueError("Expected a suite name, description, profile and exact scenario IDs")
    name, description, profile = body["name"], body["description"], body["profile"]
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("Suite names must contain 1–100 characters")
    if not isinstance(description, str) or len(description) > 1000:
        raise ValueError("Suite descriptions must contain at most 1000 characters")
    if not isinstance(profile, str) or profile not in VERSIONS:
        raise ValueError("Unknown suite profile")
    definitions = body.get("case_definitions")
    if definitions is not None:
        from .authoring import validate_definition
        if not isinstance(definitions,list) or not 1 <= len(definitions) <= 100:
            raise ValueError("Expected 1–100 frozen custom definitions")
        definitions=[validate_definition(item) for item in definitions]
    cases = select_cases(profile=profile, case_ids=body["case_ids"], case_definitions=definitions)
    if definitions is not None:
        lookup={definition["case_id"]:definition for definition in definitions}
        definitions=[lookup[case.case_id] for case in cases]
    dataset, grading = dataset_identity(profile, definitions)
    if manifest and (body["format"] != "spades-test-suite" or type(body["version"]) is not int or body["version"] != 1
                     or (body["dataset_version"], body["grading_version"]) != (dataset,grading)):
        raise ValueError("Suite format, dataset or grading version is incompatible")
    if not manifest and (("id" in body) != ("revision" in body)):
        raise ValueError("Suite updates require both ID and revision")
    if "revision" in body and (type(body["revision"]) is not int or body["revision"] < 1):
        raise ValueError("Suite revision must be a positive integer")
    return {"name": name.strip(), "description": description, "profile": profile,
            "case_ids": [case.case_id for case in cases], "dataset_version": dataset,
            "grading_version": grading, "plan": plan_cases(cases), **({"case_definitions":definitions} if definitions is not None else {})}


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
            **{key: suite[key] for key in ("name", "description", "profile", "case_ids", "dataset_version", "grading_version")},
            **({"case_definitions":suite["case_definitions"]} if suite.get("case_definitions") is not None else {})}


def compare_suite_revisions(reference, candidate):
    old, new = reference["case_ids"], candidate["case_ids"]
    before={item["case_id"]:item for item in reference.get("case_definitions",[])}
    after={item["case_id"]:item for item in candidate.get("case_definitions",[])}
    common=set(old)&set(new)
    return {"reference_revision":reference["revision"], "candidate_revision":candidate["revision"],
            "added":[case_id for case_id in new if case_id not in old], "removed":[case_id for case_id in old if case_id not in new],
            "order_changed":[case_id for case_id in old if case_id in common] != [case_id for case_id in new if case_id in common],
            "definition_changes":[case_id for case_id in new if case_id in common and before.get(case_id) != after.get(case_id)],
            "metadata_changes":{key:{"reference":reference.get(key),"candidate":candidate.get(key)}
                                for key in ("name","description","profile","dataset_version","grading_version") if reference.get(key)!=candidate.get(key)}}
