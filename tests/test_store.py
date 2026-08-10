from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore


def make_task(store: TaskStore, workspace: Path):
    return store.create_task(
        title="Repair the parser",
        objective="Reject malformed headers without regressing valid input.",
        workspace=workspace,
        acceptance_criteria=["Malformed headers return a typed error", "Existing tests pass"],
        constraints=["No network access"],
        context={"issue": "ISSUE-123"},
    )


def test_task_attempt_review_and_event_lifecycle(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    assert task.status is TaskStatus.QUEUED

    store.transition(task.id, TaskStatus.RUNNING, reason="start")
    attempt = store.start_attempt(task.id, agent="builder_codex", harness="codex-native")
    finished = store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Added validation and regression tests",
        evidence=["pytest tests/test_parser.py: 12 passed"],
    )
    review = store.record_review(
        task.id,
        attempt_id=attempt.id,
        reviewer="reviewer_claude",
        harness="claude-native",
        verdict="approve",
        summary="Acceptance criteria verified",
        evidence=["src/parser.py:42", "12 passed"],
    )
    store.transition(task.id, TaskStatus.COMPLETED, reason="approved")

    assert finished.status is AttemptStatus.SUCCEEDED
    assert review.verdict == "approve"
    assert store.get_task(task.id).status is TaskStatus.COMPLETED
    assert [event["kind"] for event in store.list_events(task.id)] == [
        "task.created",
        "task.transitioned",
        "attempt.started",
        "attempt.finished",
        "review.recorded",
        "task.transitioned",
    ]


def test_invalid_transition_is_rejected(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    with pytest.raises(ValueError, match="invalid task transition"):
        store.transition(task.id, TaskStatus.COMPLETED)


def test_review_must_use_a_different_vendor(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex", harness="codex-native")
    store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented",
    )

    with pytest.raises(ValueError, match="different vendor"):
        store.record_review(
            task.id,
            attempt_id=attempt.id,
            reviewer="reviewer_codex",
            harness="codex",
            verdict="approve",
            summary="Self-family review",
        )
