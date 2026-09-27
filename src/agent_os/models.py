"""Typed contracts shared by NOOA role definitions and task persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
    reported_cost_usd: float | None = Field(default=None, ge=0)


class AttemptUsage(ModelUsage):
    """Usage reported by the runtime that performed an attempt.

    This is observation, not estimation. A runtime may report tokens without reporting
    dollars; callers must preserve that distinction instead of manufacturing a price.
    A runtime-reported dollar figure is observation unless the caller classifies it as a
    billing receipt and supplies the exact receipt evidence reference.
    """

    reported_by: str = Field(min_length=1)
    derived_cost_usd: float | None = Field(default=None, ge=0)
    cost_source: Literal[
        "unknown",
        "runtime_reported",
        "provider_rate_derived",
        "billing_receipt",
    ] = "unknown"
    cost_evidence_ref: str | None = None
    by_model: dict[str, ModelUsage] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def legacy_cost_gets_explicit_provenance(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "cost_source" in value:
            return value
        normalized = dict(value)
        if normalized.get("derived_cost_usd") is not None:
            normalized["cost_source"] = "provider_rate_derived"
        elif normalized.get("reported_cost_usd") is not None:
            normalized["cost_source"] = "runtime_reported"
        else:
            normalized["cost_source"] = "unknown"
        return normalized

    @model_validator(mode="after")
    def cost_has_explicit_provenance(self) -> Self:
        if self.reported_by != self.reported_by.strip():
            raise ValueError("reported_by must be canonical text")
        if self.cost_evidence_ref is not None and (
            not self.cost_evidence_ref or self.cost_evidence_ref != self.cost_evidence_ref.strip()
        ):
            raise ValueError("cost_evidence_ref must be canonical text")
        if self.reported_cost_usd is not None and self.derived_cost_usd is not None:
            raise ValueError("reported and derived cost must remain separate")
        if self.cost_source == "unknown":
            if self.reported_cost_usd is not None or self.derived_cost_usd is not None:
                raise ValueError("unknown cost provenance cannot include a cost amount")
        elif self.cost_source == "runtime_reported":
            if self.reported_cost_usd is None or self.derived_cost_usd is not None:
                raise ValueError("runtime-reported cost requires only reported_cost_usd")
        elif self.cost_source == "provider_rate_derived":
            if self.derived_cost_usd is None or self.reported_cost_usd is not None:
                raise ValueError("provider-rate-derived cost requires only derived_cost_usd")
            if self.cost_evidence_ref is None:
                raise ValueError("provider-rate-derived cost requires evidence")
        elif self.cost_source == "billing_receipt":
            if self.reported_cost_usd is None or self.derived_cost_usd is not None:
                raise ValueError("billing-receipt cost requires only reported_cost_usd")
            if self.cost_evidence_ref is None:
                raise ValueError("billing-receipt cost requires evidence")
        return self


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
