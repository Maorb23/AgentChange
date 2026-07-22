# AgentChange

Evidence-backed change receipts for Codex coding sessions.

AgentChange records what Codex changed, which supported validation commands actually ran, and what the local Git state shows at the end of a turn. It produces a readable Markdown receipt, a structured JSON receipt, and an optional sanitized Slack summary.

AgentChange is an evidence and reporting tool—not a sandbox, security boundary, or replacement for code review.

## Requirements

- Python 3.11 or newer
- Codex running on native Linux or in WSL2
- A Git repository for turn-level file attribution

The current release is designed for Python projects and common Python validation workflows. Windows-native Codex agents are not supported.

## Install

Install the package using your preferred Linux user-level Python package workflow. From a source checkout, an editable install is convenient during development:

```bash
python -m pip install -e .
```

Then install and verify the Codex integration:

```bash
agentchange install
agentchange doctor
```

`agentchange install` registers or updates the personal Codex plugin, removes only stale AgentChange plugin caches, verifies the Stop hook, preserves plugin data, and never uses `sudo`. It is safe to run again after an upgrade.

Restart Codex after installation and approve the six AgentChange lifecycle hooks if prompted. The hooks use executables on the WSL/Linux PATH; users do not need to configure Python virtual-environment paths or edit hook JSON.

## Use with Codex

Work normally in Codex. When you validate Python code, use the AgentChange wrapper:

```bash
agentchange exec --auto pytest -q
```

Both `pytest ...` and `python -m pytest ...` are resolved to the project Python in this order:

1. Active `VIRTUAL_ENV`.
2. `.venv/bin/python` in the project.
3. `venv/bin/python` in the project.
4. Python on PATH.

The command is executed without a shell. AgentChange records the requested command, resolved argument array, sanitized display command, duration, and authoritative child exit code. `agentchange-run -- ...` remains available for backward compatibility.

Useful commands:

```bash
agentchange doctor
agentchange latest
agentchange status
agentchange exec --auto pytest -q tests/test_example.py
```

`latest` prints the newest Markdown receipt. `status` summarizes installation, hook readiness, Slack state, the newest receipt, and incomplete finalizations. Runtime locations are intentionally kept as an implementation detail.

## What AgentChange records

At the end of a turn, AgentChange can report:

- Files added, modified, deleted, or renamed during the turn, including non-Python files such as HTML, CSS, JavaScript, JSON, and Markdown.
- A same-turn Git diff and path-level attribution.
- Validation commands and their observed exit codes when run through `agentchange exec --auto`.
- Reported claims from Codex, clearly separated from independently observed evidence.
- Deterministic risk findings for issues such as failed validation, new files, permission requests, and claim contradictions.

Files already dirty before the turn are retained in detailed attribution but are not counted as Codex changes.

## Receipts

Receipts deliberately separate four source classes:

- **Observed:** supported hook payloads and authoritative final runner markers.
- **Inferred:** deterministic interpretation of observed evidence or local Git state.
- **Reported by Codex:** text from Codex’s answer, never promoted to observed evidence.
- **Not captured:** information unavailable through the supported path.

A receipt says `1 of 1 observed validation commands passed`, with the selected scope, instead of claiming the whole project is valid. Every relevant same-turn validation appears in a table. Results are one of `passed`, `failed`, `command_not_found`, `infrastructure_error`, `unknown`, or `not_observed`. A nonzero pytest exit is called `failed` only when captured output indicates executed test failures; setup, collection, invocation, or unavailable-command problems are described conservatively.

Personal absolute paths and webhook URLs are removed from Markdown, the Codex summary, and Slack. Exact command arrays remain in the local JSON receipt. Pre-existing dirty files stay in detailed JSON attribution but appear in Markdown only as a compact count.

For each attributed file, Codex may provide a concise description generated from its review of the same-turn Git diff. These descriptions are stored under `model_derived_change_summary` and are clearly separated from observed file paths; they are never promoted to observed evidence. Invented, absolute, traversal, duplicate, pre-existing, or overly long entries are discarded. If the structured summary is absent or invalid, receipt generation continues with an explicit fallback message.

