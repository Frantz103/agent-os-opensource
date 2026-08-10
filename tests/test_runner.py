from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.models import TaskStatus
from agent_os.runner import RunPlan, run_task
from agent_os.store import TaskStore


def test_dry_run_builds_omnigent_command_without_starting_process(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Dry run",
        objective="Inspect a run without executing it.",
        workspace=tmp_path,
        acceptance_criteria=["No process launches"],
    )
    result = run_task(
        store,
        task.id,
        tmp_path / "bundle",
        dry_run=True,
        omnigent_command="/fake/omnigent",
    )

    assert isinstance(result, RunPlan)
    assert result.command[:2] == ("/fake/omnigent", "run")
    assert task.id in result.prompt
    assert store.list_attempts(task.id) == []


@pytest.mark.parametrize("restart_status", [TaskStatus.BLOCKED, TaskStatus.FAILED])
def test_dry_run_does_not_mutate_restartable_task(
    tmp_path: Path, restart_status: TaskStatus
) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Retry",
        objective="Remain inspectable before a retry.",
        workspace=tmp_path,
        acceptance_criteria=["Dry run preserves state"],
    )
    if restart_status is TaskStatus.BLOCKED:
        store.transition(task.id, restart_status)
    else:
        store.transition(task.id, TaskStatus.RUNNING)
        store.transition(task.id, restart_status)

    run_task(
        store,
        task.id,
        tmp_path / "bundle",
        dry_run=True,
        omnigent_command="/fake/omnigent",
    )
    assert store.get_task(task.id).status is restart_status
