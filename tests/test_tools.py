from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.store import TaskStore
from agent_os.tools import (
    complete_task,
    finish_attempt,
    get_task_context,
    record_review,
    start_attempt,
)


def test_omnigent_function_tools_update_domain_state(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state))
    store = TaskStore(state)
    task = store.create_task(
        title="Tool bridge",
        objective="Persist orchestration evidence.",
        workspace=tmp_path,
        acceptance_criteria=["Review is recorded"],
    )

    assert task.id in get_task_context(task.id)
    attempt_id = start_attempt(task.id, "builder_codex", "codex-native")["attempt_id"]
    finish_attempt(attempt_id, "succeeded", "Implemented", ["pytest: 3 passed"])
    record_review(
        task.id,
        "reviewer_claude",
        "claude-native",
        "approve",
        "Verified",
        attempt_id,
        [],
        ["3 passed"],
    )
    result = complete_task(task.id, "completed", "Approved with evidence")

    assert result["status"] == "completed"
    assert store.list_reviews(task.id)[0].verdict == "approve"


def test_completed_task_requires_approved_review(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state))
    store = TaskStore(state)
    task = store.create_task(
        title="Review gate",
        objective="Do not close unreviewed work.",
        workspace=tmp_path,
        acceptance_criteria=["Approval is required"],
    )
    start_attempt(task.id, "builder_codex", "codex-native")

    with pytest.raises(ValueError, match="require.*review"):
        complete_task(task.id, "completed", "No review")
