# PHASE 1 — CODEX PLUGIN AND RELIABLE EVIDENCE CAPTURE

Continue working in the AgentChange repository.

Implement **Phase 1: a minimal Codex plugin that reliably records activity observed through supported Codex lifecycle hooks**.

Do not implement Git analysis, contradiction detection, risk scoring, receipt generation, Slack delivery, a database, or GitHub integration in this phase.

# Product boundary

AgentChange does not claim to capture everything Codex does.

Use this wording consistently:

> AgentChange records activity observed through supported Codex lifecycle hooks.

The documentation and future receipts must clearly distinguish:

* Activity observed through hooks.
* Information reported by Codex.
* Repository state inspected later.
* Activity that was not captured or remains unknown.

Do not describe the evidence as:

* Complete.
* Tamper-proof.
* A full audit trail.
* Every Codex action.
* A secure enforcement boundary.

# Phase 1 objective

At the end of this phase, a real Codex session must reliably capture:

1. `SessionStart`
2. At least one successful tool result
3. At least one failed `PostToolUse` command result
4. `Stop`
5. `Stop.last_assistant_message`, when provided by the documented payload

Each event must be stored in a separate per-session JSONL evidence stream.

The central go/no-go criterion is:

> A real Codex session reliably captures `SessionStart`, a failed `PostToolUse`, and `Stop.last_assistant_message` into the correct per-session JSONL file.

Fixture-only success is insufficient for declaring the live plugin integration complete.

# Execution discipline

This is an implementation task, not a documentation-research task.

The repository may be empty or contain only planning files. If so:

* Initialize Git.
* Initialize the Python package.
* Create the required structure.
* Begin with the smallest working vertical slice.

Do not spend time investigating why the repository is sparse.

Do not retry helper tools that are blocked by the workspace sandbox.

Consult official OpenAI documentation only when a concrete command, payload, or validation error blocks progress. Use at most one directly relevant documentation lookup per blocker.

# Required implementation order

Implement in this exact progression.

## Vertical slice 1

Create only:

1. Minimal plugin manifest.
2. One `SessionStart` hook.
3. One standard-library hook handler.
4. One fixture.
5. One JSONL output line.
6. One passing test.

Validate this before adding other events.

## Vertical slice 2

Add:

* `PreToolUse`
* `PostToolUse`
* A successful Bash fixture
* A failed Bash fixture

Then perform a live Codex test using:

```bash
python -c "raise SystemExit(0)"
```

and:

```bash
python -c "raise SystemExit(1)"
```

Inspect the real `PostToolUse.tool_response` payloads.

Do not finalize exit-code normalization until these real payloads have been inspected where the environment permits live testing.

## Vertical slice 3

Add:

* `UserPromptSubmit`
* `PermissionRequest`
* `Stop`
* Patch or `apply_patch` events
* MCP or other local tool events where supported

Only after these three slices work should you add broader fixtures, metadata, redaction, and packaging documentation.

# Architecture

Use this minimal runtime path:

```text
Codex hook JSON on stdin
          ↓
Standard-library capture handler
          ↓
Sanitized raw event JSONL
          ↓
Pydantic normalization outside the critical hook path
```

Suggested structure:

```text
AgentChange/
├── .codex-plugin/
│   └── plugin.json
├── hooks/
│   └── hooks.json
├── skills/
│   └── agentchange/
│       └── SKILL.md
├── agentchange/
│   ├── __init__.py
│   ├── hook_entry.py
│   ├── raw_capture.py
│   ├── normalize.py
│   ├── models.py
│   └── recorder.py
├── fixtures/
│   └── codex_hooks/
├── scripts/
│   ├── install_local.ps1
│   ├── install_local.sh
│   └── generate_demo_events.py
├── examples/
│   └── sample_session.jsonl
├── tests/
├── prompts/
├── pyproject.toml
├── README.md
└── .gitignore
```

Small changes are allowed when they simplify the implementation.

# Critical dependency rule

## Hook capture path

The hook’s critical capture path must use only the Python standard library.

The command invoked by Codex must not require Pydantic or another third-party package merely to record an event.

For example:

```bash
python "${PLUGIN_ROOT}/agentchange/hook_entry.py" capture
```

The capture handler must be able to:

1. Read JSON from standard input.
2. Perform minimal structural validation.
3. Redact obvious secret fields.
4. Limit oversized values.
5. Determine the session identifier.
6. Append one valid JSON line.
7. Update minimal metadata.
8. Return valid hook output.

