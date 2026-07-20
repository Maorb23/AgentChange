Continue working in the existing AgentChange repository.

Phase 1 has already created:

* A valid Codex plugin.
* An AgentChange skill.
* Lifecycle hooks.
* Per-session JSONL evidence.
* Normalized hook events.
* Hook fixtures and tests.

Implement **Phase 2: Git analysis, evidence checks, deterministic risk scoring, receipt generation, Slack delivery, and the complete end-to-end demo**.

# Goal

When Codex completes a coding turn, the `Stop` hook should automatically:

1. Load the correct session evidence.
2. Inspect the local repository state.
3. Determine what was observed.
4. Determine what changed.
5. Identify validation results.
6. Detect contradictions between Codex claims and recorded evidence where possible.
7. Calculate an explainable risk score.
8. Generate JSON and Markdown receipts.
9. Send a concise receipt to Slack.
10. Return a valid Codex hook response.

The local demo must work without Slack credentials by using dry-run mode.

# Important evidence distinction

Every receipt must distinguish between:

## Observed

Directly captured through hooks:

* Prompts.
* Commands attempted.
* Command results.
* Patch or write tools.
* MCP calls.
* Permission requests.
* Stop event.

## Repository state

Observed through local Git commands during finalization:

* Changed files.
* Added or deleted files.
* Line counts.
* Sensitive paths.
* Dependency changes.
* Working-tree state.

## Reported by Codex

Statements Codex made about:

* Completed work.
* Tests.
* Validation.
* Remaining issues.

## Unknown

Anything not observable through supported hooks or Git.

Never claim complete activity capture.

# Git analysis

At Stop time, inspect the working directory from session metadata.

Use safe subprocess argument arrays.

Never use `shell=True`.

Support repositories with:

* Staged changes.
* Unstaged changes.
* Untracked files.
* A detached HEAD where practical.
* No commits yet where practical.

Collect:

* Repository root.
* Current branch where available.
* HEAD SHA where available.
* Files added.
* Files modified.
* Files deleted.
* Untracked files.
* Added and deleted line totals.
* Whether authentication or authorization code changed.
* Whether dependency files changed.
* Whether migrations changed.
* Whether CI/CD changed.
* Whether infrastructure changed.
* Whether tests changed.
* Whether changes are documentation-only.

Keep path rules transparent and centralized.

Sensitive examples:

```text
**/auth/**
**/authentication/**
**/authorization/**
**/permissions/**
**/security/**
**/migrations/**
.github/workflows/**
infra/**
infrastructure/**
terraform/**
*.tf
Dockerfile
docker-compose*.yml
package.json
package-lock.json
yarn.lock
pnpm-lock.yaml
requirements*.txt
pyproject.toml
poetry.lock
```

Do not store the full Git diff in Slack.

# Validation-result extraction

Identify test commands conservatively.

Support patterns such as:

```text
pytest
python -m pytest
npm test
npm run test
yarn test
pnpm test
go test
cargo test
mvn test
gradle test
dotnet test
```

Also recognize lint and build commands separately where practical.

Use the latest completed relevant command as the primary result.

Do not treat an attempted command without a completion result as passed.

Classify validations as:

* Passed.
* Failed.
* Attempted but result unknown.
* Not observed.

# Codex claim capture

First determine whether the current official Stop-hook payload includes Codex’s final response or another reliable final statement.

If it does:

* Normalize and store the statement.
* Compare relevant claims with observed evidence.

If it does not:

* Do not fabricate access.
* Use the most reliable documented alternative.
* The skill may instruct Codex to emit a structured summary artifact, but that artifact must be labeled “reported by Codex,” not observed evidence.
* Keep the demo fixture able to exercise contradiction detection independently.

Support normalized test-success claims such as:

```text
all tests pass
all tests passed
tests passed
test suite passes
test suite is passing
```

The essential contradiction is:

```text
Reported by Codex:
“All tests pass.”

Observed:
pytest -q exited with code 1.

Conclusion:
TEST_CLAIM_CONTRADICTION
```

# Evidence findings

Create stable finding models with:

```python
code: str
title: str
severity: str
explanation: str
evidence: list[str]
score_delta: int
```

Support findings such as:

```text
TESTS_FAILED
TEST_CLAIM_CONTRADICTION
NO_TEST_EVIDENCE
TEST_RESULT_UNKNOWN
AUTH_CODE_CHANGED
DEPENDENCY_CHANGED
MIGRATION_CHANGED
CI_CHANGED
INFRASTRUCTURE_CHANGED
UNTRACKED_FILE
EXTERNAL_OR_MCP_TOOL_USED
PERMISSION_REQUESTED
SESSION_INCOMPLETE
WRITE_NOT_REFLECTED_IN_GIT
GIT_CHANGE_WITHOUT_OBSERVED_WRITE
```

