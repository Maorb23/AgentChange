---
name: agentchange
description: Use for coding tasks involving repository changes, commands, tests, builds, package managers, patches, MCP tools, or permission requests where honest validation and a final change summary are important.
---

# AgentChange

AgentChange records activity observed through supported Codex lifecycle hooks. This skill is an instruction layer, not the evidence source.

1. Understand the requested task before editing.
2. Run relevant validation where practical. Use `agentchange-run -- <command> [arguments...]` for tests, linters, builds, type checks, and security scans so AgentChange can independently observe the subprocess exit code.
   - `agentchange-run -- pytest -q`
   - `agentchange-run -- ruff check .`
   - `agentchange-run -- npm test`
   Do not require the wrapper for ordinary read-only commands such as `ls`, `cat`, `sed`, or `git status`.
3. Never claim tests passed unless a successful result was observed.
4. State failures and unresolved issues honestly.
5. At the end, summarize the requested task, important changes, validation performed, known failures, assumptions, and suggested reviewers.
6. Do not manually send a receipt; lifecycle hooks handle future finalization.
7. Do not modify AgentChange runtime evidence files under `PLUGIN_DATA`.

Validation results are considered independently observed only when executed through `agentchange-run` or when another supported tool provides an explicit reliable result.

AgentChange evidence is not complete, tamper-proof, a full audit trail, or a secure enforcement boundary.
