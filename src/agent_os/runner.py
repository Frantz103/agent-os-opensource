"""Process boundary from a durable Agent OS task to an Omnigent session."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agent_os.context import build_task_context
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore


@dataclass(frozen=True)
class RunPlan:
    command: tuple[str, ...]
    cwd: Path
    prompt: str

    def shell_command(self) -> str:
        return shlex.join(self.command)


def find_omnigent_cli() -> str | None:
    sibling = Path(sys.executable).with_name("omnigent")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("omnigent") or shutil.which("omni")


def build_run_plan(
    store: TaskStore,
    task_id: str,
    bundle_dir: Path | str,
    *,
    omnigent_command: str | None = None,
) -> RunPlan:
    task = store.get_task(task_id)
    executable = omnigent_command or find_omnigent_cli()
    if executable is None:
        raise RuntimeError("Omnigent CLI not found; run `uv sync --dev`")
    prompt = (
        f"Execute Agent OS task {task_id}. Begin with get_task_context('{task_id}').\n\n"
        + build_task_context(store, task_id)
    )
    return RunPlan(
        command=(executable, "run", str(Path(bundle_dir).resolve()), "-p", prompt),
        cwd=task.workspace,
        prompt=prompt,
    )


def run_task(
    store: TaskStore,
    task_id: str,
    bundle_dir: Path | str,
    *,
    dry_run: bool = False,
    omnigent_command: str | None = None,
) -> RunPlan | int:
    plan = build_run_plan(store, task_id, bundle_dir, omnigent_command=omnigent_command)
    if dry_run:
        return plan

    task = store.get_task(task_id)
    if task.status in {
        TaskStatus.QUEUED,
        TaskStatus.BLOCKED,
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.FAILED,
    }:
        store.transition(task_id, TaskStatus.RUNNING, reason="starting Omnigent coordinator")
    attempt = store.start_attempt(task_id, agent="coordinator", harness="claude-sdk")
    transcript_dir = store.state_dir / "transcripts" / task_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / f"{attempt.id}.log"
    environment = os.environ.copy()
    environment["AGENT_OS_STATE_DIR"] = str(store.state_dir)

    try:
        with transcript_path.open("w") as transcript:
            process = subprocess.Popen(
                plan.command,
                cwd=plan.cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                transcript.write(line)
            return_code = process.wait()
    except BaseException as error:
        store.finish_attempt(
            attempt.id,
            status=AttemptStatus.FAILED,
            summary=f"Omnigent process failed: {type(error).__name__}: {error}",
            transcript_path=str(transcript_path),
        )
        current = store.get_task(task_id)
        if current.status is TaskStatus.RUNNING:
            store.transition(task_id, TaskStatus.FAILED, reason="Omnigent process exception")
        raise

    status = AttemptStatus.SUCCEEDED if return_code == 0 else AttemptStatus.FAILED
    store.finish_attempt(
        attempt.id,
        status=status,
        summary=f"Omnigent coordinator exited with code {return_code}",
        evidence=[f"transcript: {transcript_path}"],
        transcript_path=str(transcript_path),
    )
    current = store.get_task(task_id)
    if current.status is TaskStatus.RUNNING:
        target = TaskStatus.NEEDS_REVIEW if return_code == 0 else TaskStatus.FAILED
        store.transition(task_id, target, reason=f"coordinator exit {return_code}")
    return return_code
