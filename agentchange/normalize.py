"""Conservative Pydantic normalization for captured hook envelopes."""

from __future__ import annotations

import re
from typing import Any

from .models import EventType, NormalizedEvent

_TEXT_EXIT_CODE = re.compile(
    r"(?im)(?:process\s+)?exit(?:ed)?\s+(?:with\s+)?code\s*[:=]?\s*(-?\d+)\b"
)
_PATCH_PATH = re.compile(r"(?m)^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$")


def _structured_exit_code(response: Any) -> int | None:
    if not isinstance(response, dict):
        return None
    for key in ("exit_code", "exitCode"):
        value = response.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for value in response.values():
        result = _structured_exit_code(value)
        if result is not None:
            return result
    return None


def _text_from_response(response: Any) -> str | None:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("output", "text", "content", "stderr", "stdout"):
            value = response.get(key)
            if isinstance(value, str):
                return value
    return None


def _command_result(response: Any) -> tuple[int | None, str, str]:
    structured = _structured_exit_code(response)
    if structured is not None:
        return structured, ("succeeded" if structured == 0 else "failed"), "observed"
    text = _text_from_response(response)
    if text:
        match = _TEXT_EXIT_CODE.search(text)
        if match:
            code = int(match.group(1))
            return code, ("succeeded" if code == 0 else "failed"), "inferred"
    return None, "unknown", "unknown"


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
                exit_code, result_status, confidence = _command_result(payload.get("tool_response"))
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
        path=path,
        result_status=result_status,
        evidence_confidence=confidence,
        last_assistant_message=(
            payload.get("last_assistant_message")
            if isinstance(payload.get("last_assistant_message"), str)
            else None
        ),
        details=details,
    )
