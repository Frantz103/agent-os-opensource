"""Registered execution identities used for attribution and review independence."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Literal

from agent_os.models import AttemptKind

ExecutionRole = Literal["coordinator", "planner", "builder", "reviewer"]


@dataclass(frozen=True)
class ExecutionIdentity:
    agent: str
    role: ExecutionRole
    harness: str
    provider: str | None
    model: str | None = None
    kind: AttemptKind = AttemptKind.IMPLEMENTATION


def provider_from_model(model: str) -> str:
    provider, separator, _ = model.partition("/")
    if not separator or not provider.strip():
        raise ValueError("model must use PROVIDER/MODEL format")
    normalized = provider.strip().lower().replace("_", "-")
    aliases = {
        "claude": "anthropic",
        "codex": "openai",
        "local": "ollama",
    }
    return aliases.get(normalized, normalized)


_PROFILES: dict[str, ExecutionIdentity] = {
    "coordinator": ExecutionIdentity(
        agent="coordinator",
        role="coordinator",
        harness="claude-sdk",
        provider="anthropic",
        kind=AttemptKind.COORDINATOR,
    ),
    "prime_coordinator": ExecutionIdentity(
        agent="prime_coordinator",
        role="builder",
        harness="prime-agent",
        provider=None,
    ),
    "planner": ExecutionIdentity(
        agent="planner",
        role="planner",
        harness="claude-sdk",
        provider="anthropic",
        kind=AttemptKind.COORDINATOR,
    ),
    "builder_claude": ExecutionIdentity(
        agent="builder_claude",
        role="builder",
        harness="claude-native",
        provider="anthropic",
    ),
    "builder_codex": ExecutionIdentity(
        agent="builder_codex",
        role="builder",
        harness="codex-native",
        provider="openai",
    ),
    "builder_opencode": ExecutionIdentity(
        agent="builder_opencode",
        role="builder",
        harness="opencode-native",
        provider="openai",
        model="openai/gpt-5",
    ),
    "builder_ollama": ExecutionIdentity(
        agent="builder_ollama",
        role="builder",
        harness="opencode-native",
        provider="ollama",
        model="ollama/qwen3:14b",
    ),
    "reviewer_claude": ExecutionIdentity(
        agent="reviewer_claude",
        role="reviewer",
        harness="claude-native",
        provider="anthropic",
        kind=AttemptKind.COORDINATOR,
    ),
    "reviewer_codex": ExecutionIdentity(
        agent="reviewer_codex",
        role="reviewer",
        harness="codex-native",
        provider="openai",
        kind=AttemptKind.COORDINATOR,
    ),
}


def execution_identity(
    agent: str,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ExecutionIdentity:
    """Resolve an allowlisted agent and its concrete intelligence provider."""
    try:
        identity = _PROFILES[agent]
    except KeyError as error:
        raise ValueError(f"unknown execution agent: {agent}") from error

    if agent == "builder_opencode":
        configured_model = model or os.environ.get("AGENT_OS_OPENCODE_MODEL") or identity.model
        assert configured_model is not None
        identity = replace(
            identity,
            model=configured_model,
            provider=provider_from_model(configured_model),
        )
    elif agent == "builder_ollama":
        configured_model = model or os.environ.get("AGENT_OS_OLLAMA_MODEL") or identity.model
        assert configured_model is not None
        identity = replace(
            identity,
            model=configured_model,
            provider=provider_from_model(configured_model),
        )
    elif model is not None:
        identity = replace(identity, model=model)

    if provider is not None:
        normalized = provider.strip().lower().replace("_", "-")
        if identity.provider is not None and normalized != identity.provider:
            raise ValueError(
                f"provider {normalized!r} does not match registered provider "
                f"{identity.provider!r} for {agent}"
            )
        identity = replace(identity, provider=normalized)

    if identity.provider is None:
        raise ValueError(f"provider is required for {agent}")
    return identity


def execution_profiles() -> tuple[ExecutionIdentity, ...]:
    return tuple(execution_identity(name) for name in _PROFILES if name != "prime_coordinator")
