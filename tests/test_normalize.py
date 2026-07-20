import json

from agentchange.models import EventType
from agentchange.normalize import normalize_envelope
from agentchange.raw_capture import capture_payload, derive_session_key
from agentchange.recorder import normalize_session


def fixture(name):
    return json.loads(open(f"fixtures/codex_hooks/{name}", encoding="utf-8").read())


def normalized(name, tmp_path):
    return normalize_envelope(capture_payload(fixture(name), tmp_path))


def test_bash_attempt_and_unwrapped_results_remain_unknown(tmp_path):
    attempted = normalized("pre_tool_use_bash.json", tmp_path)
    success = normalized("post_tool_use_bash_success.json", tmp_path)
    failure = normalized("post_tool_use_bash_failed.json", tmp_path)
    unknown_payload = fixture("post_tool_use_bash_success.json")
    unknown_payload["tool_response"] = {"output": "command finished"}
    unknown = normalize_envelope(capture_payload(unknown_payload, tmp_path))
    assert attempted.event_type == EventType.COMMAND_ATTEMPTED
    assert attempted.result_status == "not_applicable"
    assert (success.exit_code, success.result_status, success.evidence_confidence) == (None, "unknown", "unknown")
    assert (failure.exit_code, failure.result_status, failure.evidence_confidence) == (None, "unknown", "unknown")
    assert (unknown.exit_code, unknown.result_status, unknown.evidence_confidence) == (None, "unknown", "unknown")


def test_plain_text_exit_code_without_runner_marker_is_unknown(tmp_path):
    value = fixture("post_tool_use_bash_failed.json")
    value["tool_response"] = "Process exited with code 7"
    event = normalize_envelope(capture_payload(value, tmp_path))
    assert (event.exit_code, event.result_status, event.evidence_confidence) == (None, "unknown", "unknown")


def test_silent_live_bash_responses_are_unknown(tmp_path):
    success = normalized("post_tool_use_bash_silent_success.json", tmp_path)
    failure = normalized("post_tool_use_bash_silent_failed.json", tmp_path)
    assert (success.exit_code, success.result_status) == (None, "unknown")
    assert (failure.exit_code, failure.result_status) == (None, "unknown")


def test_valid_runner_markers_are_observed(tmp_path):
    success = normalized("post_tool_use_agentchange_runner_success.json", tmp_path)
    failure = normalized("post_tool_use_agentchange_runner_failed.json", tmp_path)
    assert (
        success.exit_code,
        success.duration_ms,
        success.result_status,
        success.evidence_confidence,
    ) == (0, 42, "succeeded", "observed")
    assert (
        failure.exit_code,
        failure.duration_ms,
        failure.result_status,
        failure.evidence_confidence,
    ) == (1, 51, "failed", "observed")


def test_malformed_marker_warns_and_remains_unknown(tmp_path):
    event = normalized("post_tool_use_agentchange_runner_malformed.json", tmp_path)
    assert (event.exit_code, event.duration_ms, event.result_status) == (None, None, "unknown")
    assert event.details["normalization_warnings"] == ["malformed AgentChange result marker"]


def test_misleading_lines_do_not_override_valid_final_marker(tmp_path):
    event = normalized("post_tool_use_agentchange_runner_misleading.json", tmp_path)
    assert (event.exit_code, event.duration_ms, event.result_status) == (0, 88, "succeeded")
    assert event.details["normalization_warnings"] == [
        "ignored malformed marker-like output before final result"
    ]


def test_duplicate_valid_markers_warn_and_remain_unknown(tmp_path):
    value = fixture("post_tool_use_agentchange_runner_success.json")
    value["tool_response"] = value["tool_response"] + "\n" + value["tool_response"]
    event = normalize_envelope(capture_payload(value, tmp_path))
    assert (event.exit_code, event.duration_ms, event.result_status) == (None, None, "unknown")
    assert event.details["normalization_warnings"] == ["duplicate valid AgentChange result markers"]


def test_patch_mcp_permission_prompt_and_stop(tmp_path):
    patch = normalized("pre_tool_use_patch.json", tmp_path)
    mcp = normalized("post_tool_use_mcp.json", tmp_path)
    permission = normalized("permission_request.json", tmp_path)
    prompt = normalized("user_prompt_submit.json", tmp_path)
    stop = normalized("stop.json", tmp_path)
    assert patch.event_type == EventType.FILE_CHANGE_ATTEMPTED
    assert patch.path == "app/auth/password_reset.py"
    assert patch.evidence_confidence == "inferred"
    assert mcp.event_type == EventType.MCP_TOOL_COMPLETED
    assert permission.event_type == EventType.PERMISSION_REQUESTED
    assert permission.result_status == "unknown"
    assert permission.details["final_decision"] == "not captured"
    assert prompt.prompt.startswith("Add password-reset")
    assert stop.event_type == EventType.TURN_STOPPED
    assert stop.last_assistant_message == "Implemented password-reset rate limiting. All tests pass."
    assert stop.evidence_confidence == "reported"


def test_missing_optional_and_unknown_fields_are_allowed(tmp_path):
    value = fixture("missing_optional_fields.json")
    value["future_codex_field"] = {"anything": True}
    event = normalize_envelope(capture_payload(value, tmp_path))
    assert event.source_event == "Stop"
    assert event.cwd is None


def test_normalization_failure_preserves_raw_and_records_error(tmp_path):
    captured = capture_payload(fixture("session_start.json"), tmp_path)
    session_id = captured["session_id"]
    directory = tmp_path / "sessions" / derive_session_key(session_id)
    broken = {**captured, "event_id": "broken-normalization", "payload": "not-an-object"}
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(broken) + "\n")
    events = normalize_session(tmp_path, session_id)
    raw_lines = (directory / "events.jsonl").read_text().splitlines()
    errors = (directory / "normalization_errors.jsonl").read_text().splitlines()
    assert len(events) == 1
    assert len(raw_lines) == 2
    assert len(errors) == 1
    assert json.loads(errors[0])["event_id"] == "broken-normalization"
