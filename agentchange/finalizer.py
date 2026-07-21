"""Idempotent Stop-hook finalization for one Codex turn."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .evidence import analyze_turn, load_turn_events
from .git_analysis import atomic_json, capture_git_snapshot, classify_changes, turn_directory
from .receipt import build_receipt, write_receipts
from .risk import score_risk
from .slack import ensure_delivery


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def finalize_turn(plugin_data: Path, payload: dict[str, Any]) -> dict[str, Any]:
    session_id = payload.get("session_id")
    turn_id = payload.get("turn_id")
    cwd = payload.get("cwd")
    if not all(isinstance(value, str) and value for value in (session_id, turn_id, cwd)):
        raise ValueError("Stop finalization requires session_id, turn_id, and cwd")
    turn_dir = turn_directory(plugin_data, session_id, turn_id)
    turn_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = turn_dir / "receipt.json"
    completed_path = turn_dir / "finalization.json"
    if completed_path.exists() and receipt_path.exists():
        receipt = _read_json(receipt_path)
        if receipt is None:
            raise ValueError("completed receipt is unreadable")
        ensure_delivery(plugin_data, turn_dir, receipt)
        return receipt

    lock_path = turn_dir / "finalization.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        receipt = _read_json(receipt_path)
        if receipt is not None:
            return receipt
        raise RuntimeError("turn finalization is already in progress")
    os.close(descriptor)
    try:
        events_path = turn_dir.parents[1] / "events.jsonl"
        events, normalization_errors = load_turn_events(events_path, turn_id)
        baseline_path = turn_dir / "git_baseline.json"
        baseline = _read_json(baseline_path)
        final_snapshot = capture_git_snapshot(cwd)
        atomic_json(turn_dir / "git_final.json", final_snapshot)
        attribution = classify_changes(baseline, final_snapshot)
        analysis = analyze_turn(events, attribution)
        risk = score_risk(analysis, bool(attribution.get("available")))
        receipt, markdown = build_receipt(
            session_id, turn_id, events_path, events, normalization_errors,
            analysis, attribution, baseline, final_snapshot, risk,
        )
        write_receipts(turn_dir, receipt, markdown)
        atomic_json(completed_path, {"state": "completed", "receipt_id": receipt["receipt_id"], "generated_at": receipt["generated_at"]})
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
    ensure_delivery(plugin_data, turn_dir, receipt)
    return receipt
