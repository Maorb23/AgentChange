"""Downstream readers and normalization helpers for captured evidence."""

from __future__ import annotations

import json
from pathlib import Path

from .models import NormalizedEvent
from .normalize import normalize_envelope
from .raw_capture import derive_session_key, record_normalization_error


def read_envelopes(events_path: Path) -> list[dict]:
    return [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]


def normalize_session(plugin_data: Path, session_id: str) -> list[NormalizedEvent]:
    session_dir = plugin_data / "sessions" / derive_session_key(session_id)
    normalized: list[NormalizedEvent] = []
    for envelope in read_envelopes(session_dir / "events.jsonl"):
        try:
            normalized.append(normalize_envelope(envelope))
        except Exception as exc:
            record_normalization_error(
                plugin_data,
                session_id,
                str(envelope.get("event_id", "unknown")),
                exc,
            )
    return normalized
