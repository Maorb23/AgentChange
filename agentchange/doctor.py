"""Human-readable diagnostics for the supported Linux/WSL product path."""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path
from typing import Callable

from .display import sanitize_text
from .environment import PlatformInfo, detect_platform, detect_python, find_executable, git_root, python_has_module
from .installer import VERSION, cached_plugin_roots, plugin_version, stop_hook_verified
from .slack import connectivity_description, settings
from .state import finalization_files, latest_receipt, plugin_data_directories


def installed_version() -> str:
    try:
        return metadata.version("agentchange")
    except metadata.PackageNotFoundError:
        return VERSION


def _marketplace_has_agentchange(home: Path) -> bool:
    try:
        value = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return any(item.get("name") == "agentchange" for item in value.get("plugins", []))


def collect_doctor(
    *,
    home: Path | None = None,
    cwd: Path | None = None,
    which: Callable[[str], str | None] = find_executable,
    platform_info: PlatformInfo | None = None,
) -> tuple[bool, list[str]]:
    user_home = home or Path.home()
    project = cwd or Path.cwd()
    info = platform_info or detect_platform()
    ready = True
    lines = ["AgentChange doctor", "", "Environment"]
    if info.supported:
        lines.append(f"✓ Platform: {info.label}")
    else:
        lines.extend((f"✗ Platform: {info.label}", f"Fix: {info.correction}"))
        ready = False
    codex = which("codex")
    if codex:
        lines.append("✓ Codex found")
    else:
        lines.extend(("✗ Codex executable not found", "Fix: Install Codex in WSL and ensure `codex` is on PATH."))
        ready = False

    lines.extend(("", "AgentChange"))
    for executable, label in (("agentchange", "CLI"), ("agentchange-run", "Runner"), ("agentchange-hook", "Hook")):
        if which(executable):
            lines.append(f"✓ {label} installed")
        else:
            lines.extend((f"✗ {label} unavailable", "Fix: Reinstall AgentChange 0.3.0 in your user environment."))
            ready = False
    target = user_home / "plugins" / "agentchange"
    roots = cached_plugin_roots(user_home)
    version = plugin_version(target)
    if version == VERSION and _marketplace_has_agentchange(user_home):
        lines.append(f"✓ Plugin {VERSION} enabled")
    else:
        cached_versions = sorted({value for root in roots if (value := plugin_version(root))})
        detail = ", ".join(cached_versions) if cached_versions else "not installed"
        lines.extend((f"✗ Plugin {VERSION} is not active ({detail})", "Fix: Run `agentchange install`."))
        ready = False
    current_cache = next((root for root in roots if plugin_version(root) == VERSION), None)
    stale_versions = sorted({value for root in roots if (value := plugin_version(root)) and value != VERSION})
    if current_cache:
        lines.append(f"✓ Cached plugin {VERSION} verified")
    else:
        detail = f"; stale versions: {', '.join(stale_versions)}" if stale_versions else ""
        lines.extend((f"✗ Cached plugin {VERSION} is unavailable{detail}", "Fix: Run `agentchange install`."))
        ready = False
    if current_cache and stop_hook_verified(current_cache):
        lines.append("✓ Stop finalizer configured")
    else:
        lines.extend(("✗ Stop finalizer is not configured", "Fix: Run `agentchange install`, then approve the updated hook in Codex."))
        ready = False
    data_directories = plugin_data_directories()
    if not data_directories or all(os.access(path, os.R_OK | os.W_OK) for path in data_directories):
        lines.append("✓ Plugin data directory writable" if data_directories else "○ Plugin data will be initialized by the first Codex receipt")
    else:
        lines.extend(("✗ Plugin data directory is not writable", "Fix: Restore user read/write permission on the AgentChange plugin data directory."))
        ready = False

    lines.extend(("", "Project"))
    root = git_root(project)
    if root:
        lines.append("✓ Git repository detected")
    else:
        lines.extend(("✗ Git repository not detected", "Fix: Run this command from a Git working tree."))
        ready = False
        root = project
    python = detect_python(root)
    if python:
        try:
            label = str(python.relative_to(root))
        except ValueError:
            label = sanitize_text(str(python))
        lines.append(f"✓ Python environment: {label}")
        if python_has_module(python, "pytest"):
            lines.append("✓ pytest available")
        else:
            lines.extend(("✗ pytest is unavailable in the project environment", f"Fix: {sanitize_text(str(python))} -m pip install pytest"))
            ready = False
    else:
        lines.extend(("✗ Python environment not detected", "Fix: Create `.venv` or activate a Python virtual environment."))
        ready = False

    lines.extend(("", "Slack"))
    slack_ok, slack_message = connectivity_description(settings())
    lines.append(("✓ " if slack_ok and settings().enabled else "○ " if slack_ok else "✗ ") + slack_message)
    if not slack_ok:
        lines.append("Fix: Set a valid AGENTCHANGE_SLACK_WEBHOOK_URL or disable Slack with AGENTCHANGE_SLACK_ENABLED=0.")
        ready = False

    finalizations = finalization_files()
    if finalizations:
        latest = max(finalizations, key=lambda path: path.stat().st_mtime_ns)
        try:
            state = json.loads(latest.read_text(encoding="utf-8")).get("state", "unknown")
        except (OSError, json.JSONDecodeError):
            state = "unreadable"
        lines.append(f"✓ Latest finalization: {state}" if state == "completed" else f"✗ Latest finalization: {state}")
        ready = ready and state == "completed"
    lines.extend(("", f"Result: {'Ready' if ready else 'Needs attention'}"))
    return ready, lines


def status_lines(home: Path | None = None) -> list[str]:
    user_home = home or Path.home()
    target = user_home / "plugins" / "agentchange"
    receipt = latest_receipt("receipt.md")
    session = receipt.parents[2].name if receipt else "none"
    receipt_label = "none"
    slack_state = "none"
    if receipt:
        try:
            receipt_value = json.loads((receipt.parent / "receipt.json").read_text(encoding="utf-8"))
            session = receipt_value.get("session_id", session)
            receipt_label = receipt_value.get("receipt_id", receipt.name)
        except (OSError, json.JSONDecodeError):
            receipt_label = receipt.name
        status_path = receipt.parent / "slack_delivery.json"
        try:
            slack_state = json.loads(status_path.read_text(encoding="utf-8")).get("state", "unknown")
        except (OSError, json.JSONDecodeError):
            slack_state = "unknown"
    incomplete = 0
    for path in finalization_files():
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("state") != "completed":
                incomplete += 1
        except (OSError, json.JSONDecodeError):
            incomplete += 1
    return [
        "AgentChange status",
        "",
        f"Installed version: {installed_version()}",
        f"Plugin version: {plugin_version(target) or 'not installed'}",
        f"Hook status: {'ready' if stop_hook_verified(target) else 'not ready'}",
        f"Slack status: {slack_state}",
        f"Latest session: {session}",
        f"Latest receipt: {receipt_label}",
        f"Incomplete or failed finalizations: {incomplete}",
    ]
