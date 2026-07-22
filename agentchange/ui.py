"""Small, explicit controls for Stop-hook UI continuations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


_MODES = {"off", "summary", "full"}
_ON_VALUES = {"changes", "always"}


@dataclass(frozen=True)
class UiSettings:
    mode: str = "summary"
    on: str = "changes"


def _choice(value: str | None, allowed: set[str], default: str) -> str:
    normalized = (value or default).strip().lower()
    return normalized if normalized in allowed else default


def settings(environ: Mapping[str, str] | None = None) -> UiSettings:
    values = os.environ if environ is None else environ
    return UiSettings(
        mode=_choice(values.get("AGENTCHANGE_UI_MODE"), _MODES, "summary"),
        on=_choice(values.get("AGENTCHANGE_UI_ON"), _ON_VALUES, "changes"),
    )


def should_display(receipt: dict[str, Any], configuration: UiSettings) -> bool:
    """Avoid a blocking model continuation unless the turn changed repository files."""

    if configuration.mode == "off":
        return False
    if configuration.on == "always":
        return True
    return bool(receipt.get("turn_change_count", 0))
