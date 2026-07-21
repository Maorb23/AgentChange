"""Dependency-free runner that emits an explicit validation result marker."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Sequence

RESULT_PREFIX = "__AGENTCHANGE_RESULT__="


def _write_bytes(stream: object, value: bytes) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(value)
        buffer.flush()
        return
    stream.write(value.decode("utf-8", errors="replace"))  # type: ignore[attr-defined]
    stream.flush()  # type: ignore[attr-defined]


def _emit_marker(
    exit_code: int,
    duration_ms: int,
    stdout_ended_with_newline: bool,
    metadata: dict[str, object] | None = None,
) -> None:
    if not stdout_ended_with_newline:
        _write_bytes(sys.stdout, b"\n")
    result: dict[str, object] = {
        "schema_version": "1",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    if metadata:
        result.update(metadata)
    marker = RESULT_PREFIX + json.dumps(result, separators=(",", ":")) + "\n"
    _write_bytes(sys.stdout, marker.encode("utf-8"))


def run_and_emit(
    command: Sequence[str],
    *,
    requested_command: Sequence[str] | None = None,
    display_command: str | None = None,
) -> int:
    arguments = list(command)
    started = time.perf_counter_ns()
    error_kind = None
    try:
        completed = subprocess.run(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except FileNotFoundError:
        print(f"agentchange-run: executable not found: {arguments[0]}", file=sys.stderr)
        exit_code = 127
        stdout = b""
        stderr = b""
        error_kind = "command_not_found"
    except PermissionError:
        print(f"agentchange-run: executable is not runnable: {arguments[0]}", file=sys.stderr)
        exit_code = 126
        stdout = b""
        stderr = b""
        error_kind = "permission_denied"

    duration_ms = (time.perf_counter_ns() - started) // 1_000_000
    _write_bytes(sys.stdout, stdout)
    _write_bytes(sys.stderr, stderr)
    metadata: dict[str, object] = {
        "requested_command": list(requested_command or arguments),
        "resolved_command": arguments,
    }
    if display_command:
        metadata["display_command"] = display_command
    if error_kind:
        metadata["error_kind"] = error_kind
    _emit_marker(
        exit_code,
        duration_ms,
        stdout_ended_with_newline=(not stdout or stdout.endswith(b"\n")),
        metadata=metadata,
    )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "--" or len(arguments) == 1:
        started = time.perf_counter_ns()
        print("usage: agentchange-run -- <command> [arguments...]", file=sys.stderr)
        duration_ms = (time.perf_counter_ns() - started) // 1_000_000
        _emit_marker(2, duration_ms, stdout_ended_with_newline=True)
        return 2
    return run_and_emit(arguments[1:])


if __name__ == "__main__":
    raise SystemExit(main())