It must continue working even if optional project dependencies are unavailable.

## Pydantic layer

Pydantic may be used for:

* Normalizing captured events.
* Validating stored JSONL.
* Application-level models.
* Fixture validation.
* Tests.
* Future evidence analysis and receipt generation.

Pydantic must not be required to preserve the initial raw hook event.

If Pydantic validation later fails, keep the sanitized captured event and record the normalization error separately. Do not delete the raw evidence.

# Plugin structure

Create:

```text
.codex-plugin/plugin.json
hooks/hooks.json
skills/agentchange/SKILL.md
```

The plugin manifest should be minimal and valid.

Do not add unnecessary marketplace assets before live hook capture works.

A local marketplace configuration may be added only if it is required by the actual Codex installation workflow.

# Skill

Create:

```text
skills/agentchange/SKILL.md
```

The skill should tell Codex:

1. AgentChange applies to coding tasks involving repository changes, commands, tests, builds, package managers, patches, MCP tools, or permission requests.
2. Run relevant validation where practical.
3. Never claim that tests passed unless successful evidence was observed.
4. State failures and unresolved issues honestly.
5. At the end, summarize:

   * Requested task.
   * Important changes.
   * Validation performed.
   * Known failures.
   * Assumptions.
   * Suggested reviewers.
6. Do not manually send a receipt.
7. Do not modify AgentChange evidence files.

The skill is an instruction layer, not the evidence source.

# Hooks

Use the currently supported events required for this MVP:

```text
SessionStart
UserPromptSubmit
PreToolUse
PermissionRequest
PostToolUse
Stop
```

Use catch-all tool matchers where practical rather than maintaining a fragile list of aliases.

Normalize tool types after capture.

The plugin should observe supported local tool paths such as:

* Bash and command execution.
* `apply_patch`.
* Edit or Write aliases where they map to the canonical patch tool.
* MCP tools.
* Other local function tools that enter the normal hook path.

Do not claim coverage for hosted or specialized tools that bypass these hooks.

# Passive hook behavior

AgentChange must remain passive in Phase 1.

Every hook handler should:

1. Read the event.
2. Record it.
3. Exit successfully when capture succeeds.
4. Print valid JSON such as:

```json
{}
```

Do not:

* Block tools.
* Rewrite tool input.
* Make permission decisions.
* Add model-visible context.
* Continue a stopped turn.
* Execute commands found inside event payloads.

Set short explicit hook timeouts, such as 10 seconds.

# Session isolation

Store runtime data under:

```text
${PLUGIN_DATA}/sessions/<derived-session-key>/
```

Each session directory should contain:

```text
events.jsonl
metadata.json
normalization_errors.jsonl
```

Derive the directory key from the documented `session_id`.

Do not use the raw session identifier directly as a path.

Use a readable sanitized prefix plus a short SHA-256 digest, for example:

```text
abc-session-a18f2c9042b319d1
```

The same `session_id` must always resolve to the same directory.

Do not use:

* A global current-session pointer.
* Timestamp guessing.
* The latest modified directory.
* One shared event file for all sessions.

The Stop event receives the same session identifier and must locate the correct session directly.

# Raw event storage

The standard-library capture handler should append a sanitized event envelope containing:

```json
{
  "capture_version": "1",
  "event_id": "unique-local-id",
  "captured_at": "UTC timestamp",
  "session_id": "original session identifier",
  "source_event": "PostToolUse",
  "payload": {}
}
```

The raw envelope may retain documented payload fields, subject to redaction and truncation.

Do not duplicate complete source files or excessive command output.

# Normalized model

After raw capture, normalize events with Pydantic.

Use a model similar to:

```python
event_id: str
session_id: str
timestamp: datetime
provider: Literal["codex"]
event_type: EventType
source_event: str

cwd: str | None
model: str | None
turn_id: str | None

prompt: str | None
tool_name: str | None
tool_use_id: str | None
command: str | None
exit_code: int | None
path: str | None

result_status: Literal[
    "succeeded",
    "failed",
    "unknown",
    "not_applicable"
]

evidence_confidence: Literal[
    "observed",
    "inferred",
    "reported",
    "unknown"
]

last_assistant_message: str | None
details: dict[str, Any]
```

Allow documented optional and future fields without rejecting the full event.

Require only the minimum fields needed to associate the event with a session and source event.

# Evidence provenance

Use these labels consistently:

## Observed