Be careful with the last two:

* Missing write evidence does not prove Codex did not make the change.
* A patch may touch multiple files.
* Some file operations may not be observable.

Use wording such as:

> No matching write event was captured.

Not:

> Codex secretly changed this file.

# Deterministic risk score

Implement an explainable score from 0 to 100.

Suggested initial rules:

```text
Authentication or authorization changed: +25
Infrastructure or CI/CD changed: +20
Database migration changed: +15
Dependency manifest or lockfile changed: +10
Latest test result failed: +25
No test evidence for code changes: +10
Test result unknown: +10
Test-success claim contradicted: +30
Untracked source file created: +10
MCP or external tool used: +5
Permission requested for sensitive action: +5
Session ended without a Stop event: +10
More than 30 files changed: +10
Explicit human approval captured: -10
Documentation-only change: -10
```

Clamp the result to 0–100.

Risk levels:

```text
0–29: Low
30–59: Moderate
60–79: High
80–100: Critical
```

Store every contribution.

Do not use an LLM for risk scoring.

# Receipt JSON

Generate a structured JSON receipt containing:

* Receipt version.
* Session identifier.
* Provider: Codex.
* Model where captured.
* Working directory.
* Repository.
* Branch.
* HEAD SHA.
* User request summary.
* Agent-reported summary.
* Observed-event counts.
* Changed files.
* Validation results.
* Findings.
* Risk score.
* Risk level.
* Score breakdown.
* Required reviewers.
* Evidence limitations.
* Evidence integrity digests.
* Generated timestamp.

Use stable ordering and canonical serialization where relevant.

# Markdown receipt

Generate a readable receipt resembling:

````markdown
## 🤖 AgentChange Receipt — Codex

**Risk:** 🔴 Critical — 100/100  
**Repository:** `payments-service`  
**Session:** `abc123`  
**Model:** `gpt-5.6`  

### Requested task

Add password-reset rate limiting.

### Observed activity

| Category | Result |
|---|---:|
| Commands completed | 3 |
| Files changed | 4 |
| Patch/write tools | 2 |
| MCP tools | 0 |
| Permission requests | 1 |

### Repository changes

- Authentication code changed: `src/auth/reset_password.py`
- Dependency file changed: `pyproject.toml`

### Validation

- ✅ `ruff check .` exited with code 0
- ❌ `pytest -q` exited with code 1

### Evidence conflict

> Codex reported: “All tests pass.”

Observed evidence:

```text
pytest -q
exit code: 1
````

**Conclusion: Claim not verified.**

### Risk explanation

* Authentication code changed: +25
* Dependency file changed: +10
* Tests failed: +25
* Test-success claim contradicted: +30
* Permission requested: +5

### Required review

* Application owner
* Security reviewer

### Evidence limitations

AgentChange reports supported hook events and local Git state. It does not guarantee that all Codex activity was captured.

````

Keep it concise enough for Slack.

# Evidence integrity

Calculate SHA-256 digests for:

- Raw session JSONL.
- Canonical JSON receipt body.
- Markdown receipt body.

Call these:

> Evidence integrity digests

Do not call them tamper-proof.

# Slack delivery

Use:

```text
AGENTCHANGE_SLACK_WEBHOOK_URL
````

Optional settings:

```text
AGENTCHANGE_SLACK_ENABLED=true
AGENTCHANGE_SLACK_TIMEOUT_SECONDS=10
AGENTCHANGE_SLACK_MAX_RETRIES=2
```

Requirements:

* Never commit or log the webhook.
* Never include the webhook in exceptions.
* Use a timeout.
* Retry only a small number of transient failures.
* Do not block receipt generation when Slack fails.
* Save the local receipt before attempting Slack.
* Record Slack delivery status separately.
* Keep the payload within Slack message-size constraints.
* Send a concise summary rather than the complete event history.
* Use plain webhook delivery for the MVP.
* Do not add Slack OAuth or a Slack bot.

Support dry-run mode:

```text
AGENTCHANGE_SLACK_ENABLED=false
```

When dry-run mode is active:

* Generate all receipts.
* Print where they were stored.
* Do not make a network request.
* Mark delivery status as `dry_run`.

# Stop hook

Upgrade the Phase 1 Stop handler.

It should:

1. Parse the Stop event.
2. Record it.
3. Locate the session directory.
4. Prevent duplicate finalization for the same turn where possible.
5. Load and validate session evidence.
6. Inspect Git.
7. Produce findings.
8. Calculate risk.
9. Generate JSON and Markdown.
10. Save both atomically.
11. Attempt Slack delivery.
12. Record delivery result.
13. Print the valid hook response expected by Codex.
14. Avoid blocking Codex because Slack failed.

