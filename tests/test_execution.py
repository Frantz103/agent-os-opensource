from __future__ import annotations

import pytest

from agent_os.execution import execution_identity


def test_codex_roles_use_current_tiered_defaults(monkeypatch) -> None:
    for name in (
        "AGENT_OS_CODEX_BUILDER_MODEL",
        "AGENT_OS_CODEX_REVIEWER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    assert execution_identity("builder_codex").model == "gpt-5.6-sol"
    assert execution_identity("reviewer_codex").model == "gpt-5.6-sol"


def test_codex_role_model_can_be_overridden_with_current_family(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_OS_CODEX_BUILDER_MODEL", "gpt-5.6-luna")

    identity = execution_identity("builder_codex")

    assert identity.model == "gpt-5.6-luna"
    assert identity.provider == "openai"


def test_antigravity_cli_uses_current_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_OS_ANTIGRAVITY_MODEL", raising=False)
    assert execution_identity("builder_antigravity").model == "gemini-3.6-flash-high"

    monkeypatch.setenv("AGENT_OS_ANTIGRAVITY_MODEL", "gemini-3.5-flash-high")
    identity = execution_identity("builder_antigravity")

    assert identity.harness == "antigravity-cli"
    assert identity.provider == "google"
    assert identity.model == "gemini-3.5-flash-high"


def test_model_naming_a_different_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="contradicts the 'anthropic' provider"):
        execution_identity("builder_claude", model="openai/gpt-5")


def test_reviewer_model_naming_a_different_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="contradicts the 'anthropic' provider"):
        execution_identity("reviewer_claude", model="google/gemini-3-pro")


def test_provider_qualified_model_matching_its_harness_is_accepted() -> None:
    identity = execution_identity("builder_ollama", model="ollama/gemma4:26b")
    assert identity.provider == "ollama"
    assert identity.model == "ollama/gemma4:26b"


def test_bare_model_name_stays_the_harness_namespace() -> None:
    """A bare name is not provider-qualified, so it cannot be checked here.

    This records the deliberate limit of the contradiction check: only a
    PROVIDER/MODEL name carries a claim that can be compared.
    """
    identity = execution_identity("reviewer_codex", model="gpt-5.6-terra")
    assert identity.provider == "openai"
    assert identity.model == "gpt-5.6-terra"
