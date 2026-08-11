from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_os.store import TaskStore
from agent_os.tools import (
    complete_task,
    finish_attempt,
    get_task_context,
    get_workspace_diff,
    record_review,
    start_attempt,
)


def test_workspace_diff_is_bounded_host_evidence(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state))
    task = TaskStore(state).create_task(
        title="Diff evidence",
        objective="Give the reviewer only current change evidence.",
        workspace=workspace,
        acceptance_criteria=["Git history stays outside the child sandbox"],
    )
    monkeypatch.setattr("agent_os.tools.shutil.which", lambda *args, **kwargs: "/usr/bin/git")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, *, env, **kwargs):
        calls.append((command, env))
        output = " M slug.py\n" if "status" in command else "diff --git a/slug.py b/slug.py\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr("agent_os.tools.subprocess.run", fake_run)

    evidence = get_workspace_diff(task.id)

    assert " M slug.py" in evidence
    assert "diff --git a/slug.py b/slug.py" in evidence
    assert len(calls) == 2
    for command, environment in calls:
        assert "core.hooksPath=/dev/null" in command
        assert "submodule.recurse=false" in command
        assert "--no-pager" in command
        assert command[-2:] == ["--", "."]
        assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
        assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
        assert environment["GIT_TERMINAL_PROMPT"] == "0"
        assert environment["GIT_LITERAL_PATHSPECS"] == "1"


def test_workspace_diff_rejects_oversized_evidence(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state))
    task = TaskStore(state).create_task(
        title="Bound diff evidence",
        objective="Do not flood review context.",
        workspace=workspace,
        acceptance_criteria=["Oversized evidence fails closed"],
    )
    monkeypatch.setattr("agent_os.tools.shutil.which", lambda *args, **kwargs: "/usr/bin/git")

    def oversized(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="x" * 100_001, stderr="")

    monkeypatch.setattr("agent_os.tools.subprocess.run", oversized)

    with pytest.raises(RuntimeError, match="exceeds 100000 characters"):
        get_workspace_diff(task.id)


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
    attempt_id = start_attempt(task.id, "builder_codex")["attempt_id"]
    finish_attempt(
        attempt_id,
        "succeeded",
        "Implemented",
        "completed",
        ["pytest: 3 passed"],
    )
    record_review(
        task.id,
        "reviewer_claude",
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
    attempt_id = start_attempt(task.id, "builder_codex")["attempt_id"]
    finish_attempt(
        attempt_id,
        "succeeded",
        "Implemented",
        "completed",
        ["pytest: 1 passed"],
    )
    store.transition(task.id, "needs_review", reason="awaiting review")

    with pytest.raises(ValueError, match="no independent review"):
        complete_task(task.id, "completed", "No review")


def test_finish_attempt_rejects_nonterminal_child_status(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state))
    store = TaskStore(state)
    task = store.create_task(
        title="Slow child",
        objective="Wait for terminal child evidence.",
        workspace=tmp_path,
        acceptance_criteria=["Running work is preserved"],
    )
    attempt_id = start_attempt(task.id, "builder_ollama")["attempt_id"]

    with pytest.raises(ValueError, match="end the turn and wait"):
        finish_attempt(
            attempt_id,
            "failed",
            "No output yet",
            "in_progress",
            ["child status is still in_progress"],
        )

    assert store.get_attempt(attempt_id).status.value == "running"
