"""Small, local Git snapshots and turn-level working-tree attribution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .raw_capture import derive_session_key, derive_turn_key, utc_now

ATTRIBUTION_LIMITATION = "Repository changes observed at Stop; turn-level attribution unavailable."


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _git(cwd: str, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", cwd, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=5,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git {' '.join(arguments)} failed")
    return completed.stdout


def _status_entries(raw: bytes) -> list[dict[str, str | None]]:
    tokens = raw.decode("utf-8", errors="surrogateescape").split("\0")
    entries: list[dict[str, str | None]] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        token = tokens[index]
        status = token[:2]
        path = token[3:]
        original_path = None
        if "R" in status or "C" in status:
            index += 1
            if index < len(tokens):
                original_path = tokens[index]
        entries.append({"path": path, "status": status, "original_path": original_path})
        index += 1
    return entries


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def capture_git_snapshot(cwd: str) -> dict[str, Any]:
    captured_at = utc_now()
    try:
        root = _git(cwd, "rev-parse", "--show-toplevel").decode().strip()
        head = _git(root, "rev-parse", "HEAD").decode().strip()
        branch = _git(root, "branch", "--show-current").decode().strip() or None
        porcelain_raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        entries = _status_entries(porcelain_raw)
        staged = sorted(entry["path"] for entry in entries if entry["status"][0] not in {" ", "?"})
        unstaged = sorted(entry["path"] for entry in entries if entry["status"][1] not in {" ", "?"})
        untracked = sorted(entry["path"] for entry in entries if entry["status"] == "??")
        file_digests = {
            entry["path"]: digest
            for entry in entries
            if (digest := _sha256_file(Path(root) / str(entry["path"]))) is not None
        }
        index_digests: dict[str, str] = {}
        for path in staged:
            try:
                index_digests[path] = hashlib.sha256(_git(root, "show", f":{path}" )).hexdigest()
            except RuntimeError:
                pass
        return {
            "schema_version": "1",
            "captured_at": captured_at,
            "available": True,
            "repository_root": root,
            "head": head,
            "branch": branch,
            "porcelain_v1": porcelain_raw.decode("utf-8", errors="replace"),
            "entries": entries,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
            "file_digests": file_digests,
            "index_digests": index_digests,
        }
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        return {
            "schema_version": "1",
            "captured_at": captured_at,
            "available": False,
            "repository_root": None,
            "head": None,
            "branch": None,
            "porcelain_v1": "",
            "entries": [],
            "staged": [],
            "unstaged": [],
            "untracked": [],
            "error": str(exc)[:500],
        }


def turn_directory(plugin_data: Path, session_id: str, turn_id: str) -> Path:
    return plugin_data / "sessions" / derive_session_key(session_id) / "turns" / derive_turn_key(turn_id)


def ensure_git_baseline(plugin_data: Path, session_id: str, turn_id: str, cwd: str) -> Path:
    path = turn_directory(plugin_data, session_id, turn_id) / "git_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".capturing")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path
    os.close(descriptor)
    try:
        if not path.exists():
            atomic_json(path, capture_git_snapshot(cwd))
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
    return path


def classify_changes(baseline: dict[str, Any] | None, final: dict[str, Any]) -> dict[str, Any]:
    final_entries = {str(entry["path"]): entry for entry in final.get("entries", [])}
    if not baseline or not baseline.get("available") or not final.get("available"):
        return {
            "available": False,
            "limitation": ATTRIBUTION_LIMITATION,
            "classifications": [
                {"path": path, "classification": "Attribution unknown", "final_status": entry["status"]}
                for path, entry in sorted(final_entries.items())
            ],
        }
    baseline_entries = {str(entry["path"]): entry for entry in baseline.get("entries", [])}
    baseline_signatures = {
        path: (
            entry.get("status"),
            baseline.get("file_digests", {}).get(path),
            baseline.get("index_digests", {}).get(path),
        )
        for path, entry in baseline_entries.items()
    }
    final_signatures = {
        path: (
            entry.get("status"),
            final.get("file_digests", {}).get(path),
            final.get("index_digests", {}).get(path),
        )
        for path, entry in final_entries.items()
    }
    classifications = []
    for path in sorted(set(baseline_entries) | set(final_entries)):
        if path not in final_entries:
            classification = "No longer present at Stop"
        elif path not in baseline_entries:
            classification = "New during this turn"
        elif baseline_signatures[path] != final_signatures[path]:
            classification = "Modified further during this turn"
        else:
            classification = "Pre-existing change"
        classifications.append(
            {
                "path": path,
                "classification": classification,
                "baseline_status": baseline_entries.get(path, {}).get("status"),
                "final_status": final_entries.get(path, {}).get("status"),
            }
        )
    return {"available": True, "limitation": None, "classifications": classifications}
