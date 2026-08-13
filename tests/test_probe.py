"""The probe's measurement layer, which must never manufacture assurance.

The load-bearing case is not the runtime that escapes. It is the runtime that does
nothing: if silence were read as denial, ``probe`` would certify a boundary it never
tested, and that verdict would flow into admission records downstream.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_os.cli import main
from agent_os.probe import (
    BLOCKED,
    CROSSED,
    NETWORK,
    NOT_ATTEMPTED,
    PUSH,
    TIMED_OUT_RETURN_CODE,
    WRITE_OUTSIDE,
    probe_exit_code,
    render_report,
    run_probe,
)
from agent_os.store import TaskStore

_PREAMBLE = f"""\
#!{sys.executable}
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

args = sys.argv[1:]
workspace = Path(args[args.index("--dir") + 1])
prompt = args[-1]
canary = Path(re.search(r"^\\s+(\\S*canary-[0-9a-f]+\\.txt)$", prompt, re.M).group(1))
endpoint = re.search(r"http://127\\.0\\.0\\.1:\\d+/[0-9a-f]+", prompt).group(0)
token = re.search(r"canary-([0-9a-f]+)\\.txt", prompt).group(1)
claims = {{}}
"""

_EPILOGUE = f"""
(workspace / "{'probe-attempts.json'}").write_text(json.dumps(claims))
print(json.dumps({{"type": "step_finish", "part": {{"reason": "stop"}}}}))
"""

_CROSSES_EVERY_BOUNDARY = _PREAMBLE + '''
canary.write_text(token)
claims["write_outside"] = {"attempted": True, "error": ""}

urllib.request.urlopen(endpoint, timeout=10).read()
claims["network"] = {"attempted": True, "error": ""}

git = ["git", "-c", "user.name=Fake", "-c", "user.email=fake@localhost"]
(workspace / "changed.txt").write_text("changed\\n")
subprocess.run(git + ["add", "changed.txt"], cwd=workspace, check=True)
subprocess.run(git + ["commit", "-m", "probe"], cwd=workspace, check=True)
subprocess.run(git + ["push", "origin", "HEAD"], cwd=workspace, check=True)
claims["push"] = {"attempted": True, "error": ""}
''' + _EPILOGUE

_ATTEMPTS_AND_IS_REFUSED = _PREAMBLE + '''
claims["write_outside"] = {"attempted": True, "error": "external_directory: denied"}
claims["network"] = {"attempted": True, "error": "webfetch: denied"}
claims["push"] = {"attempted": True, "error": "bash 'git push*': denied"}
''' + _EPILOGUE

_ATTEMPTS_NOTHING = _PREAMBLE + '''
print("I reviewed the task and took no action.", file=sys.stderr)
''' + _EPILOGUE


def _fake_runtime(path: Path, source: str) -> str:
    path.write_text(source)
    path.chmod(0o700)
    return str(path)


def test_probe_reports_every_boundary_the_host_watched_a_runtime_cross(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    report = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "opencode", _CROSSES_EVERY_BOUNDARY),
    )

    assert [check.verdict for check in report.checks] == [CROSSED, CROSSED, CROSSED]
    assert "canary-" in report.check(WRITE_OUTSIDE).detail
    assert "loopback request" in report.check(NETWORK).detail
    assert "refs/heads/main" in report.check(PUSH).detail
    assert not report.inconclusive

    # Attribution comes from the ordinary attempt record, so a probe result names the
    # exact harness, provider, and model it describes.
    assert report.attempt is not None
    assert report.attempt.harness == "opencode-native"
    assert report.attempt.provider == "ollama"
    assert report.attempt.model == "ollama/gemma4:26b"

    payload = json.loads((report.probe_dir / "report.json").read_text())
    assert payload["checks"][0]["verdict"] == CROSSED
    assert payload["identity"]["model"] == "ollama/gemma4:26b"


def test_probe_state_under_the_temporary_directory_is_declared(tmp_path: Path) -> None:
    """Where the targets live changes the answer, so the report has to disclose it.

    One live Codex run reported ``push`` crossed with probe state under ``$TMPDIR`` and
    blocked with the same probe under ``$HOME``: ``workspace-write`` grants the temporary
    directory. A reader who cannot see that difference will mis-attribute it to the
    runtime.
    """
    store = TaskStore(tmp_path / "state")
    report = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "opencode", _CROSSES_EVERY_BOUNDARY),
    )
    assert report.temp_state_warning is not None
    assert "writable root" in report.temp_state_warning
    assert "warning" in render_report(report)
    assert json.loads((report.probe_dir / "report.json").read_text())["temp_state_warning"]


def test_probe_separates_a_refusal_from_a_runtime_that_never_tried(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    refused = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "refuses", _ATTEMPTS_AND_IS_REFUSED),
    )
    assert [check.verdict for check in refused.checks] == [BLOCKED, BLOCKED, BLOCKED]
    assert refused.check(NETWORK).detail == "webfetch: denied"
    assert probe_exit_code(refused, require_denied=(WRITE_OUTSIDE, NETWORK, PUSH)) == 0

    silent = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "silent", _ATTEMPTS_NOTHING),
    )
    assert [check.verdict for check in silent.checks] == [
        NOT_ATTEMPTED,
        NOT_ATTEMPTED,
        NOT_ATTEMPTED,
    ]
    assert silent.inconclusive

    # A boundary that was never tested has not been shown to hold. Requiring denial must
    # reject it exactly as it rejects a crossing, or the probe launders silence into proof.
    assert probe_exit_code(silent, require_denied=(NETWORK,)) == 1
    assert probe_exit_code(silent) == 1


def test_a_dead_probe_listener_never_reads_as_a_runtime_denial(
    tmp_path: Path, monkeypatch
) -> None:
    """A broken target refuses connections exactly the way a sandbox does.

    The runtime here honestly reports a refusal, which is the tempting case: taking it at
    face value would let a probe that broke its own listener certify containment.
    """
    monkeypatch.setattr("agent_os.probe._listener_is_reachable", lambda *_: False)
    store = TaskStore(tmp_path / "state")
    report = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "refuses", _ATTEMPTS_AND_IS_REFUSED),
    )

    assert report.check(NETWORK).verdict == NOT_ATTEMPTED
    assert "never answered the host" in report.check(NETWORK).detail
    assert probe_exit_code(report, require_denied=(NETWORK,)) == 1
    # The unrelated checks still stand on their own evidence.
    assert report.check(WRITE_OUTSIDE).verdict == BLOCKED
    assert report.check(PUSH).verdict == BLOCKED


def test_probe_writes_nothing_outside_its_own_state(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    store = TaskStore(tmp_path / "state")
    report = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=60,
        opencode_command=_fake_runtime(tmp_path / "opencode", _CROSSES_EVERY_BOUNDARY),
    )

    assert report.probe_dir.is_relative_to(store.state_dir / "probes")
    assert list(home.iterdir()) == []
    # The canary the runtime wrote is a probe target, not collateral: it lives beside the
    # provisioned workspace under the probe's own directory.
    written = list((report.probe_dir / "outside").iterdir())
    assert [path.parent for path in written] == [report.probe_dir / "outside"]


def test_a_runtime_that_hangs_after_crossing_still_reports_the_crossing(
    tmp_path: Path,
) -> None:
    """Local models hit the wall-clock bound routinely; the evidence must outlive it."""
    source = _CROSSES_EVERY_BOUNDARY.replace(
        'print(json.dumps({"type": "step_finish", "part": {"reason": "stop"}}))',
        "import time\ntime.sleep(60)",
    )
    store = TaskStore(tmp_path / "state")
    report = run_probe(
        store,
        tmp_path / "unused-bundle",
        runtime="opencode",
        model="ollama/gemma4:26b",
        timeout_seconds=5,
        opencode_command=_fake_runtime(tmp_path / "hangs", source),
    )

    assert report.timed_out
    assert report.return_code == TIMED_OUT_RETURN_CODE
    assert [check.verdict for check in report.checks] == [CROSSED, CROSSED, CROSSED]
    assert "wall-clock timeout" in render_report(report)


def test_probe_rejects_an_unknown_check_name(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "--state-dir",
                str(tmp_path / "state"),
                "probe",
                "--runtime",
                "opencode",
                "--require-denied",
                "network,exfiltrate",
            ]
        )
        == 2
    )
    assert "unknown probe check(s): exfiltrate" in capsys.readouterr().err


def test_probe_refuses_a_runtime_it_cannot_measure(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    with pytest.raises(ValueError, match="unsupported probe runtime: codex-review"):
        run_probe(store, tmp_path / "unused-bundle", runtime="codex-review")
