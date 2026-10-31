"""Create version-pinned regression suites from independent saved references."""

from copy import deepcopy
import re

from .authoring import validate_definition
from .datasets import dataset_identity
from .evaluation import select_cases
from .suites import export_suite, validate_suite


def report_record(reports, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Choose a valid saved experiment ID")
    record = reports.get(run_id)
    report = record[1] if isinstance(record, tuple) else record
    if not isinstance(report, dict) or report.get("run_id") != run_id:
        raise ValueError("The saved experiment is unavailable")
    return report


def build_regression_manifest(reports, body):
    """Recover grading references, never turn observed model answers into truth."""
    if not isinstance(body, dict) or set(body)-{"run_id","case_ids","name","description"} or not {"run_id","case_ids","name"} <= set(body):
        raise ValueError("Expected source experiment, exact case IDs and a regression suite name")
    report = report_record(reports, body["run_id"])
    ids = body["case_ids"]
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Choose 1–100 unique recorded scenario IDs")
    rows = report.get("results")
    if (not isinstance(rows, list) or any(not isinstance(row,dict) or not isinstance(row.get("case_id"),str) for row in rows)
            or len({row["case_id"] for row in rows}) != len(rows)):
        raise ValueError("The saved case observations have invalid identities")
    lookup = {row["case_id"]:row for row in rows}
    if not set(ids) <= set(lookup):
        raise ValueError("Every regression scenario must have a recorded observation in this experiment")
    config = report.get("configuration") or {}
    if not isinstance(config,dict):raise ValueError("The saved experiment settings are invalid")
    profile = config.get("profile", "foundation")
    if profile not in ("foundation","complex"):
        raise ValueError("The saved evaluation profile is unsupported")
    definitions = config.get("case_definitions")
    if definitions is not None:
        if not isinstance(definitions,list) or not 1 <= len(definitions) <= 100:
            raise ValueError("The original authored definitions are invalid")
        canonical = [validate_definition(definition) for definition in definitions]
        if canonical != definitions or len({item["case_id"] for item in definitions}) != len(definitions):
            raise ValueError("The original authored definitions are not canonical frozen references")
    identity = dataset_identity(profile, definitions)
    if (config.get("dataset_version"),config.get("grading_version")) != identity:
        raise ValueError("The original dataset or grading identity is unavailable or incompatible; do not reconstruct references from model responses")
    cases = select_cases(profile=profile,case_ids=ids,case_definitions=definitions)
    for case in cases:
        row = lookup[case.case_id]
        if profile == "complex":
            if row.get("rubric") != case.rubric or row.get("required_sources") != case.required_sources:
                raise ValueError("Recorded reference assertions or required sources differ from the recoverable scenario")
        elif row.get("expected") != case.expected:
            raise ValueError("The saved foundation reference differs from the compatible scenario")
    description = body.get("description", "")
    if not isinstance(description,str) or len(description) > 800:
        raise ValueError("Regression notes must contain at most 800 characters")
    source = f"Source experiment {report['run_id']}. Independent reference assertions preserved; observed model answers are not references."
    suite = {"name":body["name"],"description":(description.strip()+"\n"+source).strip(),"profile":profile,"case_ids":list(ids)}
    if definitions is not None:
        frozen = {item["case_id"]:item for item in definitions}
        suite["case_definitions"] = [deepcopy(frozen[case_id]) for case_id in ids]
    # Built-in scenarios remain pinned to the validated dataset/grading version;
    # authored scenarios carry their complete source and typed-reference data.
    return export_suite(validate_suite(suite))
