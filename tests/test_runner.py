from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from agent_os.models import TaskStatus
from agent_os.runner import (
    RunPlan,
    _antigravity_policy_plugin,
    _antigravity_terminal_result,
    _open_private_text,
    _runtime_failure,
    check_antigravity_version,
    resolve_antigravity_version,
    run_task,
    runtime_environment,
)
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
    assert "--no-session" in result.command
    assert result.runtime == "omnigent"
    assert task.id in result.prompt
    assert task.objective not in result.shell_command()
    assert task.id not in result.shell_command()
    assert "<task-context-redacted>" in result.shell_command()
    assert task.id in result.shell_command(reveal_context=True)
    assert store.list_attempts(task.id) == []


def test_dry_run_can_use_subscription_codex_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Codex fallback",
        objective="Run without consuming Claude capacity.",
        workspace=tmp_path,
        acceptance_criteria=["Codex independently reviews the task"],
    )
    store.transition(task.id, TaskStatus.RUNNING)
    implementation = store.start_attempt(task.id, agent="builder_antigravity")
    store.finish_attempt(
        implementation.id,
        status="succeeded",
        summary="implemented",
        evidence=["implementation evidence"],
    )
    store.transition(task.id, TaskStatus.NEEDS_REVIEW)
    monkeypatch.setattr("agent_os.runner.collect_workspace_diff", lambda store, task_id: "diff")

    result = run_task(
        store,
        task.id,
        tmp_path / "bundle",
        dry_run=True,
        runtime="codex-review",
        codex_command="/fake/codex",
    )

    assert isinstance(result, RunPlan)
    assert result.agent == "reviewer_codex"
    assert result.harness == "codex"
    assert result.provider == "openai"
    assert result.command[:2] == ("/fake/codex", "exec")
    assert result.command[result.command.index("--sandbox") + 1] == "read-only"
    assert result.command[result.command.index("--config") + 1] == 'approval_policy="never"'
    assert result.command[result.command.index("--model") + 1] == "gpt-5.6-sol"
    assert result.command[-1] == "-"
    assert result.prompt not in result.command
    assert result.model == "gpt-5.6-sol"
    assert implementation.id in result.prompt
    attempts = store.list_attempts(task.id)
    assert len(attempts) == 1
    assert attempts[0].id == implementation.id
    assert attempts[0].status.value == "succeeded"


