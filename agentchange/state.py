"""Runtime discovery for receipts produced in Codex plugin data directories."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from .git_analysis import atomic_json


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "agentchange"


def remember_plugin_data(plugin_data: Path) -> None:
    try:
        atomic_json(state_home() / "runtime.json", {"plugin_data": str(plugin_data.resolve())})
    except OSError:
        pass


def plugin_data_directories() -> list[Path]:
    candidates: list[Path] = []
    user_home = Path.home()
    configured = os.environ.get("AGENTCHANGE_DATA_DIR") or os.environ.get("PLUGIN_DATA")
    if configured:
        candidates.append(Path(configured))
    try:
        runtime = json.loads((state_home() / "runtime.json").read_text(encoding="utf-8"))
        if isinstance(runtime.get("plugin_data"), str):
            candidates.append(Path(runtime["plugin_data"]))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    candidates.extend(
        (
            user_home / ".codex" / "plugins" / "data" / "agentchange",
            user_home / ".codex" / "plugin-data" / "agentchange",
            user_home / ".local" / "share" / "agentchange",
        )
    )
    plugin_data_parent = user_home / ".codex" / "plugins" / "data"
    if plugin_data_parent.is_dir():
        candidates.extend(sorted(plugin_data_parent.glob("agentchange*")))
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in unique and resolved.exists():
            unique.append(resolved)
    return unique


def receipt_files(suffix: str = "receipt.md") -> Iterable[Path]:
    for directory in plugin_data_directories():
        yield from directory.glob(f"sessions/*/turns/*/{suffix}")


def latest_receipt(suffix: str = "receipt.md") -> Path | None:
    files = list(receipt_files(suffix))
    return max(files, key=lambda path: path.stat().st_mtime_ns) if files else None


def receipt_by_id(receipt_id: str, suffix: str = "receipt.md") -> Path | None:
    matches: list[Path] = []
    for path in receipt_files("receipt.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("receipt_id") != receipt_id:
            continue
        requested = path.with_name(suffix)
        if requested.is_file():
            matches.append(requested)
    return max(matches, key=lambda path: path.stat().st_mtime_ns) if matches else None


def finalization_files() -> list[Path]:
    values: list[Path] = []
    for directory in plugin_data_directories():
        values.extend(directory.glob("sessions/*/turns/*/finalization.json"))
    return values
