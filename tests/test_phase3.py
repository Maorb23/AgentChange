import json
import shutil
import subprocess
import urllib.error
from pathlib import Path

import pytest

from agentchange import cli
from agentchange.display import display_command, sanitize_text, validation_wording
from agentchange.doctor import collect_doctor
from agentchange.environment import PlatformInfo, detect_platform, detect_python
from agentchange.evidence import extract_validations
from agentchange.finalizer import claim_ui_continuation
from agentchange.git_analysis import turn_directory
from agentchange.hook_entry import main as hook_main
from agentchange.installer import VERSION, install, remove_stale_agentchange_caches, stop_hook_verified
from agentchange.normalize import normalize_envelope
from agentchange.receipt import render_markdown, render_ui_summary
from agentchange.slack import SlackSettings, ensure_delivery


def _event(command: str, response: str):
    return normalize_envelope(
        {
            "event_id": "evt",
            "session_id": "session",
            "captured_at": "2026-07-21T10:00:00Z",
            "source_event": "PostToolUse",
            "payload": {
                "session_id": "session",
                "turn_id": "turn",
                "cwd": "/home/example/project",
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_use_id": "tool",
                "tool_input": {"command": command},
                "tool_response": response,
            },
        }
    )


def _marker(exit_code: int, **extra) -> str:
    value = {"schema_version": "1", "exit_code": exit_code, "duration_ms": 1100, **extra}
    return "__AGENTCHANGE_RESULT__=" + json.dumps(value, separators=(",", ":"))


def _receipt(*, status="passed", slack="dry_run"):
    command = {
        "category": "test",
        "scope": "tests/test_example.py",
        "status": status,
        "exit_code": 0 if status == "passed" else 1,
        "duration_ms": 1100,
    }
    return {
        "receipt_id": "acr_123",
        "risk": {"level": "low", "score": 0, "components": []},
        "repository": {
            "name": "AgentChange",
            "branch": "main",
            "turn_changes": [{"path": "agentchange/example.py", "classification": "New during this turn"}],
            "preexisting_change_count": 5,
        },
        "event_summary": {"model": "gpt-5.6-terra"},
        "turn_change_count": 1,
        "validation": {"summary": "1 of 1 observed validation command passed", "commands": [command]},
        "slack": {"state": slack},
        "requested_task": {"value": "Run /home/example/project/.venv/bin/python tests"},
        "agent_statement": {"value": "AgentChange observed exit code 0."},
        "observed": {"event_count": 4, "authoritative_validation_count": 1},
        "findings": [],
        "limitations": ["Local evidence is not remote attestation."],
        "integrity": {},
    }


def test_scoped_receipt_wording_and_reported_observed_separation():
    receipt = _receipt()
    markdown = render_markdown(receipt, include_integrity=False)
    assert "**Validation:** 1 of 1 observed validation command passed" in markdown
    assert "| Test | `tests/test_example.py` | Passed | 0 | 1.1 s |" in markdown
    assert "## Reported by Codex\n\nAgentChange observed exit code 0." in markdown
    assert "Validation outcomes below come from runner markers" in markdown
    assert "already contained 5 modified or untracked files" in markdown
    assert "/home/example" not in markdown


def test_validation_wording_counts_the_observed_scope_only():
    assert validation_wording([{"status": "passed"}]) == "1 of 1 observed validation command passed"
    assert validation_wording([{"status": "passed"}, {"status": "failed"}]) == "1 of 2 observed validation commands passed"


def test_command_not_found_and_infrastructure_error_are_not_test_failures():
    missing = _event(
        "agentchange exec --auto pytest -q",
        _marker(127, error_kind="command_not_found", requested_command=["pytest", "-q"]),
    )
    crashed = _event(
        "agentchange exec --auto pytest -q",
        "ERROR collecting tests/test_example.py\n" + _marker(2, requested_command=["pytest", "-q"]),
    )
    assert extract_validations([missing])[0].status == "command_not_found"
    assert extract_validations([crashed])[0].status == "infrastructure_error"


def test_nonzero_without_assertion_evidence_is_unknown():
    event = _event("agentchange-run -- pytest -q", _marker(1))
    assert extract_validations([event])[0].status == "unknown"


