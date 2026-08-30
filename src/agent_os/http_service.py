"""Loopback-only HTTP adapter over the Agent OS task and runner contracts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import logging
import mimetypes
import os
import secrets
import stat
import subprocess
import threading
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_os.http_contract import (
    ArtifactListResponse,
    ArtifactResponse,
    AttemptResponse,
    CancelResponse,
    EvidenceDocument,
    EvidenceResponse,
    UsageResponse,
    WorkCreateRequest,
    WorkResponse,
    WorkStatusResponse,
)
from agent_os.models import AttemptRecord, AttemptStatus, TaskSpec, TaskStatus
from agent_os.runner import run_task
from agent_os.store import TaskStore

SERVICE_TOKEN_ENV = "AGENT_OS_SERVICE_TOKEN"
ARTIFACT_DIRECTORY = "artifacts"
ARTIFACT_CONSTRAINT = "Place every returned deliverable under the artifacts/ directory."
SERVICE_RUNTIMES = ("codex",)
EXPLICIT_UNKNOWN_COST_STATUSES = {
    TaskStatus.NEEDS_REVIEW,
    TaskStatus.BLOCKED,
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}

Runner = Callable[..., object]
LOGGER = logging.getLogger(__name__)


@dataclass
class _ExecutionHandle:
    cancel_event: threading.Event
    future: Future[object]


@dataclass(frozen=True)
class _CostProjection:
    actual_cost_cents: int | None
    cost_currency: str | None
    cost_source: str | None
    cost_evidence_ref: str | None
    reported_cost_usd: float | None
    derived_cost_usd: float | None


@dataclass(frozen=True)
class _ArtifactFile:
    name: str
    content: bytes


class ExecutionSupervisor:
    """Own local workspaces and one in-process execution handle per durable work id."""

    def __init__(
        self,
        *,
        state_dir: Path | str,
        workspace_root: Path | str,
        bundle_dir: Path | str,
        runtime: str,
        timeout_seconds: int,
        runner: Runner = run_task,
    ) -> None:
        if runtime not in SERVICE_RUNTIMES:
            raise ValueError(f"unsupported service runtime: {runtime}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        raw_state_dir = Path(state_dir).expanduser()
        if raw_state_dir.is_symlink():
            raise ValueError("state directory must not be a symlink")
        self.store = TaskStore(raw_state_dir)
        self.store.initialize()
        self.workspace_root = Path(workspace_root).expanduser()
        self.workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.workspace_root.is_symlink() or not self.workspace_root.is_dir():
            raise ValueError("workspace root must be a real directory")
        self.workspace_root = self.workspace_root.resolve(strict=True)
        os.chmod(self.workspace_root, 0o700)
        self.bundle_dir = Path(bundle_dir).expanduser().resolve()
        self.runtime = runtime
        self.timeout_seconds = timeout_seconds
        self._runner = runner
        self._executor = ThreadPoolExecutor(thread_name_prefix="agent-os-http")
        self._handles: dict[str, _ExecutionHandle] = {}
        self._lock = threading.Lock()

    def _workspace_for(self, work_id: UUID) -> Path:
        workspace = self.workspace_root / str(work_id)
        if workspace.exists() or workspace.is_symlink():
            if workspace.is_symlink() or not workspace.is_dir():
                raise ValueError("work workspace must be a real directory")
        else:
            workspace.mkdir(mode=0o700)
        os.chmod(workspace, 0o700)
        git_dir = workspace / ".git"
        if not git_dir.exists():
            environment = os.environ.copy()
            environment["GIT_CONFIG_GLOBAL"] = os.devnull
            environment["GIT_CONFIG_NOSYSTEM"] = "1"
            try:
                subprocess.run(
                    (
                        "git",
                        "-c",
                        "init.defaultBranch=main",
                        "init",
                        "--quiet",
                        "--template=",
                        str(workspace),
                    ),
                    check=True,
                    capture_output=True,
                    env=environment,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise RuntimeError(
                    "could not initialize the service-owned Git workspace"
                ) from error
        artifact_dir = workspace / ARTIFACT_DIRECTORY
        artifact_dir.mkdir(exist_ok=True, mode=0o700)
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise ValueError("artifact directory must be a real directory")
        os.chmod(artifact_dir, 0o700)
        return workspace.resolve(strict=True)

    @staticmethod
    def _task_context(request: WorkCreateRequest) -> dict[str, str]:
        return {
            "institution_id": str(request.institution.id),
            "institution_name": request.institution.name,
            "company_id": str(request.company.id),
            "company_name": request.company.name,
            "project_id": str(request.project.id),
            "project_name": request.project.name,
            "owner_principal_id": str(request.owner.id),
            "owner_principal_name": request.owner.name,
            "budget_cents": str(request.budget.amount_cents),
            "budget_currency": request.budget.currency,
            "artifact_directory": ARTIFACT_DIRECTORY,
        }

    def submit(self, request: WorkCreateRequest) -> tuple[TaskSpec, bool]:
        work_id = str(request.idempotency_key)
        with self._lock:
            workspace = self._workspace_for(request.idempotency_key)
            try:
                self.store.get_task(work_id)
                created = False
            except KeyError:
                created = True
            constraints = list(request.constraints)
            if ARTIFACT_CONSTRAINT not in constraints:
                constraints.append(ARTIFACT_CONSTRAINT)
            task = self.store.create_task(
                task_id=work_id,
                title=request.title,
                objective=request.objective,
                workspace=workspace,
                acceptance_criteria=[request.required_outcome],
                constraints=constraints,
                context=self._task_context(request),
            )
            handle = self._handles.get(work_id)
            attempts = self.store.list_attempts(work_id)
            if (
                task.status is TaskStatus.QUEUED
                and not attempts
                and (handle is None or handle.future.done())
            ):
                cancel_event = threading.Event()
                future = self._executor.submit(self._execute, work_id, cancel_event)
                self._handles[work_id] = _ExecutionHandle(cancel_event, future)
            return task, created

    def _execute(self, work_id: str, cancel_event: threading.Event) -> object:
        try:
            return self._runner(
                self.store,
                work_id,
                self.bundle_dir,
                runtime=self.runtime,
                timeout_seconds=self.timeout_seconds,
                cancel_event=cancel_event,
            )
        except Exception as error:
            for attempt in self.store.list_attempts(work_id):
                if attempt.status is not AttemptStatus.RUNNING:
                    continue
                self.store.finish_attempt(
                    attempt.id,
                    status=AttemptStatus.FAILED,
                    summary=(
                        "service runner failed before a terminal attempt outcome: "
                        f"{type(error).__name__}: {error}"
                    ),
                    transcript_path=attempt.transcript_path,
                )
            task = self.store.get_task(work_id)
            if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                self.store.transition(
                    work_id,
                    TaskStatus.FAILED,
                    reason=(
                        "service runner failed before a terminal task outcome: "
                        f"{type(error).__name__}"
                    ),
                )
            return 1

    def get_task(self, work_id: UUID) -> TaskSpec:
        return self.store.get_task(str(work_id))

    def request_cancel(self, work_id: UUID) -> tuple[TaskSpec, bool]:
        task_id = str(work_id)
        with self._lock:
            task = self.store.get_task(task_id)
            if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                return task, False
            if task.status is TaskStatus.QUEUED:
                handle = self._handles.get(task_id)
                if handle is not None and not handle.future.done():
                    handle.cancel_event.set()
                try:
                    task = self.store.cancel_task(task_id, reason="caller requested cancellation")
                    return task, False
                except ValueError:
                    task = self.store.get_task(task_id)
                    if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                        return task, False
                    if (
                        task.status is TaskStatus.RUNNING
                        and handle is not None
                        and not handle.future.done()
                    ):
                        return task, True
                    raise
            handle = self._handles.get(task_id)
            if handle is None or handle.future.done():
                task = self.store.get_task(task_id)
                if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                    return task, False
                raise ValueError("running work is not owned by this service process")
            handle.cancel_event.set()
            return task, True

    def close(self) -> None:
        with self._lock:
            handles = list(self._handles.values())
        for handle in handles:
            if not handle.future.done():
                handle.cancel_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)


def _usage_response(attempt: AttemptRecord) -> UsageResponse | None:
    if attempt.usage is None:
        return None
    return UsageResponse.model_validate(attempt.usage.model_dump(mode="json"))


def _evidence_reference(reference: str, *, attempt_id: str) -> str:
    if reference.startswith("transcript:"):
        return f"document:transcript:{attempt_id}"
    if reference.startswith("stderr:"):
        return f"document:stderr:{attempt_id}"
    return reference


def _evidence_refs(attempt: AttemptRecord) -> list[str]:
    return [_evidence_reference(reference, attempt_id=attempt.id) for reference in attempt.evidence]


def _attempt_response(attempt: AttemptRecord, *, include_evidence: bool) -> AttemptResponse:
    return AttemptResponse(
        id=attempt.id,
        status=attempt.status,
        kind=attempt.kind,
        work_item=attempt.work_item,
        provider=attempt.provider,
        model=attempt.model,
        summary=attempt.summary,
        evidence_refs=_evidence_refs(attempt) if include_evidence else [],
        usage=_usage_response(attempt),
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
    )


def _cost_projection(
    work_id: UUID,
    attempts: list[AttemptRecord],
    *,
    task_status: TaskStatus,
) -> _CostProjection:
    observed: list[tuple[AttemptRecord, Decimal, str]] = []
    reported: list[Decimal] = []
    derived: list[Decimal] = []
    evidence_refs: list[str] = []
    for attempt in attempts:
        usage = attempt.usage
        if usage is None:
            continue
        if usage.reported_cost_usd is not None:
            amount = Decimal(str(usage.reported_cost_usd))
            reported.append(amount)
        elif usage.derived_cost_usd is not None:
            amount = Decimal(str(usage.derived_cost_usd))
        else:
            continue
        if usage.derived_cost_usd is not None:
            derived.append(Decimal(str(usage.derived_cost_usd)))
        observed.append((attempt, amount, usage.cost_source))
        if usage.cost_source == "billing_receipt":
            if usage.reported_cost_usd is None or usage.cost_evidence_ref is None:
                raise ValueError("billing receipt usage is missing validated receipt evidence")
            evidence_refs.append(usage.cost_evidence_ref)
        else:
            evidence_refs.append(
                usage.cost_evidence_ref or f"agent-os:attempt-usage:{work_id}:{attempt.id}"
            )
    if not observed and task_status in EXPLICIT_UNKNOWN_COST_STATUSES:
        return _CostProjection(
            actual_cost_cents=None,
            cost_currency=None,
            cost_source="unknown",
            cost_evidence_ref=f"agent-os:{work_id}:cost-unknown",
            reported_cost_usd=None,
            derived_cost_usd=None,
        )
    if not observed:
        return _CostProjection(None, None, None, None, None, None)

    sources = {source for _attempt, _amount, source in observed}
    complete_cost_coverage = len(observed) == len(attempts)
    source = (
        next(iter(sources))
        if len(sources) == 1 and complete_cost_coverage
        else "mixed_observed"
    )
    actual_cost_cents = None
    billing_evidence_ref = None
    if complete_cost_coverage and sources == {"billing_receipt"}:
        billing_evidence_refs = set(evidence_refs)
        if len(billing_evidence_refs) != 1:
            raise ValueError(
                "billing projection requires one exact aggregate receipt evidence ref"
            )
        dollars = sum((amount for _attempt, amount, _source in observed), Decimal())
        actual_cost_cents = int((dollars * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        billing_evidence_ref = next(iter(billing_evidence_refs))
    observed_attempt_ids = ",".join(attempt.id for attempt, _amount, _source in observed)
    if billing_evidence_ref is not None:
        evidence_ref = billing_evidence_ref
    elif not complete_cost_coverage:
        retained_attempt_ids = ",".join(attempt.id for attempt in attempts)
        evidence_ref = f"agent-os:attempt-usage:{work_id}:{retained_attempt_ids}"
    elif len(evidence_refs) == 1:
        evidence_ref = evidence_refs[0]
    else:
        evidence_ref = f"agent-os:attempt-usage:{work_id}:{observed_attempt_ids}"
    return _CostProjection(
        actual_cost_cents=actual_cost_cents,
        cost_currency="USD",
        cost_source=source,
        cost_evidence_ref=evidence_ref,
        reported_cost_usd=float(sum(reported, Decimal())) if reported else None,
        derived_cost_usd=float(sum(derived, Decimal())) if derived else None,
    )


def _outcome(
    supervisor: ExecutionSupervisor,
    *,
    task: TaskSpec,
    latest: AttemptRecord | None,
) -> str | None:
    if task.status in {
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }:
        for event in reversed(supervisor.store.list_events(task.id)):
            payload = event.get("payload")
            if (
                event.get("kind") == "task.transitioned"
                and isinstance(payload, dict)
                and payload.get("to") == task.status.value
                and isinstance(payload.get("reason"), str)
            ):
                return payload["reason"]
    return latest.summary if latest is not None and latest.summary else None


def _status_response(supervisor: ExecutionSupervisor, work_id: UUID) -> WorkStatusResponse:
    task = supervisor.get_task(work_id)
    attempts = supervisor.store.list_attempts(str(work_id))
    latest = attempts[-1] if attempts else None
    usages = [usage for attempt in attempts if (usage := _usage_response(attempt)) is not None]
    cost = _cost_projection(work_id, attempts, task_status=task.status)
    return WorkStatusResponse(
        id=work_id,
        work_id=work_id,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        outcome=_outcome(supervisor, task=task, latest=latest),
        actual_cost_cents=cost.actual_cost_cents,
        cost_currency=cost.cost_currency,
        cost_source=cost.cost_source,
        cost_evidence_ref=cost.cost_evidence_ref,
        reported_cost_usd=cost.reported_cost_usd,
        derived_cost_usd=cost.derived_cost_usd,
        latest_attempt=(
            _attempt_response(latest, include_evidence=False) if latest is not None else None
        ),
        costs=usages,
    )


def _work_response(supervisor: ExecutionSupervisor, work_id: UUID) -> WorkResponse:
    task = supervisor.get_task(work_id)
    status_response = _status_response(supervisor, work_id)
    return WorkResponse(
        **status_response.model_dump(),
        title=task.title,
        objective=task.objective,
        required_outcome=task.acceptance_criteria[0],
        constraints=[item for item in task.constraints if item != ARTIFACT_CONSTRAINT],
    )


def _directory_open_flags() -> int:
    try:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    except AttributeError as error:
        raise OSError("descriptor-bound file reads require no-follow directory opens") from error


def _regular_file_open_flags() -> int:
    try:
        return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    except AttributeError as error:
        raise OSError("descriptor-bound file reads require no-follow file opens") from error


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int:
    flags = _directory_open_flags()
    descriptor = (
        os.open(path, flags) if dir_fd is None else os.open(path, flags, dir_fd=dir_fd)
    )
    try:
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
    except OSError:
        os.close(descriptor)
        raise
    if not is_directory:
        os.close(descriptor)
        raise ValueError("trusted path component is not a directory")
    return descriptor


def _safe_relative_parts(relative: str | Path) -> tuple[str, ...]:
    path = Path(relative)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("file path is not a canonical relative descendant")
    return parts


def _read_regular_descendant(directory_fd: int, relative: str | Path) -> bytes:
    parts = _safe_relative_parts(relative)
    opened_directories: list[int] = []
    current_directory = directory_fd
    file_descriptor: int | None = None
    try:
        for component in parts[:-1]:
            current_directory = _open_directory(component, dir_fd=current_directory)
            opened_directories.append(current_directory)
        file_descriptor = os.open(
            parts[-1],
            _regular_file_open_flags(),
            dir_fd=current_directory,
        )
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise ValueError("returned file is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def _artifact_response(artifact: _ArtifactFile, *, work_id: UUID) -> ArtifactResponse:
    digest = hashlib.sha256(artifact.content).hexdigest()
    artifact_id = hashlib.sha256(f"{artifact.name}\0{digest}".encode()).hexdigest()
    return ArtifactResponse(
        id=artifact_id,
        name=artifact.name,
        content_type=mimetypes.guess_type(artifact.name)[0] or "application/octet-stream",
        byte_size=len(artifact.content),
        sha256=digest,
        download_url=f"/v1/work/{work_id}/artifacts/{artifact_id}",
    )


def _open_artifact_directory(supervisor: ExecutionSupervisor, work_id: UUID) -> int:
    task = supervisor.get_task(work_id)
    expected_workspace = supervisor.workspace_root / str(work_id)
    if task.workspace != expected_workspace:
        raise ValueError("task workspace is outside the service-owned work root")
    root_descriptor = _open_directory(supervisor.workspace_root)
    workspace_descriptor: int | None = None
    try:
        workspace_descriptor = _open_directory(str(work_id), dir_fd=root_descriptor)
        return _open_directory(ARTIFACT_DIRECTORY, dir_fd=workspace_descriptor)
    finally:
        if workspace_descriptor is not None:
            os.close(workspace_descriptor)
        os.close(root_descriptor)


def _artifact_relative_names(directory_fd: int) -> list[str]:
    names: list[str] = []

    def collect(current_directory: int, prefix: tuple[str, ...]) -> None:
        with os.scandir(current_directory) as entries:
            sorted_entries = sorted(entries, key=lambda entry: entry.name)
        for entry in sorted_entries:
            if entry.is_symlink():
                continue
            relative_parts = (*prefix, entry.name)
            if entry.is_file(follow_symlinks=False):
                names.append(Path(*relative_parts).as_posix())
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            child_descriptor = _open_directory(entry.name, dir_fd=current_directory)
            try:
                collect(child_descriptor, relative_parts)
            finally:
                os.close(child_descriptor)

    collect(directory_fd, ())
    return names


def _artifact_files(supervisor: ExecutionSupervisor, work_id: UUID) -> list[_ArtifactFile]:
    directory_fd = _open_artifact_directory(supervisor, work_id)
    try:
        names = _artifact_relative_names(directory_fd)
        artifacts: list[_ArtifactFile] = []
        for name in names:
            artifacts.append(
                _ArtifactFile(
                    name=name,
                    content=_read_regular_descendant(directory_fd, name),
                )
            )
        return artifacts
    finally:
        os.close(directory_fd)


def _relative_descendant(path: Path, *, root: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(root)
    except ValueError as error:
        raise ValueError("file is outside the trusted directory") from error
    _safe_relative_parts(relative)
    return relative


def _read_regular_path(path: Path, *, root: Path) -> bytes:
    directory_fd = _open_directory(root)
    try:
        canonical_root = root.expanduser().resolve(strict=True)
        canonical_descriptor = _open_directory(canonical_root)
        try:
            opened_metadata = os.fstat(directory_fd)
            canonical_metadata = os.fstat(canonical_descriptor)
            if (opened_metadata.st_dev, opened_metadata.st_ino) != (
                canonical_metadata.st_dev,
                canonical_metadata.st_ino,
            ):
                raise ValueError("trusted directory changed while resolving its canonical path")
        finally:
            os.close(canonical_descriptor)
        relative = _relative_descendant(path, root=canonical_root)
        return _read_regular_descendant(directory_fd, relative)
    finally:
        os.close(directory_fd)


def _artifacts_response(supervisor: ExecutionSupervisor, work_id: UUID) -> ArtifactListResponse:
    files = _artifact_files(supervisor, work_id)
    return ArtifactListResponse(
        work_id=work_id,
        artifacts=[_artifact_response(artifact, work_id=work_id) for artifact in files],
    )


def _evidence_document(
    *,
    attempt_id: str,
    kind: Literal["transcript", "stderr"],
    path: Path,
    state_dir: Path,
    created_at: datetime,
) -> EvidenceDocument | None:
    try:
        content = _read_regular_path(path, root=state_dir)
    except (OSError, ValueError):
        return None
    digest = hashlib.sha256(content).hexdigest()
    return EvidenceDocument(
        id=hashlib.sha256(f"{attempt_id}\0{kind}\0{digest}".encode()).hexdigest(),
        attempt_id=attempt_id,
        kind=kind,
        byte_size=len(content),
        sha256=digest,
        created_at=created_at,
        content_base64=base64.b64encode(content).decode("ascii"),
    )

def _evidence_response(supervisor: ExecutionSupervisor, work_id: UUID) -> EvidenceResponse:
    supervisor.get_task(work_id)
    task_id = str(work_id)
    attempts = supervisor.store.list_attempts(task_id)
    state_dir = supervisor.store.state_dir
    documents: list[EvidenceDocument] = []
    observations: list[dict[str, object]] = []
    for attempt in attempts:
        candidates: list[tuple[Literal["transcript", "stderr"], Path]] = []
        if attempt.transcript_path is not None:
            candidates.append(("transcript", Path(attempt.transcript_path)))
        candidates.append(
            (
                "stderr",
                state_dir / "transcripts" / task_id / f"{attempt.id}.stderr.log",
            )
        )
        for kind, path in candidates:
            document = _evidence_document(
                attempt_id=attempt.id,
                kind=kind,
                path=path,
                state_dir=state_dir,
                created_at=attempt.finished_at or attempt.started_at,
            )
            if document is not None:
                documents.append(document)
    reviews: list[dict[str, object]] = []
    for review in supervisor.store.list_reviews(task_id):
        projection = review.model_dump(mode="json")
        reference_attempt_id = review.attempt_id or review.id
        projection["evidence"] = [
            _evidence_reference(reference, attempt_id=reference_attempt_id)
            for reference in review.evidence
        ]
        reviews.append(projection)
    events = supervisor.store.list_events(task_id)
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        attempt_id = payload.get("attempt_id")
        failure_ref = payload.get("failure_evidence_ref")
        if isinstance(attempt_id, str) and isinstance(failure_ref, str):
            payload["failure_evidence_ref"] = _evidence_reference(
                failure_ref,
                attempt_id=attempt_id,
            )
    return EvidenceResponse(
        work_id=work_id,
        attempts=[_attempt_response(attempt, include_evidence=True) for attempt in attempts],
        documents=documents,
        observations=observations,
        reviews=reviews,
        events=events,
    )


def create_app(
    *,
    state_dir: Path | str,
    workspace_root: Path | str,
    bundle_dir: Path | str,
    runtime: str,
    timeout_seconds: int,
    bearer_token: str,
    runner: Runner = run_task,
) -> FastAPI:
    if not bearer_token or bearer_token != bearer_token.strip():
        raise ValueError("bearer_token must be non-empty canonical text")
    supervisor = ExecutionSupervisor(
        state_dir=state_dir,
        workspace_root=workspace_root,
        bundle_dir=bundle_dir,
        runtime=runtime,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            supervisor.close()

    app = FastAPI(title="Agent OS local work service", version="1", lifespan=lifespan)
    app.state.supervisor = supervisor

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "The request does not match the Agent OS work contract.",
                    "next_action": "send only the documented canonical fields and types",
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def service_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == status.HTTP_401_UNAUTHORIZED:
            code = "authentication_required"
            next_action = "send the bearer token configured when the service started"
        elif error.status_code == status.HTTP_404_NOT_FOUND:
            if error.detail == "artifact not found":
                code = "artifact_not_found"
                next_action = "refresh the work artifact list before retrying"
            else:
                code = "work_not_found"
                next_action = "use an id returned by POST /v1/work"
        elif error.status_code == status.HTTP_409_CONFLICT:
            code = "work_conflict"
            next_action = "inspect the current work projection before retrying"
        else:
            code = f"http_{error.status_code}"
            next_action = "inspect the Agent OS service logs"
        message = error.detail if isinstance(error.detail, str) else "Agent OS refused the request."
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "next_action": next_action,
                }
            },
        )

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, error: Exception) -> JSONResponse:
        LOGGER.error(
            "unhandled local work service error",
            exc_info=(type(error), error, error.__traceback__),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Agent OS could not complete the local service request.",
                    "next_action": "inspect the Agent OS service logs",
                }
            },
        )

    def require_bearer_token(
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        scheme, separator, supplied = (authorization or "").partition(" ")
        authorized = (
            separator == " "
            and scheme == "Bearer"
            and bool(supplied)
            and secrets.compare_digest(supplied, bearer_token)
        )
        if not authorized:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="valid bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    authorization = Depends(require_bearer_token)

    @app.post(
        "/v1/work",
        response_model=WorkResponse,
        dependencies=[authorization],
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_work(request: WorkCreateRequest, response: Response) -> WorkResponse:
        try:
            _task, created = supervisor.submit(request)
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if not created:
            response.status_code = status.HTTP_200_OK
        return _work_response(supervisor, request.idempotency_key)

    @app.get(
        "/v1/work/{work_id}",
        response_model=WorkResponse,
        dependencies=[authorization],
    )
    def get_work(work_id: UUID) -> WorkResponse:
        try:
            return _work_response(supervisor, work_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error

    @app.get(
        "/v1/work/{work_id}/status",
        response_model=WorkStatusResponse,
        dependencies=[authorization],
    )
    def get_work_status(work_id: UUID) -> WorkStatusResponse:
        try:
            return _status_response(supervisor, work_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error

    @app.get(
        "/v1/work/{work_id}/artifacts",
        response_model=ArtifactListResponse,
        dependencies=[authorization],
    )
    def get_work_artifacts(work_id: UUID) -> ArtifactListResponse:
        try:
            return _artifacts_response(supervisor, work_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/v1/work/{work_id}/artifacts/{artifact_id}",
        dependencies=[authorization],
        response_class=Response,
    )
    def download_work_artifact(work_id: UUID, artifact_id: str) -> Response:
        try:
            for file in _artifact_files(supervisor, work_id):
                artifact = _artifact_response(file, work_id=work_id)
                if artifact.id == artifact_id:
                    return Response(
                        content=file.content,
                        media_type=artifact.content_type,
                        headers={"ETag": f'"{artifact.sha256}"'},
                    )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        raise HTTPException(status_code=404, detail="artifact not found")

    @app.get(
        "/v1/work/{work_id}/evidence",
        response_model=EvidenceResponse,
        dependencies=[authorization],
    )
    def get_work_evidence(work_id: UUID) -> EvidenceResponse:
        try:
            return _evidence_response(supervisor, work_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error

    @app.post(
        "/v1/work/{work_id}/cancel",
        response_model=CancelResponse,
        dependencies=[authorization],
    )
    def cancel_work(work_id: UUID, response: Response) -> CancelResponse:
        try:
            _task, cancellation_requested = supervisor.request_cancel(work_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="work not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        work = _work_response(supervisor, work_id)
        cancellation_requested = cancellation_requested and work.status in {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
        }
        response.status_code = (
            status.HTTP_202_ACCEPTED if cancellation_requested else status.HTTP_200_OK
        )
        return CancelResponse(
            **work.model_dump(),
            cancellation_requested=cancellation_requested,
        )

    return app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os-service", description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path(".agent-os-service"))
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--runtime", choices=SERVICE_RUNTIMES, default="codex")
    parser.add_argument("--timeout-seconds", type=int, default=1_800)
    parser.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    token = os.environ.get(SERVICE_TOKEN_ENV)
    if token is None or not token or token != token.strip():
        raise SystemExit(f"{SERVICE_TOKEN_ENV} is required as non-empty canonical text")
    workspace_root = args.workspace_root or args.state_dir / "workspaces"
    bundle_dir = args.bundle or args.state_dir / "bundles" / "coordinator"
    app = create_app(
        state_dir=args.state_dir,
        workspace_root=workspace_root,
        bundle_dir=bundle_dir,
        runtime=args.runtime,
        timeout_seconds=args.timeout_seconds,
        bearer_token=token,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
