"""Linux/WSL platform and Python-project environment detection."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class PlatformInfo:
    supported: bool
    kind: str
    label: str
    correction: str | None = None


def detect_platform(
    *,
    sys_platform: str | None = None,
    proc_version: str | None = None,
    os_release: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PlatformInfo:
    current = sys_platform or sys.platform
    if current != "linux":
        return PlatformInfo(
            False,
            "unsupported",
            platform.system() or current,
            "Change Agent environment to WSL in ChatGPT settings and restart the app.",
        )
    if proc_version is None:
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            proc_version = ""
    if os_release is None:
        try:
            os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
        except OSError:
            os_release = ""
    distro = "Linux"
    for line in os_release.splitlines():
        if line.startswith("NAME="):
            distro = line.partition("=")[2].strip().strip('"') or distro
            break
    values = os.environ if environ is None else environ
    if "microsoft" in proc_version.lower() or values.get("WSL_INTEROP"):
        return PlatformInfo(True, "wsl2", f"WSL2 {distro}")
    return PlatformInfo(True, "linux", distro)


def git_root(cwd: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def detect_python(project: Path, environ: Mapping[str, str] | None = None) -> Path | None:
    values = os.environ if environ is None else environ
    candidates: list[Path] = []
    active = values.get("VIRTUAL_ENV")
    if active:
        candidates.append(Path(active) / "bin" / "python")
    candidates.extend((project / ".venv" / "bin" / "python", project / "venv" / "bin" / "python"))
    resolved = shutil.which("python3") or shutil.which("python")
    if resolved:
        candidates.append(Path(resolved))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            # Keep the project-facing path (for example `.venv/bin/python`) in
            # diagnostics and markers instead of exposing its symlink target.
            return candidate.absolute()
    return None


def python_has_module(python: Path, module: str) -> bool:
    try:
        completed = subprocess.run(
            [str(python), "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def find_executable(name: str) -> str | None:
    return shutil.which(name)
