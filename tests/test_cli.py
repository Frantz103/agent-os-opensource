from __future__ import annotations

from pathlib import Path

from agent_os import cli
from agent_os.specs import sync_specs


def test_doctor_fails_loudly_for_incompatible_installed_opencode(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    bundle = tmp_path / "coordinator"
    sync_specs(bundle)
    monkeypatch.setattr(cli, "find_omnigent_cli", lambda: "/bin/omnigent")
    monkeypatch.setattr(cli, "find_prime_agent_cli", lambda: None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli, "resolve_opencode_version", lambda path: "1.18.4")

    def reject_version(version: str) -> None:
        raise cli.OpenCodeVersionError(f"unsupported {version}")

    monkeypatch.setattr(cli, "check_opencode_version", reject_version)

    assert cli._doctor(bundle) == 1
    assert "opencode   INCOMPATIBLE unsupported 1.18.4" in capsys.readouterr().out
