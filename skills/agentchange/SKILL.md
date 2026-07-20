---
name: agentchange
description: Use for coding tasks involving repository changes, commands, tests, builds, package managers, patches, MCP tools, or permission requests where honest validation and a final change summary are important.
---

# AgentChange

AgentChange records activity observed through supported Codex lifecycle hooks. This skill is an instruction layer, not the evidence source.

1. Understand the requested task before editing.
2. Run relevant validation where practical.
3. Never claim tests passed unless a successful result was observed.
4. State failures and unresolved issues honestly.
5. At the end, summarize the requested task, important changes, validation performed, known failures, assumptions, and suggested reviewers.
6. Do not manually send a receipt; lifecycle hooks handle future finalization.
7. Do not modify AgentChange runtime evidence files under `PLUGIN_DATA`.

AgentChange evidence is not complete, tamper-proof, a full audit trail, or a secure enforcement boundary.
