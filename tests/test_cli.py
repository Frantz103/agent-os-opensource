from __future__ import annotations

from pathlib import Path

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
