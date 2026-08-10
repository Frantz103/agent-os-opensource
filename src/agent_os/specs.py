"""Compile NOOA role definitions into Omnigent multi-harness agent bundles."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_os.definitions import BuilderAgent, CoordinatorAgent, PlannerAgent, ReviewerAgent


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


VARIANTS = (
    AgentVariant("planner", PlannerAgent, "claude-sdk", "read_only", "Read-only task planner"),
    AgentVariant(
        "builder_claude",
        BuilderAgent,
        "claude-native",
        "read_write",
        "Claude Code implementation worker",
    ),
    AgentVariant(
        "builder_codex",
        BuilderAgent,
        "codex-native",
        "read_write",
        "Codex implementation worker",
    ),
    AgentVariant(
        "builder_opencode",
        BuilderAgent,
        "opencode-native",
        "read_write",
        "OpenCode implementation worker using a Doppler-provided OpenAI key",
        "openai/gpt-5.6-terra",
    ),
    AgentVariant(
        "builder_ollama",
        BuilderAgent,
        "opencode-native",
        "read_write",
        "Local Ollama implementation worker through OpenCode",
        "ollama/qwen3:14b",
    ),
    AgentVariant(
        "reviewer_claude",
        ReviewerAgent,
        "claude-native",
        "read_only",
        "Read-only Claude Code reviewer",
    ),
    AgentVariant(
        "reviewer_codex",
        ReviewerAgent,
        "codex-native",
        "read_only",
        "Read-only Codex reviewer",
    ),
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
                    "arguments": {"gate_pushes": False},
                },
            }
        },
    }


def _function_tools() -> dict[str, Any]:
    def string_array() -> dict[str, Any]:
        return {"type": "array", "items": {"type": "string"}}

    return {
        "get_task_context": {
            "type": "function",
            "description": "Load the authoritative task contract and prior evidence.",
            "callable": "agent_os.tools.get_task_context",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        },
        "start_attempt": {
            "type": "function",
            "description": "Create an attributed attempt before child-agent dispatch.",
            "callable": "agent_os.tools.start_attempt",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "agent": {"type": "string"},
                    "harness": {"type": "string"},
                },
                "required": ["task_id", "agent", "harness"],
            },
        },
        "finish_attempt": {
            "type": "function",
            "description": "Finalize a child attempt with status, summary, and evidence.",
            "callable": "agent_os.tools.finish_attempt",
            "parameters": {
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["succeeded", "failed", "cancelled"],
                    },
                    "summary": {"type": "string"},
                    "evidence": string_array(),
                },
                "required": ["attempt_id", "status", "summary"],
            },
        },
        "record_review": {
            "type": "function",
            "description": "Persist an independent review verdict and its evidence.",
            "callable": "agent_os.tools.record_review",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "attempt_id": {"type": "string"},
                    "reviewer": {"type": "string"},
                    "harness": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["approve", "request_changes", "blocked"],
                    },
                    "summary": {"type": "string"},
                    "issues": string_array(),
                    "evidence": string_array(),
                },
                "required": ["task_id", "reviewer", "harness", "verdict", "summary"],
            },
        },
        "complete_task": {
            "type": "function",
            "description": "Close a reviewed task with a truthful terminal outcome.",
            "callable": "agent_os.tools.complete_task",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["completed", "blocked", "failed"],
                    },
                    "summary": {"type": "string"},
                },
                "required": ["task_id", "status", "summary"],
            },
        },
    }


def coordinator_config() -> dict[str, Any]:
    tools: dict[str, Any] = {"agents": [variant.name for variant in VARIANTS]}
    tools.update(_function_tools())
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


def expected_specs(bundle_dir: Path | str) -> dict[Path, str]:
    bundle = Path(bundle_dir)
    specs = {bundle / "config.yaml": _dump(coordinator_config())}
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
    """Ask Omnigent's own loader to validate the emitted bundle."""
    from omnigent.spec import load

    load(Path(bundle_dir).resolve())
