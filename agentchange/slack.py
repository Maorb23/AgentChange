"""Best-effort Slack incoming-webhook delivery with bounded retries."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .git_analysis import atomic_json
from .raw_capture import utc_now


def _webhook_url(plugin_data: Path) -> str | None:
    value = os.environ.get("AGENTCHANGE_SLACK_WEBHOOK_URL")
    if value:
        return value
    path = plugin_data / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = config.get("slack_webhook_url") if isinstance(config, dict) else None
    return value if isinstance(value, str) and value else None


def _summary(receipt: dict[str, Any]) -> str:
    finding_codes = ", ".join(item["code"] for item in receipt["findings"]) or "none"
    validations = ", ".join(
        f"{item['category']}={item['status']}" for item in receipt["validation"]["commands"]
    ) or "not observed"
    return (
        f"AgentChange receipt {receipt['receipt_id']}\n"
        f"Risk: {receipt['risk']['level']} ({receipt['risk']['score']}/100)\n"
        f"Findings: {finding_codes}\n"
        f"Validations: {validations}\n"
        "The full receipt is stored locally under PLUGIN_DATA."
    )


def ensure_delivery(plugin_data: Path, turn_dir: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    status_path = turn_dir / "slack_delivery.json"
    if status_path.exists():
        try:
            return json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "unknown", "retry_policy": "manual only after an ambiguous local state"}
    url = _webhook_url(plugin_data)
    if not url:
        status = {"state": "not_configured", "attempts": 0, "updated_at": utc_now()}
        atomic_json(status_path, status)
        return status

    # Persist before network I/O. A crash after acceptance therefore cannot cause an automatic duplicate.
    status = {
        "state": "attempting",
        "attempts": 0,
        "updated_at": utc_now(),
        "retry_policy": "at most two transient attempts in this finalization; never automatic after an ambiguous attempt",
    }
    atomic_json(status_path, status)
    body = json.dumps({"text": _summary(receipt)}).encode("utf-8")
    for attempt in (1, 2):
        status["attempts"] = attempt
        status["updated_at"] = utc_now()
        atomic_json(status_path, status)
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                code = response.getcode()
            if 200 <= code < 300:
                status.update({"state": "accepted", "http_status": code, "updated_at": utc_now()})
                atomic_json(status_path, status)
                return status
            transient = code in {408, 429} or code >= 500
            status.update({"state": "failed_transient" if transient else "failed_permanent", "http_status": code})
        except urllib.error.HTTPError as exc:
            transient = exc.code in {408, 429} or exc.code >= 500
            status.update({"state": "failed_transient" if transient else "failed_permanent", "http_status": exc.code})
        except (urllib.error.URLError, TimeoutError, OSError):
            transient = True
            status.update({"state": "failed_transient", "error": "network request failed or timed out"})
        if not transient or attempt == 2:
            break
        time.sleep(0.2)
    status["updated_at"] = utc_now()
    atomic_json(status_path, status)
    return status