def test_personal_paths_and_webhooks_are_sanitized():
    text = sanitize_text("/home/example/project https://hooks.slack.com/services/T/B/SECRET")
    assert text == "~/project [REDACTED]"
    assert display_command(["/home/example/.local/bin/agentchange-run"]) == "agentchange-run"
    assert display_command(["/home/example/project/.venv/bin/python", "-m", "pytest"]) == "python -m pytest"


def test_ui_summary_is_concise_and_path_safe():
    summary = render_ui_summary(_receipt())
    assert summary.startswith("AgentChange Receipt\n")
    assert "Scope: tests/test_example.py" in summary
    assert "Slack: Dry run" in summary
    assert "/home/" not in summary


def test_only_one_stop_continuation_is_claimed(tmp_path):
    turn = turn_directory(tmp_path, "session", "turn")
    turn.mkdir(parents=True)
    (turn / "finalization.json").write_text(
        json.dumps({"state": "completed", "ui_continuation_issued": False}), encoding="utf-8"
    )
    assert claim_ui_continuation(tmp_path, "session", "turn") is True
    assert claim_ui_continuation(tmp_path, "session", "turn") is False


def test_continuation_stop_exits_without_finalizing(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "stop.json"
    fixture.write_text(
        json.dumps(
            {
                "session_id": "session",
                "turn_id": "turn",
                "cwd": str(tmp_path),
                "hook_event_name": "Stop",
                "stop_hook_active": True,
                "last_assistant_message": "Done",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("agentchange.finalizer.finalize_turn", lambda *_: pytest.fail("must not regenerate"))
    assert hook_main(["finalize", "--fixture", str(fixture), "--plugin-data", str(tmp_path / "data")]) == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_first_stop_returns_one_documented_continuation(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "stop.json"
    fixture.write_text(
        json.dumps(
            {
                "session_id": "session",
                "turn_id": "turn",
                "cwd": str(tmp_path),
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "last_assistant_message": "Done",
            }
        ),
        encoding="utf-8",
    )
    receipt = _receipt()
    claims = iter((True, False))
    finalizations = []
    monkeypatch.setattr("agentchange.finalizer.load_finalized_receipt", lambda *_: None)
    monkeypatch.setattr(
        "agentchange.finalizer.finalize_turn",
        lambda *_: finalizations.append("finalized") or receipt,
    )
    monkeypatch.setattr("agentchange.finalizer.claim_ui_continuation", lambda *_: next(claims))
    monkeypatch.setattr("agentchange.git_analysis.ensure_git_baseline", lambda *_: None)
    monkeypatch.setattr("agentchange.slack.ensure_delivery", lambda *_args, **_kwargs: {"state": "duplicate_suppressed"})
    arguments = ["finalize", "--fixture", str(fixture), "--plugin-data", str(tmp_path / "data")]
    assert hook_main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["decision"] == "block"
    assert first["reason"].startswith("Display this concise receipt summary exactly once")
    assert "\n\nAgentChange Receipt\n" in first["reason"]
    assert hook_main(arguments) == 0
    assert capsys.readouterr().out.strip() == "{}"
    assert finalizations == ["finalized", "finalized"]


def _plugin_source(root: Path, version: str = VERSION) -> Path:
    source = root / "source"
    (source / ".codex-plugin").mkdir(parents=True)
    (source / "hooks").mkdir()
    (source / "skills" / "agentchange").mkdir(parents=True)
    (source / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "agentchange", "version": version}), encoding="utf-8"
    )
    (source / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "agentchange-hook finalize"}]}]}}),
        encoding="utf-8",
    )
    (source / "skills" / "agentchange" / "SKILL.md").write_text("# AgentChange\n", encoding="utf-8")
    return source