Directly present in a supported hook payload.

Examples:

* User prompt.
* Command submitted.
* Tool response.
* Stop event.
* Final assistant message.

## Inferred

Derived conservatively from observed data.

Examples:

* File paths parsed from patch text.
* Exit code parsed from recognizable response text.
* Command category inferred from its command string.

## Reported

Statements generated by Codex.

Example:

* `Stop.last_assistant_message`.

## Unknown

Information that could not be reliably determined.

Never silently convert inferred or unknown information into observed facts.

# Command-result normalization

`PostToolUse.tool_response` may not use one guaranteed structure.

Therefore:

1. Preserve a sanitized form of the response.
2. Accept clearly documented or observed structured exit-code fields.
3. Parse textual exit codes only when the format is unambiguous.
4. Mark text-parsed results as `inferred`.
5. Mark unclear results as `unknown`.
6. Never assume success because no explicit error was found.
7. Never mark an attempted command as completed without `PostToolUse`.

Live-test at least:

```bash
python -c "raise SystemExit(0)"
python -c "raise SystemExit(1)"
```

Use the resulting payload shapes to create or update fixtures.

# Permission requests

`PermissionRequest` proves only that Codex requested permission.

Unless a documented payload explicitly includes the final result, record:

```text
permission requested
final decision not captured
```

Do not infer approval or denial.

The passive Phase 1 plugin must not answer permission requests.

# Redaction

Redact common sensitive keys, including:

```text
authorization
token
access_token
refresh_token
api_key
apikey
password
secret
cookie
set-cookie
webhook
private_key
```

Apply case-insensitive matching.

Replace values with:

```text
[REDACTED]
```

Also redact likely secret values in obvious environment-variable or header structures.

Do not promise complete secret detection.

# Truncation

Limit large text and nested values.

Use clear markers such as:

```text
[TRUNCATED: original length 18420]
```

The capture handler must avoid writing arbitrarily large payloads.

Document the chosen limits.

# Metadata

Maintain minimal `metadata.json` fields:

```text
session_key
original_session_id
initial_cwd
model
started_at
last_event_at
event_count
last_source_event
state
```

Write metadata atomically through a temporary file and replacement.

Do not make advanced cross-platform locking a prerequisite for the first live event.

Begin with:

* One encoded append per event.
* Per-session files.
* Atomic metadata replacement.

Add a small locking mechanism only if tests or live validation reveal actual corruption or concurrent-write problems.

# Fixtures

Do not attempt to model every undocumented payload variant.

Create fixtures for:

```text
session_start.json
user_prompt_submit.json
pre_tool_use_bash.json
post_tool_use_bash_success.json
post_tool_use_bash_failed.json
pre_tool_use_patch.json
post_tool_use_patch.json
pre_tool_use_mcp.json
post_tool_use_mcp.json
permission_request.json
stop.json
missing_optional_fields.json
malformed.json
```

Initially base them on the documented schema.

After live validation, update the success, failure, and Stop fixtures to match sanitized real payloads where they differ.

Record in fixture metadata whether each fixture is:

* Documentation-based.
* Live-validated.
* Synthetic edge case.

# Diagnostic mode

Support fixture testing without a running Codex session:

```bash
python -m agentchange.hook_entry capture \
  --fixture fixtures/codex_hooks/post_tool_use_bash_failed.json \
  --plugin-data /tmp/agentchange-test
```

On Windows PowerShell, support an equivalent explicit path.

The production hook still reads from standard input.

Diagnostic mode must use the exact same capture and normalization logic as the production path.

# Sample session

Create:

```text
scripts/generate_demo_events.py
```

It should generate a session containing:

* Session start.
* User request to add password-reset rate limiting.
* Authentication-file patch attempt.
* Dependency-file patch attempt.
* Successful lint command.
* Failed test command.
* Permission request.
* Stop event.
* Final assistant message where available in the fixture.

Generate:

```text
examples/sample_session.jsonl
```

through the production capture and normalization paths.

Do not manually maintain a sample that can drift from the implementation.

Phase 1 must not yet detect contradictions or assign risk.

# Tests

Add focused tests for:

## Standard-library capture path

* Valid stdin JSON.
* Malformed JSON.
* Missing session identifier.
* Session-key sanitization.
* Per-session directory creation.
* JSONL append.
* One event per line.
* UTC timestamp.
* Unique event identifier.
* Redaction.
* Truncation.
* Atomic metadata replacement.
* Separate concurrent sessions.
* Hook output is valid JSON.
* No dependency on Pydantic for raw capture.

