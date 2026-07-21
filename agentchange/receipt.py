"""Deterministic JSON and Markdown receipt construction."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import Receipt
from .raw_capture import utc_now

SCHEMA_VERSION = "1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def receipt_id(session_id: str, turn_id: str) -> str:
    return "acr_" + hashlib.sha256(f"{SCHEMA_VERSION}\0{session_id}\0{turn_id}".encode()).hexdigest()[:24]


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _analysis_payload(analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "validations": [item.model_dump(mode="json") for item in analysis["validations"]],
        "overall_validation_status": analysis["overall_validation_status"],
        "claims": analysis["claims"],
        "findings": [item.model_dump(mode="json") for item in analysis["findings"]],
        "introduced_paths": analysis["introduced_paths"],
        "docs_only": analysis["docs_only"],
        "sensitive_permission": analysis["sensitive_permission"],
    }


def build_receipt(
    session_id: str,
    turn_id: str,
    events_path: Path,
    events: list[Any],
    normalization_errors: list[str],
    analysis: dict[str, Any],
    attribution: dict[str, Any],
    baseline: dict[str, Any] | None,
    final_snapshot: dict[str, Any],
    risk: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    generated_at = utc_now()
    raw_bytes = events_path.read_bytes()
    analysis_payload = _analysis_payload(analysis)
    limitations = [
        "Hooks observe only supported Codex tool paths and can be disabled or bypassed.",
        "Local evidence files can be modified; local Git inspection is not remote attestation.",
        "This receipt is evidence, not proof that every action was captured, and AgentChange is not a secure execution sandbox.",
    ]
    if attribution.get("limitation"):
        limitations.append(attribution["limitation"])
    if normalization_errors:
        limitations.append("Some same-turn evidence lines could not be normalized; see event_summary.normalization_errors.")
    base = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id(session_id, turn_id),
        "session_id": session_id,
        "turn_id": turn_id,
        "generated_at": generated_at,
        "source_labels": {
            "observed": "directly captured by a supported hook or authoritative runner marker",
            "inferred": "derived deterministically from observed evidence or local Git state",
            "reported": "stated by Codex; not treated as observed evidence",
            "not_captured": "not available through the supported evidence path",
        },
        "agent_statement": {"value": analysis["agent_statement"], "source": "reported_by_codex" if analysis["agent_statement"] else "not_captured", "claims": analysis["claims"]},
        "validation": {"overall_status": analysis["overall_validation_status"], "commands": [item.model_dump(mode="json") for item in analysis["validations"]]},
        "repository": {"baseline": baseline, "final": final_snapshot, "attribution": attribution},
        "findings": [item.model_dump(mode="json") for item in analysis["findings"]],
        "risk": risk,
        "limitations": limitations,
        "event_summary": {
            "event_count": len(events),
            "chronological_event_ids": [event.event_id for event in events],
            "original_line_numbers": [event.line_number for event in events],
            "normalization_errors": normalization_errors,
        },
    }
    receipt_body_digest = sha256_hex(canonical_bytes(base))
    integrity = {
        "algorithm": "sha256",
        "raw_jsonl": {"digest": sha256_hex(raw_bytes), "coverage": "exact session events.jsonl bytes read immediately after Stop capture; may include other turns"},
        "canonical_analysis": {"digest": sha256_hex(canonical_bytes(analysis_payload)), "coverage": "canonical same-turn analysis payload before integrity fields"},
        "canonical_receipt_body": {"digest": receipt_body_digest, "coverage": "canonical JSON receipt body excluding the integrity object"},
    }
    receipt = {**base, "integrity": integrity}
    markdown_body = render_markdown(receipt, include_integrity=False)
    integrity["markdown_body"] = {"digest": sha256_hex(markdown_body.encode("utf-8")), "coverage": "UTF-8 Markdown bytes before the Integrity section"}
    Receipt.model_validate(receipt)
    markdown = render_markdown(receipt, include_integrity=True)
    return receipt, markdown


def render_markdown(receipt: dict[str, Any], *, include_integrity: bool) -> str:
    lines = [
        "# AgentChange receipt",
        "",
        f"- Receipt: `{receipt['receipt_id']}`",
        f"- Session: `{receipt['session_id']}`",
        f"- Turn: `{receipt['turn_id']}`",
        f"- Risk: **{receipt['risk']['level']} ({receipt['risk']['score']}/100)**",
        f"- Validation: **{receipt['validation']['overall_status']}**",
        "",
        "## Reported by Codex",
        "",
        receipt["agent_statement"]["value"] or "Not captured.",
        "",
        "## Observed validation",
        "",
    ]
    commands = receipt["validation"]["commands"]
    if commands:
        lines.extend(f"- `{item['category']}`: **{item['status']}** — `{item['command']}` ({item['result_source']})" for item in commands)
    else:
        lines.append("- No relevant validation command was captured.")
    lines.extend(["", "## Findings", ""])
    if receipt["findings"]:
        lines.extend(f"- **{item['code']}**: {item['summary']}" for item in receipt["findings"])
    else:
        lines.append("- None.")
    lines.extend(["", "## Repository attribution", ""])
    classifications = receipt["repository"]["attribution"]["classifications"]
    if classifications:
        lines.extend(f"- `{item['path']}` — {item['classification']}" for item in classifications)
    else:
        lines.append("- No working-tree changes observed.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in receipt["limitations"])
    if include_integrity:
        lines.extend(["", "## Integrity", ""])
        lines.extend(f"- `{name}`: `{value['digest']}` — {value['coverage']}" for name, value in receipt["integrity"].items() if isinstance(value, dict))
    return "\n".join(lines) + "\n"


def write_receipts(turn_dir: Path, receipt: dict[str, Any], markdown: str) -> None:
    _atomic_bytes(turn_dir / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8") + b"\n")
    _atomic_bytes(turn_dir / "receipt.md", markdown.encode("utf-8"))