def test_install_is_idempotent_and_replaces_only_stale_agentchange_cache(tmp_path, monkeypatch):
    source = _plugin_source(tmp_path)
    stale = tmp_path / ".codex" / "plugins" / "cache" / "personal" / "agentchange" / "0.2.0"
    unrelated = tmp_path / ".codex" / "plugins" / "cache" / "personal" / "other" / "1.0.0"
    (stale / ".codex-plugin").mkdir(parents=True)
    (stale / "hooks").mkdir()
    (stale / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "agentchange", "version": "0.2.0"}), encoding="utf-8"
    )
    (stale / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "old finalizer"}]}]}}), encoding="utf-8"
    )
    (unrelated / ".codex-plugin").mkdir(parents=True)
    (unrelated / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "other", "version": "1.0.0"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "agentchange.installer.detect_platform",
        lambda: PlatformInfo(True, "wsl2", "WSL2 Ubuntu"),
    )
    which = lambda name: f"/usr/bin/{name}"
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        cached = tmp_path / ".codex" / "plugins" / "cache" / "personal" / "agentchange" / VERSION
        if not cached.exists():
            shutil.copytree(tmp_path / "plugins" / "agentchange", cached)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    first, _ = install(home=tmp_path, source=source, which=which, run=run)
    second, _ = install(home=tmp_path, source=source, which=which, run=run)
    assert first and second
    assert not stale.exists()
    assert unrelated.exists()
    marketplace = json.loads((tmp_path / ".agents" / "plugins" / "marketplace.json").read_text())
    assert [item["name"] for item in marketplace["plugins"]].count("agentchange") == 1
    assert len(calls) == 2


def test_stop_hook_verification_requires_the_finalizer(tmp_path):
    source = _plugin_source(tmp_path)
    assert stop_hook_verified(source)
    (source / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": []}}), encoding="utf-8")
    assert not stop_hook_verified(source)


def test_same_version_cache_with_old_content_is_stale(tmp_path):
    expected = _plugin_source(tmp_path / "expected")
    cached = tmp_path / ".codex" / "plugins" / "cache" / "personal" / "agentchange" / VERSION
    shutil.copytree(expected, cached)
    (cached / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "old finalizer"}]}]}}), encoding="utf-8"
    )
    removed = remove_stale_agentchange_caches(tmp_path, expected_root=expected)
    assert removed == [cached.resolve()]
    assert not cached.exists()


def test_wsl_and_native_linux_detection():
    assert detect_platform(sys_platform="linux", proc_version="Linux Microsoft WSL2", os_release='NAME="Ubuntu"', environ={}).kind == "wsl2"
    assert detect_platform(sys_platform="linux", proc_version="Linux generic", os_release='NAME="Debian"', environ={}).kind == "linux"
    unsupported = detect_platform(sys_platform="win32", environ={})
    assert not unsupported.supported and "WSL" in unsupported.correction


def test_dot_venv_is_detected_before_path_python(tmp_path):
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    assert detect_python(tmp_path, {}) == python.absolute()


def test_exec_auto_resolves_pytest_and_records_requested_command(tmp_path, monkeypatch):
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    recorded = {}

    def run(command, **kwargs):
        recorded["command"] = list(command)
        recorded.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_and_emit", run)
    assert cli.main(["exec", "--auto", "pytest", "-q", "tests/test_example.py"]) == 0
    assert recorded["command"] == [str(python.absolute()), "-m", "pytest", "-q", "tests/test_example.py"]
    assert recorded["requested_command"] == ["pytest", "-q", "tests/test_example.py"]
    assert recorded["display_command"] == "python -m pytest -q tests/test_example.py"


def test_doctor_gives_a_concrete_pytest_fix(tmp_path, monkeypatch):
    source = _plugin_source(tmp_path)
    target = tmp_path / "plugins" / "agentchange"
    target.parent.mkdir(parents=True)
    source.rename(target)
    marketplace = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(json.dumps({"plugins": [{"name": "agentchange"}]}), encoding="utf-8")
    cache = tmp_path / ".codex" / "plugins" / "cache" / "personal" / "agentchange" / VERSION
    shutil.copytree(target, cache)
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    monkeypatch.setattr("agentchange.doctor.git_root", lambda cwd: tmp_path)
    monkeypatch.setattr("agentchange.doctor.detect_python", lambda root: python)
    monkeypatch.setattr("agentchange.doctor.python_has_module", lambda *_: False)
    monkeypatch.setattr("agentchange.doctor.plugin_data_directories", lambda: [])
    monkeypatch.setattr("agentchange.doctor.finalization_files", lambda: [])
    ready, lines = collect_doctor(
        home=tmp_path,
        cwd=tmp_path,
        which=lambda name: f"/usr/bin/{name}",
        platform_info=PlatformInfo(True, "wsl2", "WSL2 Ubuntu"),
    )
    output = "\n".join(lines)
    assert not ready
    assert "pytest is unavailable" in output
    assert ".venv/bin/python -m pip install pytest" in output


