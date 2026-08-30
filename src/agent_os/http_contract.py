"""Typed local HTTP contract for non-Python Agent OS callers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from agent_os.models import AttemptKind, AttemptStatus, TaskStatus


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _canonical_text(value: str, *, label: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be non-empty canonical text")
    return value


class ContextReference(ContractModel):
    id: UUID
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def name_is_canonical(cls, value: str) -> str:
        return _canonical_text(value, label="context name")


class BudgetContext(ContractModel):
    amount_cents: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class WorkCreateRequest(ContractModel):
    """Institution context for one bounded unit of work.

    Organizational ids and budget are context, not Agent OS authority or accounting.
    Runtime, provider, model, credentials, commands, and filesystem paths are intentionally absent.
    """

    idempotency_key: UUID
    title: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    required_outcome: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    institution: ContextReference
    company: ContextReference
    project: ContextReference
    owner: ContextReference
    budget: BudgetContext

    @field_validator("title", "objective", "required_outcome")
    @classmethod
    def text_is_canonical(cls, value: str, info: ValidationInfo) -> str:
        field_name = info.field_name or "work text"
        return _canonical_text(value, label=field_name.replace("_", " "))

    @field_validator("constraints")
    @classmethod
    def constraints_are_canonical(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if values != normalized or any(not value for value in normalized):
            raise ValueError("constraints must contain canonical non-empty text")
        if len(values) != len(set(values)):
            raise ValueError("constraints must be unique")
        return values


class UsageResponse(ContractModel):
    reported_by: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reported_cost_usd: float | None = None
    derived_cost_usd: float | None = None
    cost_source: Literal["unknown", "runtime_reported", "provider_rate_derived", "billing_receipt"]
    cost_evidence_ref: str | None = None
    by_model: dict[str, dict[str, int | float | None]] = Field(default_factory=dict)


class AttemptResponse(ContractModel):
    id: str
    status: AttemptStatus
    kind: AttemptKind
    work_item: str
    provider: str
    model: str | None
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)
    usage: UsageResponse | None
    started_at: datetime
    finished_at: datetime | None


class WorkStatusResponse(ContractModel):
    id: UUID
    work_id: UUID
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    outcome: str | None
    actual_cost_cents: int | None
    cost_currency: str | None
    cost_source: str | None
    cost_evidence_ref: str | None
    reported_cost_usd: float | None
    derived_cost_usd: float | None
    latest_attempt: AttemptResponse | None
    costs: list[UsageResponse] = Field(default_factory=list)


class WorkResponse(WorkStatusResponse):
    title: str
    objective: str
    required_outcome: str
    constraints: list[str]


class ArtifactResponse(ContractModel):
    id: str
    name: str
    content_type: str
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    download_url: str


class ArtifactListResponse(ContractModel):
    work_id: UUID
    artifacts: list[ArtifactResponse]


class EvidenceDocument(ContractModel):
    id: str
    attempt_id: str
    kind: Literal["transcript", "stderr"]
    content_type: Literal["text/plain"] = "text/plain"
    byte_size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    content_base64: str


class EvidenceResponse(ContractModel):
    work_id: UUID
    attempts: list[AttemptResponse]
    documents: list[EvidenceDocument]
    observations: list[dict[str, object]]
    reviews: list[dict[str, object]]
    events: list[dict[str, object]]


class CancelResponse(WorkResponse):
    cancellation_requested: bool
