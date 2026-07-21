"""User-facing sanitization and concise validation wording."""

from __future__ import annotations

import re
import shlex
from pathlib import PurePath
from typing import Iterable

_HOME_PATH = re.compile(r"/home/[^/\s`'\"]+")
_SLACK_WEBHOOK = re.compile(r"https://hooks\.slack\.com/services/[^\s`'\"]+", re.I)


def sanitize_text(value: str) -> str:
    value = _SLACK_WEBHOOK.sub("[REDACTED]", value)
    return _HOME_PATH.sub("~", value)


def sanitize_command_tokens(tokens: Iterable[str]) -> list[str]:
    values = list(tokens)
    output: list[str] = []
    for token in values:
        normalized = token.replace("\\", "/")
        name = PurePath(normalized).name
        if name in {"agentchange-run", "agentchange-run.exe"}:
            output.append("agentchange-run")
        elif name.startswith("python") and "/" in normalized:
            output.append("python")
        else:
            output.append(sanitize_text(token))
    return output


def display_command(tokens: Iterable[str]) -> str:
    return shlex.join(sanitize_command_tokens(tokens))


def validation_wording(commands: list[dict]) -> str:
    if not commands:
        return "No relevant validation command was observed"
    passed = sum(command.get("status") == "passed" for command in commands)
    noun = "command" if len(commands) == 1 else "commands"
    return f"{passed} of {len(commands)} observed validation {noun} passed"


def duration_display(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "—"
    return f"{duration_ms / 1000:.1f} s"
