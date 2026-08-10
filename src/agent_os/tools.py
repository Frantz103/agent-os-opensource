"""Host-side function tools called by the Omnigent coordinator."""

from __future__ import annotations

from agent_os.context import build_task_context
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore


def _store() -> TaskStore:
    return TaskStore()


def get_task_context(task_id: str) -> str:
    """Return the authoritative task contract plus bounded prior evidence."""
    return build_task_context(_store(), task_id)


def start_attempt(task_id: str, agent: str, harness: str) -> dict[str, str]:
    """Create an attributed attempt before dispatching a child agent."""
    store = _store()
    task = store.get_task(task_id)
    if task.status in {TaskStatus.QUEUED, TaskStatus.NEEDS_REVIEW, TaskStatus.BLOCKED}:
        store.transition(task_id, TaskStatus.RUNNING, reason=f"dispatching {agent}")
    attempt = store.start_attempt(task_id, agent=agent, harness=harness)
    return {"attempt_id": attempt.id, "status": attempt.status.value}


def finish_attempt(
    attempt_id: str,
    status: str,
    summary: str,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Finalize an attempt with its real status and evidence."""
    attempt = _store().finish_attempt(
        attempt_id,
        status=AttemptStatus(status),
        summary=summary,
        evidence=evidence or [],
    )
    return {"attempt_id": attempt.id, "status": attempt.status.value}


def record_review(
    task_id: str,
    reviewer: str,
    harness: str,
    verdict: str,
    summary: str,
    attempt_id: str | None = None,
    issues: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Persist an independent review verdict and its evidence."""
    store = _store()
    review = store.record_review(
        task_id,
        reviewer=reviewer,
        harness=harness,
        verdict=verdict,
        summary=summary,
        attempt_id=attempt_id,
        issues=issues or [],
        evidence=evidence or [],
    )
    if verdict == "approve":
        store.transition(
            task_id,
            TaskStatus.NEEDS_REVIEW,
            reason="review approved; awaiting closure",
        )
    return {"review_id": review.id, "verdict": review.verdict}


def complete_task(task_id: str, status: str, summary: str) -> dict[str, str]:
    """Close the task after review, or record a truthful blocked/failed outcome."""
    target = TaskStatus(status)
    if target not in {TaskStatus.COMPLETED, TaskStatus.BLOCKED, TaskStatus.FAILED}:
        raise ValueError("status must be completed, blocked, or failed")
    store = _store()
    if target is TaskStatus.COMPLETED:
        reviews = store.list_reviews(task_id)
        if not reviews or reviews[-1].verdict != "approve":
            raise ValueError(
                "completed tasks require a latest independent review verdict of approve"
            )
    task = store.transition(task_id, target, reason=summary)
    return {"task_id": task.id, "status": task.status.value}
