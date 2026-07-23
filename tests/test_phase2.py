import json
import subprocess
import urllib.error
import hashlib
from pathlib import Path

from agentchange.evidence import analyze_turn, extract_validations, load_turn_events, overall_validation_status
from agentchange.finalizer import finalize_turn
from agentchange.git_analysis import capture_git_snapshot, classify_changes, ensure_git_baseline, turn_directory
from agentchange.raw_capture import capture_payload, derive_session_key
from agentchange.slack import ensure_delivery
from agentchange.receipt import canonical_bytes
from agentchange.risk import score_risk


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "agentchange@example.invalid")
    git(repo, "config", "user.name", "AgentChange Test")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-qm", "baseline")
    return repo


def payload(repo: Path, event: str, *, session="phase2-session", turn="turn-a", **extra):
    value = {
        "session_id": session,
        "cwd": str(repo),
        "hook_event_name": event,
        "turn_id": turn,
        "model": "gpt-5.6",
        "permission_mode": "default",
    }
    value.update(extra)
    return value


def test_git_baseline_does_not_attribute_preexisting_untracked_file(tmp_path):
    repo = init_repo(tmp_path)
    data = tmp_path / "data"
    (repo / "old.py").write_text("old = True\n", encoding="utf-8")
    path = ensure_git_baseline(data, "s", "t", str(repo))
    baseline = json.loads(path.read_text(encoding="utf-8"))
    (repo / "new.py").write_text("new = True\n", encoding="utf-8")
    attribution = classify_changes(baseline, capture_git_snapshot(str(repo)))
    values = {item["path"]: item["classification"] for item in attribution["classifications"]}
    assert values["old.py"] == "Pre-existing change"
    assert values["new.py"] == "New during this turn"


def test_git_attribution_detects_modified_further_and_removed_dirty_state(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "README.md").write_text("dirty baseline\n", encoding="utf-8")
    (repo / "temporary.py").write_text("temporary = True\n", encoding="utf-8")
    baseline = capture_git_snapshot(str(repo))
    (repo / "README.md").write_text("changed again\n", encoding="utf-8")
    (repo / "temporary.py").unlink()
    attribution = classify_changes(baseline, capture_git_snapshot(str(repo)))
    values = {item["path"]: item["classification"] for item in attribution["classifications"]}
    assert values["README.md"] == "Modified further during this turn"
    assert values["temporary.py"] == "No longer present at Stop"


def test_missing_baseline_uses_exact_attribution_limitation(tmp_path):
    repo = init_repo(tmp_path)
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    attribution = classify_changes(None, capture_git_snapshot(str(repo)))
    assert attribution["limitation"] == "Repository changes observed at Stop; turn-level attribution unavailable."
    assert attribution["classifications"][0]["classification"] == "Attribution unknown"


def _envelope(event_id, timestamp, turn_id, event, *, tool_id=None, command=None, response=None, statement=None):
    data = {
        "capture_version": "1",
        "event_id": event_id,
        "captured_at": timestamp,
        "session_id": "session-order",
        "source_event": event,
        "payload": {
            "session_id": "session-order",
            "turn_id": turn_id,
            "cwd": "/repo",
            "hook_event_name": event,
        },
    }
    if tool_id:
        data["payload"].update({"tool_name": "Bash", "tool_use_id": tool_id, "tool_input": {"command": command}})
    if response is not None:
        data["payload"]["tool_response"] = response
    if statement:
        data["payload"]["last_assistant_message"] = statement
    return data


