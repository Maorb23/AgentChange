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


def _emit_marker(exit_code: int, duration_ms: int, stdout_ended_with_newline: bool) -> None:
    if not stdout_ended_with_newline:
        _write_bytes(sys.stdout, b"\n")
    result = {
        "schema_version": "1",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    marker = RESULT_PREFIX + json.dumps(result, separators=(",", ":")) + "\n"
    _write_bytes(sys.stdout, marker.encode("utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    started = time.perf_counter_ns()
    if not arguments or arguments[0] != "--" or len(arguments) == 1:
        print("usage: agentchange-run -- <command> [arguments...]", file=sys.stderr)
        duration_ms = (time.perf_counter_ns() - started) // 1_000_000
        _emit_marker(2, duration_ms, stdout_ended_with_newline=True)
        return 2

    command = arguments[1:]
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except FileNotFoundError:
        print(f"agentchange-run: executable not found: {command[0]}", file=sys.stderr)
        exit_code = 127
        stdout = b""
        stderr = b""
    except PermissionError:
        print(f"agentchange-run: executable is not runnable: {command[0]}", file=sys.stderr)
        exit_code = 126
        stdout = b""
        stderr = b""

    duration_ms = (time.perf_counter_ns() - started) // 1_000_000
    _write_bytes(sys.stdout, stdout)
    _write_bytes(sys.stderr, stderr)
    _emit_marker(exit_code, duration_ms, stdout_ended_with_newline=(not stdout or stdout.endswith(b"\n")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
