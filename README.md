# AgentChange for Codex

AgentChange creates an evidence-backed receipt after each completed Codex coding turn. It records supported lifecycle events, independently observes selected validation commands, attributes local Git changes, applies deterministic risk rules, displays a concise receipt once in Codex, and can send a sanitized summary to Slack.

Phase 3 supports native Linux and WSL2 with Codex configured to run in WSL. It is designed for Python projects using pytest and common Python validation tools. It does not support Windows-native Codex agents.

## Install

Install the Python package once using your preferred Linux user-level package mechanism, then product setup is two commands:

```bash
agentchange install
agentchange doctor
```

`agentchange install` registers or updates `agentchange@personal`, removes only stale AgentChange plugin caches, verifies the `agentchange-hook finalize` Stop hook, preserves plugin data, and never uses `sudo`. It is safe to run again after an upgrade.

Restart Codex after installation and approve the six AgentChange lifecycle hooks if prompted. The hooks use executables on the WSL/Linux PATH; users do not need to configure Python virtual-environment paths or edit hook JSON.

## Daily use

Work normally in Codex. The AgentChange skill directs Python validation through:

```bash
agentchange exec --auto pytest -q
```

Both `pytest ...` and `python -m pytest ...` are resolved to the detected project Python in this order:

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

`latest` prints the newest Markdown receipt. `status` summarizes the installed version, hook readiness, Slack state, newest session and receipt, and incomplete finalizations. Runtime locations remain an implementation detail.

## What a receipt says

Receipts deliberately separate four source classes:

- **Observed:** supported hook payloads and authoritative final runner markers.
- **Inferred:** deterministic interpretation of observed evidence or local Git state.
- **Reported by Codex:** text from Codex’s answer, never promoted to observed evidence.
- **Not captured:** information unavailable through the supported path.

A receipt says `1 of 1 observed validation commands passed`, with the selected scope, instead of claiming the whole project is valid. Every relevant same-turn validation appears in a table. Results are one of `passed`, `failed`, `command_not_found`, `infrastructure_error`, `unknown`, or `not_observed`. A nonzero pytest exit is called `failed` only when captured output indicates executed test failures; setup, collection, invocation, or unavailable-command problems are described conservatively.

Personal absolute paths and webhook URLs are removed from Markdown, the Codex summary, and Slack. Exact command arrays remain in the local JSON receipt. Pre-existing dirty files stay in detailed JSON attribution but appear in Markdown only as a compact count.

On the first Stop, AgentChange saves JSON and Markdown before Slack delivery, then returns one documented Stop continuation containing a concise receipt. The continuation Stop sees `stop_hook_active`, exits normally, and does not regenerate, revalidate, or resend.

## Slack

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

## Known limitations

- Hooks observe only supported Codex tool paths. Hosted or specialized tools and actions outside Codex may not be captured.
- Hooks can be disabled or bypassed; local evidence and receipts can be modified.
- MCP hooks observe the call boundary, not necessarily all external side effects.
- `PermissionRequest` shows that permission was requested, not the final human decision.
- Git attribution is path-level, and local Git inspection is not remote attestation.
- Slack delivery means the incoming webhook returned success, not that a person read the message.
- AgentChange is evidence, not proof that every action was captured, and is not a secure execution sandbox.
- This phase intentionally excludes Windows-native agents, macOS, non-Python productization, remote backends, dashboards, databases, GitHub integration, and MCP servers.
