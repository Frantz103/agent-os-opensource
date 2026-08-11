"""Compile NOOA role definitions into Omnigent multi-harness agent bundles."""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_os.definitions import BuilderAgent, CoordinatorAgent, PlannerAgent, ReviewerAgent
from agent_os.execution import execution_identity

LEDGER_TOOL_NAMES = {
    "get_task_context",
    "start_attempt",
    "finish_attempt",
    "record_review",
    "complete_task",
}


class LiteralString(str):
    """Marker for readable YAML block scalars."""


class AgentOSDumper(yaml.SafeDumper):
    pass


AgentOSDumper.add_representer(
    LiteralString,
    lambda dumper, data: dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|"),
)


@dataclass(frozen=True)
class AgentVariant:
    name: str
    definition: type
    harness: str
    access: str
    description: str
    model: str | None = None
    provider: str | None = None


def _variant(name: str, definition: type, access: str, description: str) -> AgentVariant:
    identity = execution_identity(name)
    return AgentVariant(
        name=name,
        definition=definition,
        harness=identity.harness,
        access=access,
        description=description,
        model=identity.model,
        provider=identity.provider,
    )


VARIANTS = (
    _variant("planner", PlannerAgent, "read_only", "Read-only task planner"),
    _variant(
        "builder_claude", BuilderAgent, "read_write", "Claude Code implementation worker"
    ),
    _variant("builder_codex", BuilderAgent, "read_write", "Codex implementation worker"),
    _variant(
        "builder_opencode",
        BuilderAgent,
        "read_write",
        "OpenCode implementation worker using the configured cloud provider",
    ),
    _variant(
        "builder_ollama",
        BuilderAgent,
        "read_write",
        "Local Ollama implementation worker through OpenCode",
    ),
    _variant(
        "reviewer_claude", ReviewerAgent, "read_only", "Read-only Claude Code reviewer"
    ),
    _variant("reviewer_codex", ReviewerAgent, "read_only", "Read-only Codex reviewer"),
)


def _executor(harness: str, model: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"harness": harness}
    if harness == "claude-native":
        config["permission_mode"] = "auto"
    if harness == "codex-native":
        config["yolo"] = True
    executor: dict[str, Any] = {"type": "omnigent", "config": config}
    if model is not None:
        executor["model"] = model
    return executor


def _os_env(access: str) -> dict[str, Any]:
    # Omitting type makes Omnigent choose its platform backend at parse time
    # (darwin_seatbelt, linux_bwrap, or windows_jobobject).
    sandbox: dict[str, Any] = {"allow_network": False}
    sandbox["write_paths"] = ["."] if access == "read_write" else []
    return {"type": "caller_process", "cwd": ".", "sandbox": sandbox}


def _guardrails() -> dict[str, Any]:
    return {
        "ask_timeout": 86400,
        "policies": {
            "blast_radius": {
                "type": "function",
                "on": ["tool_call"],
                "function": {
                    "path": "omnigent.inner.nessie.policies.blast_radius",
                    "arguments": {"gate_pushes": True, "risky_action": "DENY"},
                },
            }
        },
    }


def coordinator_config() -> dict[str, Any]:
    tools: dict[str, Any] = {"agents": [variant.name for variant in VARIANTS]}
    return {
        "spec_version": 1,
        "name": "agent_os_coordinator",
        "description": "NOOA-defined coordinator using Omnigent child sessions and policies",
        "executor": _executor("claude-sdk"),
        "prompt": LiteralString(inspect.getdoc(CoordinatorAgent) or ""),
        "async": True,
        "cancellable": True,
        "tools": tools,
        "guardrails": {
            "ask_timeout": 86400,
            "policies": {
                "spawn_bounds": {
                    "type": "function",
                    "function": {
                        "path": "omnigent.inner.nessie.policies.spawn_bounds",
                        "arguments": {
                            "max_dispatches_per_turn": 4,
                            "dispatch_tools": ["sys_session_send"],
                        },
                    },
                },
                "headless_subagent_purpose_guard": {
                    "type": "function",
                    "function": {
                        "path": "omnigent.inner.nessie.policies.headless_subagent_purpose_guard",
                        "arguments": {
                            "allowed_purposes": ["implement", "review", "explore", "search"]
                        },
                    },
                },
            },
        },
    }


