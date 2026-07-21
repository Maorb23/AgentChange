# PHASE 2 LIVE-EVIDENCE AND ATTRIBUTION REQUIREMENTS

Phase 1 and Phase 1.5 have passed live validation.

A real Codex session confirmed that:

* `SessionStart`, `PostToolUse`, and `Stop` are captured in one session.
* `Stop.last_assistant_message` contains Codex’s final reported statement.
* Ordinary Bash `tool_response` does not reliably include an exit status.
* `agentchange-run` emits reliable machine-readable validation markers.
* Hook events may be appended to JSONL out of chronological order.

Observed live markers:

```text
__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":0,"duration_ms":83}
__AGENTCHANGE_RESULT__={"schema_version":"1","exit_code":1,"duration_ms":29}
```

These markers are the authoritative source for independently observed test, lint, build, type-check, and security-scan outcomes.

Before adding new functionality:

1. Add sanitized versions of the real successful and failed payloads as regression fixtures.
2. Verify that:

   * exit code `0` becomes `succeeded`;
   * nonzero exit code becomes `failed`;
   * confidence is `observed`.
3. Keep ordinary Bash responses without a valid final marker as `unknown`.
4. Do not infer success from output text, empty output, or Codex’s final statement.

# PER-TURN RECEIPTS

Generate one receipt per Codex turn, not one undifferentiated receipt for the entire session.

Use:

```text
session_id
turn_id
```

as the main correlation identifiers.

Every finding, validation result, agent claim, and finalization record must belong to the same `turn_id`.

The Stop handler must:

1. Receive the Stop event.
2. identify its `session_id` and `turn_id`.
3. Load only events belonging to that turn for turn-specific analysis.
4. Optionally include session-level metadata separately.
5. Compare `Stop.last_assistant_message` only with validation evidence from the same turn.
6. Never combine a failed test from an earlier turn with a claim from a later turn.

The receipt identifier should be deterministic from:

```text
session_id + turn_id + receipt_schema_version
```

# EVENT ORDERING AND CONCURRENCY

Do not assume JSONL line order represents execution order.

Hook handlers and tool calls may execute concurrently, so events can be appended in a different order than their timestamps.

Requirements:

* Parse all UTC timestamps.
* Sort events by timestamp for presentation.
* Correlate `PreToolUse` and `PostToolUse` using `tool_use_id`.
* Use `turn_id` to isolate each coding turn.
* Preserve the original JSONL line number for diagnostics.
* Do not use “last line in the file” as the latest event.
* Do not select one arbitrary validation as authoritative when several ran concurrently.

Represent every validation separately.

Example:

```text
ruff check .       passed
pytest tests/unit  passed
pytest tests/e2e   failed
```

The overall validation summary must be:

```text
failed
```

when any independently observed required validation failed.

Use:

* `failed` if at least one authoritative validation failed;
* `passed` only if at least one authoritative validation passed and none failed;
* `unknown` if commands were attempted but no authoritative result was captured;
* `not_observed` if no relevant validation command was captured.

# GIT BASELINE AND TURN ATTRIBUTION

Do not compare only the final working tree at Stop.

The repository may already contain staged, unstaged, or untracked changes before the Codex turn starts. Those changes must not automatically be attributed to the current turn.

At `UserPromptSubmit`, or before the first tool event for the turn, save a lightweight baseline under the session directory:

```text
turns/<turn_id>/git_baseline.json
```

Capture where available:

* Git repository root.
* HEAD SHA.
* Branch.
* `git status --porcelain=v1`.
* Staged file list.
* Unstaged file list.
* Untracked file list.
* Timestamp.

At Stop, capture the equivalent final snapshot.

The analysis should distinguish:

```text
Pre-existing change
New during this turn
Modified further during this turn
No longer present at Stop
Attribution unknown
```

For the MVP, exact line-level attribution is not required.

Do not claim that Codex created a file merely because it is untracked at Stop. Only classify it as newly introduced during the turn if it was absent from the baseline.

If no baseline exists, label repository attribution as:

```text
Repository changes observed at Stop; turn-level attribution unavailable.
```

Do not silently attribute the full dirty working tree to Codex.

# VALIDATION EVIDENCE RULES

Validation results are authoritative only when one of these is true:

1. A valid final `__AGENTCHANGE_RESULT__=` marker was captured.
2. Another supported tool returned an explicit reliable status.

For `agentchange-run` events:

* Parse only the final valid marker.
* Require `schema_version`, `exit_code`, and `duration_ms`.
* Ignore marker-like strings in earlier child output.
* Treat malformed or duplicate final markers as unknown.
* Preserve the original command.
* Record that the result source is `agentchange-run`.
* Set evidence confidence to `observed`.

For ordinary Bash:

* Record that the command was attempted.
* Preserve sanitized output.
* Set the result to `unknown` unless an explicit reliable status exists.
* Do not infer failure from empty output.
* Do not infer success from nonempty output.

# CLAIM COMPARISON

Use `Stop.last_assistant_message` as Codex-reported evidence.

Compare claims only against observed validation events from the same turn.

Support claims such as:

