"""Process boundary from a durable Agent OS task to a supported agent runtime."""

from __future__ import annotations

import inspect
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from omnigent.opencode_native_app_server import (
    OpenCodeVersionError,
    check_opencode_version,
    resolve_opencode_version,
)

from agent_os.context import build_task_context
from agent_os.definitions import BuilderAgent, PrimeCoordinatorAgent
from agent_os.execution import execution_identity, provider_from_model
from agent_os.models import AttemptKind, AttemptRecord, AttemptStatus, TaskStatus
from agent_os.store import TaskStore
from agent_os.tools import collect_workspace_diff


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
    workspace: Path | None = None
    review_attempt_ids: tuple[str, ...] = ()

    def shell_command(self, *, reveal_context: bool = False) -> str:
        if reveal_context:
            return shlex.join(self.command)
        redacted: list[str] = []
        redact_next = False
        for item in self.command:
            if item == f"--print={self.prompt}":
                redacted.append("--print=<task-context-redacted>")
                continue
            if redact_next or item == self.prompt:
                redacted.append("<task-context-redacted>")
                redact_next = False
                continue
            redacted.append(item)
            redact_next = item in {"-p", "--goal"}
        return shlex.join(redacted)


_BASE_ENV = {
    "AGENT_OS_ANTIGRAVITY_MODEL",
    "AGENT_OS_CODEX_BUILDER_MODEL",
    "AGENT_OS_CODEX_REVIEWER_MODEL",
    "AGENT_OS_OLLAMA_MODEL",
    "AGENT_OS_OPENCODE_MODEL",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SHELL",
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
    "google": set(),
}

_OPENCODE_ISOLATION_CONFIG = {
    "$schema": "https://opencode.ai/config.json",
    "agent": {"build": {"tools": {"skill": False}}},
}

_OPENCODE_DIRECT_PERMISSIONS = {
    "*": "allow",
    "external_directory": "deny",
    "question": "deny",
    "task": "deny",
    "skill": "deny",
    "webfetch": "deny",
    "websearch": "deny",
    "bash": {
        "*": "allow",
        "curl *": "deny",
        "docker *": "deny",
        "gh *": "deny",
        "git commit*": "deny",
        "git push*": "deny",
        "git reset*": "deny",
        "git clean*": "deny",
        "npm publish*": "deny",
        "podman *": "deny",
        "rm *": "deny",
        "rsync *": "deny",
        "scp *": "deny",
        "ssh *": "deny",
        "twine *": "deny",
        "uv publish*": "deny",
        "wget *": "deny",
    },
}

# Omnigent 0.8.2's headless ``-p`` async-orchestrator drain has a fixed 30-minute
# total ceiling. Reject a larger outer timeout instead of promising a bound the
# inner runtime cannot honor.
OMNIGENT_HEADLESS_MAX_SECONDS = 1_800
ANTIGRAVITY_MIN_VERSION = (1, 1, 6)
ANTIGRAVITY_AGENT_NAME = "agent-os-builder"
_CODEX_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "summary",
        "blocking_issues",
        "non_blocking_issues",
        "evidence",
    ],
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "request_changes", "blocked"]},
        "summary": {"type": "string", "minLength": 1},
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "non_blocking_issues": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
}
_ANTIGRAVITY_AGENT = """\
---
name: agent-os-builder
description: Bounded Agent OS implementation worker
tools:
  - view_file
  - list_dir
  - find_by_name
  - grep_search
  - replace_file_content
  - multi_replace_file_content
  - write_to_file
  - run_command
mainAgent: true
subagent: false
inheritMcp: false
model: inherit
commandExecutionPolicy: sandbox
---

# System Prompt

You are the Agent OS Antigravity implementation worker. Follow the supplied authoritative task
contract exactly. Work only in the added task workspace. Never push, merge, deploy, contact
external systems, or perform broad deletion. Return changed files, exact verification commands and
results, and every unresolved risk. Do not claim independent review or task completion. Never use
the phrase "Final Task Status: Completed"; say the implementation is awaiting independent review.
"""


