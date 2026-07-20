import json

from agentchange.raw_capture import capture_payload, derive_session_key


def test_session_start_creates_one_jsonl_line(tmp_path):
    fixture = json.loads(
        open("fixtures/codex_hooks/session_start.json", encoding="utf-8").read()
    )
    envelope = capture_payload(fixture, tmp_path)
    events = (
        tmp_path
        / "sessions"
        / derive_session_key("demo-session-001")
        / "events.jsonl"
    )
    lines = events.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == envelope
    assert envelope["source_event"] == "SessionStart"
