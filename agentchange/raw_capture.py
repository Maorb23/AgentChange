"""Dependency-free critical path for capturing Codex hook payloads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPTURE_VERSION = "1"
MAX_STRING_LENGTH = 8192
MAX_COLLECTION_ITEMS = 100
MAX_DEPTH = 8
TRUNCATED_VALUE = "[TRUNCATED]"
REDACTED_VALUE = "[REDACTED]"

_SENSITIVE_PARTS = {
    "authorization",
    "token",
    "accesstoken",
    "refreshtoken",
    "apikey",
    "password",
    "secret",
    "cookie",
    "setcookie",
    "webhook",
    "privatekey",
}
_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_KEY|APIKEY|WEBHOOK|PRIVATE_KEY)[A-Z0-9_]*)"
    r"\s*=\s*([^\s;,]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_SLACK_WEBHOOK = re.compile(r"https://hooks\.slack\.com/services/[^\s\"']+", re.IGNORECASE)


class CaptureError(ValueError):
    """Raised when a hook payload cannot be safely associated with a session."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def derive_session_key(session_id: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "-", session_id).strip("-._")
    readable = re.sub(r"\.{2,}", "-", readable)
    readable = (readable or "session")[:40]
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return f"{readable}-{digest}"


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _sanitize_string(value: str) -> str:
    value = _BEARER_SECRET.sub("Bearer [REDACTED]", value)
    value = _SLACK_WEBHOOK.sub(REDACTED_VALUE, value)
    value = _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED_VALUE}", value)
    if len(value) > MAX_STRING_LENGTH:
        original_length = len(value)
        value = value[:MAX_STRING_LENGTH] + f"\n[TRUNCATED: original length {original_length}]"
    return value


def sanitize_value(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return TRUNCATED_VALUE
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:MAX_COLLECTION_ITEMS]:
            string_key = str(key)
            sanitized[string_key] = (
                REDACTED_VALUE
                if _is_sensitive_key(key)
                else sanitize_value(item, depth + 1)
            )
        if len(items) > MAX_COLLECTION_ITEMS:
            sanitized["__truncated_items__"] = len(items) - MAX_COLLECTION_ITEMS
        return sanitized
    if isinstance(value, (list, tuple)):
        sanitized_list = [sanitize_value(item, depth + 1) for item in value[:MAX_COLLECTION_ITEMS]]
        if len(value) > MAX_COLLECTION_ITEMS:
            sanitized_list.append(f"[TRUNCATED: {len(value) - MAX_COLLECTION_ITEMS} items]")
        return sanitized_list
    if isinstance(value, str):
        return _sanitize_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_string(str(value))


def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="metadata-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def capture_payload(payload: dict[str, Any], plugin_data: str | os.PathLike[str]) -> dict[str, Any]:
    session_id = payload.get("session_id")
    source_event = payload.get("hook_event_name")
    if not isinstance(session_id, str) or not session_id.strip():
        raise CaptureError("hook payload requires a non-empty string session_id")
    if not isinstance(source_event, str) or not source_event.strip():
        raise CaptureError("hook payload requires a non-empty string hook_event_name")

    captured_at = utc_now()
    sanitized_payload = sanitize_value(payload)
    envelope = {
        "capture_version": CAPTURE_VERSION,
        "event_id": str(uuid.uuid4()),
        "captured_at": captured_at,
        "session_id": session_id,
        "source_event": source_event,
        "payload": sanitized_payload,
    }

    session_key = derive_session_key(session_id)
    session_dir = Path(plugin_data) / "sessions" / session_key
    session_dir.mkdir(parents=True, exist_ok=True)
    events_path = session_dir / "events.jsonl"
    encoded_line = (json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(events_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded_line)
    finally:
        os.close(descriptor)

    (session_dir / "normalization_errors.jsonl").touch(exist_ok=True)

    metadata_path = session_dir / "metadata.json"
    previous: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    metadata = {
        "session_key": session_key,
        "original_session_id": session_id,
        "initial_cwd": previous.get("initial_cwd", sanitized_payload.get("cwd")),
        "model": previous.get("model") or sanitized_payload.get("model"),
        "started_at": previous.get("started_at", captured_at),
        "last_event_at": captured_at,
        "event_count": int(previous.get("event_count", 0)) + 1,
        "last_source_event": source_event,
        "state": "stopped" if source_event == "Stop" else "active",
    }
    _write_metadata(metadata_path, metadata)
    return envelope


def record_normalization_error(
    plugin_data: str | os.PathLike[str], session_id: str, event_id: str, error: Exception
) -> None:
    session_dir = Path(plugin_data) / "sessions" / derive_session_key(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    error_record = {
        "event_id": event_id,
        "recorded_at": utc_now(),
        "error_type": type(error).__name__,
        "message": _sanitize_string(str(error)),
    }
    encoded_line = (json.dumps(error_record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(
        session_dir / "normalization_errors.jsonl",
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded_line)
    finally:
        os.close(descriptor)