```text
all tests pass
all tests passed
tests passed
test suite passes
lint passes
build succeeded
```

Do not create `TEST_CLAIM_CONTRADICTION` merely because:

* no test was observed;
* a test result is unknown;
* a failed result belongs to another turn;
* the failed command is unrelated to the stated claim.

Use:

```text
TEST_CLAIM_CONTRADICTION
```

only when the same turn contains:

1. A clear positive validation claim.
2. A matching independently observed failed validation.

When a positive claim exists but evidence is missing or unknown, use a separate finding:

```text
VALIDATION_CLAIM_NOT_VERIFIABLE
```

This should be lower severity than a proven contradiction.

# REVISED FINDINGS

Include:

```text
TESTS_FAILED
TEST_CLAIM_CONTRADICTION
VALIDATION_CLAIM_NOT_VERIFIABLE
NO_TEST_EVIDENCE
TEST_RESULT_UNKNOWN
AUTH_CODE_CHANGED
DEPENDENCY_CHANGED
MIGRATION_CHANGED
CI_CHANGED
INFRASTRUCTURE_CHANGED
NEW_UNTRACKED_FILE
PREEXISTING_REPOSITORY_CHANGES
TURN_ATTRIBUTION_UNAVAILABLE
EXTERNAL_OR_MCP_TOOL_USED
PERMISSION_REQUESTED
SESSION_INCOMPLETE
WRITE_NOT_REFLECTED_IN_GIT
GIT_CHANGE_WITHOUT_OBSERVED_WRITE
```

Use cautious language:

```text
No matching write event was captured.
```

Never say:

```text
Codex secretly changed this file.
```

# REVISED RISK RULES

Use:

```text
Authentication or authorization changed during turn: +25
Infrastructure or CI/CD changed during turn: +20
Database migration changed during turn: +15
Dependency manifest or lockfile changed during turn: +10
Observed validation failure: +25
No test evidence for substantive code changes: +10
Validation result unknown: +10
Observed validation claim contradiction: +30
Positive validation claim not verifiable: +10
New untracked source file introduced during turn: +10
MCP or external tool used: +5
Permission requested for sensitive action: +5
Session ended without Stop: +10
More than 30 files changed during turn: +10
Explicit human approval captured: -10
Documentation-only change during turn: -10
```

Do not score pre-existing repository changes as if Codex introduced them.

If turn-level Git attribution is unavailable:

* Report the limitation.
* Score only findings supported by hooks and clearly observed final repository state.
* Do not apply change-attribution penalties that require a baseline.

# STOP FINALIZATION AND IDEMPOTENCY

Use an idempotency key based on:

```text
session_id + turn_id + receipt_schema_version
```

The Stop handler must:

1. Record the Stop event first.
2. Acquire a per-turn finalization guard.
3. Check whether that turn already has a completed receipt.
4. Load and sort same-turn events.
5. Load the Git baseline and final snapshot.
6. Produce findings and risk score.
7. Save receipt JSON and Markdown atomically.
8. Save a completed local finalization marker.
9. Attempt Slack delivery.
10. Store Slack delivery status separately.
11. Return valid hook JSON even when Slack fails.

A failed Slack attempt must not cause the local receipt to be regenerated or lost.

Repeated Stop events may retry Slack only according to an explicit delivery policy. They must not create duplicate local receipts or duplicate Slack messages.

# EVIDENCE INTEGRITY DIGESTS

Avoid self-referential hashes.

Calculate:

1. Raw JSONL digest from the exact captured bytes.
2. Canonical analysis digest before adding digest fields.
3. Canonical JSON receipt-body digest before adding digest fields.
4. Markdown-body digest before adding the evidence-integrity section.

Then append the digest values.

Document exactly what each digest covers.

Do not call the receipts tamper-proof or remotely attested.

# SLACK DELIVERY LIMITS

Slack delivery must never delay the Stop hook excessively.

Requirements:

* Save local receipts before any network request.
* Use a short timeout.
* Cap total Slack retry time.
* Retry only transient failures.
* Do not retry HTTP errors that are clearly permanent.
* Never expose the webhook URL.
* Keep the complete receipt local.
* Send a shorter Slack summary with the risk, major findings, validation results, and local receipt identifier.

Slack acceptance proves delivery to the webhook endpoint only. It does not prove that a human read or approved the receipt.

# REVISED ACCEPTANCE CRITERIA

Phase 2 is complete only when:

* Live AgentChange runner payloads are covered by regression fixtures.
* Exit code `0` and nonzero exit codes normalize as observed evidence.
* Raw Bash results without markers remain unknown.
* Receipt analysis is isolated by `turn_id`.
* Events are not interpreted according to JSONL append order.
* Parallel validations are represented separately.
* A Git baseline is captured before turn changes where possible.
* Pre-existing dirty files are not attributed to the current Codex turn.
* Claims are compared only with same-turn evidence.
* A proven contradiction and an unverifiable claim are separate findings.
* Repeated Stop events are idempotent.
* JSON and Markdown receipts are saved before Slack delivery.
* Slack failure preserves all local results.
* The controlled contradiction demo works.
* A real honest Codex task generates a receipt.
* All tests pass.
