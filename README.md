# AgentChange for Codex

AgentChange creates one evidence-backed change receipt for each completed Codex turn. Supported lifecycle hooks preserve sanitized evidence, the Stop hook compares same-turn validation with Codex's final statement, local Git snapshots provide working-tree attribution, and optional Slack delivery sends a short summary.

The central demo is deliberately adversarial:

```text
Reported by Codex: All tests pass.
Observed runner result: pytest exited 1.
Finding: TEST_CLAIM_CONTRADICTION.
```

## Evidence model

The receipt keeps three sources separate:

- **Observed:** supported hook payloads and authoritative final `agentchange-run` markers.
- **Inferred:** deterministic interpretation of observed evidence or local Git snapshots.
- **Reported by Codex:** `Stop.last_assistant_message`; never promoted to observed evidence.
- **Not captured:** data unavailable through the supported path.

For tests, lint, builds, type checks, and security scans, use:

```bash
agentchange-run -- pytest -q
agentchange-run -- ruff check .
agentchange-run -- npm test
```

Only one valid marker on the final nonempty response line of an `agentchange-run -- ...` command is authoritative. Exit code zero becomes `passed`; nonzero becomes `failed`. Ordinary Bash responses, malformed markers, duplicate markers, and non-final markers remain `unknown`.

## Turn isolation and files

The hook payload's exact `session_id` and `turn_id` select the receipt. JSONL line order is not trusted: same-turn events are parsed, given their original line numbers, sorted by UTC timestamp, and Pre/Post tool events are correlated by `tool_use_id`.

Runtime files are written only under `PLUGIN_DATA`:

```text
sessions/<session-key>/
├── events.jsonl
├── metadata.json
├── normalization_errors.jsonl
└── turns/<turn-key>/
    ├── git_baseline.json
    ├── git_final.json
    ├── receipt.json
    ├── receipt.md
    ├── finalization.json
    └── slack_delivery.json
```

`UserPromptSubmit`, or the first `PreToolUse` fallback, captures the turn baseline. Stop records itself first, reads only matching-turn evidence, takes the final snapshot, attributes dirty paths, writes JSON and Markdown atomically, records local completion, and only then attempts Slack.

Existing dirty files are classified as pre-existing and are not scored as introduced. A file already dirty at baseline and changed again is `Modified further during this turn`. If the baseline is unavailable, the receipt says exactly: `Repository changes observed at Stop; turn-level attribution unavailable.` Baseline-dependent penalties are then skipped.

## Deterministic risk

Risk uses inspectable fixed weights for authentication, CI/infrastructure, migrations, dependencies, observed validation failures, missing or unknown validation, claim contradictions, new untracked files, MCP/external tools, sensitive permission requests, incomplete sessions, large changes, and docs-only reductions. Scores are clamped to 0–100. Pre-existing changes are informational only. The approval reduction is not applied because current permission hooks do not reliably capture the final human decision.

Receipt identifiers are deterministic from schema version, session ID, and turn ID. Integrity fields cover the exact JSONL bytes read at finalization, canonical analysis before digests, canonical JSON receipt body before integrity, and Markdown before its Integrity section. These local hashes detect accidental changes; they are not remote attestation.

## Slack configuration

Do not commit a webhook. Set it in the environment visible to Codex:

```powershell
$env:AGENTCHANGE_SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/..."
```

Or create `${PLUGIN_DATA}/config.json` outside the plugin installation:

```json
{"slack_webhook_url":"https://hooks.slack.com/services/..."}
```

Local receipts are complete before delivery starts. Slack receives only receipt ID, risk, findings, validation summaries, and a note that the full receipt is local. Requests use a two-second timeout and at most two attempts for transient network, 408, 429, or 5xx failures. Permanent 4xx responses are not retried. Delivery means only that the webhook returned 2xx. A persisted attempt is never automatically replayed on repeated Stop, preventing duplicate messages after an ambiguous crash; manual retry requires an explicit operator action.

## Development and validation

PowerShell:

```powershell
Set-Location C:\Users\maorb\work\AgentChange
$env:UV_CACHE_DIR=(Resolve-Path .).Path + '\.uv-cache'
$env:UV_PROJECT_ENVIRONMENT='.venv-codex'
uv sync --extra dev
uv run pytest -q
uv run python -m scripts.generate_demo_events
uv run python -m scripts.demo_end_to_end --export-examples
```

WSL/Linux:

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest -q
python3 -m scripts.generate_demo_events
python3 -m scripts.demo_end_to_end --export-examples
```

The controlled demo creates a temporary Git repository and plugin-data directory, records a failed authoritative pytest result followed by the statement “All tests pass,” and exits nonzero if the contradiction finding is absent. With `--export-examples`, it updates `examples/sample_receipt.json` and `examples/sample_receipt.md`.

## Local plugin update

The personal plugin source is `~/plugins/agentchange`; its marketplace entry is in `~/.agents/plugins/marketplace.json`. Copy the working tree with the local installer, install the Python package so both `agentchange-run` and `agentchange-hook` are on Codex's PATH, refresh the plugin cachebuster, reinstall `agentchange@personal`, and start a new Codex task. The two executables share one isolated Python environment, so Stop finalization does not depend on a system-Python alias. In `/hooks`, review and trust the six commands before relying on capture.

## Known limitations

- Hooks observe only supported Codex tool paths. Hosted or specialized tools, actions outside Codex, and activity while hooks are disabled or failing may not be captured.
- Hooks can be bypassed, and local evidence and receipts can be modified.
- MCP hooks observe the call boundary, not necessarily all external side effects.
- `PermissionRequest` proves a request occurred, not the final decision.
- Git attribution is path-level, not line-level, and local Git inspection is not remote attestation.
- Concurrent appends can make a session JSONL digest historical: its coverage text identifies the exact bytes read at finalization time.
- Slack acceptance does not prove a person read or retained the message.
- AgentChange is evidence, not proof that every action was captured, and is not a secure execution sandbox.