def runtime_environment(
    *, providers: set[str], blocked_names: set[str] | None = None
) -> dict[str, str]:
    """Build a minimal child environment with explicit provider credential families."""
    allowed = set(_BASE_ENV)
    for provider in providers:
        allowed.update(_PROVIDER_ENV.get(provider, set()))
    configured = os.environ.get("AGENT_OS_ALLOWED_ENV", "")
    allowed.update(item.strip() for item in configured.split(",") if item.strip())
    allowed.difference_update(blocked_names or set())
    environment = {name: value for name, value in os.environ.items() if name in allowed}
    # Keep Codex provider connectivity in the harness while forcing repository I/O through
    # Omnigent's independently sandboxed dynamic tools.
    environment["HARNESS_CODEX_DISABLE_NATIVE_TOOLS"] = "1"
    environment["HARNESS_CODEX_ENABLE_WEB_SEARCH"] = "0"
    return environment


def find_omnigent_cli() -> str | None:
    sibling = Path(sys.executable).with_name("omnigent")
    if sibling.is_file():
        return str(sibling)
    return shutil.which("omnigent") or shutil.which("omni")


def find_prime_agent_cli() -> str | None:
    return shutil.which("prime-agent")


def find_opencode_cli() -> str | None:
    return shutil.which("opencode")


def find_antigravity_cli() -> str | None:
    return shutil.which("agy")