def test_direct_codex_builder_has_workspace_write_baseline(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Codex fallback",
        objective="Implement without consuming Claude capacity.",
        workspace=workspace,
        acceptance_criteria=["Codex records an attributed implementation"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "unused-bundle",
        dry_run=True,
        runtime="codex",
        codex_command="/fake/codex",
    )

    assert isinstance(result, RunPlan)
    assert result.runtime == "codex"
    assert result.agent == "builder_codex"
    assert result.harness == "codex"
    assert result.provider == "openai"
    assert result.model == "gpt-5.6-sol"
    assert result.command[:2] == ("/fake/codex", "exec")
    assert result.command[result.command.index("--sandbox") + 1] == "workspace-write"
    assert result.command[result.command.index("--config") + 1] == 'approval_policy="never"'
    assert result.command[result.command.index("--cd") + 1] == str(workspace)
    assert result.command[-1] == "-"
    assert result.prompt not in result.command
    assert "awaiting independent review" in result.prompt
    assert store.list_attempts(task.id) == []


def test_direct_codex_builder_executes_and_cleans_private_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_codex_home = tmp_path / "source-codex-home"
    source_codex_home.mkdir()
    source_auth = source_codex_home / "auth.json"
    source_auth.write_text('{"test_token":"subscription-login"}\n')
    source_auth.chmod(0o600)
    monkeypatch.setenv("CODEX_HOME", str(source_codex_home))
    codex_runtime = tmp_path / "codex"
    codex_runtime.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "prompt = sys.stdin.read()\n"
        "assert 'Implement through direct Codex' in prompt\n"
        "assert args[args.index('--sandbox') + 1] == 'workspace-write'\n"
        "assert args[args.index('--config') + 1] == 'approval_policy=\"never\"'\n"
        "workspace = Path(args[args.index('--cd') + 1])\n"
        "codex_home = Path(os.environ['CODEX_HOME'])\n"
        "assert codex_home.parent.name == os.environ['AGENT_OS_TASK_ID']\n"
        "assert codex_home.name.startswith('codex-home.')\n"
        "assert codex_home.stat().st_mode & 0o777 == 0o700\n"
        "assert (codex_home / 'auth.json').stat().st_mode & 0o777 == 0o600\n"
        "(workspace / 'codex.txt').write_text('implemented\\n')\n"
        "result = Path(args[args.index('--output-last-message') + 1])\n"
        "result.write_text('Implementation is awaiting independent review.\\n')\n"
        "print(json.dumps({'type': 'turn.completed'}))\n"
    )
    codex_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Direct Codex",
        objective="Implement through direct Codex.",
        workspace=workspace,
        acceptance_criteria=["The implementation is attributed and awaits review"],
    )

    assert (
        run_task(
            store,
            task.id,
            tmp_path / "unused-bundle",
            runtime="codex",
            codex_command=str(codex_runtime),
            timeout_seconds=30,
        )
        == 0
    )

    assert (workspace / "codex.txt").read_text() == "implemented\n"
    assert store.get_task(task.id).status is TaskStatus.NEEDS_REVIEW
    attempt = store.list_attempts(task.id)[0]
    assert attempt.agent == "builder_codex"
    assert attempt.kind.value == "implementation"
    assert attempt.provider == "openai"
    assert attempt.model == "gpt-5.6-sol"
    assert attempt.status.value == "succeeded"
    runtime_dir = store.state_dir / "runtime" / "codex" / task.id
    assert (runtime_dir / "implementation.result.txt").read_text().startswith(
        "Implementation is awaiting independent review."
    )
    assert (runtime_dir / "implementation.result.txt").stat().st_mode & 0o777 == 0o600
    assert list(runtime_dir.glob("codex-home.*")) == []
    assert source_auth.read_text() == '{"test_token":"subscription-login"}\n'


