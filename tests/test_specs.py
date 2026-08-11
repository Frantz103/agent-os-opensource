from __future__ import annotations

from pathlib import Path

import yaml

from agent_os.specs import (
    LEDGER_TOOL_NAMES,
    VARIANTS,
    check_specs,
    sync_specs,
    validate_bundle,
)


def test_compiler_emits_multi_harness_bundle_from_definitions(tmp_path: Path) -> None:
    bundle = tmp_path / "coordinator"
    written = sync_specs(bundle)

    assert len(written) == 1 + len(LEDGER_TOOL_NAMES) + len(VARIANTS)
    assert check_specs(bundle) == []

    root = yaml.safe_load((bundle / "config.yaml").read_text())
    assert root["executor"]["config"]["harness"] == "claude-sdk"
    assert root["skills"] == "none"
    assert root["os_env"]["sandbox"]["write_paths"] == []
    assert root["tools"]["agents"] == [variant.name for variant in VARIANTS]
    assert "record_review" not in root["tools"]
    for name in LEDGER_TOOL_NAMES:
        ledger_source = (bundle / "tools" / "python" / f"{name}.py").read_text()
        assert f"def {name}(" in ledger_source

    harnesses = {}
    models = {}
    sandboxes = {}
    for variant in VARIANTS:
        path = bundle / "agents" / variant.name / "config.yaml"
        config = yaml.safe_load(path.read_text())
        harnesses[variant.name] = config["executor"]["config"]["harness"]
        models[variant.name] = config["executor"].get("model")
        sandboxes[variant.name] = config["os_env"]["sandbox"]
        assert config["skills"] == "none"
        assert config["prompt"].strip()
        assert "type" not in config["os_env"]["sandbox"]
    assert harnesses["builder_claude"] == "claude-sdk"
    assert sandboxes["builder_claude"]["allow_network"] is False
    assert "egress_rules" not in sandboxes["builder_claude"]
    assert harnesses["planner"] == "claude-sdk"
    assert harnesses["builder_codex"] == "codex"
    assert models["builder_codex"] == "gpt-5.6-sol"
    assert harnesses["builder_opencode"] == "opencode-native"
    assert models["builder_opencode"] == "openai/gpt-5"
    assert harnesses["builder_ollama"] == "opencode-native"
    assert models["builder_ollama"] == "ollama/qwen3:14b"
    assert harnesses["reviewer_codex"] == "codex"
    assert models["reviewer_codex"] == "gpt-5.6-sol"
    assert "egress_rules" not in sandboxes["builder_ollama"]


def test_omnigent_accepts_generated_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    validate_bundle(bundle)


def test_check_detects_hand_edited_generated_file(tmp_path: Path) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    target = bundle / "agents" / "planner" / "config.yaml"
    target.write_text(target.read_text() + "\n# drift\n")
    assert target in check_specs(bundle)
