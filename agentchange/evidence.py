"""Chronological, same-turn evidence analysis."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .models import Finding, NormalizedEvent, ValidationRecord
from .normalize import normalize_envelope

_CLAIMS = [
    ("test", re.compile(r"\b(?:all\s+tests?|tests?|test\s+suite)\s+(?:pass|passes|passed)\b", re.I)),
    ("lint", re.compile(r"\blint(?:ing)?\s+(?:pass|passes|passed)\b", re.I)),
    ("build", re.compile(r"\bbuild\s+(?:succeeded|passes|passed)\b", re.I)),
]
_CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".cs", ".swift",
}


def load_turn_events(events_path: Path, turn_id: str) -> tuple[list[NormalizedEvent], list[str]]:
    events: list[NormalizedEvent] = []
    errors: list[str] = []
    for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            envelope = json.loads(line)
            envelope["_line_number"] = line_number
            payload = envelope.get("payload")
            if not isinstance(payload, dict) or payload.get("turn_id") != turn_id:
                continue
            events.append(normalize_envelope(envelope))
        except Exception as exc:
            errors.append(f"line {line_number}: {type(exc).__name__}: {exc}")
    events.sort(key=lambda event: (event.timestamp, event.line_number or 0, event.event_id))
    return events, errors


def validation_category(command: str) -> str:
    lowered = command.lower()
    if re.search(r"\b(pytest|unittest|jest|vitest|mocha|go\s+test|cargo\s+test|npm\s+test|pnpm\s+test|yarn\s+test)\b", lowered):
        return "test"
    if re.search(r"\b(ruff|eslint|flake8|pylint|golangci-lint|cargo\s+clippy)\b", lowered):
        return "lint"
    if re.search(r"\b(mypy|pyright|tsc)\b", lowered):
        return "type_check"
    if re.search(r"\b(bandit|npm\s+audit|pip-audit|semgrep)\b", lowered):
        return "security"
    if re.search(r"\b(build|compile|cargo\s+build|go\s+build)\b", lowered):
        return "build"
    return "other"


def extract_validations(events: list[NormalizedEvent]) -> list[ValidationRecord]:
    attempts = {
        event.tool_use_id: event
        for event in events
        if event.source_event == "PreToolUse" and event.tool_use_id and event.command
    }
    records: list[ValidationRecord] = []
    for event in events:
        if event.source_event != "PostToolUse" or not event.command or event.tool_name != "Bash":
            continue
        category = validation_category(event.command)
        if category == "other" and "agentchange-run" not in event.command:
            continue
        status = {"succeeded": "passed", "failed": "failed"}.get(event.result_status, "unknown")
        authoritative = event.evidence_confidence == "observed" and event.exit_code is not None
        records.append(
            ValidationRecord(
                validation_id=hashlib.sha256(f"{event.event_id}:validation".encode()).hexdigest()[:20],
                tool_use_id=event.tool_use_id,
                category=category,
                command=event.command,
                status=status if authoritative else "unknown",
                authoritative=authoritative,
                result_source=str(event.details.get("result_source", "not authoritative")),
                exit_code=event.exit_code if authoritative else None,
                duration_ms=event.duration_ms if authoritative else None,
                attempted_event_id=attempts.get(event.tool_use_id).event_id if event.tool_use_id in attempts else None,
                completed_event_id=event.event_id,
                line_number=event.line_number or 0,
                timestamp=event.timestamp,
            )
        )
    return records


def overall_validation_status(validations: list[ValidationRecord]) -> str:
    authoritative = [record for record in validations if record.authoritative]
    if any(record.status == "failed" for record in authoritative):
        return "failed"
    if authoritative and all(record.status == "passed" for record in authoritative):
        return "passed"
    if validations:
        return "unknown"
    return "not_observed"


def _finding(code: str, severity: str, summary: str, evidence: list[str] | None = None) -> Finding:
    return Finding(code=code, severity=severity, summary=summary, evidence=evidence or [])


def _path_flags(path: str) -> set[str]:
    normalized = path.replace("\\", "/").lower()
    name = PurePosixPath(normalized).name
    flags: set[str] = set()
    if re.search(r"(^|[/_.-])(auth|oauth|authentication|authorization|password|security)([/_.-]|$)", normalized):
        flags.add("AUTH_CODE_CHANGED")
    if name in {"pyproject.toml", "uv.lock", "poetry.lock", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum"} or name.startswith("requirements"):
        flags.add("DEPENDENCY_CHANGED")
    if "/migrations/" in f"/{normalized}" or name.startswith("migration"):
        flags.add("MIGRATION_CHANGED")
    if normalized.startswith(".github/workflows/") or name in {".gitlab-ci.yml", "azure-pipelines.yml", "jenkinsfile"}:
        flags.add("CI_CHANGED")
    if normalized.endswith(".tf") or any(part in normalized for part in ("dockerfile", "docker-compose", "/helm/", "/k8s/", "/terraform/", "/deploy/")):
        flags.add("INFRASTRUCTURE_CHANGED")
    return flags


def analyze_turn(events: list[NormalizedEvent], attribution: dict[str, Any]) -> dict[str, Any]:
    validations = extract_validations(events)
    stop_events = [event for event in events if event.source_event == "Stop"]
    statement = stop_events[-1].last_assistant_message if stop_events else None
    claims = [category for category, pattern in _CLAIMS if statement and pattern.search(statement)]
    findings: list[Finding] = []

    failed_categories = {record.category for record in validations if record.authoritative and record.status == "failed"}
    observed_categories = {record.category for record in validations if record.authoritative}
    unknown_categories = {record.category for record in validations if not record.authoritative}
    if "test" in failed_categories:
        findings.append(_finding("TESTS_FAILED", "high", "An authoritative same-turn test command failed."))
    if unknown_categories:
        findings.append(_finding("TEST_RESULT_UNKNOWN", "medium", "At least one validation attempt had no authoritative result."))
    for category in claims:
        if category in failed_categories:
            findings.append(_finding("TEST_CLAIM_CONTRADICTION", "critical", f"Codex reported that {category} validation passed, but same-turn observed evidence records a failure."))
        elif category not in observed_categories:
            findings.append(_finding("VALIDATION_CLAIM_NOT_VERIFIABLE", "medium", f"Codex reported that {category} validation passed, but no matching authoritative same-turn result was captured."))

    classifications = attribution.get("classifications", [])
    introduced = [item for item in classifications if item["classification"] in {"New during this turn", "Modified further during this turn"}]
    preexisting = [item for item in classifications if item["classification"] == "Pre-existing change"]
    if preexisting:
        findings.append(_finding("PREEXISTING_REPOSITORY_CHANGES", "info", "Pre-existing repository changes were present and are not attributed to this turn.", [item["path"] for item in preexisting]))
    if not attribution.get("available"):
        findings.append(_finding("TURN_ATTRIBUTION_UNAVAILABLE", "medium", attribution["limitation"]))
    for code in sorted({flag for item in introduced for flag in _path_flags(item["path"])}):
        findings.append(_finding(code, "high" if code in {"AUTH_CODE_CHANGED", "CI_CHANGED", "INFRASTRUCTURE_CHANGED"} else "medium", code.replace("_", " ").title() + ".", [item["path"] for item in introduced if code in _path_flags(item["path"])]))
    new_untracked = [item["path"] for item in introduced if item.get("final_status") == "??"]
    if new_untracked:
        findings.append(_finding("NEW_UNTRACKED_FILE", "medium", "New untracked files were observed at Stop.", new_untracked))

    substantive = [item["path"] for item in introduced if PurePosixPath(item["path"].lower()).suffix in _CODE_SUFFIXES]
    if substantive and not any(record.category == "test" for record in validations):
        findings.append(_finding("NO_TEST_EVIDENCE", "medium", "Substantive code changed without a captured same-turn test command.", substantive))
    if any(event.event_type.value.startswith("mcp_tool") for event in events):
        findings.append(_finding("EXTERNAL_OR_MCP_TOOL_USED", "low", "An MCP or external tool path was observed; its external side effects may not be represented in local Git."))
    permission_events = [event for event in events if event.source_event == "PermissionRequest"]
    if permission_events:
        findings.append(_finding("PERMISSION_REQUESTED", "low", "A permission request was observed; the final human decision was not captured."))
    if not stop_events:
        findings.append(_finding("SESSION_INCOMPLETE", "medium", "No same-turn Stop event was captured."))

    observed_writes = {
        str(path).replace("\\", "/")
        for event in events
        if event.event_type.value.startswith("file_change")
        for path in event.details.get("paths", [])
    }
    final_changed = {item["path"].replace("\\", "/") for item in classifications if item.get("final_status")}
    missing_git = sorted(path for path in observed_writes if path not in final_changed)
    missing_write = sorted(path for path in (item["path"] for item in introduced) if path.replace("\\", "/") not in observed_writes)
    if missing_git:
        findings.append(_finding("WRITE_NOT_REFLECTED_IN_GIT", "low", "A captured write path was not present in the final Git changes.", missing_git))
    if missing_write:
        findings.append(_finding("GIT_CHANGE_WITHOUT_OBSERVED_WRITE", "low", "No matching write event was captured.", missing_write))

    deduplicated = {finding.code: finding for finding in findings}
    return {
        "events": events,
        "validations": validations,
        "overall_validation_status": overall_validation_status(validations),
        "agent_statement": statement,
        "claims": claims,
        "findings": [deduplicated[code] for code in sorted(deduplicated)],
        "introduced_paths": [item["path"] for item in introduced],
        "substantive_paths": substantive,
        "docs_only": bool(introduced) and all(PurePosixPath(item["path"].lower()).suffix in {".md", ".rst", ".txt"} for item in introduced),
        "sensitive_permission": any(
            re.search(r"\b(sudo|administrator|delete|remove-item|rm|network|install|credential|secret|sandbox)\b", json.dumps(event.details), re.I)
            for event in permission_events
        ),
    }
