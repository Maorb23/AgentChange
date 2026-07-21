"""Pydantic models used after raw hook evidence has been preserved."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(StrEnum):
    SESSION_STARTED = "session_started"
    USER_PROMPT_SUBMITTED = "user_prompt_submitted"
    COMMAND_ATTEMPTED = "command_attempted"
    COMMAND_COMPLETED = "command_completed"
    FILE_CHANGE_ATTEMPTED = "file_change_attempted"
    FILE_CHANGE_COMPLETED = "file_change_completed"
    MCP_TOOL_ATTEMPTED = "mcp_tool_attempted"
    MCP_TOOL_COMPLETED = "mcp_tool_completed"
    PERMISSION_REQUESTED = "permission_requested"
    TURN_STOPPED = "turn_stopped"
    OTHER_TOOL_ATTEMPTED = "other_tool_attempted"
    OTHER_TOOL_COMPLETED = "other_tool_completed"


class NormalizedEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    session_id: str
    timestamp: datetime
    provider: Literal["codex"] = "codex"
    event_type: EventType
    source_event: str
    cwd: str | None = None
    model: str | None = None
    turn_id: str | None = None
    prompt: str | None = None
    tool_name: str | None = None
    tool_use_id: str | None = None
    command: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    path: str | None = None
    result_status: Literal["succeeded", "failed", "unknown", "not_applicable"]
    evidence_confidence: Literal["observed", "inferred", "reported", "unknown"]
    last_assistant_message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    line_number: int | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value


class ValidationRecord(BaseModel):
    validation_id: str
    tool_use_id: str | None = None
    category: Literal["test", "lint", "build", "type_check", "security", "other"]
    command: str
    status: Literal[
        "passed",
        "failed",
        "command_not_found",
        "infrastructure_error",
        "unknown",
        "not_observed",
    ]
    authoritative: bool
    result_source: str
    requested_command: list[str] = Field(default_factory=list)
    resolved_command: list[str] = Field(default_factory=list)
    display_command: str
    scope: str
    exit_code: int | None = None
    duration_ms: int | None = None
    attempted_event_id: str | None = None
    completed_event_id: str
    line_number: int
    timestamp: datetime


class Finding(BaseModel):
    code: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    summary: str
    evidence: list[str] = Field(default_factory=list)


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"] = "2"
    receipt_id: str
    session_id: str
    turn_id: str
    generated_at: datetime
    source_labels: dict[str, str]
    requested_task: dict[str, Any]
    agent_statement: dict[str, Any]
    observed: dict[str, Any]
    validation: dict[str, Any]
    repository: dict[str, Any]
    findings: list[Finding]
    risk: dict[str, Any]
    slack: dict[str, Any]
    limitations: list[str]
    event_summary: dict[str, Any]
    turn_change_count: int
    integrity: dict[str, Any]
