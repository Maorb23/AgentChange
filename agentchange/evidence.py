"""Chronological, same-turn evidence analysis."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from .models import Finding, NormalizedEvent, ValidationRecord
from .normalize import normalize_envelope
from .display import display_command as make_display_command, sanitize_text

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


def _command_parts(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return command
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def validation_category(command: str | list[str]) -> str:
    parts = _command_parts(command)
    lowered = " ".join(parts).lower()
    for index, part in enumerate(parts[:-1]):
        if PurePosixPath(part.replace("\\", "/")).name.lower() != "manage.py":
            continue
        if index == 0 or not re.fullmatch(
            r"python(?:\d+(?:\.\d+)*)?",
            PurePosixPath(parts[index - 1].replace("\\", "/")).name.lower(),
        ):
            continue
        action = parts[index + 1].lower()
        if action == "check":
            return "django_system_check"
        if action == "test":
            return "django_test"
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


def _command_tokens(command: str, marker: dict[str, Any], key: str) -> list[str]:
    value = marker.get(key)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if "--" in tokens and any("agentchange-run" in token for token in tokens[: tokens.index("--")]):
        return tokens[tokens.index("--") + 1 :]
    for index, token in enumerate(tokens):
        if token.rsplit("/", 1)[-1] == "agentchange" and tokens[index + 1 : index + 3] == ["exec", "--auto"]:
            return tokens[index + 3 :]
    return tokens


def validation_scope(tokens: list[str], category: str, display: str | None = None) -> str:
    if category in {"django_system_check", "django_test"}:
        return sanitize_text(display or make_display_command(tokens))
    if category != "test":
        return "Selected command"
    pytest_index = next(
        (index for index, token in enumerate(tokens) if token.rsplit("/", 1)[-1] == "pytest"),
        None,
    )
    if pytest_index is None:
        return "Selected tests"
    arguments = tokens[pytest_index + 1 :]
    options_with_value = {"-k", "-m", "--maxfail", "--tb", "--rootdir", "-c", "--confcutdir"}
    scope: list[str] = []
    skip_next = False
    for token in arguments:
        if skip_next:
            skip_next = False
            continue
        if token in options_with_value:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        scope.append(sanitize_text(token))
    return ", ".join(scope) if scope else "Project pytest discovery"


def _validation_status(
    category: str,
    authoritative: bool,
    exit_code: int | None,
    response: Any,
    marker: dict[str, Any],
) -> str:
    if not authoritative or exit_code is None:
        return "unknown"
    if exit_code == 0:
        return "passed"
    if exit_code == 127 or marker.get("error_kind") == "command_not_found":
        return "command_not_found"
    if exit_code == 126 or marker.get("error_kind") == "permission_denied":
        return "infrastructure_error"
    if category not in {"test", "django_test"}:
        return "failed"
    text = json.dumps(response, ensure_ascii=False).lower()
    if re.search(r"\b\d+\s+failed\b|=+\s*failures\s*=+|assertionerror|failed\s*\(.*failures?=|\bfail:", text):
        return "failed"
    if any(
        pattern in text
        for pattern in (
            "internalerror",
            "error collecting",
            "importerror while loading conftest",
            "modulenotfounderror",
            "no tests ran",
            "usage error",
        )
    ) or exit_code in {2, 3, 4, 5}:
        return "infrastructure_error"
    return "unknown"


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
        runner_results = event.details.get("runner_results")
        markers = [item for item in runner_results if isinstance(item, dict)] if isinstance(runner_results, list) else []
        if not markers:
            fallback = event.details.get("runner_metadata")
            marker = dict(fallback) if isinstance(fallback, dict) else {}
            if event.exit_code is not None:
                marker.update({"exit_code": event.exit_code, "duration_ms": event.duration_ms})
            markers = [marker]
        for marker_index, marker in enumerate(markers):
            marker_exit_code = marker.get("exit_code")
            marker_duration = marker.get("duration_ms")
            authoritative = event.evidence_confidence == "observed" and isinstance(marker_exit_code, int)
            requested = _command_tokens(event.command, marker, "requested_command")
            resolved = _command_tokens(event.command, marker, "resolved_command")
            category = validation_category(requested or resolved or event.command)
            status = _validation_status(
                category,
                authoritative,
                marker_exit_code if isinstance(marker_exit_code, int) else None,
                event.details.get("tool_response"),
                marker,
            )
            display = marker.get("display_command")
            display = sanitize_text(display) if isinstance(display, str) else make_display_command(resolved)
            records.append(
                ValidationRecord(
                    validation_id=hashlib.sha256(f"{event.event_id}:validation:{marker_index}".encode()).hexdigest()[:20],
                    tool_use_id=event.tool_use_id,
                    category=category,
                    command=event.command,
                    status=status,
                    authoritative=authoritative,
                    result_source=str(event.details.get("result_source", "not authoritative")),
                    requested_command=requested,
                    resolved_command=resolved,
                    display_command=display,
                    scope=validation_scope(requested or resolved, category, display),
                    exit_code=marker_exit_code if authoritative else None,
                    duration_ms=marker_duration if authoritative and isinstance(marker_duration, int) else None,
                    attempted_event_id=attempts.get(event.tool_use_id).event_id if event.tool_use_id in attempts else None,
                    completed_event_id=event.event_id,
                    line_number=event.line_number or 0,
                    timestamp=event.timestamp,
                )
            )
    return records


def overall_validation_status(validations: list[ValidationRecord]) -> str:
    authoritative = [record for record in validations if record.authoritative]
    if any(record.status in {"failed", "command_not_found", "infrastructure_error"} for record in authoritative):
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

    claim_category = lambda category: "test" if category == "django_test" else category
    failed_categories = {claim_category(record.category) for record in validations if record.authoritative and record.status == "failed"}
    passed_categories = {claim_category(record.category) for record in validations if record.authoritative and record.status == "passed"}
    uncertain = [record for record in validations if record.status in {"unknown", "command_not_found", "infrastructure_error"}]
    if "test" in failed_categories:
        findings.append(_finding("TESTS_FAILED", "high", "An authoritative same-turn test command failed."))
    if uncertain:
        findings.append(_finding("TEST_RESULT_UNKNOWN", "medium", "At least one validation attempt did not produce a verified pass/fail result."))
    if any(record.status == "command_not_found" for record in validations):
        findings.append(_finding("VALIDATION_COMMAND_NOT_FOUND", "medium", "A validation command could not start because an executable was unavailable."))
    if any(record.status == "infrastructure_error" for record in validations):
        findings.append(_finding("VALIDATION_INFRASTRUCTURE_ERROR", "medium", "A validation command encountered an infrastructure or collection error."))
    for category in claims:
        if category in failed_categories:
            findings.append(_finding("TEST_CLAIM_CONTRADICTION", "critical", f"Codex reported that {category} validation passed, but same-turn observed evidence records a failure."))
        elif category not in passed_categories:
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
    if substantive and not any(record.category in {"test", "django_test"} for record in validations):
        findings.append(_finding("NO_TEST_EVIDENCE", "medium", "Substantive code changed without a captured same-turn test command.", substantive))
    if any(event.event_type.value.startswith("mcp_tool") for event in events):
        findings.append(_finding("EXTERNAL_OR_MCP_TOOL_USED", "low", "An MCP or external tool path was observed; its external side effects may not be represented in local Git."))
    permission_events = [event for event in events if event.source_event == "PermissionRequest"]
    if permission_events:
        findings.append(_finding("PERMISSION_REQUESTED", "low", "A permission request was observed; the final human decision was not captured."))
    if not stop_events:
        findings.append(_finding("SESSION_INCOMPLETE", "medium", "No same-turn Stop event was captured."))

    repository_root = attribution.get("repository_root")

    def repository_relative(path: Any) -> str | None:
        normalized = posixpath.normpath(str(path).replace("\\", "/"))
        if normalized.startswith("/"):
            if not repository_root:
                return None
            root = posixpath.normpath(str(repository_root).replace("\\", "/"))
            prefix = root.rstrip("/") + "/"
            if normalized == root:
                return "."
            if not normalized.startswith(prefix):
                return None
            return normalized[len(prefix) :]
        if normalized == ".." or normalized.startswith("../"):
            return None
        return normalized.removeprefix("./")

    captured_writes = [
        str(path)
        for event in events
        if event.event_type.value.startswith("file_change")
        for path in event.details.get("paths", [])
    ]
    observed_writes = {
        relative
        for path in captured_writes
        if (relative := repository_relative(path)) is not None
    }
    outside_writes = [path for path in captured_writes if repository_relative(path) is None]
    final_changed = {posixpath.normpath(item["path"].replace("\\", "/")) for item in classifications if item.get("final_status")}
    missing_git = sorted(outside_writes + [path for path in observed_writes if path not in final_changed])
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
        "requested_task": next((event.prompt for event in events if event.source_event == "UserPromptSubmit" and event.prompt), None),
        "model": next((event.model for event in reversed(events) if event.model), None),
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
