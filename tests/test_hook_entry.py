import json
import os
import subprocess
import sys

from agentchange.raw_capture import derive_session_key


def run_hook(tmp_path, text, *, no_site=False):
    command = [sys.executable]
    if no_site:
        command.append("-S")
    command.extend(["agentchange/hook_entry.py", "capture", "--plugin-data", str(tmp_path)])
    return subprocess.run(command, input=text, text=True, capture_output=True, check=False)


def test_stdin_hook_output_is_valid_json_and_raw_path_needs_no_pydantic(tmp_path):
    text = open("fixtures/codex_hooks/session_start.json", encoding="utf-8").read()
    result = run_hook(tmp_path, text, no_site=True)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_malformed_json_is_clear_and_does_not_damage_existing_evidence(tmp_path):
    valid = open("fixtures/codex_hooks/session_start.json", encoding="utf-8").read()
    assert run_hook(tmp_path, valid).returncode == 0
    path = tmp_path / "sessions" / derive_session_key("demo-session-001") / "events.jsonl"
    before = path.read_bytes()
    malformed = open("fixtures/codex_hooks/malformed.json", encoding="utf-8").read()
    result = run_hook(tmp_path, malformed)
    assert result.returncode == 1
    assert "capture failed" in result.stderr
    assert path.read_bytes() == before


def test_fixture_mode_uses_capture_then_prints_normalized_event(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentchange.hook_entry",
            "capture",
            "--fixture",
            "fixtures/codex_hooks/post_tool_use_bash_failed.json",
            "--plugin-data",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["result_status"] == "failed"
