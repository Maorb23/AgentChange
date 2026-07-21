You are Codex GPT-5.6 High acting as a pragmatic senior engineer and startup CTO.

# Product

We are building a one-day MVP called **AgentChange for Codex**.

AgentChange is a Codex plugin that automatically creates an evidence-backed receipt after a Codex coding task and sends it to a configured Slack destination.

The product statement is:

> Install AgentChange once, and every completed Codex coding task automatically sends an evidence-backed change receipt to Slack.

The MVP is deliberately narrow. It supports Codex first and does not attempt to become a complete enterprise agent-governance platform.

# Main workflow

```text
Developer gives Codex a coding task
                ↓
AgentChange hooks observe supported lifecycle events
                ↓
Events are normalized into local JSONL evidence
                ↓
The Stop hook examines the evidence and local Git changes
                ↓
AgentChange creates a deterministic risk assessment
                ↓
Markdown and JSON receipts are generated
                ↓
The receipt is sent to Slack through an incoming webhook
```

# Key demo scenario

The finished demo must prove that AgentChange can detect a contradiction between what Codex says and what the recorded evidence shows.

Example:

```text
Codex statement:
“All tests pass.”

Captured evidence:
pytest -q
exit code: 1

AgentChange conclusion:
Claim not verified.
```

This contradiction is the most important demonstration moment.

# One-day constraint

The implementation must be:

* Functional.
* Small.
* Easy to understand.
* Easy to run locally.
* Easy to explain in five minutes.
* Realistic enough to demonstrate to a CTO.
* Implementable and reviewable in one day.

Prefer straightforward code over abstractions.

Do not build:

* A database.
* A web dashboard.
* User accounts.
* Organization management.
* Billing.
* GitHub Actions.
* GitHub pull-request comments.
* A GitHub App.
* Claude Code support.
* Multi-agent compatibility.
* A remote backend.
* An LLM-based scoring engine.
* A full security sandbox.
* Cryptographic remote attestation.
* A complex policy language.

# Required implementation choices

Use:

* Python 3.11+
* Pydantic for normalized models
* JSONL for event evidence
* Pytest for tests
* Codex plugin packaging
* Codex lifecycle hooks
* A Codex skill
* Local Git commands for final-state inspection
* Deterministic risk rules
* Markdown and JSON receipt output
* Slack incoming webhook delivery
* Standard library HTTP support where practical

No paid API or hosted service should be required beyond the user-provided Slack webhook.

# Codex extension model

The plugin should contain:

```text
agentchange/
├── .codex-plugin/
│   └── plugin.json
├── skills/
│   └── agentchange/
│       └── SKILL.md
├── hooks/
│   └── hooks.json
├── agentchange/
│   ├── __init__.py
│   ├── models.py
│   ├── normalize.py
│   ├── recorder.py
│   ├── git_analysis.py
│   ├── evidence.py
│   ├── risk.py
│   ├── receipt.py
│   ├── slack.py
│   └── hook_entry.py
├── scripts/
│   ├── install_local.sh
│   ├── generate_demo_events.py
│   └── demo_end_to_end.sh
├── fixtures/
│   └── codex_hooks/
├── examples/
│   ├── sample_session.jsonl
│   ├── sample_receipt.json
│   └── sample_receipt.md
├── tests/
├── pyproject.toml
└── README.md
```

You may make small changes when they materially simplify the implementation.

# Hook design

Use these Codex lifecycle events where supported:

* `SessionStart`
* `UserPromptSubmit`
* `PreToolUse`
* `PermissionRequest`
* `PostToolUse`
* `Stop`

Use `PLUGIN_ROOT` to locate plugin code.

Use `PLUGIN_DATA` for writable runtime state.

Do not write runtime data into the installed plugin directory.

Store sessions separately:

```text
${PLUGIN_DATA}/sessions/<session_id>/events.jsonl
${PLUGIN_DATA}/sessions/<session_id>/metadata.json
${PLUGIN_DATA}/sessions/<session_id>/receipt.json
${PLUGIN_DATA}/sessions/<session_id>/receipt.md
```

Do not use one global “current session” file because Codex may have more than one active thread.

# Source-of-truth rules

Separate these three concepts:

1. **Observed evidence**

   * Hook events that AgentChange actually received.

2. **Repository state**

   * Local Git diff and working-tree state inspected during finalization.

3. **Agent statement**

   * What Codex says it completed or validated.

Never present agent statements as observed evidence.

The receipt must clearly label whether information was:

* Observed.
* Inferred.
* Reported by Codex.
* Not captured.

# Security honesty

The product must state clearly:

* Hooks observe only supported Codex tool paths.
* Hosted or specialized tools may not be captured.
* Hooks can be disabled or bypassed.
* Local evidence files can be modified.
* Local Git inspection is not remote attestation.
* A receipt is evidence, not proof that every action was captured.
* AgentChange is not a secure execution sandbox.

# Two implementation phases

## Phase 1

Build and validate:

* Plugin structure.
* Plugin manifest.
* AgentChange skill.
* Codex hook configuration.
* Hook entry point.
* Hook-payload fixtures.
* Normalized event schema.
* Per-session JSONL recording.
* Diagnostic and local installation flow.

## Phase 2

Build and validate:

* Local Git analysis.
* Test-result extraction.
* Contradiction detection.
* Deterministic risk scoring.
* Markdown and JSON receipts.
* Slack webhook delivery.
* Stop-hook finalization.
* End-to-end demo.
* Documentation.

# Your task now

Do not implement the full product yet.

First:

1. Inspect the existing repository.
2. Read the current official Codex documentation for:

   * Plugins.
   * Skills.
   * Lifecycle hooks.
   * Hook input and output schemas.
   * Hook trust and review.
3. Do not rely solely on assumptions in this prompt when official schemas differ.
4. Explain what already exists in the repository.
5. Identify what should be preserved.
6. Identify which files should be added or modified.
7. Confirm the exact hook events and payload fields that are currently supported.
8. Explain how commands, patches, MCP tools, permissions, prompts, and Stop events can be observed.
9. Identify events or tools that cannot be observed.
10. Propose the smallest realistic architecture.
11. Explain how concurrent Codex sessions will remain isolated.
12. Explain how the Stop hook will locate the correct session.
13. Explain how Slack delivery will be configured without committing secrets.
14. State all assumptions.
15. Produce a concise Phase 1 and Phase 2 implementation plan.

Do not create broad placeholders for both phases.

Do not ask minor implementation questions. Choose the simplest documented option, note the choice, and proceed only after presenting the plan.

End with:

* Proposed repository tree.
* Phase 1 acceptance criteria.
* Phase 2 acceptance criteria.
* Exact validation commands.
* Main known limitations.