def resolve_antigravity_version(executable: str) -> tuple[int, int, int]:
    result = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", result.stdout)
    if match is None:
        raise RuntimeError(f"could not parse Antigravity CLI version: {result.stdout.strip()!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def check_antigravity_version(version: tuple[int, int, int]) -> None:
    if version < ANTIGRAVITY_MIN_VERSION:
        minimum = ".".join(str(part) for part in ANTIGRAVITY_MIN_VERSION)
        actual = ".".join(str(part) for part in version)
        raise RuntimeError(
            f"Antigravity CLI {actual} is unsupported; install {minimum} or newer"
        )


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
    identity = execution_identity("coordinator")
    prompt = (
        f"Coordinator runtime contract: {identity.agent}/{identity.harness}/{identity.provider}. "
        "Dispatch the named planner `planner`; do not substitute another planner.\n\n"
        + f"Execute Agent OS task {task_id}. Begin with get_task_context('{task_id}').\n\n"
        + build_task_context(store, task_id)
    )
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
        agent=identity.agent,
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
    local_control = "/no_think\n" if identity.provider == "ollama" else ""
    prompt = (
        f"{local_control}{role}\n\nAuthoritative Agent OS task context:\n\n{task_context}"
    )
    provider_options = ("--provider", identity.provider)
    if identity.model is not None:
        provider_options += ("--model", identity.model)
    local_options = (
        ("--offline", "--thinking", "off") if identity.provider == "ollama" else ()
    )
    return RunPlan(
        command=(
            executable,
            "--print",
            "--mode",
            "json",
            "--cwd",
            str(task.workspace),
            "--no-extensions",
            "--no-skills",
            "--skill",
            "goal",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            *local_options,
            *provider_options,
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


def build_opencode_run_plan(
    store: TaskStore,
    task_id: str,
    *,
    opencode_command: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> RunPlan:
    """Build a direct OpenCode implementation run without a Claude coordinator."""
    task = store.get_task(task_id)
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    selected_model = model or os.environ.get("AGENT_OS_OLLAMA_MODEL") or "ollama/qwen3:14b"
    selected_provider = provider_from_model(selected_model)
    agent = "builder_ollama" if selected_provider == "ollama" else "builder_opencode"
    identity = execution_identity(
        agent,
        provider=provider or selected_provider,
        model=selected_model,
    )
    assert identity.provider is not None
    executable = opencode_command or find_opencode_cli()
    if executable is None:
        raise RuntimeError("OpenCode CLI not found; install the pinned supported version")
    if opencode_command is None:
        try:
            check_opencode_version(resolve_opencode_version(executable))
        except (OSError, OpenCodeVersionError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"OpenCode CLI is incompatible: {error}") from error
    role = inspect.getdoc(BuilderAgent) or ""
    local_control = "/no_think\n" if identity.provider == "ollama" else ""
    prompt = (
        f"{local_control}{role}\n\n"
        "You are the direct Agent OS OpenCode implementation worker. Work only in the supplied "
        "task workspace. Do not push, commit, merge, deploy, contact external systems, use network "
        "tools, launch subagents, or perform broad deletion. Implement the task, run bounded local "
        "verification, and report changed files, exact verification results, and unresolved risks. "
        "Do not claim independent review or durable task completion.\n\n"
        f"Authoritative Agent OS task context for {task_id}:\n\n"
        f"{build_task_context(store, task_id)}"
    )
    runtime_dir = store.state_dir / "runtime" / "opencode-direct" / task_id
    return RunPlan(
        command=(
            executable,
            "run",
            "--pure",
            "--model",
            identity.model or "",
            "--format",
            "json",
            "--dir",
            str(task.workspace),
            prompt,
        ),
        cwd=runtime_dir,
        prompt=prompt,
        runtime="opencode",
        agent=identity.agent,
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
        work_item="primary",
        workspace=task.workspace,
    )


def build_antigravity_run_plan(
    store: TaskStore,
    task_id: str,
    *,
    antigravity_command: str | None = None,
    model: str | None = None,
    timeout_seconds: int = 1_800,
) -> RunPlan:
    task = store.get_task(task_id)
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    executable = antigravity_command or find_antigravity_cli()
    if executable is None:
        raise RuntimeError("Antigravity CLI not found; install `agy` and authenticate once")
    if antigravity_command is None:
        check_antigravity_version(resolve_antigravity_version(executable))
    identity = execution_identity("builder_antigravity", model=model)
    assert identity.provider is not None
    role = inspect.getdoc(BuilderAgent) or ""
    prompt = (
        f"{role}\n\n"
        f"Authoritative Agent OS task context for {task_id}:\n\n"
        f"{build_task_context(store, task_id)}"
    )
    runtime_dir = store.state_dir / "runtime" / "antigravity" / task_id
    return RunPlan(
        command=(
            executable,
            "--output-format",
            "stream-json",
            "--mode",
            "accept-edits",
            "--sandbox",
            "--disable-slash-commands",
            "--agent",
            ANTIGRAVITY_AGENT_NAME,
            "--add-dir",
            str(task.workspace),
            "--model",
            identity.model or "",
            "--print-timeout",
            f"{timeout_seconds}s",
            f"--print={prompt}",
        ),
        cwd=runtime_dir,
        prompt=prompt,
        runtime="antigravity",
        agent=identity.agent,
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
        work_item="primary",
        workspace=task.workspace,
    )


def build_codex_review_plan(
    store: TaskStore,
    task_id: str,
    *,
    codex_command: str | None = None,
    model: str | None = None,
) -> RunPlan:
    task = store.get_task(task_id)
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    executable = codex_command or shutil.which("codex")
    if executable is None:
        raise RuntimeError("Codex CLI not found; install it and authenticate once")
    identity = execution_identity("reviewer_codex", model=model)
    assert identity.provider is not None
    targets = _review_targets(store, task_id, reviewer_provider=identity.provider)
    runtime_dir = store.state_dir / "runtime" / "codex-review" / task_id
    schema_path = runtime_dir / "review.schema.json"
    result_path = runtime_dir / "review.result.json"
    target_list = ", ".join(attempt.id for attempt in targets)
    prompt = (
        "You are the independent, read-only Agent OS reviewer. Inspect the actual workspace and "
        "run bounded verification without modifying files. Review the implementation attempts "
        f"{target_list} against every acceptance criterion. Return only the required structured "
        "verdict. Approve only with concrete evidence.\n\n"
        f"{build_task_context(store, task_id)}\n\n"
        f"{collect_workspace_diff(store, task_id)}"
    )
    return RunPlan(
        command=(
            executable,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--config",
            'approval_policy="never"',
            "--model",
            identity.model or "",
            "--cd",
            str(task.workspace),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(result_path),
            "-",
        ),
        cwd=runtime_dir,
        prompt=prompt,
        runtime="codex-review",
        agent=identity.agent,
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
        work_item="review",
        workspace=task.workspace,
        review_attempt_ids=tuple(attempt.id for attempt in targets),
    )


def build_codex_run_plan(
    store: TaskStore,
    task_id: str,
    *,
    codex_command: str | None = None,
    model: str | None = None,
) -> RunPlan:
    """Build a direct, subscription-backed Codex implementation run."""
    task = store.get_task(task_id)
    if not task.workspace.is_dir():
        raise RuntimeError(f"task workspace is unavailable: {task.workspace}")
    executable = codex_command or shutil.which("codex")
    if executable is None:
        raise RuntimeError("Codex CLI not found; install it and authenticate once")
    identity = execution_identity("builder_codex", model=model)
    assert identity.provider is not None
    role = inspect.getdoc(BuilderAgent) or ""
    prompt = (
        f"{role}\n\n"
        "You are the direct Agent OS Codex implementation worker. Work only in the supplied "
        "task workspace. Do not push, merge, deploy, contact external systems, or perform broad "
        "deletion. Implement the task, run bounded verification, and report changed files, exact "
        "verification results, and every unresolved risk. Do not claim independent review or "
        "task completion; say the implementation is awaiting independent review.\n\n"
        f"Authoritative Agent OS task context for {task_id}:\n\n"
        f"{build_task_context(store, task_id)}"
    )
    runtime_dir = store.state_dir / "runtime" / "codex" / task_id
    result_path = runtime_dir / "implementation.result.txt"
    return RunPlan(
        command=(
            executable,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "workspace-write",
            "--config",
            'approval_policy="never"',
            "--model",
            identity.model or "",
            "--cd",
            str(task.workspace),
            "--output-last-message",
            str(result_path),
            "-",
        ),
        cwd=runtime_dir,
        prompt=prompt,
        runtime="codex",
        agent=identity.agent,
        harness=identity.harness,
        provider=identity.provider,
        model=identity.model,
        kind=identity.kind,
        work_item="primary",
        workspace=task.workspace,
    )


def _review_targets(
    store: TaskStore, task_id: str, *, reviewer_provider: str
) -> list[AttemptRecord]:
    implementations = [
        attempt
        for attempt in store.list_attempts(task_id)
        if attempt.kind is AttemptKind.IMPLEMENTATION
    ]
    if not implementations:
        raise ValueError("Codex fallback review requires a successful implementation attempt")
    latest_by_work_item: dict[str, AttemptRecord] = {}
    for attempt in implementations:
        latest_by_work_item[attempt.work_item] = attempt
    targets = list(latest_by_work_item.values())
    failed = [attempt.id for attempt in targets if attempt.status is not AttemptStatus.SUCCEEDED]
    if failed:
        raise ValueError(f"latest implementation attempts did not succeed: {', '.join(failed)}")
    same_provider = [attempt.id for attempt in targets if attempt.provider == reviewer_provider]
    if same_provider:
        raise ValueError(
            "Codex cannot independently review OpenAI-backed implementation attempts: "
            + ", ".join(same_provider)
        )
    reviewed = {review.attempt_id for review in store.list_reviews(task_id)}
    pending = [attempt for attempt in targets if attempt.id not in reviewed]
    if not pending:
        raise ValueError("latest implementation attempts already have review records")
    return pending


def run_task(
    store: TaskStore,
    task_id: str,
    bundle_dir: Path | str,
    *,
    dry_run: bool = False,
    runtime: str = "omnigent",
    omnigent_command: str | None = None,
    prime_agent_command: str | None = None,
    opencode_command: str | None = None,
    antigravity_command: str | None = None,
    codex_command: str | None = None,
    token_budget: int = 80_000,
    max_turns: int = 12,
    timeout_seconds: int = 1_800,
    provider: str | None = None,
    model: str | None = None,
) -> RunPlan | int:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if runtime == "omnigent":
        if timeout_seconds > OMNIGENT_HEADLESS_MAX_SECONDS:
            raise ValueError(
                "Omnigent 0.8.2 headless runs support at most 1800 seconds; "
                "use a faster child model/task or Prime Agent for longer work"
            )
        else:
            plan = build_run_plan(
                store,
                task_id,
                bundle_dir,
                omnigent_command=omnigent_command,
            )
    elif runtime == "codex":
        if provider is not None:
            raise ValueError("--provider applies only to the Prime Agent runtime")
        plan = build_codex_run_plan(
            store,
            task_id,
            codex_command=codex_command,
            model=model,
        )
    elif runtime == "codex-review":
        if provider is not None:
            raise ValueError("--provider applies only to the Prime Agent runtime")
        plan = build_codex_review_plan(
            store,
            task_id,
            codex_command=codex_command,
            model=model,
        )
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
    elif runtime == "opencode":
        plan = build_opencode_run_plan(
            store,
            task_id,
            opencode_command=opencode_command,
            provider=provider,
            model=model,
        )
    elif runtime == "antigravity":
        if provider is not None:
            raise ValueError("--provider applies only to the Prime Agent runtime")
        plan = build_antigravity_run_plan(
            store,
            task_id,
            antigravity_command=antigravity_command,
            model=model,
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
        store.transition(
            task_id,
            TaskStatus.RUNNING,
            reason=f"starting {plan.runtime} {_attempt_label(plan)}",
        )
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
        transcript_dir / f"{attempt.id}.stderr.log"
        if plan.runtime in {
            "prime-agent",
            "opencode",
            "antigravity",
            "codex",
            "codex-review",
        }
        else None
    )
    providers = (
        {"anthropic", "openai"} if plan.runtime == "omnigent" else {plan.provider}
    )
    blocked_names = {"ANTHROPIC_API_KEY"} if plan.runtime == "omnigent" else set()
    environment = runtime_environment(providers=providers, blocked_names=blocked_names)
    environment["AGENT_OS_STATE_DIR"] = str(store.state_dir)
    environment["AGENT_OS_TASK_ID"] = task_id
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if plan.runtime == "omnigent":
        # Omnigent gives OpenCode a session-owned XDG config directory, but OpenCode also
        # discovers Claude-compatible prompts/skills and ~/.agents/skills from the host HOME.
        # Disable Claude compatibility and give OpenCode a separate Agent OS config directory
        # that removes the skill tool from the model-facing build agent. Omnigent deliberately
        # strips OPENCODE_CONFIG_CONTENT, but permits OPENCODE_CONFIG_DIR. This does not modify
        # the operator's global configuration.
        environment["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"
        environment["OPENCODE_CONFIG_DIR"] = str(_prepare_opencode_isolation_config(store))
    if plan.runtime == "prime-agent":
        environment.setdefault("PRIME_AGENT_TELEMETRY", "0")
    if plan.runtime == "opencode":
        opencode_environment = _prepare_direct_opencode_runtime(
            plan.cwd,
            model=plan.model or "",
        )
        environment.update(opencode_environment)
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_TERMINAL_PROMPT"] = "0"
    if plan.runtime == "antigravity":
        environment["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_TERMINAL_PROMPT"] = "0"
        xdg_config = plan.cwd / "xdg-config"
        xdg_config.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(xdg_config, 0o700)
        environment["XDG_CONFIG_HOME"] = str(xdg_config)
        _prepare_antigravity_runtime(plan.cwd, workspace=plan.workspace or plan.cwd)
    if plan.runtime in {"codex", "codex-review"}:
        _prepare_codex_runtime(plan.cwd, review=plan.runtime == "codex-review")
    workspace = plan.workspace or plan.cwd

    process: subprocess.Popen[str] | None = None
    runtime_failures: list[str] = []
    reader_errors: list[BaseException] = []
    antigravity_results: list[dict[str, object]] = []
    opencode_results: list[dict[str, object]] = []
    codex_review_result: dict[str, object] | None = None
    try:
        with ExitStack() as stack:
            if plan.runtime == "antigravity":
                activation = stack.enter_context(
                    _antigravity_policy_plugin(
                        workspace=workspace,
                        plugin_dir=(
                            store.state_dir / "runtime" / "antigravity-test-plugin"
                            if antigravity_command is not None
                            else None
                        ),
                    )
                )
                environment["AGENT_OS_ANTIGRAVITY_POLICY_TOKEN"] = activation
            if plan.runtime in {"codex", "codex-review"}:
                codex_home = stack.enter_context(_codex_home(plan.cwd))
                environment["CODEX_HOME"] = str(codex_home)
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
                stdin=(
                    subprocess.PIPE
                    if plan.runtime in {"codex", "codex-review"}
                    else None
                ),
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                bufsize=1,
                start_new_session=os.name == "posix",
            )
            store.set_attempt_process(attempt.id, process.pid)
            if plan.runtime in {"codex", "codex-review"}:
                stdin = process.stdin
                assert stdin is not None
                stdin.write(plan.prompt)
                stdin.close()
            stdout = process.stdout
            assert stdout is not None

            def stream_output() -> None:
                try:
                    for line in stdout:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                        transcript.write(line)
                        failure = _runtime_failure(line)
                        if failure is not None and not runtime_failures:
                            runtime_failures.append(failure)
                        if plan.runtime == "antigravity":
                            terminal = _antigravity_terminal_result(line)
                            if terminal is not None:
                                antigravity_results.append(terminal)
                        if plan.runtime == "opencode":
                            terminal = _opencode_terminal_result(line)
                            if terminal is not None:
                                opencode_results.append(terminal)
                except BaseException as error:
                    reader_errors.append(error)

            reader = threading.Thread(target=stream_output, name=f"agent-os-{attempt.id}")
            reader.start()
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as error:
                _terminate_process(process)
                raise TimeoutError(
                    f"{plan.runtime} process exceeded {timeout_seconds} seconds"
                ) from error
            finally:
                reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError("runtime output reader did not stop")
            if reader_errors:
                raise RuntimeError(f"runtime output reader failed: {reader_errors[0]}")
            if plan.runtime in {"codex", "codex-review"}:
                output_name = (
                    "implementation.result.txt"
                    if plan.runtime == "codex"
                    else "review.result.json"
                )
                with suppress(FileNotFoundError):
                    os.chmod(plan.cwd / output_name, 0o600)
    except BaseException as error:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        if plan.kind is AttemptKind.COORDINATOR:
            _fail_running_child_attempts(
                store,
                task_id,
                coordinator_attempt_id=attempt.id,
                reason=f"{plan.runtime} coordinator terminated before child completion",
            )
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
    incomplete_children = (
        _fail_running_child_attempts(
            store,
            task_id,
            coordinator_attempt_id=attempt.id,
            reason=f"{plan.runtime} coordinator exited before child completion",
        )
        if plan.kind is AttemptKind.COORDINATOR
        else []
    )
    if incomplete_children:
        runtime_failures.append(
            "coordinator exited with running child attempts: " + ", ".join(incomplete_children)
        )
    if plan.runtime == "antigravity":
        if not antigravity_results:
            runtime_failures.append("Antigravity stream ended without a terminal result event")
        elif antigravity_results[-1].get("status") != "SUCCESS":
            runtime_failures.append(
                "Antigravity terminal status was "
                f"{antigravity_results[-1].get('status', 'missing')!r}"
            )
    if plan.runtime == "opencode" and not opencode_results:
        runtime_failures.append("OpenCode stream ended without a terminal stop event")
    if plan.runtime == "codex-review":
        try:
            codex_review_result = _load_codex_review_result(plan.cwd / "review.result.json")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            runtime_failures.append(f"Codex review result was invalid: {error}")
    runtime_failure = runtime_failures[0] if runtime_failures else None
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
            f"{plan.runtime} {_attempt_label(plan)} failed: {runtime_failure}"
            if runtime_failure is not None
            else f"{plan.runtime} {_attempt_label(plan)} exited with code {return_code}"
        ),
        evidence=evidence,
        transcript_path=str(transcript_path),
    )
    current = store.get_task(task_id)
    if current.status is TaskStatus.RUNNING:
        target = TaskStatus.NEEDS_REVIEW if return_code == 0 else TaskStatus.FAILED
        store.transition(
            task_id,
            target,
            reason=f"{_attempt_label(plan)} exit {return_code}",
        )
    if return_code == 0 and codex_review_result is not None:
        _record_codex_review(store, task_id, plan, codex_review_result)
    return return_code


def _open_private_text(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def _attempt_label(plan: RunPlan) -> str:
    return "coordinator" if plan.kind is AttemptKind.COORDINATOR else "implementation"


def _prepare_antigravity_runtime(runtime_dir: Path, *, workspace: Path) -> None:
    agent_dir = runtime_dir / ".agents" / "agents" / ANTIGRAVITY_AGENT_NAME
    agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    os.chmod(runtime_dir / ".agents", 0o700)
    os.chmod(runtime_dir / ".agents" / "agents", 0o700)
    os.chmod(agent_dir, 0o700)
    agent_path = agent_dir / "agent.md"
    descriptor, temp_name = tempfile.mkstemp(prefix="agent.md.", dir=agent_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_ANTIGRAVITY_AGENT)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, agent_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _prepare_codex_runtime(runtime_dir: Path, *, review: bool) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    if review:
        _write_private_json(runtime_dir / "review.schema.json", _CODEX_REVIEW_SCHEMA)
        result_path = runtime_dir / "review.result.json"
    else:
        result_path = runtime_dir / "implementation.result.txt"
    with suppress(FileNotFoundError):
        result_path.unlink()


@contextmanager
def _codex_home(runtime_dir: Path):
    """Give Codex private writable state while reusing the operator's saved login."""
    codex_home = Path(tempfile.mkdtemp(prefix="codex-home.", dir=runtime_dir))
    os.chmod(codex_home, 0o700)
    configured_home = os.environ.get("CODEX_HOME")
    source_home = (
        Path(configured_home).expanduser()
        if configured_home
        else Path.home() / ".codex"
    )
    source_auth = source_home / "auth.json"
    if source_auth.is_file():
        _copy_private_file(source_auth, codex_home / "auth.json")
    try:
        yield codex_home
    finally:
        shutil.rmtree(codex_home)


def _copy_private_file(source: Path, target: Path) -> None:
    """Copy one credential file without following a substituted source symlink."""
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    source_descriptor = os.open(source, source_flags)
    target_descriptor: int | None = None
    try:
        target_descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        while chunk := os.read(source_descriptor, 64 * 1024):
            os.write(target_descriptor, chunk)
        os.fchmod(target_descriptor, 0o600)
    finally:
        os.close(source_descriptor)
        if target_descriptor is not None:
            os.close(target_descriptor)


def _load_codex_review_result(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("result must be a JSON object")
    verdict = payload.get("verdict")
    if verdict not in {"approve", "request_changes", "blocked"}:
        raise ValueError("result has an invalid verdict")
    summary = payload.get("summary")
    evidence = payload.get("evidence")
    blocking = payload.get("blocking_issues")
    non_blocking = payload.get("non_blocking_issues")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("result summary is required")
    for name, value in {
        "evidence": evidence,
        "blocking_issues": blocking,
        "non_blocking_issues": non_blocking,
    }.items():
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"result {name} must be a string array")
    if not evidence:
        raise ValueError("result evidence must not be empty")
    return payload


def _record_codex_review(
    store: TaskStore,
    task_id: str,
    plan: RunPlan,
    payload: dict[str, object],
) -> None:
    verdict = str(payload["verdict"])
    summary = str(payload["summary"])
    blocking = cast(list[str], payload["blocking_issues"])
    non_blocking = cast(list[str], payload["non_blocking_issues"])
    review_evidence = cast(list[str], payload["evidence"])
    issues = [
        *blocking,
        *non_blocking,
    ]
    evidence = list(review_evidence)
    for attempt_id in plan.review_attempt_ids:
        store.record_review(
            task_id,
            reviewer="reviewer_codex",
            verdict=verdict,
            summary=summary,
            attempt_id=attempt_id,
            issues=issues,
            evidence=evidence,
        )
    if verdict == "approve":
        store.complete_task(task_id, summary=summary)
    else:
        store.transition(task_id, TaskStatus.BLOCKED, reason=summary)


@contextmanager
def _antigravity_policy_plugin(*, workspace: Path, plugin_dir: Path | None = None):
    """Install a per-run global hook because AGY 1.1 does not load workspace hooks headlessly."""
    activation = secrets.token_hex(24)
    plugin_dir = plugin_dir or (
        Path.home() / ".gemini" / "config" / "plugins" / "agent-os-runtime-boundary"
    )
    try:
        plugin_dir.mkdir(parents=True, mode=0o700)
    except FileExistsError as error:
        raise RuntimeError(
            "Antigravity policy plugin is already active; wait for the other Agent OS run "
            "to finish or remove a stale ~/.gemini/config/plugins/agent-os-runtime-boundary"
        ) from error
    os.chmod(plugin_dir, 0o700)
    policy_command = shlex.join(
        (
            sys.executable,
            "-m",
            "agent_os.antigravity_policy",
            str(workspace),
            activation,
        )
    )
    hooks = {
        "agent-os-runtime-boundary": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": policy_command, "timeout": 5}
                    ],
                }
            ]
        }
    }
    plugin_path = plugin_dir / "plugin.json"
    hooks_path = plugin_dir / "hooks.json"
    try:
        _write_private_json(plugin_path, {"name": "agent-os-runtime-boundary"})
        _write_private_json(hooks_path, hooks)
        yield activation
    finally:
        for path in (hooks_path, plugin_path):
            with suppress(FileNotFoundError):
                path.unlink()
        with suppress(OSError):
            plugin_dir.rmdir()


