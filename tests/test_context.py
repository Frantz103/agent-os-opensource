from __future__ import annotations

from pathlib import Path

from agent_os.context import build_task_context
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore


def test_context_preserves_contract_and_bounds_old_evidence(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Bound context",
        objective="Always preserve the acceptance contract.",
        workspace=tmp_path,
        acceptance_criteria=["The acceptance criterion is never truncated"],
    )
    store.transition(task.id, TaskStatus.RUNNING)
    for index in range(6):
        attempt = store.start_attempt(
            task.id, agent="builder_codex", work_item=f"work-{index}"
        )
        store.finish_attempt(
            attempt.id,
            status=AttemptStatus.SUCCEEDED,
            summary="x" * 400,
            evidence=["e" * 400],
        )

    context = build_task_context(store, task.id, max_chars=1800)
    assert "The acceptance criterion is never truncated" in context
    assert "older record(s) omitted" in context
    assert len(context) <= 1800