def test_latest_prints_the_newest_markdown_receipt(tmp_path, monkeypatch, capsys):
    receipt = tmp_path / "receipt.md"
    receipt.write_text("# AgentChange Receipt\n", encoding="utf-8")
    monkeypatch.setattr(cli, "latest_receipt", lambda suffix: receipt)
    assert cli.main(["latest"]) == 0
    assert capsys.readouterr().out == "# AgentChange Receipt\n"


def _slack_receipt():
    return {
        "receipt_id": "acr_test",
        "requested_task": {"value": "Test safely"},
        "risk": {"level": "moderate", "score": 40},
        "findings": [],
        "validation": {"commands": [{"status": "passed"}]},
        "turn_change_count": 1,
    }


class _Response:
    def __init__(self, code=200):
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def getcode(self):
        return self.code


def _settings(*, retries=1):
    return SlackSettings(True, "https://hooks.slack.com/services/T/B/SECRET", 0.2, retries)


def test_slack_dry_run_and_success(tmp_path):
    dry = tmp_path / "dry"
    dry.mkdir()
    assert ensure_delivery(tmp_path, dry, _slack_receipt(), configuration=SlackSettings(False, None, 1, 0))["state"] == "dry_run"
    live = tmp_path / "live"
    live.mkdir()
    assert ensure_delivery(tmp_path, live, _slack_receipt(), configuration=_settings(retries=0), opener=lambda *_args, **_kwargs: _Response())["state"] == "delivered"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("timeout"), "failed_transient"),
        (urllib.error.HTTPError("redacted", 400, "bad", {}, None), "failed_permanent"),
    ],
)
def test_slack_timeout_and_permanent_failure(tmp_path, error, expected):
    turn = tmp_path / expected
    turn.mkdir()

    def fail(*_args, **_kwargs):
        raise error

    status = ensure_delivery(tmp_path, turn, _slack_receipt(), configuration=_settings(retries=0), opener=fail)
    assert status["state"] == expected
    assert "SECRET" not in (turn / "slack_delivery.json").read_text(encoding="utf-8")


def test_slack_transient_retry_and_duplicate_suppression(tmp_path):
    turn = tmp_path / "turn"
    turn.mkdir()
    calls = []

    def flaky(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("offline")
        return _Response()

    first = ensure_delivery(tmp_path, turn, _slack_receipt(), configuration=_settings(), opener=flaky, sleeper=lambda _: None)
    second = ensure_delivery(tmp_path, turn, _slack_receipt(), configuration=_settings(), opener=flaky)
    assert first["state"] == "delivered" and first["attempts"] == 2
    assert second["state"] == "duplicate_suppressed"
    assert len(calls) == 2


def test_slack_429_respects_retry_after(tmp_path):
    turn = tmp_path / "turn"
    turn.mkdir()
    calls = []
    sleeps = []

    def limited(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("redacted", 429, "limited", {"Retry-After": "0.25"}, None)
        return _Response()

    status = ensure_delivery(tmp_path, turn, _slack_receipt(), configuration=_settings(), opener=limited, sleeper=sleeps.append)
    assert status["state"] == "delivered"
    assert sleeps == [0.25]


def test_slack_failure_preserves_saved_receipt(tmp_path):
    turn = tmp_path / "turn"
    turn.mkdir()
    receipt_path = turn / "receipt.json"
    receipt_path.write_text(json.dumps(_slack_receipt()), encoding="utf-8")

    def offline(*_args, **_kwargs):
        raise urllib.error.URLError("contains https://hooks.slack.com/services/T/B/SECRET")

    status = ensure_delivery(tmp_path, turn, _slack_receipt(), configuration=_settings(retries=0), opener=offline)
    assert status["state"] == "failed_transient"
    assert receipt_path.exists()
    assert "SECRET" not in (turn / "slack_delivery.json").read_text(encoding="utf-8")
