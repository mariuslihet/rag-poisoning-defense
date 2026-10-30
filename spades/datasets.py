"""Stable identities for built-in and frozen operator-authored datasets."""
import hashlib
import json

VERSIONS = {"foundation": ("0.2", "substring-2"), "complex": ("enterprise-1.1", "typed-rubric-2")}


def dataset_identity(profile, case_definitions=None):
    if case_definitions is None:
        return VERSIONS[profile]
    digest = hashlib.sha256(json.dumps(case_definitions, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return "custom-" + digest, "typed-rubric-2"
