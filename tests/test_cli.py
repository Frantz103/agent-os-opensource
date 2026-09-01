from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from agent_os import cli
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.specs import sync_specs
from agent_os.store import TaskStore


def test_init_uses_state_owned_bundle_and_generates_valid_specs(
    tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "private-state"

    assert cli.main(["--state-dir", str(state_dir), "init"]) == 0

    bundle = state_dir / "bundles" / "coordinator"
    assert bundle.is_dir()
    assert (bundle / "config.yaml").is_file()
    assert "bundle:" in capsys.readouterr().out
    assert cli.main(["--state-dir", str(state_dir), "spec", "check"]) == 0


def test_reconcile_command_force_closes_running_attempt(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task = store.create_task(
        title="Interrupted work",
        objective="Recover deterministically.",
        workspace=tmp_path,
        acceptance_criteria=["Attempt is reconciled"],
    )
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex")

    assert cli.main(["--state-dir", str(state_dir), "task", "reconcile", "--force"]) == 0

    assert store.get_attempt(attempt.id).status is AttemptStatus.FAILED
    assert store.get_task(task.id).status is TaskStatus.FAILED
    assert "reconciled 1 attempt(s)" in capsys.readouterr().out


def test_doctor_fails_loudly_for_incompatible_installed_opencode(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli, "resolve_opencode_version", lambda path: "1.18.4")

    def reject_version(version: str) -> None:
        raise cli.OpenCodeVersionError(f"unsupported {version}")

    monkeypatch.setattr(cli, "check_opencode_version", reject_version)

    assert cli._doctor(bundle) == 1
    assert "opencode   INCOMPATIBLE unsupported 1.18.4" in capsys.readouterr().out


def test_runtime_scoped_doctor_does_not_fail_for_unrelated_incompatible_runtime(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: "/bin/prime-agent")
    monkeypatch.setattr(cli, "find_antigravity_cli", lambda: "/bin/agy")
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")

    def antigravity_timeout(_path: str):
        raise TimeoutError("version probe timed out")

    monkeypatch.setattr(cli, "resolve_antigravity_version", antigravity_timeout)

    assert cli._doctor(bundle) == 1
    capsys.readouterr()
    assert cli._doctor(bundle, runtime="codex", json_output=True) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "agent-os.doctor.v1"
    assert report["available"] is True
    assert report["runtime"] == "codex"
    antigravity = next(item for item in report["checks"] if item["name"] == "antigravity")
    assert antigravity == {
        "name": "antigravity",
        "status": "incompatible",
        "required": False,
        "path": "/bin/agy",
        "version": None,
        "detail": "version probe timed out",
    }


def test_runtime_scoped_doctor_fails_when_selected_runtime_is_unavailable(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(cli, "find_antigravity_cli", lambda: None)
    monkeypatch.setattr(
        cli.shutil,
        "which",
        lambda name: None if name == "opencode" else f"/bin/{name}",
    )

    assert cli._doctor(bundle, runtime="opencode", json_output=True) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["available"] is False
    assert report["failures"] == ["opencode is required and was not found on PATH"]


def test_doctor_cli_accepts_runtime_and_json(monkeypatch, tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    bundle = state_dir / "bundles" / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(cli, "find_antigravity_cli", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli, "resolve_opencode_version", lambda _path: "1.17.20")

    assert (
        cli.main(
            [
                "--state-dir",
                str(state_dir),
                "doctor",
                "--runtime",
                "codex",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["runtime"] == "codex"
    assert report["available"] is True


def test_run_keyboard_interrupt_exits_cleanly(monkeypatch, tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task = store.create_task(
        title="Interrupt cleanly",
        objective="Avoid a Python traceback after governed cleanup.",
        workspace=tmp_path,
        acceptance_criteria=["CLI returns the conventional interrupt code"],
    )

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_task", interrupt)

    assert cli.main(["--state-dir", str(state_dir), "run", task.id]) == 130
    assert capsys.readouterr().err == "interrupted\n"


def test_run_timeout_exits_cleanly(monkeypatch, tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task = store.create_task(
        title="Time out cleanly",
        objective="Avoid a Python traceback after governed timeout cleanup.",
        workspace=tmp_path,
        acceptance_criteria=["CLI reports the bounded timeout"],
    )

    def time_out(*args, **kwargs):
        raise TimeoutError("omnigent process exceeded 1 seconds")

    monkeypatch.setattr(cli, "run_task", time_out)

    assert cli.main(["--state-dir", str(state_dir), "run", task.id]) == 2
    assert capsys.readouterr().err == "error: omnigent process exceeded 1 seconds\n"


def test_quickstart_create_show_and_context_round_trip(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert (
        cli.main(
            [
                "--state-dir",
                str(state_dir),
                "task",
                "create",
                "--title",
                "Add a repository health command",
                "--objective",
                "Add a read-only command that reports config and test readiness.",
                "--workspace",
                str(workspace),
                "--accept",
                "The command exits zero when required tools are present",
                "--constraint",
                "Do not push, merge, deploy, or contact external services",
                "--context",
                "ticket=FRA-1",
            ]
        )
        == 0
    )
    task_id = capsys.readouterr().out.strip()
    assert task_id.startswith("tsk_")

    assert cli.main(["--state-dir", str(state_dir), "task", "show", task_id]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == task_id
    assert payload["context"] == {"ticket": "FRA-1"}
    assert payload["attempts"] == []
    assert payload["reviews"] == []

    assert cli.main(["--state-dir", str(state_dir), "task", "list"]) == 0
    assert task_id in capsys.readouterr().out

    assert cli.main(["--state-dir", str(state_dir), "context", task_id]) == 0
    rendered = capsys.readouterr().out
    assert "# Agent OS task contract" in rendered
    assert "Do not push, merge, deploy, or contact external services" in rendered


def test_task_create_rejects_malformed_context(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert (
        cli.main(
            [
                "--state-dir",
                str(state_dir),
                "task",
                "create",
                "--title",
                "Bad context",
                "--objective",
                "Reject malformed key/value context.",
                "--workspace",
                str(workspace),
                "--accept",
                "Exits non-zero",
                "--context",
                "not-a-pair",
            ]
        )
        == 2
    )
    assert "context must use KEY=VALUE: not-a-pair" in capsys.readouterr().err


def test_agents_command_lists_runtime_variants(tmp_path: Path, capsys) -> None:
    assert cli.main(["--state-dir", str(tmp_path / "state"), "agents"]) == 0
    listed = capsys.readouterr().out
    assert "coordinator\tclaude-sdk" in listed
    assert "builder_antigravity\tantigravity-cli" in listed


def test_run_dry_run_prints_plan_and_redacts_task_context(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task = store.create_task(
        title="Plan only",
        objective="Show the execution plan without revealing task context.",
        workspace=tmp_path,
        acceptance_criteria=["Dry run prints the plan"],
    )
    plan = cli.RunPlan(
        command=("omnigent", "run", "--print=SENSITIVE"),
        cwd=tmp_path,
        prompt="SENSITIVE",
        runtime="omnigent",
        agent="coordinator",
        harness="claude-sdk",
        provider="anthropic",
    )
    monkeypatch.setattr(cli, "run_task", lambda *args, **kwargs: plan)

    assert cli.main(["--state-dir", str(state_dir), "run", task.id, "--dry-run"]) == 0

    printed = capsys.readouterr().out
    assert "runtime: omnigent" in printed
    assert "identity: coordinator/claude-sdk/anthropic" in printed
    assert "model: runtime default" in printed
    assert "SENSITIVE" not in printed


def test_doctor_reports_missing_required_tool_with_summary(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: None)
    monkeypatch.setattr(cli, "find_antigravity_cli", lambda: None)
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    assert cli._doctor(bundle) == 1

    printed = capsys.readouterr().out
    assert "omnigent   MISSING" in printed
    assert "doctor failed:" in printed
    assert "omnigent is required and was not found on PATH" in printed


def test_doctor_reports_invalid_bundle(monkeypatch, tmp_path: Path, capsys) -> None:
    bundle = tmp_path / "coordinator"
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_antigravity_cli", lambda: None)
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: None if name == "opencode" else f"/bin/{name}"
    )

    assert cli._doctor(bundle) == 1

    printed = capsys.readouterr().out
    assert "bundle     INVALID" in printed
    assert "did not validate" in printed


def test_termination_handler_raises_so_cleanup_can_unwind() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    try:
        cli.install_termination_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(cli.RuntimeTerminated, match="SIGTERM"):
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_run_terminated_by_supervisor_exits_cleanly(monkeypatch, tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task = store.create_task(
        title="Terminate cleanly",
        objective="Close the attempt when a supervisor cancels the process.",
        workspace=tmp_path,
        acceptance_criteria=["CLI reports the terminating signal"],
    )

    def terminate(*args, **kwargs):
        raise cli.RuntimeTerminated("SIGTERM")

    monkeypatch.setattr(cli, "run_task", terminate)

    assert cli.main(["--state-dir", str(state_dir), "run", task.id]) == 143
    assert capsys.readouterr().err == "terminated on SIGTERM\n"


def _succeeded_implementation(store: TaskStore, tmp_path: Path):
    task = store.create_task(
        title="Owner review",
        objective="Let the owner supply the independent verdict.",
        workspace=tmp_path,
        acceptance_criteria=["Owner approves the exact attempt"],
    )
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_ollama")
    store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="done",
        evidence=["message.txt changed from before to release"],
    )
    store.transition(task.id, TaskStatus.NEEDS_REVIEW)
    return task, attempt


def test_owner_verdict_completes_the_task(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task, attempt = _succeeded_implementation(store, tmp_path)

    assert (
        cli.main(
            [
                "--state-dir", str(state_dir), "review", task.id,
                "--attempt", attempt.id,
                "--verdict", "approve",
                "--summary", "Owner checked the diff and the test.",
                "--evidence", "git diff shows only the intended file",
            ]
        )
        == 0
    )
    assert "completed" in capsys.readouterr().out
    stored = store.get_task(task.id)
    assert stored.status is TaskStatus.COMPLETED
    review = store.list_reviews(task.id)[0]
    assert review.reviewer == "reviewer_owner"
    assert review.provider == "operator"
    assert review.attempt_id == attempt.id


def test_owner_approval_without_evidence_is_refused(tmp_path: Path, capsys) -> None:
    """An owner verdict is a review, not a rubber stamp."""
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task, attempt = _succeeded_implementation(store, tmp_path)

    assert (
        cli.main(
            [
                "--state-dir", str(state_dir), "review", task.id,
                "--attempt", attempt.id,
                "--verdict", "approve",
                "--summary", "Looks fine.",
            ]
        )
        == 2
    )
    assert "approved reviews require evidence" in capsys.readouterr().err
    assert store.get_task(task.id).status is TaskStatus.NEEDS_REVIEW


def test_owner_request_changes_blocks_the_task(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task, attempt = _succeeded_implementation(store, tmp_path)

    assert (
        cli.main(
            [
                "--state-dir", str(state_dir), "review", task.id,
                "--attempt", attempt.id,
                "--verdict", "request_changes",
                "--summary", "The test does not cover the stated criterion.",
                "--issue", "missing coverage",
            ]
        )
        == 0
    )
    assert store.get_task(task.id).status is TaskStatus.BLOCKED


def test_owner_verdict_requires_an_exact_attempt(tmp_path: Path, capsys) -> None:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    task, _ = _succeeded_implementation(store, tmp_path)

    assert (
        cli.main(
            [
                "--state-dir", str(state_dir), "review", task.id,
                "--attempt", "att_does_not_exist",
                "--verdict", "approve",
                "--summary", "Approving without naming the real attempt.",
                "--evidence", "none",
            ]
        )
        == 2
    )
    assert store.get_task(task.id).status is TaskStatus.NEEDS_REVIEW
