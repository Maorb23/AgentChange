"""Idempotent Linux/WSL personal-plugin installation helpers."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Callable

from .environment import detect_platform, find_executable

VERSION = "0.3.3"
PLUGIN_NAME = "agentchange"
COPY_PATHS = (".codex-plugin", "hooks", "skills", "agentchange", "scripts", "pyproject.toml", "README.md")


def plugin_source_root() -> Path | None:
    configured = os.environ.get("AGENTCHANGE_PLUGIN_SOURCE")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        (
            Path(__file__).resolve().parents[1],
            Path(sys.prefix) / "share" / "agentchange",
            Path(sysconfig.get_path("data")) / "share" / "agentchange",
        )
    )
    for candidate in candidates:
        if (candidate / ".codex-plugin" / "plugin.json").is_file():
            return candidate.resolve()
    return None


def copy_plugin_source(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return
    for relative in COPY_PATHS:
        source_path = source / relative
        target_path = target / relative
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                target_path,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            )
        elif source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def update_personal_marketplace(home: Path) -> Path:
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = json.loads(marketplace.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
    value.setdefault("name", "personal")
    value.setdefault("interface", {}).setdefault("displayName", "Personal")
    plugins = value.setdefault("plugins", [])
    entry = {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Developer Tools",
    }
    plugins[:] = [plugin for plugin in plugins if plugin.get("name") != PLUGIN_NAME]
    plugins.append(entry)
    temporary = marketplace.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(marketplace)
    return marketplace


def plugin_version(root: Path) -> str | None:
    try:
        value = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value.get("version") if value.get("name") == PLUGIN_NAME else None


def cached_plugin_roots(home: Path) -> list[Path]:
    cache = (home / ".codex" / "plugins" / "cache").resolve()
    if not cache.exists():
        return []
    roots: list[Path] = []
    for manifest in cache.rglob(".codex-plugin/plugin.json"):
        root = manifest.parent.parent.resolve()
        try:
            root.relative_to(cache)
        except ValueError:
            continue
        if plugin_version(root) is not None:
            roots.append(root)
    return sorted(set(roots))


def plugin_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in COPY_PATHS:
        path = root / relative
        files = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
        for file_path in files:
            if not file_path.is_file() or "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                continue
            relative_path = file_path.relative_to(root).as_posix()
            digest.update(relative_path.encode("utf-8") + b"\0")
            digest.update(file_path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def remove_stale_agentchange_caches(
    home: Path,
    expected_version: str = VERSION,
    expected_root: Path | None = None,
) -> list[Path]:
    removed: list[Path] = []
    expected_fingerprint = plugin_fingerprint(expected_root) if expected_root else None
    for root in cached_plugin_roots(home):
        stale = plugin_version(root) != expected_version
        if not stale and expected_fingerprint is not None:
            stale = plugin_fingerprint(root) != expected_fingerprint
        if stale:
            shutil.rmtree(root)
            removed.append(root)
    return removed


def stop_hook_verified(root: Path) -> bool:
    try:
        hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return False
    for group in hooks.get("Stop", []):
        for handler in group.get("hooks", []):
            if "agentchange-hook finalize" in handler.get("command", ""):
                return True
    return False


def install(
    *,
    home: Path | None = None,
    source: Path | None = None,
    which: Callable[[str], str | None] = find_executable,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[bool, list[str]]:
    user_home = (home or Path.home()).resolve()
    lines = ["AgentChange installation", ""]
    platform_info = detect_platform()
    if not platform_info.supported:
        lines.extend((f"✗ Platform: {platform_info.label}", f"Fix: {platform_info.correction}"))
        return False, lines
    lines.append(f"✓ Platform: {platform_info.label}")
    codex = which("codex")
    if not codex:
        lines.extend(("✗ Codex executable not found", "Fix: Install Codex in the WSL environment and ensure `codex` is on PATH."))
        return False, lines
    lines.append("✓ Codex found")
    for executable, label in (("agentchange", "AgentChange CLI"), ("agentchange-run", "Validation runner"), ("agentchange-hook", "Hook executable")):
        if not which(executable):
            lines.extend((f"✗ {label} is unavailable", "Fix: Reinstall the AgentChange package in your user environment."))
            return False, lines
        lines.append(f"✓ {label} installed")
    plugin_source = source or plugin_source_root()
    if plugin_source is None:
        lines.extend((f"✗ Bundled plugin source is unavailable", f"Fix: Reinstall AgentChange {VERSION} and run `agentchange install` again."))
        return False, lines
    target = user_home / "plugins" / PLUGIN_NAME
    copy_plugin_source(plugin_source, target)
    update_personal_marketplace(user_home)
    remove_stale_agentchange_caches(user_home, expected_root=target)
    completed = run(
        [codex, "plugin", "add", "agentchange@personal"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        lines.extend(("✗ Codex could not install agentchange@personal", "Fix: Run `codex plugin add agentchange@personal`, then rerun `agentchange doctor`."))
        return False, lines
    if plugin_version(target) != VERSION:
        lines.extend(("✗ Installed plugin version could not be verified", f"Fix: Reinstall AgentChange {VERSION}."))
        return False, lines
    lines.append(f"✓ Plugin {VERSION} installed")
    roots = cached_plugin_roots(user_home)
    verified_root = next((root for root in roots if plugin_version(root) == VERSION), None)
    if verified_root is None:
        lines.extend(("✗ Cached plugin version could not be verified", "Fix: Run `codex plugin add agentchange@personal`, then rerun `agentchange install`."))
        return False, lines
    if plugin_fingerprint(verified_root) != plugin_fingerprint(target):
        lines.extend(("✗ Cached plugin fingerprint does not match the installed source", "Fix: Run `agentchange install` again."))
        return False, lines
    lines.append("✓ Cached plugin fingerprint verified")
    if not stop_hook_verified(verified_root):
        lines.extend(("✗ Stop finalizer is not configured", "Fix: Run `agentchange install` again, then approve the updated hooks in Codex."))
        return False, lines
    lines.extend(("✓ Stop finalizer verified", "⚠ Approve AgentChange hooks in Codex if prompted", "", "Next:", "  agentchange doctor"))
    return True, lines
