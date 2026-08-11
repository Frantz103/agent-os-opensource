"""Host-side function tools called by the Omnigent coordinator."""

from __future__ import annotations

import os
import shutil
import subprocess

from agent_os.context import build_task_context
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore

_TERMINAL_CHILD_STATUSES = {"completed", "failed", "cancelled"}
_GIT_EVIDENCE_MAX_CHARS = 100_000
_GIT_EVIDENCE_TIMEOUT_SECONDS = 10


def _store() -> TaskStore:
    return TaskStore()


def get_task_context(task_id: str) -> str:
    """Return the authoritative task contract plus bounded prior evidence."""
    return build_task_context(_store(), task_id)


def collect_workspace_diff(store: TaskStore, task_id: str) -> str:
    """Return bounded working-tree evidence without exposing repository history to a child."""
    task = store.get_task(task_id)
    git = shutil.which("git", path=os.defpath)
    if git is None:
        raise RuntimeError("git is required to collect workspace diff evidence")
    environment = {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }
    base = [
        git,
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "submodule.recurse=false",
        "--no-pager",
    ]

    def run(arguments: list[str]) -> str:
        result = subprocess.run(
            [*base, *arguments],
            cwd=task.workspace,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_GIT_EVIDENCE_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip()[:500] or f"exit {result.returncode}"
            raise RuntimeError(f"git evidence command failed: {detail}")
        return result.stdout

    status = run(
        ["status", "--short", "--untracked-files=all", "--ignore-submodules=all", "--", "."]
    )
    diff = run(
        ["diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", "HEAD", "--", "."]
    )
    evidence = (
        "WORKSPACE STATUS\n"
        + (status or "(clean)\n")
        + "\nDIFF AGAINST HEAD\n"
        + (diff or "(no tracked diff)\n")
    )
    if len(evidence) > _GIT_EVIDENCE_MAX_CHARS:
        raise RuntimeError(
            f"workspace diff evidence exceeds {_GIT_EVIDENCE_MAX_CHARS} characters; "
            "reduce or split the task before review"
        )
    return evidence


def get_workspace_diff(task_id: str) -> str:
    """Collect bounded diff evidence for an Omnigent function-tool call."""
    return collect_workspace_diff(_store(), task_id)


def start_attempt(task_id: str, agent: str, work_item: str = "primary") -> dict[str, str]:
    """Create an attributed attempt before dispatching a child agent."""
    store = _store()
    task = store.get_task(task_id)
    if task.status in {TaskStatus.QUEUED, TaskStatus.NEEDS_REVIEW, TaskStatus.BLOCKED}:
        store.transition(task_id, TaskStatus.RUNNING, reason=f"dispatching {agent}")
    attempt = store.start_attempt(task_id, agent=agent, work_item=work_item)
    return {"attempt_id": attempt.id, "status": attempt.status.value}


def finish_attempt(
    attempt_id: str,
    status: str,
    summary: str,
    child_task_status: str,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Finalize an attempt only after Omnigent reports a terminal child task."""
    target = AttemptStatus(status)
    if child_task_status not in _TERMINAL_CHILD_STATUSES:
        raise ValueError(
            "child_task_status must be completed, failed, or cancelled; "
            "end the turn and wait while the child is launching or in progress"
        )
    if target is AttemptStatus.SUCCEEDED and child_task_status != "completed":
        raise ValueError("a successful attempt requires child_task_status=completed")
    if target is AttemptStatus.CANCELLED and child_task_status != "cancelled":
        raise ValueError("a cancelled attempt requires child_task_status=cancelled")
    attempt = _store().finish_attempt(
        attempt_id,
        status=target,
        summary=summary,
        evidence=evidence or [],
    )
    return {"attempt_id": attempt.id, "status": attempt.status.value}


def record_review(
    task_id: str,
    reviewer: str,
    verdict: str,
    summary: str,
    attempt_id: str,
    issues: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Persist an independent review verdict and its evidence."""
    store = _store()
    review = store.record_review(
        task_id,
        reviewer=reviewer,
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
        task = store.complete_task(task_id, summary=summary)
    else:
        task = store.transition(task_id, target, reason=summary)
    return {"task_id": task.id, "status": task.status.value}
