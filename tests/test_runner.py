from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from agent_os.models import TaskStatus
from agent_os.runner import RunPlan, _open_private_text, run_task, runtime_environment
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
    assert result.runtime == "omnigent"
    assert task.id in result.prompt
    assert task.objective not in result.shell_command()
    assert task.id not in result.shell_command()
    assert "<task-context-redacted>" in result.shell_command()
    assert task.id in result.shell_command(reveal_context=True)
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


def test_dry_run_builds_bounded_prime_agent_command_without_mutation(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Persistent run",
        objective="Implement and verify a useful change.",
        workspace=tmp_path,
        acceptance_criteria=["Evidence is recorded"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "unused-bundle",
        dry_run=True,
        runtime="prime-agent",
        prime_agent_command="/fake/prime-agent",
        token_budget=12_345,
        max_turns=7,
        timeout_seconds=90,
        provider="openai",
        model="openai/gpt-5",
    )

    assert isinstance(result, RunPlan)
    assert result.runtime == "prime-agent"
    assert result.agent == "prime_coordinator"
    assert result.harness == "prime-agent"
    assert result.command[:5] == (
        "/fake/prime-agent",
        "--mode",
        "json",
        "--cwd",
        str(tmp_path),
    )
    assert result.command[result.command.index("--goal") + 1] == task.objective
    assert result.command[result.command.index("--goal-token-budget") + 1] == "12345"
    assert result.command[result.command.index("--autonomous-max-turns") + 1] == "7"
    assert result.command[result.command.index("--autonomous-timeout-ms") + 1] == "90000"
    assert task.id in result.prompt
    assert "never claim the task itself is complete" in result.prompt
    assert store.list_attempts(task.id) == []


@pytest.mark.parametrize("field", ["token_budget", "max_turns", "timeout_seconds"])
def test_prime_agent_limits_must_be_positive(tmp_path: Path, field: str) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Invalid bound",
        objective="Reject an invalid autonomous limit.",
        workspace=tmp_path,
        acceptance_criteria=["Invalid input is rejected"],
    )
    kwargs = {"token_budget": 1, "max_turns": 1, "timeout_seconds": 1, field: 0}

    with pytest.raises(ValueError, match=f"{field} must be positive"):
        run_task(
            store,
            task.id,
            tmp_path / "unused-bundle",
            dry_run=True,
            runtime="prime-agent",
            prime_agent_command="/fake/prime-agent",
            provider="openai",
            **cast(Any, kwargs),
        )


def test_prime_agent_requires_declared_intelligence_provider(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Attributed run",
        objective="Do not run without provider attribution.",
        workspace=tmp_path,
        acceptance_criteria=["Provider is recorded"],
    )

    with pytest.raises(ValueError, match="provider is required"):
        run_task(
            store,
            task.id,
            tmp_path / "unused-bundle",
            dry_run=True,
            runtime="prime-agent",
            prime_agent_command="/fake/prime-agent",
        )


def test_runtime_environment_is_allowlisted(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("UNRELATED_PRIVATE_TOKEN", "must-not-pass")

    environment = runtime_environment(providers={"openai"})

    assert environment["PATH"] == "/bin"
    assert environment["OPENAI_API_KEY"] == "openai-secret"
    assert "UNRELATED_PRIVATE_TOKEN" not in environment


def test_runtime_environment_allows_explicit_extra_names(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_OS_ALLOWED_ENV", "CUSTOM_PROVIDER_KEY")
    monkeypatch.setenv("CUSTOM_PROVIDER_KEY", "allowed")

    assert runtime_environment(providers={"custom"})["CUSTOM_PROVIDER_KEY"] == "allowed"


def test_transcript_file_is_private(tmp_path: Path) -> None:
    transcript = tmp_path / "attempt.log"
    with _open_private_text(transcript) as stream:
        stream.write("evidence")

    assert transcript.stat().st_mode & 0o777 == 0o600