def test_dry_run_builds_bounded_antigravity_cli_command(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Antigravity fallback",
        objective="Implement without consuming Claude capacity.",
        workspace=workspace,
        acceptance_criteria=["Antigravity performs an attributed implementation"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "unused-bundle",
        dry_run=True,
        runtime="antigravity",
        antigravity_command="/fake/agy",
        timeout_seconds=90,
    )

    assert isinstance(result, RunPlan)
    assert result.runtime == "antigravity"
    assert result.agent == "builder_antigravity"
    assert result.harness == "antigravity-cli"
    assert result.provider == "google"
    assert result.model == "gemini-3.6-flash-high"
    assert result.command[:3] == ("/fake/agy", "--output-format", "stream-json")
    assert "--sandbox" in result.command
    assert "--disable-slash-commands" in result.command
    assert result.command[result.command.index("--agent") + 1] == "agent-os-builder"
    assert result.command[result.command.index("--add-dir") + 1] == str(workspace)
    assert result.command[result.command.index("--print-timeout") + 1] == "90s"
    assert "Final Task Status: Completed" not in result.prompt
    assert "awaiting independent review" in result.prompt
    assert task.id not in result.shell_command()
    assert "--print=<task-context-redacted>" in result.shell_command()
    assert not result.cwd.exists()
    assert store.list_attempts(task.id) == []


def test_antigravity_cli_version_gate(tmp_path: Path) -> None:
    executable = tmp_path / "agy"
    executable.write_text("#!/bin/sh\nprintf '1.1.12\\n'\n")
    executable.chmod(0o700)

    assert resolve_antigravity_version(str(executable)) == (1, 1, 12)
    check_antigravity_version((1, 1, 6))
    with pytest.raises(RuntimeError, match="1.1.6 or newer"):
        check_antigravity_version((1, 1, 5))


def test_antigravity_result_event_parser() -> None:
    line = json.dumps(
        {"event": "result", "result": {"status": "SUCCESS", "response": "done"}}
    )

    assert _antigravity_terminal_result(line) == {"status": "SUCCESS", "response": "done"}
    assert _antigravity_terminal_result('{"event":"step_update"}') is None
    assert _antigravity_terminal_result("not-json") is None


def test_antigravity_policy_plugin_is_private_activation_scoped_and_removed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    plugin_dir = tmp_path / "plugin"

    with _antigravity_policy_plugin(workspace=workspace, plugin_dir=plugin_dir) as token:
        assert len(token) == 48
        plugin = json.loads((plugin_dir / "plugin.json").read_text())
        hooks = json.loads((plugin_dir / "hooks.json").read_text())
        command = hooks["agent-os-runtime-boundary"]["PreToolUse"][0]["hooks"][0][
            "command"
        ]
        assert plugin == {"name": "agent-os-runtime-boundary"}
        assert str(workspace) in command
        assert token in command
        assert (plugin_dir / "plugin.json").stat().st_mode & 0o777 == 0o600
        assert (plugin_dir / "hooks.json").stat().st_mode & 0o777 == 0o600

    assert not plugin_dir.exists()


def test_antigravity_policy_plugin_refuses_an_existing_path(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    marker = plugin_dir / "user-owned.txt"
    marker.write_text("preserve\n")

    with (
        pytest.raises(RuntimeError, match="already active"),
        _antigravity_policy_plugin(workspace=tmp_path, plugin_dir=plugin_dir),
    ):
        pass

    assert marker.read_text() == "preserve\n"


def test_omnigent_rejects_timeout_above_headless_runtime_limit(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Honest timeout",
        objective="Do not promise a bound the inner runtime cannot honor.",
        workspace=tmp_path,
        acceptance_criteria=["Oversized bounds fail before launch"],
    )

    with pytest.raises(ValueError, match="at most 1800 seconds"):
        run_task(
            store,
            task.id,
            tmp_path / "bundle",
            dry_run=True,
            omnigent_command="/fake/omnigent",
            timeout_seconds=1_801,
        )

    assert store.list_attempts(task.id) == []


def test_codex_review_rejects_prime_provider_option(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = store.create_task(
        title="Wrong runtime option",
        objective="Reject ambiguous coordinator routing.",
        workspace=tmp_path,
        acceptance_criteria=["The option fails loudly"],
    )

    with pytest.raises(ValueError, match="applies only to the Prime Agent runtime"):
        run_task(
            store,
            task.id,
            tmp_path / "bundle",
            dry_run=True,
            runtime="codex-review",
            provider="openai",
        )


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
    monkeypatch.setenv("AGENT_OS_OLLAMA_MODEL", "ollama/qwen3:0.6b")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/private-agent.sock")
    monkeypatch.setenv("UNRELATED_PRIVATE_TOKEN", "must-not-pass")

    environment = runtime_environment(providers={"openai"})

    assert environment["PATH"] == "/bin"
    assert environment["OPENAI_API_KEY"] == "openai-secret"
    assert environment["AGENT_OS_OLLAMA_MODEL"] == "ollama/qwen3:0.6b"
    assert environment["HARNESS_CODEX_DISABLE_NATIVE_TOOLS"] == "1"
    assert environment["HARNESS_CODEX_ENABLE_WEB_SEARCH"] == "0"
    assert "SSH_AUTH_SOCK" not in environment
    assert "UNRELATED_PRIVATE_TOKEN" not in environment


def test_runtime_environment_allows_explicit_extra_names(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_OS_ALLOWED_ENV", "CUSTOM_PROVIDER_KEY")
    monkeypatch.setenv("CUSTOM_PROVIDER_KEY", "allowed")

    assert runtime_environment(providers={"custom"})["CUSTOM_PROVIDER_KEY"] == "allowed"


def test_runtime_environment_cannot_readd_explicitly_blocked_credential(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_OS_ALLOWED_ENV", "ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-pass")

    environment = runtime_environment(providers={"anthropic"}, blocked_names={"ANTHROPIC_API_KEY"})

    assert "ANTHROPIC_API_KEY" not in environment


def test_transcript_file_is_private(tmp_path: Path) -> None:
    transcript = tmp_path / "attempt.log"
    with _open_private_text(transcript) as stream:
        stream.write("evidence")

    assert transcript.stat().st_mode & 0o777 == 0o600


def test_runtime_authentication_failure_is_not_treated_as_success() -> None:
    message = "Failed to authenticate: OAuth session expired and could not be refreshed\n"
    usage_limit = "You've hit your weekly limit · resets tomorrow\n"

    assert _runtime_failure(message) == message.strip()
    assert _runtime_failure(usage_limit) == usage_limit.strip()
    assert _runtime_failure("agent: implementation completed\n") is None


def test_omnigent_runtime_disables_ambient_opencode_skills(tmp_path: Path) -> None:
    fake_runtime = tmp_path / "fake-omnigent"
    fake_runtime.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$OPENCODE_DISABLE_CLAUDE_CODE\" > opencode-isolation.txt\n"
        "printf '%s\\n' \"$OPENCODE_CONFIG_DIR\" >> opencode-isolation.txt\n"
        "exit 0\n"
    )
    fake_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Isolate OpenCode",
        objective="Do not expose ambient host skills to a delegated model.",
        workspace=workspace,
        acceptance_criteria=["The skill tool is disabled"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "bundle",
        omnigent_command=str(fake_runtime),
    )

    assert result == 0
    disabled, config_dir = (workspace / "opencode-isolation.txt").read_text().splitlines()
    assert disabled == "1"
    config_path = Path(config_dir) / "opencode.json"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(config_path.read_text()) == {
        "$schema": "https://opencode.ai/config.json",
        "agent": {"build": {"tools": {"skill": False}}},
    }


@pytest.mark.parametrize(
    ("fatal_output", "summary_fragment"),
    [
        ("Failed to authenticate: expired test session", "expired test session"),
        ("You've hit your weekly limit · resets tomorrow", "weekly limit"),
    ],
)
def test_zero_exit_runtime_failure_fails_attempt(
    tmp_path: Path, fatal_output: str, summary_fragment: str
) -> None:
    fake_runtime = tmp_path / "fake-omnigent"
    fake_runtime.write_text(f'#!/bin/sh\nprintf "%s\\n" "{fatal_output}"\nexit 0\n')
    fake_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Fail closed",
        objective="Do not accept a misleading zero exit.",
        workspace=workspace,
        acceptance_criteria=["Authentication failure is recorded"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "bundle",
        omnigent_command=str(fake_runtime),
    )

    assert result == 1
    assert store.get_task(task.id).status is TaskStatus.FAILED
    attempt = store.list_attempts(task.id)[0]
    assert attempt.status.value == "failed"
    assert summary_fragment in attempt.summary


def test_codex_fallback_review_requires_prior_cross_provider_implementation(
    tmp_path: Path,
) -> None:
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Require implementation",
        objective="Do not review work that does not exist.",
        workspace=workspace,
        acceptance_criteria=["Codex review fails closed"],
    )

    with pytest.raises(ValueError, match="requires a successful implementation"):
        run_task(
            store,
            task.id,
            tmp_path / "bundle",
            runtime="codex-review",
            codex_command="/fake/codex",
        )


def test_failed_claude_capacity_can_use_antigravity_then_codex_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_codex_home = tmp_path / "source-codex-home"
    source_codex_home.mkdir()
    source_auth = source_codex_home / "auth.json"
    source_auth.write_text('{"test_token":"subscription-login"}\n')
    source_auth.chmod(0o600)
    monkeypatch.setenv("CODEX_HOME", str(source_codex_home))
    claude_runtime = tmp_path / "claude-at-capacity"
    claude_runtime.write_text(
        '#!/bin/sh\nprintf "%s\\n" "You\'ve hit your weekly limit"\nexit 0\n'
    )
    claude_runtime.chmod(0o700)
    antigravity_runtime = tmp_path / "agy"
    antigravity_runtime.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "workspace = Path(args[args.index('--add-dir') + 1])\n"
        "agent = Path.cwd() / '.agents/agents/agent-os-builder/agent.md'\n"
        "assert agent.is_file()\n"
        "assert os.environ['AGY_CLI_DISABLE_AUTO_UPDATE'] == 'true'\n"
        "assert os.environ['GIT_CONFIG_GLOBAL'] == os.devnull\n"
        "assert os.environ['GIT_CONFIG_NOSYSTEM'] == '1'\n"
        "assert os.environ['GIT_TERMINAL_PROMPT'] == '0'\n"
        "assert os.environ['XDG_CONFIG_HOME'] == str(Path.cwd() / 'xdg-config')\n"
        "(workspace / 'antigravity.txt').write_text('implemented\\n')\n"
        "print(json.dumps({'event': 'init', 'init': {'model': 'gemini-3.6-flash-high'}}))\n"
        "print(json.dumps({'event': 'result', 'result': {"
        "'status': 'SUCCESS', 'response': 'implemented'}}))\n"
    )
    antigravity_runtime.chmod(0o700)
    codex_runtime = tmp_path / "codex"
    codex_runtime.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "codex_home = Path(os.environ['CODEX_HOME'])\n"
        "assert codex_home.parent.name == os.environ['AGENT_OS_TASK_ID']\n"
        "assert codex_home.name.startswith('codex-home.')\n"
        "assert codex_home.stat().st_mode & 0o777 == 0o700\n"
        "auth = codex_home / 'auth.json'\n"
        "assert auth.stat().st_mode & 0o777 == 0o600\n"
        "assert json.loads(auth.read_text()) == {'test_token': 'subscription-login'}\n"
        "schema = Path(args[args.index('--output-schema') + 1])\n"
        "result = Path(args[args.index('--output-last-message') + 1])\n"
        "assert schema.is_file()\n"
        "payload = {'verdict': 'approve', 'summary': 'Independent review passed', "
        "'blocking_issues': [], 'non_blocking_issues': [], "
        "'evidence': ['workspace diff and acceptance evidence verified']}\n"
        "result.write_text(json.dumps(payload))\n"
        "print(json.dumps({'type': 'turn.completed'}))\n"
    )
    codex_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Switch to Antigravity",
        objective="Continue after Claude capacity is exhausted.",
        workspace=workspace,
        acceptance_criteria=["The same durable task records Google-backed work"],
    )

    assert (
        run_task(
            store,
            task.id,
            tmp_path / "bundle",
            omnigent_command=str(claude_runtime),
        )
        == 1
    )
    assert (
        run_task(
            store,
            task.id,
            tmp_path / "unused-bundle",
            runtime="antigravity",
            antigravity_command=str(antigravity_runtime),
            timeout_seconds=30,
        )
        == 0
    )

    assert (workspace / "antigravity.txt").read_text() == "implemented\n"
    assert store.get_task(task.id).status is TaskStatus.NEEDS_REVIEW
    attempts = store.list_attempts(task.id)
    assert [attempt.agent for attempt in attempts] == ["coordinator", "builder_antigravity"]
    assert attempts[1].kind.value == "implementation"
    assert attempts[1].provider == "google"
    assert attempts[1].model == "gemini-3.6-flash-high"
    assert attempts[1].status.value == "succeeded"
    assert len(attempts[1].evidence) == 2
    monkeypatch.setattr("agent_os.runner.collect_workspace_diff", lambda store, task_id: "diff")

    assert (
        run_task(
            store,
            task.id,
            tmp_path / "unused-bundle",
            runtime="codex-review",
            codex_command=str(codex_runtime),
            timeout_seconds=30,
        )
        == 0
    )
    assert store.get_task(task.id).status is TaskStatus.COMPLETED
    attempts = store.list_attempts(task.id)
    assert [attempt.agent for attempt in attempts] == [
        "coordinator",
        "builder_antigravity",
        "reviewer_codex",
    ]
    reviews = store.list_reviews(task.id)
    assert len(reviews) == 1
    assert reviews[0].attempt_id == attempts[1].id
    assert reviews[0].provider == "openai"
    assert reviews[0].verdict == "approve"
    review_result = (
        store.state_dir / "runtime" / "codex-review" / task.id / "review.result.json"
    )
    assert review_result.stat().st_mode & 0o777 == 0o600
    assert list((store.state_dir / "runtime" / "codex-review" / task.id).glob("codex-home.*")) == []
    assert source_auth.read_text() == '{"test_token":"subscription-login"}\n'


