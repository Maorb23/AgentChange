import json
import subprocess
import sys

from agentchange.command_runner import RESULT_PREFIX


def run_wrapped(*child_arguments):
    return subprocess.run(
        [sys.executable, "-m", "agentchange.command_runner", "--", *child_arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def marker_from(stdout):
    final_line = stdout.splitlines()[-1]
    assert final_line.startswith(RESULT_PREFIX)
    return json.loads(final_line.removeprefix(RESULT_PREFIX))


def test_success_preserves_stdout_and_emits_zero_marker():
    result = run_wrapped(sys.executable, "-c", "print('child-out')")
    marker = marker_from(result.stdout)
    assert result.returncode == 0
    assert result.stdout.startswith("child-out\n")
    assert marker["schema_version"] == "1"
    assert marker["exit_code"] == 0
    assert isinstance(marker["duration_ms"], int)
    assert marker["duration_ms"] >= 0


def test_failure_preserves_stderr_marker_and_exit_code():
    result = run_wrapped(
        sys.executable,
        "-c",
        "import sys; print('child-error', file=sys.stderr); raise SystemExit(1)",
    )
    marker = marker_from(result.stdout)
    assert result.returncode == 1
    assert result.stderr == "child-error\n"
    assert marker["exit_code"] == 1


def test_output_without_newline_is_preserved_before_final_marker():
    result = run_wrapped(sys.executable, "-c", "import sys; sys.stdout.write('exact')")
    assert result.stdout.startswith("exact\n" + RESULT_PREFIX)
    assert marker_from(result.stdout)["exit_code"] == 0


def test_missing_executable_is_useful_and_machine_readable():
    result = run_wrapped("agentchange-executable-that-does-not-exist")
    assert result.returncode == 127
    assert "executable not found" in result.stderr
    assert marker_from(result.stdout)["exit_code"] == 127


def test_missing_command_returns_usage_and_marker():
    result = subprocess.run(
        [sys.executable, "-m", "agentchange.command_runner", "--"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage: agentchange-run" in result.stderr
    assert marker_from(result.stdout)["exit_code"] == 2


def test_runner_never_requests_a_shell():
    source = open("agentchange/command_runner.py", encoding="utf-8").read()
    assert "shell=True" not in source
