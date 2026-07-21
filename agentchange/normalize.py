"""Conservative Pydantic normalization for captured hook envelopes."""

from __future__ import annotations

import json
import re
from typing import Any

from .models import EventType, NormalizedEvent

_RESULT_PREFIX = "__AGENTCHANGE_RESULT__="
_PATCH_PATH = re.compile(r"(?m)^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$")
_LEGACY_RUNNER = re.compile(r"(?:^|[\\/\s])agentchange-run(?:\.exe)?\s+--(?:\s|$)")
_AUTO_RUNNER = re.compile(r"(?:^|[\\/\s])agentchange(?:\.exe)?\s+exec\s+--auto(?:\s|$)")


def _response_texts(response: Any) -> list[str]:
    if isinstance(response, str):
        return [response]
    if isinstance(response, dict):
        texts: list[str] = []
        for value in response.values():
            texts.extend(_response_texts(value))
        return texts
    if isinstance(response, list):
        texts = []
        for value in response:
            texts.extend(_response_texts(value))
        return texts
    return []


def _parse_marker(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith(_RESULT_PREFIX):
        return None
    try:
        value = json.loads(stripped.removeprefix(_RESULT_PREFIX))
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("schema_version") != "1":
        return None
    exit_code = value.get("exit_code")
    duration_ms = value.get("duration_ms")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return None
    if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
        return None
    return value


def _command_result(
    command: str | None, response: Any
) -> tuple[int | None, int | None, str, str, list[str], dict[str, Any], list[dict[str, Any]]]:
    wrapper_count = sum(len(pattern.findall(command or "")) for pattern in (_LEGACY_RUNNER, _AUTO_RUNNER))
    authoritative_command = bool(
        command and wrapper_count
    )
    if not authoritative_command:
        return None, None, "unknown", "unknown", [], {}, []
    texts = _response_texts(response)
    marker_like_lines: list[str] = []
    valid_markers: list[tuple[dict[str, Any], bool]] = []
    for text in texts:
        nonempty_lines = [line for line in text.splitlines() if line.strip()]
        for index, line in enumerate(nonempty_lines):
            if _RESULT_PREFIX not in line:
                continue
            marker_like_lines.append(line)
            parsed = _parse_marker(line)
            if parsed is not None:
                valid_markers.append((parsed, index == len(nonempty_lines) - 1))

    if not marker_like_lines:
        return None, None, "unknown", "unknown", [], {}, []
    if len(valid_markers) > wrapper_count:
        return None, None, "unknown", "unknown", ["duplicate valid AgentChange result markers"], {}, []
    if not valid_markers:
        return None, None, "unknown", "unknown", ["malformed AgentChange result marker"], {}, []

    marker, is_final = valid_markers[-1]
    if not is_final:
        return None, None, "unknown", "unknown", ["AgentChange result marker was not final"], {}, []
    if len(valid_markers) > 1 and any(
        not isinstance(value.get("requested_command"), list)
        or not isinstance(value.get("resolved_command"), list)
        for value, _ in valid_markers
    ):
        return None, None, "unknown", "unknown", ["chained AgentChange markers lacked command metadata"], {}, []
    warnings = []
    if len(marker_like_lines) > 1:
        warnings.append("ignored malformed marker-like output before final result")
    return (
        marker["exit_code"],
        marker["duration_ms"],
        "succeeded" if marker["exit_code"] == 0 else "failed",
        "observed",
        warnings,
        marker,
        [value for value, _ in valid_markers],
    )


def normalize_envelope(envelope: dict[str, Any]) -> NormalizedEvent:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("captured envelope payload must be an object")
    source_event = envelope.get("source_event")
    if not isinstance(source_event, str):
        raise ValueError("captured envelope source_event must be a string")

    tool_name = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    command = command if isinstance(command, str) else None
    event_type = EventType.OTHER_TOOL_ATTEMPTED
    result_status = "not_applicable"
    confidence = "observed"
    exit_code = None
    duration_ms = None
    path = None
    details: dict[str, Any] = {"permission_mode": payload.get("permission_mode")}

    if source_event == "SessionStart":
        event_type = EventType.SESSION_STARTED
        details["source"] = payload.get("source")
    elif source_event == "UserPromptSubmit":
        event_type = EventType.USER_PROMPT_SUBMITTED
    elif source_event == "PermissionRequest":
        event_type = EventType.PERMISSION_REQUESTED
        result_status = "unknown"
        details.update(
            {
                "requested_action": command or tool_input,
                "description": tool_input.get("description") if isinstance(tool_input, dict) else None,
                "final_decision": "not captured",
            }
        )
    elif source_event == "Stop":
        event_type = EventType.TURN_STOPPED
        if payload.get("last_assistant_message") is not None:
            confidence = "reported"
        details["stop_hook_active"] = payload.get("stop_hook_active")
    elif source_event in {"PreToolUse", "PostToolUse"}:
        completed = source_event == "PostToolUse"
        if tool_name == "Bash":
            event_type = EventType.COMMAND_COMPLETED if completed else EventType.COMMAND_ATTEMPTED
            if completed:
                exit_code, duration_ms, result_status, confidence, warnings, marker, runner_results = _command_result(
                    command, payload.get("tool_response")
                )
                details["result_source"] = (
                    "agentchange-run final marker" if confidence == "observed" else "not authoritative"
                )
                if warnings:
                    details["normalization_warnings"] = warnings
                if marker:
                    details["runner_metadata"] = {
                        key: marker[key]
                        for key in (
                            "requested_command",
                            "resolved_command",
                            "display_command",
                            "error_kind",
                        )
                        if key in marker
                    }
                if runner_results:
                    details["runner_results"] = runner_results
        elif tool_name == "apply_patch":
            event_type = EventType.FILE_CHANGE_COMPLETED if completed else EventType.FILE_CHANGE_ATTEMPTED
            paths = _PATCH_PATH.findall(command or "")
            path = paths[0] if paths else None
            details["paths"] = paths
            if paths:
                confidence = "inferred"
        elif tool_name and tool_name.startswith("mcp__"):
            event_type = EventType.MCP_TOOL_COMPLETED if completed else EventType.MCP_TOOL_ATTEMPTED
        else:
            event_type = EventType.OTHER_TOOL_COMPLETED if completed else EventType.OTHER_TOOL_ATTEMPTED
        details["tool_input"] = tool_input
        if completed:
            details["tool_response"] = payload.get("tool_response")

    return NormalizedEvent(
        event_id=envelope["event_id"],
        session_id=envelope["session_id"],
        timestamp=envelope["captured_at"],
        event_type=event_type,
        source_event=source_event,
        cwd=payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
        model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        turn_id=payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None,
        prompt=payload.get("prompt") if isinstance(payload.get("prompt"), str) else None,
        tool_name=tool_name,
        tool_use_id=payload.get("tool_use_id") if isinstance(payload.get("tool_use_id"), str) else None,
        command=command,
        exit_code=exit_code,
        duration_ms=duration_ms,
        path=path,
        result_status=result_status,
        evidence_confidence=confidence,
        last_assistant_message=(
            payload.get("last_assistant_message")
            if isinstance(payload.get("last_assistant_message"), str)
            else None
        ),
        details=details,
        line_number=envelope.get("_line_number") if isinstance(envelope.get("_line_number"), int) else None,
    )