## Pydantic normalization layer

* Valid event normalization.
* Unknown optional fields.
* Missing optional fields.
* Bash pre-event.
* Bash success result.
* Bash failure result.
* Unknown command result.
* Patch event.
* MCP event.
* Permission request.
* Stop event.
* `last_assistant_message` provenance is `reported`.
* Text-parsed exit code provenance is `inferred`.
* Structured exit code provenance is `observed`.
* Normalization failure preserves raw evidence.

## Packaging

* Plugin manifest parses.
* Hook configuration parses.
* Skill frontmatter is valid.
* Required six hooks are registered.
* Hook commands use `PLUGIN_ROOT`.
* Runtime writes use `PLUGIN_DATA`.

Tests must use temporary directories.

Never write test data to the real plugin data directory.

# Live validation

After fixtures and core tests pass:

1. Install or enable the plugin locally.
2. Review and trust the hooks using the documented Codex interface.
3. Start a new Codex session.
4. Run one successful command.
5. Run one failed command.
6. Perform one small patch.
7. Finish the turn.
8. Inspect the correct per-session JSONL file.
9. Confirm `SessionStart`, `PostToolUse`, and `Stop`.
10. Confirm `Stop.last_assistant_message` when the payload includes it.

Clearly report:

* Events verified live.
* Events verified only through fixtures.
* Any payload differences.
* Any fields that remain unreliable.

Do not claim live validation succeeded unless evidence files were actually produced by the installed plugin.

# Documentation

Write a focused README covering:

1. What Phase 1 captures.
2. What it does not capture.
3. “Observed,” “inferred,” “reported,” and “unknown.”
4. Local installation.
5. Hook trust and review.
6. Diagnostic fixture mode.
7. Runtime data location.
8. Sample-session generation.
9. Uninstallation.
10. Known limitations.

Use this limitation statement:

> AgentChange records activity observed through supported Codex lifecycle hooks. Hosted tools, specialized tool paths, actions outside Codex, and activity while hooks are disabled or failing may not be captured.

# Validation commands

Run:

```bash
python --version
python -m pip install -e ".[dev]"
python -m compileall agentchange
python -m pytest -q
python -m json.tool .codex-plugin/plugin.json
python -m json.tool hooks/hooks.json
```

Run each valid fixture through diagnostic mode.

Run the malformed fixture and confirm:

* It exits clearly.
* It writes no partial JSONL line.
* Existing evidence remains intact.

Run:

```bash
python scripts/generate_demo_events.py
```

Inspect:

```text
examples/sample_session.jsonl
```

Then attempt live plugin validation.

# Explicitly deferred work

Do not implement during Phase 1:

* Git diff analysis.
* Test-claim contradiction detection.
* Risk scoring.
* Markdown receipts.
* JSON receipts.
* Slack delivery.
* Databases.
* Remote storage.
* GitHub integration.
* Claude Code support.
* Subagent governance.
* Advanced locking.
* Marketplace publishing.
* Cryptographic attestation.

# Acceptance criteria

Phase 1 is complete only when:

* The repository is initialized.
* The plugin manifest is valid.
* The skill is valid.
* All six hook events are configured.
* The capture path runs with the Python standard library only.
* Pydantic is used only after raw evidence has been preserved.
* Sessions are isolated by documented `session_id`.
* Every valid fixture produces a sanitized JSONL event.
* Malformed input does not corrupt evidence.
* Success, failure, and unknown command outcomes remain distinct.
* `Stop.last_assistant_message` is labeled as reported by Codex.
* Permission requests do not imply approval.
* Redaction and truncation work.
* All tests pass.
* A real Codex session captures `SessionStart`, failed `PostToolUse`, and `Stop`, where local plugin testing is supported.
* Live and fixture-only results are reported honestly.
* No Phase 2 functionality has been added prematurely.

# Final response

When Phase 1 is complete, provide:

1. Concise architecture summary.
2. Repository tree.
3. Files created or changed.
4. Test results.
5. One normalized successful command event.
6. One normalized failed command event.
7. One normalized Stop event.
8. Events confirmed through live testing.
9. Events validated only through fixtures.
10. Exact installation and diagnostic commands.
11. Observation gaps and limitations.
12. Go/no-go conclusion for Phase 2.

Commit the completed phase with:

```text
feat: add reliable Codex evidence capture
```