def _write_private_json(path: Path, payload: object) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _antigravity_terminal_result(line: str) -> dict[str, object] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if payload.get("event") != "result" or not isinstance(payload.get("result"), dict):
        return None
    return payload["result"]


def _opencode_terminal_result(line: str) -> dict[str, object] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    part = payload.get("part")
    if (
        payload.get("type") != "step_finish"
        or not isinstance(part, dict)
        or part.get("reason") != "stop"
    ):
        return None
    return payload


def _prepare_direct_opencode_runtime(runtime_dir: Path, *, model: str) -> dict[str, str]:
    """Create private OpenCode state and a fail-closed direct-worker configuration."""
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    directories = {
        "OPENCODE_CONFIG_DIR": runtime_dir / "config",
        "XDG_CONFIG_HOME": runtime_dir / "xdg-config",
        "XDG_DATA_HOME": runtime_dir / "xdg-data",
        "XDG_CACHE_HOME": runtime_dir / "xdg-cache",
        "XDG_STATE_HOME": runtime_dir / "xdg-state",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
    payload: dict[str, object] = {
        "$schema": "https://opencode.ai/config.json",
        "permission": _OPENCODE_DIRECT_PERMISSIONS,
        "agent": {"build": {"tools": {"skill": False}}},
    }
    if provider_from_model(model) == "ollama":
        model_id = model.partition("/")[2]
        payload["provider"] = {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (local)",
                "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                "models": {model_id: {"name": f"{model_id} (local)"}},
            }
        }
    _write_private_json(directories["OPENCODE_CONFIG_DIR"] / "opencode.json", payload)
    return {
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        **{name: str(path) for name, path in directories.items()},
    }


