"""Registered execution identities used for attribution and review independence."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Literal

from agent_os.models import AttemptKind

ExecutionRole = Literal["coordinator", "planner", "builder", "reviewer"]

CODEX_BUILDER_MODEL = "gpt-5.6-sol"
CODEX_REVIEWER_MODEL = "gpt-5.6-sol"
ANTIGRAVITY_MODEL = "gemini-3.6-flash-high"


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


def _reject_contradictory_model(identity: ExecutionIdentity) -> None:
    """Refuse a model whose named provider contradicts the resolved identity.

    Attempt provenance and the review-independence check both read the recorded
    provider, so a model that names a different one must not be stored beside it.
    A bare model name belongs to the harness's own namespace and stays the
    operator's responsibility; a ``PROVIDER/MODEL`` name is checkable, so a
    mismatch is refused before it becomes evidence.
    """
    model = identity.model
    if model is None or identity.provider is None or "/" not in model:
        return
    named = provider_from_model(model)
    if named != identity.provider:
        raise ValueError(
            f"model {model!r} names provider {named!r}, which contradicts the "
            f"{identity.provider!r} provider recorded for {identity.agent}"
        )


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
        harness="claude-sdk",
        provider="anthropic",
    ),
    "builder_codex": ExecutionIdentity(
        agent="builder_codex",
        role="builder",
        harness="codex",
        provider="openai",
        model=CODEX_BUILDER_MODEL,
    ),
    "builder_antigravity": ExecutionIdentity(
        agent="builder_antigravity",
        role="builder",
        harness="antigravity-cli",
        provider="google",
        model=ANTIGRAVITY_MODEL,
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
        harness="claude-sdk",
        provider="anthropic",
        kind=AttemptKind.COORDINATOR,
    ),
    "reviewer_codex": ExecutionIdentity(
        agent="reviewer_codex",
        role="reviewer",
        harness="codex",
        provider="openai",
        model=CODEX_REVIEWER_MODEL,
        kind=AttemptKind.COORDINATOR,
    ),
}

_MODEL_ENV_BY_AGENT = {
    "builder_codex": "AGENT_OS_CODEX_BUILDER_MODEL",
    "reviewer_codex": "AGENT_OS_CODEX_REVIEWER_MODEL",
    "builder_antigravity": "AGENT_OS_ANTIGRAVITY_MODEL",
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

    model_env = _MODEL_ENV_BY_AGENT.get(agent)
    if model_env is not None:
        configured_model = model or os.environ.get(model_env) or identity.model
        assert configured_model is not None
        identity = replace(identity, model=configured_model)
    elif agent == "builder_opencode":
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
    _reject_contradictory_model(identity)
    return identity


def execution_profiles() -> tuple[ExecutionIdentity, ...]:
    return tuple(execution_identity(name) for name in _PROFILES if name != "prime_coordinator")
