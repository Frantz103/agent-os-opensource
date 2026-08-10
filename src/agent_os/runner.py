"""Process boundary from a durable Agent OS task to a supported agent runtime."""

from __future__ import annotations

import inspect
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from agent_os.context import build_task_context
from agent_os.definitions import PrimeCoordinatorAgent
from agent_os.models import AttemptStatus, TaskStatus
from agent_os.store import TaskStore


@dataclass(frozen=True)
class RunPlan:
    command: tuple[str, ...]
    cwd: Path
    prompt: str
    runtime: str
    agent: str
    harness: str

    def shell_command(self) -> str:
        return shlex.join(self.command)


def find_omnigent_cli() -> str | None:
    sibling = Path(sys.executable).with_name("omnigent")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("omnigent") or shutil.which("omni")


def find_prime_agent_cli() -> str | None:
    return shutil.which("prime-agent")


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
        runtime="omnigent",
        agent="coordinator",
        harness="claude-sdk",
    )


def build_prime_agent_run_plan(
    store: TaskStore,
    task_id: str,
    *,
    prime_agent_command: str | None = None,
    token_budget: int = 80_000,
    max_turns: int = 12,
    timeout_seconds: int = 1_800,
) -> RunPlan:
    for name, value in {
        "token_budget": token_budget,
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    task = store.get_task(task_id)
    executable = prime_agent_command or find_prime_agent_cli()
    if executable is None:
        raise RuntimeError(
            "Prime Agent CLI not found; install PrimeIntellect-ai/prime-agent or use Omnigent"
        )
    role = inspect.getdoc(PrimeCoordinatorAgent) or ""
    task_context = build_task_context(store, task_id)
    prompt = f"{role}\n\nAuthoritative Agent OS task context:\n\n{task_context}"
    return RunPlan(
        command=(
            executable,
            "--mode",
            "json",
            "--cwd",
            str(task.workspace),
            "--goal",
            task.objective,
            "--goal-token-budget",
            str(token_budget),
            "--autonomous",
            "--autonomous-max-continuations",
            "3",
            "--autonomous-max-turns",
            str(max_turns),
            "--autonomous-max-tokens",
            str(token_budget),
            "--autonomous-timeout-ms",
            str(timeout_seconds * 1_000),
            prompt,
        ),
        cwd=task.workspace,
        prompt=prompt,
        runtime="prime-agent",
        agent="prime_coordinator",
        harness="prime-agent",
    )


def run_task(
    store: TaskStore,
    task_id: str,
    bundle_dir: Path | str,
    *,
    dry_run: bool = False,
    runtime: str = "omnigent",
    omnigent_command: str | None = None,
    prime_agent_command: str | None = None,
    token_budget: int = 80_000,
    max_turns: int = 12,
    timeout_seconds: int = 1_800,
) -> RunPlan | int:
    if runtime == "omnigent":
        plan = build_run_plan(store, task_id, bundle_dir, omnigent_command=omnigent_command)
    elif runtime == "prime-agent":
        plan = build_prime_agent_run_plan(
            store,
            task_id,
            prime_agent_command=prime_agent_command,
            token_budget=token_budget,
            max_turns=max_turns,
            timeout_seconds=timeout_seconds,
        )
    else:
        raise ValueError(f"unsupported runtime: {runtime}")
    if dry_run:
        return plan

    task = store.get_task(task_id)
    if task.status in {
        TaskStatus.QUEUED,
        TaskStatus.BLOCKED,
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.FAILED,
    }:
        store.transition(task_id, TaskStatus.RUNNING, reason=f"starting {plan.runtime} coordinator")
    attempt = store.start_attempt(task_id, agent=plan.agent, harness=plan.harness)
    transcript_dir = store.state_dir / "transcripts" / task_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / f"{attempt.id}.log"
    stderr_path = (
        transcript_dir / f"{attempt.id}.stderr.log" if plan.runtime == "prime-agent" else None
    )
    environment = os.environ.copy()
    environment["AGENT_OS_STATE_DIR"] = str(store.state_dir)
    if plan.runtime == "prime-agent":
        environment.setdefault("PRIME_AGENT_TELEMETRY", "0")

    try:
        with ExitStack() as stack:
            transcript = stack.enter_context(transcript_path.open("w"))
            stderr = (
                stack.enter_context(stderr_path.open("w"))
                if stderr_path is not None
                else subprocess.STDOUT
            )
            process = subprocess.Popen(
                plan.command,
                cwd=plan.cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=stderr,
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
            summary=f"{plan.runtime} process failed: {type(error).__name__}: {error}",
            transcript_path=str(transcript_path),
        )
        current = store.get_task(task_id)
        if current.status is TaskStatus.RUNNING:
            store.transition(task_id, TaskStatus.FAILED, reason=f"{plan.runtime} process exception")
        raise

    status = AttemptStatus.SUCCEEDED if return_code == 0 else AttemptStatus.FAILED
    evidence = [f"transcript: {transcript_path}"]
    if stderr_path is not None:
        evidence.append(f"stderr: {stderr_path}")
    store.finish_attempt(
        attempt.id,
        status=status,
        summary=f"{plan.runtime} coordinator exited with code {return_code}",
        evidence=evidence,
        transcript_path=str(transcript_path),
    )
    current = store.get_task(task_id)
    if current.status is TaskStatus.RUNNING:
        target = TaskStatus.NEEDS_REVIEW if return_code == 0 else TaskStatus.FAILED
        store.transition(task_id, target, reason=f"coordinator exit {return_code}")
    return return_code
