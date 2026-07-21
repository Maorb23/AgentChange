"""Deterministic and inspectable Phase 2 risk rules."""

from __future__ import annotations

from typing import Any


WEIGHTS = {
    "AUTH_CODE_CHANGED": 25,
    "INFRASTRUCTURE_CHANGED": 20,
    "CI_CHANGED": 20,
    "MIGRATION_CHANGED": 15,
    "DEPENDENCY_CHANGED": 10,
    "NO_TEST_EVIDENCE": 10,
    "TEST_RESULT_UNKNOWN": 10,
    "TEST_CLAIM_CONTRADICTION": 30,
    "VALIDATION_CLAIM_NOT_VERIFIABLE": 10,
    "NEW_UNTRACKED_FILE": 10,
    "EXTERNAL_OR_MCP_TOOL_USED": 5,
    "SESSION_INCOMPLETE": 10,
}


def score_risk(analysis: dict[str, Any], attribution_available: bool) -> dict[str, Any]:
    codes = {finding.code for finding in analysis["findings"]}
    components: list[dict[str, Any]] = []
    baseline_required = {
        "AUTH_CODE_CHANGED", "INFRASTRUCTURE_CHANGED", "CI_CHANGED", "MIGRATION_CHANGED",
        "DEPENDENCY_CHANGED", "NO_TEST_EVIDENCE", "NEW_UNTRACKED_FILE",
    }
    for code, weight in WEIGHTS.items():
        if code in codes and (attribution_available or code not in baseline_required):
            components.append({"rule": code, "points": weight})
    if any(record.authoritative and record.status == "failed" for record in analysis["validations"]):
        components.append({"rule": "OBSERVED_VALIDATION_FAILURE", "points": 25})
    if attribution_available and len(analysis["introduced_paths"]) > 30:
        components.append({"rule": "MORE_THAN_30_TURN_ATTRIBUTED_FILES", "points": 10})
    if analysis.get("sensitive_permission"):
        components.append({"rule": "SENSITIVE_PERMISSION_REQUESTED", "points": 5})
    # Phase 2 hooks do not capture a reliable approval decision, so the approval reduction is not applied.
    if attribution_available and analysis["docs_only"]:
        components.append({"rule": "DOCS_ONLY", "points": -10})
    total = max(0, min(100, sum(component["points"] for component in components)))
    level = "low" if total < 25 else "moderate" if total < 50 else "high" if total < 75 else "critical"
    return {"score": total, "level": level, "components": components, "method": "deterministic rules v1"}
