"""Bounded, duplicate-safe Slack incoming-webhook delivery."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping

from .display import sanitize_text
from .git_analysis import atomic_json
from .raw_capture import utc_now

_MODES = {"summary", "full"}
_ON_VALUES = {"changes", "always"}


@dataclass(frozen=True)
class SlackSettings:
    enabled: bool
    webhook_url: str | None
    timeout_seconds: float
    max_retries: int
    mode: str = "summary"
    on: str = "always"


def _boolean(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _choice(value: str | None, allowed: set[str], default: str) -> str:
    normalized = (value or default).strip().lower()
    return normalized if normalized in allowed else default


def settings(environ: Mapping[str, str] | None = None) -> SlackSettings:
    values = os.environ if environ is None else environ
    try:
        timeout = float(values.get("AGENTCHANGE_SLACK_TIMEOUT_SECONDS", "2"))
    except ValueError:
        timeout = 2.0
    try:
        retries = int(values.get("AGENTCHANGE_SLACK_MAX_RETRIES", "1"))
    except ValueError:
        retries = 1
    return SlackSettings(
        enabled=_boolean(values.get("AGENTCHANGE_SLACK_ENABLED")),
        webhook_url=values.get("AGENTCHANGE_SLACK_WEBHOOK_URL") or None,
        timeout_seconds=max(0.1, min(timeout, 5.0)),
        max_retries=max(0, min(retries, 3)),
        mode=_choice(values.get("AGENTCHANGE_SLACK_MODE"), _MODES, "full"),
        on=_choice(values.get("AGENTCHANGE_SLACK_ON"), _ON_VALUES, "changes"),
    )


def connectivity_description(configuration: SlackSettings) -> tuple[bool, str]:
    if not configuration.enabled:
        return True, "Disabled — receipts will use dry-run mode"
    if not configuration.webhook_url:
        return False, "Enabled, but AGENTCHANGE_SLACK_WEBHOOK_URL is not configured"
    parsed = urllib.parse.urlparse(configuration.webhook_url)
    if parsed.scheme != "https" or parsed.hostname != "hooks.slack.com":
        return False, "Webhook must be an HTTPS hooks.slack.com incoming-webhook URL"
    return True, "Configured — no test message sent"


def preview_state(configuration: SlackSettings) -> str:
    if not configuration.enabled:
        return "dry_run"
    return "pending" if configuration.webhook_url else "not_configured"


def display_state(state: str) -> str:
    if state == "delivered":
        return "Delivered"
    if state == "dry_run":
        return "Dry run"
    if state == "not_configured":
        return "Not configured"
    if state == "duplicate_suppressed":
        return "Duplicate suppressed"
    if state == "skipped_no_changes":
        return "Skipped — no changes"
    if state == "pending":
        return "Pending"
    return "Failed"


def _summary(receipt: dict[str, Any]) -> str:
    task = sanitize_text(str(receipt.get("requested_task", {}).get("value") or "Not captured"))
    commands = receipt.get("validation", {}).get("commands", [])
    passed = sum(item.get("status") == "passed" for item in commands)
    failed = sum(item.get("status") == "failed" for item in commands)
    inconclusive = len(commands) - passed - failed
    validation_parts = [f"{passed} passed", f"{failed} failed"]
    if inconclusive:
        validation_parts.append(f"{inconclusive} inconclusive")
    main_finding = receipt.get("findings", [{}])[0].get("summary", "No material findings") if receipt.get("findings") else "No material findings"
    return sanitize_text(
        f"AgentChange — {receipt['risk']['level'].title()} risk, {receipt['risk']['score']}/100\n\n"
        f"Task: {task}\n"
        f"Changes this turn: {receipt.get('turn_change_count', 0)} files\n"
        f"Validation: {', '.join(validation_parts)}\n"
        f"Main finding: {main_finding}\n"
        f"Receipt: {receipt['receipt_id']}"
    )


def _message(receipt: dict[str, Any], mode: str) -> str:
    if mode == "full":
        from .receipt import render_markdown

        return sanitize_text(render_markdown(receipt, include_integrity=True))
    return _summary(receipt)


def _retry_after_seconds(headers: Any, now: float) -> float:
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return 0.0


def ensure_delivery(
    plugin_data: Path,
    turn_dir: Path,
    receipt: dict[str, Any],
    *,
    configuration: SlackSettings | None = None,
    opener: Any = None,
    sleeper: Any = None,
    clock: Any = None,
) -> dict[str, Any]:
    del plugin_data  # Kept in the API because delivery belongs to this plugin-data receipt.
    status_path = turn_dir / "slack_delivery.json"
    if status_path.exists():
        try:
            previous = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {"state": "failed_transient"}
        previous["duplicate_suppressed_count"] = int(previous.get("duplicate_suppressed_count", 0)) + 1
        previous["last_duplicate_suppressed_at"] = utc_now()
        atomic_json(status_path, previous)
        return {"state": "duplicate_suppressed", "previous_state": previous.get("state"), "attempts": previous.get("attempts", 0)}

    configuration = configuration or settings()
    if not configuration.enabled:
        status = {"state": "dry_run", "attempts": 0, "updated_at": utc_now()}
        atomic_json(status_path, status)
        return status
    if not configuration.webhook_url:
        status = {"state": "not_configured", "attempts": 0, "updated_at": utc_now()}
        atomic_json(status_path, status)
        return status
    if configuration.on == "changes" and not receipt.get("turn_change_count", 0):
        status = {"state": "skipped_no_changes", "attempts": 0, "updated_at": utc_now()}
        atomic_json(status_path, status)
        return status

    opener = opener or urllib.request.urlopen
    sleeper = sleeper or time.sleep
    clock = clock or time.monotonic
    deadline = clock() + min(8.0, configuration.timeout_seconds * (configuration.max_retries + 1) + 2.0)
    body = json.dumps({"text": _message(receipt, configuration.mode)}).encode("utf-8")
    request = urllib.request.Request(
        configuration.webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    attempts = configuration.max_retries + 1
    status: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            status = {"state": "failed_transient", "attempts": attempt - 1, "error": "delivery time budget exhausted"}
            break
        status = {"state": "failed_transient", "attempts": attempt, "ambiguous": True, "updated_at": utc_now()}
        atomic_json(status_path, status)
        retry_after = 0.0
        try:
            with opener(request, timeout=min(configuration.timeout_seconds, remaining)) as response:
                code = response.getcode()
            if 200 <= code < 300:
                status = {"state": "delivered", "attempts": attempt, "http_status": code, "updated_at": utc_now()}
                atomic_json(status_path, status)
                return status
            transient = code in {408, 429} or code >= 500
            status = {"state": "failed_transient" if transient else "failed_permanent", "attempts": attempt, "http_status": code}
        except urllib.error.HTTPError as exc:
            transient = exc.code in {408, 429} or exc.code >= 500
            retry_after = _retry_after_seconds(exc.headers, time.time()) if exc.code == 429 else 0.0
            status = {"state": "failed_transient" if transient else "failed_permanent", "attempts": attempt, "http_status": exc.code}
        except (urllib.error.URLError, TimeoutError, OSError):
            transient = True
            status = {"state": "failed_transient", "attempts": attempt, "error": "network request failed or timed out"}
        if not transient or attempt == attempts:
            break
        delay = min(max(0.2, retry_after), max(0.0, deadline - clock()))
        if delay:
            sleeper(delay)
    status["updated_at"] = utc_now()
    atomic_json(status_path, status)
    return status
