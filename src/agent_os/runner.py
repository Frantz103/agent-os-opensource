"""Process boundary from a durable Agent OS task to a supported agent runtime."""

from __future__ import annotations

import inspect
import os
import shlex
import shutil
import signal
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from agent_os.context import build_task_context
from agent_os.definitions import PrimeCoordinatorAgent
from agent_os.execution import execution_identity
from agent_os.models import AttemptKind, AttemptStatus, TaskStatus
from agent_os.store import TaskStore


@dataclass(frozen=True)
class RunPlan:
    command: tuple[str, ...]
    cwd: Path
    prompt: str
    runtime: str
    agent: str
    harness: str
    provider: str
    model: str | None = None
    kind: AttemptKind = AttemptKind.COORDINATOR
    work_item: str = "coordinator"
    goal: str | None = None

    def shell_command(self, *, reveal_context: bool = False) -> str:
        if reveal_context:
            return shlex.join(self.command)
        redacted: list[str] = []
        redact_next = False
        for item in self.command:
            if redact_next or item == self.prompt:
                redacted.append("<task-context-redacted>")
                redact_next = False
                continue
            redacted.append(item)
            redact_next = item in {"-p", "--goal"}
        return shlex.join(redacted)


_BASE_ENV = {
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SHELL",
    "SSH_AUTH_SOCK",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
}

_PROVIDER_ENV = {
    "anthropic": {"ANTHROPIC_API_KEY"},
    "openai": {"OPENAI_API_KEY"},
    "ollama": set(),
}


def runtime_environment(*, providers: set[str]) -> dict[str, str]:
    """Build a minimal child environment with explicit provider credential families."""
    allowed = set(_BASE_ENV)
    for provider in providers:
        allowed.update(_PROVIDER_ENV.get(provider, set()))
    configured = os.environ.get("AGENT_OS_ALLOWED_ENV", "")
    allowed.update(item.strip() for item in configured.split(",") if item.strip())
    return {name: value for name, value in os.environ.items() if name in allowed}


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
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    executable = omnigent_command or find_omnigent_cli()
    if executable is None:
        raise RuntimeError("Omnigent CLI not found; run `uv sync --dev`")
    prompt = (
        f"Execute Agent OS task {task_id}. Begin with get_task_context('{task_id}').\n\n"
        + build_task_context(store, task_id)
    )
    identity = execution_identity("coordinator")
    assert identity.provider is not None
    return RunPlan(
        command=(
            executable,
            "run",
            str(Path(bundle_dir).resolve()),
            "--no-session",
            "-p",
            prompt,
        ),
        cwd=task.workspace,
        prompt=prompt,
        runtime="omnigent",
        agent="coordinator",
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
    )


def build_prime_agent_run_plan(
    store: TaskStore,
    task_id: str,
    *,
    prime_agent_command: str | None = None,
    token_budget: int = 80_000,
    max_turns: int = 12,
    timeout_seconds: int = 1_800,
    provider: str | None = None,
    model: str | None = None,
) -> RunPlan:
    for name, value in {
        "token_budget": token_budget,
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    task = store.get_task(task_id)
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    identity = execution_identity("prime_coordinator", provider=provider, model=model)
    assert identity.provider is not None
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
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
        work_item="primary",
        goal=task.objective,
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
    provider: str | None = None,
    model: str | None = None,
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
            provider=provider,
            model=model,
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
    attempt = store.start_attempt(
        task_id,
        agent=plan.agent,
        work_item=plan.work_item,
        provider=plan.provider,
        model=plan.model,
    )
    transcript_dir = store.state_dir / "transcripts" / task_id
    transcript_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(transcript_dir, 0o700)
    transcript_path = transcript_dir / f"{attempt.id}.log"
    stderr_path = (
        transcript_dir / f"{attempt.id}.stderr.log" if plan.runtime == "prime-agent" else None
    )
    providers = {"anthropic", "openai"} if plan.runtime == "omnigent" else {plan.provider}
    environment = runtime_environment(providers=providers)
    environment["AGENT_OS_STATE_DIR"] = str(store.state_dir)
    if plan.runtime == "prime-agent":
        environment.setdefault("PRIME_AGENT_TELEMETRY", "0")

    process: subprocess.Popen[str] | None = None
    runtime_failure: str | None = None
    try:
        with ExitStack() as stack:
            transcript = stack.enter_context(_open_private_text(transcript_path))
            stderr = (
                stack.enter_context(_open_private_text(stderr_path))
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
                start_new_session=os.name == "posix",
            )
            store.set_attempt_process(attempt.id, process.pid)
            assert process.stdout is not None
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                transcript.write(line)
                runtime_failure = runtime_failure or _runtime_failure(line)
            return_code = process.wait()
    except BaseException as error:
        if process is not None and process.poll() is None:
            _terminate_process(process)
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

    if runtime_failure is not None and return_code == 0:
        return_code = 1
    status = AttemptStatus.SUCCEEDED if return_code == 0 else AttemptStatus.FAILED
    evidence = [f"transcript: {transcript_path}"]
    if stderr_path is not None:
        evidence.append(f"stderr: {stderr_path}")
    store.finish_attempt(
        attempt.id,
        status=status,
        summary=(
            f"{plan.runtime} coordinator failed: {runtime_failure}"
            if runtime_failure is not None
            else f"{plan.runtime} coordinator exited with code {return_code}"
        ),
        evidence=evidence,
        transcript_path=str(transcript_path),
    )
    current = store.get_task(task_id)
    if current.status is TaskStatus.RUNNING:
        target = TaskStatus.NEEDS_REVIEW if return_code == 0 else TaskStatus.FAILED
        store.transition(task_id, target, reason=f"coordinator exit {return_code}")
    return return_code


def _open_private_text(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def _runtime_failure(line: str) -> str | None:
    """Recognize fatal launcher messages emitted with a misleading zero exit status."""
    stripped = line.strip()
    fatal_prefixes = (
        "Failed to authenticate:",
        "Failed to start agent:",
        "Failed to launch agent:",
    )
    return stripped if stripped.startswith(fatal_prefixes) else None


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=5)
