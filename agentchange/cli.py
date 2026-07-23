"""User-facing AgentChange CLI for Linux and WSL2 Python projects."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path, PurePath

from .command_runner import run_and_emit
from .display import display_command
from .doctor import collect_doctor, status_lines
from .environment import detect_python, git_root
from .installer import install
from .state import latest_receipt, receipt_by_id

_RECEIPT_ID = re.compile(r"^acr_[0-9a-f]{24}$")


def resolve_auto_command(
    requested: list[str],
    *,
    cwd: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[list[str], str]:
    if not requested:
        raise ValueError("exec --auto requires a command")
    working = cwd or Path.cwd()
    project = git_root(working) or working
    name = PurePath(requested[0].replace("\\", "/")).name
    pytest_command = name == "pytest" or (
        name.startswith("python") and len(requested) >= 3 and requested[1:3] == ["-m", "pytest"]
    )
    if pytest_command:
        python = detect_python(project, os.environ if environ is None else environ)
        if python is None:
            raise ValueError("no project Python environment was detected")
        remaining = requested[1:] if name == "pytest" else requested[3:]
        resolved = [str(python), "-m", "pytest", *remaining]
        return resolved, display_command(["python", "-m", "pytest", *remaining])
    return list(requested), display_command(requested)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentchange")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("install")
    subparsers.add_parser("doctor")
    subparsers.add_parser("latest")
    show = subparsers.add_parser("show")
    show.add_argument("receipt_id")
    subparsers.add_parser("status")
    execute = subparsers.add_parser("exec")
    execute.add_argument("--auto", action="store_true", required=True)
    execute.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "install":
        success, lines = install()
        print("\n".join(lines))
        return 0 if success else 1
    if args.command == "doctor":
        ready, lines = collect_doctor()
        print("\n".join(lines))
        return 0 if ready else 1
    if args.command == "latest":
        path = latest_receipt("receipt.md")
        if path is None:
            print("No AgentChange receipt has been generated yet.")
            return 1
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "show":
        if not _RECEIPT_ID.fullmatch(args.receipt_id):
            print("Invalid AgentChange receipt identifier.", file=sys.stderr)
            return 2
        path = receipt_by_id(args.receipt_id, "receipt.md")
        if path is None:
            print(f"No AgentChange receipt found for {args.receipt_id}.", file=sys.stderr)
            return 1
        print(path.read_text(encoding="utf-8"), end="")
        return 0
    if args.command == "status":
        print("\n".join(status_lines()))
        return 0
    try:
        resolved, rendered = resolve_auto_command(args.arguments)
    except ValueError as exc:
        print(f"AgentChange could not resolve the command: {exc}", file=sys.stderr)
        return 2
    return run_and_emit(
        resolved,
        requested_command=args.arguments,
        display_command=rendered,
    )


if __name__ == "__main__":
    raise SystemExit(main())
