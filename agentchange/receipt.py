"""Deterministic JSON plus clear, accurately scoped Markdown receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .display import duration_display, sanitize_text, validation_wording
from .models import Receipt
from .raw_capture import utc_now
from .slack import display_state

SCHEMA_VERSION = "2"

_CATEGORY_LABELS = {
    "django_system_check": "Django System Check",
    "django_test": "Django Tests",
}
_CHANGE_SUMMARY_BLOCK = re.compile(
    r"(?ms)^[ \t]*AGENTCHANGE_CHANGE_SUMMARY_JSON[ \t]*\r?\n"
    r".*?^[ \t]*END_AGENTCHANGE_CHANGE_SUMMARY_JSON[ \t]*(?:\r?\n|$)"
)


def _reported_statement(value: Any) -> str:
    if not isinstance(value, str):
        return "Not captured."
    narrative = _CHANGE_SUMMARY_BLOCK.sub("", value).strip()
    return narrative or "No narrative statement provided."


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
        "model_derived_change_summary": analysis["model_derived_change_summary"].model_dump(mode="json"),
        "introduced_paths": analysis["introduced_paths"],
        "docs_only": analysis["docs_only"],
        "sensitive_permission": analysis["sensitive_permission"],
    }


def _attach_integrity(
    receipt: dict[str, Any],
    *,
    raw_digest: str,
    analysis_digest: str,
) -> tuple[dict[str, Any], str]:
    base = {key: value for key, value in receipt.items() if key != "integrity"}
    integrity = {
        "algorithm": "sha256",
        "raw_jsonl": {
            "digest": raw_digest,
            "coverage": "exact session events.jsonl bytes read immediately after Stop capture; may include other turns",
        },
        "canonical_analysis": {
            "digest": analysis_digest,
            "coverage": "canonical same-turn analysis payload before integrity fields",
        },
        "canonical_receipt_body": {
            "digest": sha256_hex(canonical_bytes(base)),
            "coverage": "canonical JSON receipt body excluding the integrity object",
        },
    }
    updated = {**base, "integrity": integrity}
    markdown_body = render_markdown(updated, include_integrity=False)
    integrity["markdown_body"] = {
        "digest": sha256_hex(markdown_body.encode("utf-8")),
        "coverage": "UTF-8 Markdown bytes before the Integrity section",
    }
    Receipt.model_validate(updated)
    return updated, render_markdown(updated, include_integrity=True)


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
    slack_state: str,
) -> tuple[dict[str, Any], str]:
    raw_bytes = events_path.read_bytes()
    limitations = [
        "Hooks observe only supported Codex tool paths and can be disabled or bypassed.",
        "Local evidence files can be modified; local Git inspection is not remote attestation.",
        "This receipt is evidence, not proof that every action was captured, and AgentChange is not a secure execution sandbox.",
    ]
    if attribution.get("limitation"):
        limitations.append(attribution["limitation"])
    if normalization_errors:
        limitations.append("Some same-turn evidence lines could not be normalized; see event_summary.normalization_errors.")
    classifications = attribution.get("classifications", [])
    attributed = [
        item
        for item in classifications
        if item.get("classification") in {"New during this turn", "Modified further during this turn", "No longer present at Stop"}
    ]
    preexisting_count = sum(item.get("classification") == "Pre-existing change" for item in classifications)
    validations = [item.model_dump(mode="json") for item in analysis["validations"]]
    repository_root = final_snapshot.get("repository_root") or (baseline or {}).get("repository_root")
    base = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id(session_id, turn_id),
        "session_id": session_id,
        "turn_id": turn_id,
        "generated_at": utc_now(),
        "source_labels": {
            "observed": "directly captured by a supported hook or authoritative runner marker",
            "inferred": "derived deterministically from observed evidence or local Git state",
            "reported": "stated by Codex; never promoted to observed evidence",
            "not_captured": "not available through the supported evidence path",
        },
        "requested_task": {"value": analysis.get("requested_task"), "source": "observed" if analysis.get("requested_task") else "not_captured"},
        "agent_statement": {
            "value": analysis["agent_statement"],
            "source": "reported_by_codex" if analysis["agent_statement"] else "not_captured",
            "claims": analysis["claims"],
        },
        "observed": {
            "event_count": len(events),
            "authoritative_validation_count": sum(item["authoritative"] for item in validations),
            "runner_markers_are_source_of_validation_results": True,
        },
        "validation": {
            "overall_status": analysis["overall_validation_status"],
            "summary": validation_wording(validations),
            "commands": validations,
        },
        "repository": {
            "name": Path(repository_root).name if repository_root else "Not captured",
            "branch": final_snapshot.get("branch") or (baseline or {}).get("branch"),
            "baseline": baseline,
            "final": final_snapshot,
            "attribution": attribution,
            "turn_changes": attributed,
            "preexisting_change_count": preexisting_count,
        },
        "model_derived_change_summary": analysis["model_derived_change_summary"].model_dump(mode="json"),
        "findings": [item.model_dump(mode="json") for item in analysis["findings"]],
        "risk": risk,
        "slack": {"state": slack_state},
        "limitations": limitations,
        "event_summary": {
            "event_count": len(events),
            "model": analysis.get("model"),
            "chronological_event_ids": [event.event_id for event in events],
            "original_line_numbers": [event.line_number for event in events],
            "normalization_errors": normalization_errors,
        },
        "turn_change_count": len(attributed),
    }
    return _attach_integrity(
        base,
        raw_digest=sha256_hex(raw_bytes),
        analysis_digest=sha256_hex(canonical_bytes(_analysis_payload(analysis))),
    )


def update_delivery_receipt(
    turn_dir: Path,
    receipt: dict[str, Any],
    delivery: dict[str, Any],
) -> dict[str, Any]:
    receipt = dict(receipt)
    receipt["slack"] = {
        key: value
        for key, value in delivery.items()
        if key in {"state", "attempts", "http_status", "updated_at", "error"}
    }
    integrity = receipt.get("integrity", {})
    updated, markdown = _attach_integrity(
        receipt,
        raw_digest=integrity.get("raw_jsonl", {}).get("digest", ""),
        analysis_digest=integrity.get("canonical_analysis", {}).get("digest", ""),
    )
    write_receipts(turn_dir, updated, markdown)
    return updated


def render_markdown(receipt: dict[str, Any], *, include_integrity: bool) -> str:
    risk = receipt["risk"]
    repository = receipt["repository"]
    model = receipt["event_summary"].get("model") or "Not captured"
    change_noun = "file" if receipt["turn_change_count"] == 1 else "files"
    marker_count = receipt["observed"]["authoritative_validation_count"]
    marker_noun = "marker" if marker_count == 1 else "markers"
    lines = [
        "# AgentChange Receipt",
        "",
        f"**Risk:** {risk['level'].title()} — {risk['score']}/100",
        f"**Repository:** {sanitize_text(repository['name'])}",
        f"**Branch:** {sanitize_text(repository.get('branch') or 'Not captured')}",
        f"**Model:** {sanitize_text(model)}",
        f"**Turn changes:** {receipt['turn_change_count']} {change_noun}",
        f"**Validation:** {receipt['validation']['summary']}",
        f"**Slack:** {display_state(receipt['slack']['state'])}",
        "",
        "## Requested task",
        "",
        sanitize_text(receipt["requested_task"].get("value") or "Not captured."),
        "",
        "## Reported by Codex",
        "",
        sanitize_text(_reported_statement(receipt["agent_statement"].get("value"))),
        "",
        "## Observed by AgentChange",
        "",
        f"- Captured {receipt['observed']['event_count']} supported same-turn lifecycle events.",
        f"- Captured {marker_count} authoritative validation result {marker_noun}.",
        "- Validation outcomes below come from runner markers, not from statements in Codex’s answer.",
        "",
        "## Observed files changed",
        "",
    ]
    changes = repository.get("turn_changes", [])
    if changes:
        lines.extend(f"- `{sanitize_text(item['path'])}`" for item in changes)
    else:
        lines.append("- No turn-attributed files were observed.")
    preexisting_count = repository.get("preexisting_change_count", 0)
    if preexisting_count:
        lines.extend(
            (
                "",
                f"The repository already contained {preexisting_count} modified or untracked files before this turn. They were not attributed to Codex.",
            )
        )
    lines.extend(("", "## Codex summary of observed changes", ""))
    change_summary = receipt.get("model_derived_change_summary", {})
    summaries = change_summary.get("file_summaries", [])
    if summaries:
        lines.append(change_summary.get("source_label", "Generated by Codex from the observed Git diff."))
        lines.append("")
        lines.extend(
            f"- `{sanitize_text(item['path'])}`: {sanitize_text(item['summary'])}"
            for item in summaries
        )
    else:
        lines.append("No file-level summary was provided by Codex.")
    lines.extend(("", "## Validation results", ""))
    commands = receipt["validation"]["commands"]
    if commands:
        lines.extend(
            (
                "| Type | Scope | Result | Exit code | Duration |",
                "|---|---|---:|---:|---:|",
            )
        )
        for item in commands:
            result = item["status"].replace("_", " ").title()
            exit_code = item["exit_code"] if item["exit_code"] is not None else "—"
            lines.append(
                f"| {_CATEGORY_LABELS.get(item['category'], item['category'].replace('_', ' ').title())} | `{sanitize_text(item['scope'])}` | {result} | {exit_code} | {duration_display(item['duration_ms'])} |"
            )
    else:
        lines.append("No relevant validation command was observed.")
    lines.extend(("", "## Findings", ""))
    prominent = [item for item in receipt["findings"] if item["code"] != "PREEXISTING_REPOSITORY_CHANGES"]
    lines.extend(f"- **{item['code']}**: {sanitize_text(item['summary'])}" for item in prominent)
    if not prominent:
        lines.append("- No material findings.")
    lines.extend(("", "## Risk explanation", ""))
    components = risk.get("components", [])
    lines.extend(f"- {item['rule'].replace('_', ' ').title()}: {item['points']:+d} points" for item in components)
    if not components:
        lines.append("- No deterministic risk rules added points.")
    lines.extend(("", "## Evidence limitations", ""))
    lines.extend(f"- {sanitize_text(item)}" for item in receipt["limitations"])
    lines.extend(("", "## Receipt identifier", "", f"`{receipt['receipt_id']}`"))
    if include_integrity:
        lines.extend(("", "## Integrity", ""))
        lines.extend(
            f"- `{name}`: `{value['digest']}` — {value['coverage']}"
            for name, value in receipt["integrity"].items()
            if isinstance(value, dict)
        )
    return "\n".join(lines) + "\n"


def render_ui_summary(receipt: dict[str, Any]) -> str:
    commands = receipt["validation"]["commands"]
    change_noun = "file" if receipt["turn_change_count"] == 1 else "files"
    lines = [
        "AgentChange Receipt",
        "",
        f"Risk: {receipt['risk']['level'].title()} — {receipt['risk']['score']}/100",
        f"Changes this turn: {receipt['turn_change_count']} {change_noun}",
        f"Validation: {receipt['validation']['summary']}",
    ]
    scopes = [item["scope"] for item in commands if item.get("scope")]
    if scopes:
        lines.append(f"Scope: {sanitize_text('; '.join(scopes))}")
    lines.extend(
        (
            f"Slack: {display_state(receipt['slack']['state'])}",
            f"Receipt: {receipt['receipt_id']}",
        )
    )
    return "\n".join(lines)


def render_ui_continuation_reason(receipt: dict[str, Any]) -> str:
    """Render the same complete receipt shown by ``agentchange latest`` for Codex.

    The Stop hook uses this continuation reason as the conversation-end display.
    Keeping it on the Markdown renderer prevents the terminal and conversation
    views from drifting apart.
    """
    return "Display this full AgentChange receipt exactly once, then stop:\n\n" + render_markdown(
        receipt, include_integrity=True
    )


def write_receipts(turn_dir: Path, receipt: dict[str, Any], markdown: str) -> None:
    _atomic_bytes(
        turn_dir / "receipt.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode("utf-8") + b"\n",
    )
    _atomic_bytes(turn_dir / "receipt.md", markdown.encode("utf-8"))
