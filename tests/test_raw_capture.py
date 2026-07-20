import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from agentchange.raw_capture import (
    CaptureError,
    MAX_STRING_LENGTH,
    capture_payload,
    derive_session_key,
)


def payload(session_id="session/with unsafe spaces", event="SessionStart", **extra):
    return {
        "session_id": session_id,
        "hook_event_name": event,
        "cwd": "C:/repo",
        "model": "gpt-test",
        **extra,
    }


def test_session_key_is_stable_safe_and_collision_resistant():
    key = derive_session_key("abc/../../session")
    assert key == derive_session_key("abc/../../session")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", key)
    assert ".." not in key
    assert key != derive_session_key("abc session")


def test_capture_creates_per_session_files_and_atomic_metadata(tmp_path):
    first = capture_payload(payload(), tmp_path)
    second = capture_payload(payload(event="Stop"), tmp_path)
    directory = tmp_path / "sessions" / derive_session_key(first["session_id"])
    lines = (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["event_count"] == 2
    assert metadata["state"] == "stopped"
    assert list(directory.glob("metadata-*.tmp")) == []
    assert (directory / "normalization_errors.jsonl").exists()
    assert first["event_id"] != second["event_id"]
    assert first["captured_at"].endswith("Z")
    assert datetime.fromisoformat(first["captured_at"].replace("Z", "+00:00")).utcoffset() is not None


def test_redaction_and_truncation(tmp_path):
    event = capture_payload(
        payload(
            authorization="Bearer should-not-survive",
            headers={"X-Api-Key": "secret-key", "Accept": "text/plain"},
            command="TOKEN=abc123 run " + "x" * (MAX_STRING_LENGTH + 100),
            webhook_url="https://hooks.slack.com/services/A/B/C",
        ),
        tmp_path,
    )
    serialized = json.dumps(event)
    assert "should-not-survive" not in serialized
    assert "secret-key" not in serialized
    assert "abc123" not in serialized
    assert "hooks.slack.com" not in serialized
    assert "[REDACTED]" in serialized
    assert "[TRUNCATED: original length" in serialized


def test_missing_session_id_writes_nothing(tmp_path):
    with pytest.raises(CaptureError):
        capture_payload({"hook_event_name": "Stop"}, tmp_path)
    assert not (tmp_path / "sessions").exists()


def test_concurrent_sessions_remain_separate(tmp_path):
    session_ids = [f"session-{number}" for number in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda value: capture_payload(payload(value), tmp_path), session_ids))
    directories = list((tmp_path / "sessions").iterdir())
    assert len(directories) == len(session_ids)
    assert all(len((directory / "events.jsonl").read_text().splitlines()) == 1 for directory in directories)