def _prepare_opencode_isolation_config(store: TaskStore) -> Path:
    """Write the fixed OpenCode tool-deny config under private Agent OS state."""
    config_dir = store.state_dir / "runtime" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    config_path = config_dir / "opencode.json"
    payload = json.dumps(_OPENCODE_ISOLATION_CONFIG, indent=2, sort_keys=True) + "\n"
    descriptor, temp_name = tempfile.mkstemp(prefix="opencode.json.", dir=config_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, config_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return config_dir


def _fail_running_child_attempts(
    store: TaskStore,
    task_id: str,
    *,
    coordinator_attempt_id: str,
    reason: str,
) -> list[str]:
    """Close child attempts orphaned by a terminal coordinator process."""
    failed: list[str] = []
    for child in store.list_attempts(task_id):
        if child.id == coordinator_attempt_id or child.status is not AttemptStatus.RUNNING:
            continue
        store.finish_attempt(
            child.id,
            status=AttemptStatus.FAILED,
            summary=reason,
            evidence=[],
            transcript_path=child.transcript_path,
        )
        failed.append(child.id)
    return failed


def _runtime_failure(line: str) -> str | None:
    """Recognize fatal launcher messages emitted with a misleading zero exit status."""
    stripped = line.strip()
    fatal_prefixes = (
        "Failed to authenticate:",
        "Failed to start agent:",
        "Failed to launch agent:",
    )
    fatal_substrings = ("You've hit your weekly limit",)
    return (
        stripped
        if stripped.startswith(fatal_prefixes)
        or any(marker in stripped for marker in fatal_substrings)
        else None
    )


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
