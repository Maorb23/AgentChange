import json

from agentchange.raw_capture import capture_payload, derive_session_key


def _fixture(name):
    return json.loads(
        open(f"fixtures/codex_hooks/{name}", encoding="utf-8").read()
    )


def test_bash_attempt_and_results_append_as_separate_events(tmp_path):
    names = [
        "pre_tool_use_bash.json",
        "post_tool_use_bash_success.json",
        "post_tool_use_bash_failed.json",
    ]
    for name in names:
        capture_payload(_fixture(name), tmp_path)

    events_path = (
        tmp_path
        / "sessions"
        / derive_session_key("demo-session-001")
        / "events.jsonl"
    )
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [event["source_event"] for event in events] == [
        "PreToolUse",
        "PostToolUse",
        "PostToolUse",
    ]
    assert events[1]["payload"]["tool_response"]["exit_code"] == 0
    assert events[2]["payload"]["tool_response"]["exit_code"] == 1
