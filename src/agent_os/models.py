"""Typed contracts shared by NOOA role definitions and task persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class AttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    COORDINATOR = "coordinator"
    IMPLEMENTATION = "implementation"


class TaskSpec(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1)
    workspace: Path
    acceptance_criteria: list[str] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.QUEUED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("acceptance_criteria")
    @classmethod
    def non_empty_criteria(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty acceptance criterion is required")
        return cleaned


class WorkItem(BaseModel):
    id: str
    description: str
    owner_role: Literal[
        "builder_claude",
        "builder_codex",
        "builder_opencode",
        "builder_ollama",
    ]
    depends_on: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    summary: str
    work_items: list[WorkItem] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)


class WorkResult(BaseModel):
    status: Literal["completed", "blocked", "failed"]
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ReviewVerdict(BaseModel):
    verdict: Literal["approve", "request_changes", "blocked"]
    summary: str
    blocking_issues: list[str] = Field(default_factory=list)
    non_blocking_issues: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class FinalOutcome(BaseModel):
    status: Literal["completed", "blocked", "failed"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    review: ReviewVerdict | None = None


class ModelUsage(BaseModel):
    """Provider-reported usage for one model inside an attempt."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cache_read_input_tokens: int | None = Field(default=None, ge=0)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0)
    actual_cost_usd: float | None = Field(default=None, ge=0)


class AttemptUsage(ModelUsage):
    """Usage reported by the runtime that performed an attempt.

    This is observation, not estimation. A runtime may report tokens without reporting
    dollars; callers must preserve that distinction instead of manufacturing a price.
    """

    reported_by: str = Field(min_length=1)
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)


class AttemptRecord(BaseModel):
    id: str
    task_id: str
    agent: str
    harness: str
    provider: str
    model: str | None = None
    kind: AttemptKind = AttemptKind.IMPLEMENTATION
    work_item: str = "primary"
    status: AttemptStatus
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)
    transcript_path: str | None = None
    usage: AttemptUsage | None = None
    pid: int | None = None
    started_at: datetime
    finished_at: datetime | None = None


class ReviewRecord(BaseModel):
    id: str
    task_id: str
    attempt_id: str | None = None
    reviewer: str
    harness: str
    provider: str
    verdict: Literal["approve", "request_changes", "blocked"]
    summary: str
    issues: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
