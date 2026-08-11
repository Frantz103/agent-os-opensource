from __future__ import annotations

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