Use a finalization marker or deterministic turn identifier to avoid duplicate Slack receipts when Stop is delivered more than once.

# Demo without a false live claim

A real Codex model may correctly report that tests failed, so the demo must not depend on forcing Codex to lie.

Provide two demos:

## Demo A: real, honest Codex task

* Run a small Codex coding task.
* Capture its real events.
* Generate an honest receipt.
* Send it to Slack or dry-run output.

## Demo B: deterministic contradiction fixture

* Feed fixture events where:

  * `pytest -q` exits with code 1.
  * The agent-reported summary says “All tests pass.”
* Generate a receipt containing `TEST_CLAIM_CONTRADICTION`.

Label Demo B as a controlled integrity test, not a claim that Codex normally lies.

# End-to-end script

Create:

```text
scripts/demo_end_to_end.sh
```

The script should:

1. Create a temporary Git repository.
2. Configure a local demo Git identity.
3. Create an initial application and commit.
4. Generate fixture events through the real normalizer.
5. Modify:

   * `src/auth/reset_password.py`
   * `pyproject.toml`
6. Record corresponding patch or write events.
7. Record a successful lint result.
8. Record a failed test result.
9. Add the controlled “All tests pass” reported statement.
10. Record Stop.
11. Run the real finalizer.
12. Generate JSON and Markdown receipts.
13. Run Slack in dry-run mode by default.
14. Print:

* Session path.
* JSON receipt path.
* Markdown receipt path.
* Risk score.
* Main contradiction.

15. Exit successfully.

Do not destructively modify the AgentChange repository.

# Tests

Add tests for:

* Git repository detection.
* Staged changes.
* Unstaged changes.
* Untracked files.
* Sensitive-path classification.
* Dependency classification.
* Validation-command recognition.
* Successful command result.
* Failed command result.
* Unknown command result.
* Claim normalization.
* Claim contradiction.
* Finding generation.
* Score contributions.
* Score clamping.
* Risk boundaries.
* Review recommendations.
* Canonical JSON output.
* Stable Markdown output.
* Evidence digests.
* Slack dry run.
* Slack success.
* Slack timeout.
* Slack transient retry.
* Slack permanent failure.
* Webhook redaction.
* Receipt persistence despite Slack failure.
* Duplicate Stop/finalization handling.
* Controlled contradiction demo.

Mock Slack network requests in tests.

Do not require a real webhook for tests.

# README

Document:

1. What AgentChange does.
2. What it does not guarantee.
3. Local plugin installation.
4. Hook trust through `/hooks`.
5. Skill activation.
6. Configuration.
7. Slack webhook setup.
8. Dry-run mode.
9. Where evidence and receipts are stored.
10. End-to-end demo.
11. Real Codex task test.
12. Controlled contradiction test.
13. Risk-scoring rules.
14. Supported observations.
15. Unsupported or incomplete observations.
16. Uninstallation.
17. One-day MVP boundaries.

Provide copy-paste commands.

# Final validation

Run:

```bash
python -m compileall agentchange
pytest -q
./scripts/demo_end_to_end.sh
```

Validate:

```text
.codex-plugin/plugin.json
hooks/hooks.json
skills/agentchange/SKILL.md
```

Generate:

```text
examples/sample_session.jsonl
examples/sample_receipt.json
examples/sample_receipt.md
```

Where supported, perform a real local plugin test:

1. Install or enable AgentChange.
2. Trust the hooks through `/hooks`.
3. Run a small Codex code-editing task.
4. Confirm events were recorded.
5. Confirm Stop generated a receipt.
6. Confirm Slack delivery or dry-run output.

Do not claim that a Slack message was sent unless it was actually sent.

# Phase 2 acceptance criteria

Phase 2 is complete only when:

* Stop automatically finalizes the correct session.
* Git state is analyzed.
* Validation results are extracted.
* Controlled contradictions are detected.
* Risk scoring is deterministic and explainable.
* JSON and Markdown receipts are produced.
* Slack delivery works with a real webhook where available.
* Dry-run mode works without a webhook.
* Slack failure does not destroy local receipts.
* Duplicate Stop events do not create duplicate receipts.
* All tests pass.
* The complete demo works.
* The code remains understandable in one day.
* No database, backend, GitHub integration, or dashboard was added.

After completion, provide:

1. Final architecture.
2. Repository structure.
3. Files changed.
4. Exact installation commands.
5. Exact demo commands.
6. Test results.
7. Controlled demo risk score.
8. The contradiction finding.
9. Live Codex hook test results.
10. Slack delivery result.
11. Known limitations.
12. The three best next product steps.

Commit with:

```text
feat: complete AgentChange receipts and Slack delivery
```