def test_events_sort_by_timestamp_isolate_turn_and_preserve_parallel_validations(tmp_path):
    path = tmp_path / "events.jsonl"
    marker0 = '__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":0,"duration_ms":83}'
    marker1 = '1 failed\n__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":1,"duration_ms":29}'
    lines = [
        _envelope("post-b", "2026-07-20T10:00:04Z", "turn-a", "PostToolUse", tool_id="b", command="agentchange-run -- ruff check .", response=marker0),
        _envelope("other", "2026-07-20T10:00:01Z", "turn-b", "PostToolUse", tool_id="x", command="agentchange-run -- pytest -q", response=marker1),
        _envelope("pre-b", "2026-07-20T10:00:02Z", "turn-a", "PreToolUse", tool_id="b", command="agentchange-run -- ruff check ."),
        _envelope("post-a", "2026-07-20T10:00:03Z", "turn-a", "PostToolUse", tool_id="a", command="agentchange-run -- pytest -q", response=marker1),
        _envelope("pre-a", "2026-07-20T10:00:00Z", "turn-a", "PreToolUse", tool_id="a", command="agentchange-run -- pytest -q"),
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    events, errors = load_turn_events(path, "turn-a")
    assert not errors
    assert [event.event_id for event in events] == ["pre-a", "pre-b", "post-a", "post-b"]
    assert [event.line_number for event in events] == [5, 3, 4, 1]
    validations = extract_validations(events)
    assert [(item.tool_use_id, item.status, item.attempted_event_id) for item in validations] == [
        ("a", "failed", "pre-a"),
        ("b", "passed", "pre-b"),
    ]
    assert overall_validation_status(validations) == "failed"


def test_claim_comparison_distinguishes_contradiction_from_unverifiable(tmp_path):
    path = tmp_path / "events.jsonl"
    failed = '1 failed\n__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":1,"duration_ms":29}'
    lines = [
        _envelope("failed", "2026-07-20T10:00:00Z", "turn-a", "PostToolUse", tool_id="a", command="agentchange-run -- pytest -q", response=failed),
        _envelope("stop-a", "2026-07-20T10:00:01Z", "turn-a", "Stop", statement="All tests pass."),
        _envelope("stop-b", "2026-07-20T10:00:02Z", "turn-b", "Stop", statement="All tests pass."),
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    empty_attribution = {"available": True, "limitation": None, "classifications": []}
    a, _ = load_turn_events(path, "turn-a")
    b, _ = load_turn_events(path, "turn-b")
    codes_a = {item.code for item in analyze_turn(a, empty_attribution)["findings"]}
    codes_b = {item.code for item in analyze_turn(b, empty_attribution)["findings"]}
    assert "TEST_CLAIM_CONTRADICTION" in codes_a
    assert "VALIDATION_CLAIM_NOT_VERIFIABLE" not in codes_a
    assert "VALIDATION_CLAIM_NOT_VERIFIABLE" in codes_b
    assert "TEST_CLAIM_CONTRADICTION" not in codes_b


def test_stop_finalization_is_local_first_turn_scoped_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    repo = init_repo(tmp_path)
    data = tmp_path / "data"
    session, turn = "receipt-session", "receipt-turn"
    capture_payload(payload(repo, "UserPromptSubmit", session=session, turn=turn, prompt="Change auth"), data)
    ensure_git_baseline(data, session, turn, str(repo))
    (repo / "auth.py").write_text("enabled = True\n", encoding="utf-8")
    capture_payload(payload(repo, "PreToolUse", session=session, turn=turn, tool_name="apply_patch", tool_use_id="patch", tool_input={"command": "*** Begin Patch\n*** Add File: auth.py\n+x\n*** End Patch"}), data)
    command = "agentchange-run -- pytest -q"
    capture_payload(payload(repo, "PreToolUse", session=session, turn=turn, tool_name="Bash", tool_use_id="test", tool_input={"command": command}), data)
    capture_payload(payload(repo, "PostToolUse", session=session, turn=turn, tool_name="Bash", tool_use_id="test", tool_input={"command": command}, tool_response='1 failed\n__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":1,"duration_ms":29}'), data)
    capture_payload(payload(repo, "PostToolUse", session=session, turn="other-turn", tool_name="Bash", tool_use_id="other", tool_input={"command": command}, tool_response='__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":0,"duration_ms":83}'), data)
    stop = payload(repo, "Stop", session=session, turn=turn, last_assistant_message="All tests pass.")
    capture_payload(stop, data)  # Stop is always evidence before finalization.

    delivery_checks = []
    def local_first(plugin_data, directory, receipt, **kwargs):
        assert (directory / "receipt.json").exists()
        assert (directory / "receipt.md").exists()
        assert (directory / "turn.diff").exists()
        assert (directory / "finalization.json").exists()
        delivery_checks.append(receipt["receipt_id"])
        return {"state": "not_configured"}
    monkeypatch.setattr("agentchange.finalizer.ensure_delivery", local_first)
    first = finalize_turn(data, stop)
    directory = turn_directory(data, session, turn)
    first_json = (directory / "receipt.json").read_bytes()
    second = finalize_turn(data, stop)
    assert first["receipt_id"] == second["receipt_id"]
    assert (directory / "receipt.json").read_bytes() == first_json
    assert first["validation"]["overall_status"] == "failed"
    assert len(first["validation"]["commands"]) == 1
    assert "TEST_CLAIM_CONTRADICTION" in {item["code"] for item in first["findings"]}
    assert delivery_checks == [first["receipt_id"]]
    assert first["integrity"]["raw_jsonl"]["digest"] == hashlib.sha256(
        (directory.parents[1] / "events.jsonl").read_bytes()
    ).hexdigest()
    body = {key: value for key, value in first.items() if key != "integrity"}
    assert first["integrity"]["canonical_receipt_body"]["digest"] == hashlib.sha256(canonical_bytes(body)).hexdigest()


def test_risk_rules_score_observed_failure_and_skip_baseline_rules_without_attribution():
    class Record:
        authoritative = True
        status = "failed"
    class Item:
        def __init__(self, code):
            self.code = code
    analysis = {
        "findings": [Item("AUTH_CODE_CHANGED"), Item("TEST_CLAIM_CONTRADICTION")],
        "validations": [Record()],
        "introduced_paths": ["auth.py"],
        "docs_only": False,
        "sensitive_permission": False,
    }
    attributed = score_risk(analysis, True)
    unavailable = score_risk(analysis, False)
    assert attributed["score"] == 80  # auth 25 + contradiction 30 + observed failure 25
    assert unavailable["score"] == 55  # baseline-dependent auth rule is skipped


def test_slack_acceptance_is_not_sent_twice_on_repeated_stop(tmp_path, monkeypatch):
    turn_dir = tmp_path / "turn"
    turn_dir.mkdir()
    receipt = {"receipt_id": "acr_test", "risk": {"level": "low", "score": 0}, "findings": [], "validation": {"commands": []}}
    monkeypatch.setenv("AGENTCHANGE_SLACK_ENABLED", "true")
    monkeypatch.setenv("AGENTCHANGE_SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/SECRET")
    monkeypatch.setenv("AGENTCHANGE_SLACK_MODE", "summary")
    monkeypatch.setenv("AGENTCHANGE_SLACK_ON", "always")
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def getcode(self): return 200
    def accepted(request, timeout):
        calls.append(request)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", accepted)
    assert ensure_delivery(tmp_path, turn_dir, receipt)["state"] == "delivered"
    duplicate = ensure_delivery(tmp_path, turn_dir, receipt)
    assert duplicate["state"] == "duplicate_suppressed"
    assert duplicate["previous_state"] == "delivered"
    assert len(calls) == 1


def test_slack_failure_preserves_receipt_and_never_leaks_webhook(tmp_path, monkeypatch):
    turn_dir = tmp_path / "turn"
    turn_dir.mkdir()
    receipt = {"receipt_id": "acr_test", "risk": {"level": "low", "score": 0}, "findings": [], "validation": {"commands": []}}
    (turn_dir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    secret = "https://hooks.slack.com/services/T/B/SECRET"
    monkeypatch.setenv("AGENTCHANGE_SLACK_ENABLED", "true")
    monkeypatch.setenv("AGENTCHANGE_SLACK_WEBHOOK_URL", secret)
    monkeypatch.setenv("AGENTCHANGE_SLACK_MODE", "summary")
    monkeypatch.setenv("AGENTCHANGE_SLACK_ON", "always")
    calls = []
    def fail(request, timeout):
        calls.append(request.full_url)
        raise urllib.error.URLError("offline")
    monkeypatch.setattr("urllib.request.urlopen", fail)
    first = ensure_delivery(tmp_path, turn_dir, receipt)
    second = ensure_delivery(tmp_path, turn_dir, receipt)
    assert first["state"] == "failed_transient"
    assert second["state"] == "duplicate_suppressed"
    assert second["previous_state"] == "failed_transient"
    assert len(calls) == 2
    serialized = (turn_dir / "slack_delivery.json").read_text(encoding="utf-8")
    assert secret not in serialized and "SECRET" not in serialized
    assert (turn_dir / "receipt.json").exists()