On the first Stop, AgentChange saves the isolated same-turn patch as `turn.diff`, then saves JSON and Markdown before Slack delivery and returns one documented Stop continuation containing a concise receipt. The continuation Stop sees `stop_hook_active`, exits normally, and does not regenerate, revalidate, or resend.

### UI receipt controls

After `agentchange install`, start a new Codex task (or restart Codex). No UI environment variables are required for the recommended default:

```text
AGENTCHANGE_UI_ON=changes
AGENTCHANGE_UI_MODE=summary
```

This default avoids an extra Codex continuation for ordinary diagnostic turns. It shows one concise receipt only when AgentChange observed a turn-attributed file change. Validation-only turns remain in local evidence without consuming an extra Codex continuation.

Override the defaults only when needed, using environment variables available to the WSL environment that runs Codex:

```bash
export AGENTCHANGE_UI_ON=changes       # changes (default) or always
export AGENTCHANGE_UI_MODE=summary     # off, summary (default), or full
```

`off` always returns normally after saving the local receipt. `always` shows a receipt for every turn. `full` is a debugging option that displays the complete Markdown receipt and consumes more context.

## Slack notifications

Slack uses an incoming webhook; no bot, OAuth flow, backend, or hosted AgentChange service is required. Keep the webhook outside Git and provide it to the Codex WSL/Linux environment:

```bash
export AGENTCHANGE_SLACK_ENABLED=true
export AGENTCHANGE_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'
export AGENTCHANGE_SLACK_TIMEOUT_SECONDS=2
export AGENTCHANGE_SLACK_MAX_RETRIES=1
```

With Slack disabled (the default), receipts use `dry_run`. If Slack is enabled without a webhook, the state is `not_configured`. Delivery states are `dry_run`, `delivered`, `failed_transient`, `failed_permanent`, `not_configured`, and `duplicate_suppressed`.

Receipts are saved before the network request. Transient network errors, HTTP 408, 429, and 5xx responses are retried within a short total budget; permanent 4xx responses are not retried. `Retry-After` is respected where practical. A persisted attempt suppresses repeated Stop delivery, and neither saved status nor user-facing output contains the webhook URL. `agentchange doctor` validates configuration syntax but never sends a test message.

## Evidence and risk model

The hook payload’s `session_id` and `turn_id` select isolated storage. Same-turn events are normalized from per-session JSONL, ordered by timestamp, and correlated by `tool_use_id`. The first `UserPromptSubmit` or `PreToolUse` captures a Git baseline. Stop captures itself first, reads only matching-turn evidence, takes a final local Git snapshot, and attributes paths changed during the turn.

Risk uses fixed, inspectable rules for sensitive code areas, observed failures, missing or inconclusive validation, claim contradictions, new files, external tools, permission requests, incomplete capture, and change size. A key demo remains:

```text
Reported by Codex: All tests pass.
Observed runner marker: pytest exited 1 after test assertions failed.
Finding: TEST_CLAIM_CONTRADICTION.
```

## Development

From Linux or WSL2:

```bash
python -m pip install -e '.[dev]'
python -m compileall agentchange
pytest -q
agentchange doctor
```

Automated Slack tests mock all network requests. Never use a real webhook in the test suite.

## Limitations

- Hooks observe only supported Codex tool paths. Hosted or specialized tools and actions outside Codex may not be captured.
- Hooks can be disabled or bypassed; local evidence and receipts can be modified.
- MCP hooks observe the call boundary, not necessarily all external side effects.
- `PermissionRequest` shows that permission was requested, not the final human decision.
- Git attribution is path-level, and local Git inspection is not remote attestation.
- Slack delivery means the incoming webhook returned success, not that a person read the message.
- AgentChange is evidence, not proof that every action was captured, and is not a secure execution sandbox.
- This phase intentionally excludes Windows-native agents, macOS, non-Python productization, remote backends, dashboards, databases, GitHub integration, and MCP servers.
