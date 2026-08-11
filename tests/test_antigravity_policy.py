from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from agent_os.antigravity_policy import evaluate, main


def _call(name: str, **arguments: str) -> dict[str, object]:
    return {"toolCall": {"name": name, "args": arguments}}


def test_policy_allows_bounded_workspace_work(tmp_path: Path) -> None:
    target = tmp_path / "src" / "module.py"

    assert evaluate(_call("view_file", AbsolutePath=str(target)), tmp_path)["decision"] == "allow"
    assert (
        evaluate(
            _call("run_command", CommandLine="pytest tests", Cwd=str(tmp_path)), tmp_path
        )["decision"]
        == "allow"
    )


@pytest.mark.parametrize("tool", ["search_web", "read_url_content", "call_mcp_tool"])
def test_policy_denies_network_and_ambient_tools(tmp_path: Path, tool: str) -> None:
    decision = evaluate(_call(tool), tmp_path)

    assert decision["decision"] == "deny"
    assert "outside" in decision["reason"]


@pytest.mark.parametrize(
    "command", ["git push origin main", "curl https://example.com", "rm -rf ."]
)
def test_policy_denies_outward_or_destructive_commands(tmp_path: Path, command: str) -> None:
    decision = evaluate(_call("run_command", CommandLine=command, Cwd=str(tmp_path)), tmp_path)

    assert decision == {"decision": "deny", "reason": "outward or destructive command denied"}


def test_policy_denies_paths_outside_workspace(tmp_path: Path) -> None:
    decision = evaluate(_call("view_file", AbsolutePath="/etc/passwd"), tmp_path)

    assert decision["decision"] == "deny"
    assert "outside the declared" in decision["reason"]


def test_inactive_global_hook_is_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("AGENT_OS_ANTIGRAVITY_POLICY_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["policy", str(tmp_path), "expected"])

    assert main() == 0
    assert capsys.readouterr().out == ""


def test_active_global_hook_emits_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AGENT_OS_ANTIGRAVITY_POLICY_TOKEN", "expected")
    monkeypatch.setattr(sys, "argv", ["policy", str(tmp_path), "expected"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_call("search_web"))))

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "deny"