def test_antigravity_zero_exit_without_terminal_result_fails_closed(tmp_path: Path) -> None:
    antigravity_runtime = tmp_path / "agy"
    antigravity_runtime.write_text("#!/bin/sh\nprintf '%s\\n' '{\"event\":\"init\"}'\n")
    antigravity_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Require structured completion",
        objective="Reject an incomplete Antigravity stream.",
        workspace=workspace,
        acceptance_criteria=["Missing terminal evidence fails closed"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "unused-bundle",
        runtime="antigravity",
        antigravity_command=str(antigravity_runtime),
    )

    assert result == 1
    assert store.get_task(task.id).status is TaskStatus.FAILED
    attempt = store.list_attempts(task.id)[0]
    assert attempt.status.value == "failed"
    assert "without a terminal result event" in attempt.summary


def test_omnigent_runtime_timeout_terminates_and_records_failure(tmp_path: Path) -> None:
    fake_runtime = tmp_path / "slow-omnigent"
    fake_runtime.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import time\n"
        "from agent_os.store import TaskStore\n"
        "store = TaskStore(os.environ['AGENT_OS_STATE_DIR'])\n"
        "store.start_attempt(os.environ['AGENT_OS_TASK_ID'], agent='builder_ollama')\n"
        "time.sleep(30)\n"
    )
    fake_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Bound runtime",
        objective="Terminate a stalled process.",
        workspace=workspace,
        acceptance_criteria=["Timeout is recorded"],
    )

    with pytest.raises(TimeoutError, match="exceeded 1 seconds"):
        run_task(
            store,
            task.id,
            tmp_path / "bundle",
            omnigent_command=str(fake_runtime),
            timeout_seconds=1,
        )

    assert store.get_task(task.id).status is TaskStatus.FAILED
    attempts = store.list_attempts(task.id)
    assert [attempt.status.value for attempt in attempts] == ["failed", "failed"]
    assert "TimeoutError" in attempts[0].summary
    assert "terminated before child completion" in attempts[1].summary


def test_zero_exit_with_running_child_fails_closed(tmp_path: Path) -> None:
    fake_runtime = tmp_path / "incomplete-omnigent"
    fake_runtime.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from agent_os.store import TaskStore\n"
        "store = TaskStore(os.environ['AGENT_OS_STATE_DIR'])\n"
        "store.start_attempt(os.environ['AGENT_OS_TASK_ID'], agent='builder_ollama')\n"
    )
    fake_runtime.chmod(0o700)
    store = TaskStore(tmp_path / "state")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Fail incomplete coordination",
        objective="Do not leave a child attempt running after coordinator exit.",
        workspace=workspace,
        acceptance_criteria=["All attempts are terminal"],
    )

    result = run_task(
        store,
        task.id,
        tmp_path / "bundle",
        omnigent_command=str(fake_runtime),
    )

    assert result == 1
    assert store.get_task(task.id).status is TaskStatus.FAILED
    attempts = store.list_attempts(task.id)
    assert [attempt.status.value for attempt in attempts] == ["failed", "failed"]
    assert "running child attempts" in attempts[0].summary
    assert "exited before child completion" in attempts[1].summary