def variant_config(variant: AgentVariant) -> dict[str, Any]:
    prompt = inspect.getdoc(variant.definition) or ""
    return {
        "spec_version": 1,
        "name": variant.name,
        "description": variant.description,
        "executor": _executor(variant.harness, variant.model),
        "prompt": LiteralString(
            f"You are `{variant.name}`, running through the "
            f"`{variant.harness}` harness.\n\n{prompt}"
        ),
        "async": True,
        "cancellable": True,
        "os_env": _os_env(variant.access),
        "guardrails": _guardrails(),
    }


def _dump(data: dict[str, Any]) -> str:
    body = yaml.dump(
        data,
        Dumper=AgentOSDumper,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    return "# Generated from src/agent_os/definitions.py; do not edit by hand.\n" + body


def _ledger_tools_source() -> str:
    return textwrap.dedent(
        '''\
        """Generated Agent OS ledger tools for Omnigent runtime discovery."""

        from omnigent_client.tools import tool

        from agent_os import tools as ledger


        @tool
        def get_task_context(task_id: str) -> str:
            """Load the authoritative task contract and prior evidence."""
            return ledger.get_task_context(task_id)


        @tool
        def start_attempt(task_id: str, agent: str, work_item: str = "primary") -> dict[str, str]:
            """Create an attributed attempt before child-agent dispatch."""
            return ledger.start_attempt(task_id, agent, work_item)


        @tool
        def finish_attempt(
            attempt_id: str,
            status: str,
            summary: str,
            evidence: list[str] | None = None,
        ) -> dict[str, str]:
            """Finalize a child attempt with status, summary, and evidence."""
            return ledger.finish_attempt(attempt_id, status, summary, evidence)


        @tool
        def record_review(
            task_id: str,
            attempt_id: str,
            reviewer: str,
            verdict: str,
            summary: str,
            issues: list[str] | None = None,
            evidence: list[str] | None = None,
        ) -> dict[str, str]:
            """Persist an independent review verdict and its evidence."""
            return ledger.record_review(
                task_id,
                reviewer,
                verdict,
                summary,
                attempt_id,
                issues,
                evidence,
            )


        @tool
        def complete_task(task_id: str, status: str, summary: str) -> dict[str, str]:
            """Close a reviewed task with a truthful terminal outcome."""
            return ledger.complete_task(task_id, status, summary)
        '''
    )


def expected_specs(bundle_dir: Path | str) -> dict[Path, str]:
    bundle = Path(bundle_dir)
    specs = {
        bundle / "config.yaml": _dump(coordinator_config()),
        bundle / "tools" / "python" / "task_ledger.py": _ledger_tools_source(),
    }
    for variant in VARIANTS:
        specs[bundle / "agents" / variant.name / "config.yaml"] = _dump(variant_config(variant))
    return specs


def sync_specs(bundle_dir: Path | str) -> list[Path]:
    written: list[Path] = []
    for path, content in expected_specs(bundle_dir).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
            written.append(path)
    return written


def check_specs(bundle_dir: Path | str) -> list[Path]:
    drifted: list[Path] = []
    for path, content in expected_specs(bundle_dir).items():
        if not path.exists() or path.read_text() != content:
            drifted.append(path)
    return drifted


def validate_bundle(bundle_dir: Path | str) -> None:
    """Validate the bundle and confirm every ledger tool reaches the runtime registry."""
    from omnigent.spec import load
    from omnigent.tools.manager import ToolManager

    bundle = Path(bundle_dir).resolve()
    spec = load(bundle)
    manager = ToolManager(spec, workdir=bundle, sandbox_enabled=False)
    missing = LEDGER_TOOL_NAMES.difference(manager.get_tool_names())
    if missing:
        raise RuntimeError(f"generated bundle is missing runtime ledger tools: {sorted(missing)}")
