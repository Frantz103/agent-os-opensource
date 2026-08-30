from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_os import http_service
from agent_os import runner as runner_module
from agent_os.http_service import (
    ARTIFACT_DIRECTORY,
    SERVICE_TOKEN_ENV,
    _cost_projection,
    create_app,
    main,
)
from agent_os.models import (
    AttemptRecord,
    AttemptStatus,
    AttemptUsage,
    TaskSpec,
    TaskStatus,
    utc_now,
)
from agent_os.store import TaskStore

TOKEN = "test-local-bearer-token"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}


class FakeRunner:
    def __init__(self, *, released: bool = False, include_cost: bool = True) -> None:
        self.started = Event()
        self.release = Event()
        if released:
            self.release.set()
        self.include_cost = include_cost
        self.calls = 0
        self._lock = Lock()

    def __call__(
        self,
        store: TaskStore,
        task_id: str,
        _bundle_dir: Path,
        *,
        runtime: str,
        timeout_seconds: int,
        cancel_event: Event,
    ) -> int:
        assert runtime == "codex"
        assert timeout_seconds == 30
        with self._lock:
            self.calls += 1
        if cancel_event.is_set():
            store.cancel_task(task_id, reason="cancelled before fake execution")
            return 130
        store.transition(task_id, TaskStatus.RUNNING, reason="fake execution started")
        attempt = store.start_attempt(task_id, agent="builder_codex")
        self.started.set()
        while not self.release.wait(0.01):
            if cancel_event.is_set():
                store.finish_attempt(
                    attempt.id,
                    status=AttemptStatus.CANCELLED,
                    summary="fake execution cancelled",
                )
                store.cancel_task(task_id, reason="caller requested cancellation")
                return 130

        task = store.get_task(task_id)
        artifact = task.workspace / ARTIFACT_DIRECTORY / "result.txt"
        artifact.write_text("real artifact\n")
        transcript_dir = store.state_dir / "transcripts" / task_id
        transcript_dir.mkdir(parents=True, mode=0o700)
        transcript = transcript_dir / f"{attempt.id}.log"
        transcript.write_text("bounded fake transcript\n")
        os.chmod(transcript, 0o600)
        store.finish_attempt(
            attempt.id,
            status=AttemptStatus.SUCCEEDED,
            summary="artifact produced; awaiting review",
            evidence=["transcript: /private/path-that-must-not-be-read"],
            transcript_path=str(transcript),
            usage=(
                AttemptUsage(
                    reported_by="fake-runtime",
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                    reported_cost_usd=0.42,
                    cost_source="runtime_reported",
                )
                if self.include_cost
                else None
            ),
        )
        store.transition(task_id, TaskStatus.NEEDS_REVIEW, reason="fake execution exit 0")
        return 0


def _payload() -> dict[str, object]:
    return {
        "idempotency_key": str(uuid4()),
        "title": "Institutional deliverable",
        "objective": "Create the bounded institutional deliverable.",
        "required_outcome": "A text artifact exists.",
        "constraints": ["Do not contact external systems"],
        "institution": {"id": str(uuid4()), "name": "Test Institution"},
        "company": {"id": str(uuid4()), "name": "Test Company"},
        "project": {"id": str(uuid4()), "name": "Test Project"},
        "owner": {"id": str(uuid4()), "name": "Test Owner"},
        "budget": {"amount_cents": 500, "currency": "USD"},
    }


def _app(tmp_path: Path, runner: FakeRunner):  # type: ignore[no-untyped-def]
    return create_app(
        state_dir=tmp_path / "state",
        workspace_root=tmp_path / "workspaces",
        bundle_dir=tmp_path / "bundle",
        runtime="codex",
        timeout_seconds=30,
        bearer_token=TOKEN,
        runner=runner,
    )


def _wait_for_status(client: TestClient, work_id: str, expected: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/v1/work/{work_id}/status", headers=AUTHORIZATION)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == expected:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"work {work_id} did not reach {expected}")


@pytest.mark.parametrize(
    "task_status",
    [
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    ],
)
def test_reviewable_and_terminal_work_without_cost_observations_is_explicitly_unknown(
    task_status: TaskStatus,
) -> None:
    work_id = uuid4()

    projection = _cost_projection(work_id, [], task_status=task_status)

    assert projection.actual_cost_cents is None
    assert projection.reported_cost_usd is None
    assert projection.derived_cost_usd is None
    assert projection.cost_currency is None
    assert projection.cost_source == "unknown"
    assert projection.cost_evidence_ref == f"agent-os:{work_id}:cost-unknown"


@pytest.mark.parametrize("task_status", [TaskStatus.QUEUED, TaskStatus.RUNNING])
def test_nonterminal_work_without_cost_observations_remains_unprojected(
    task_status: TaskStatus,
) -> None:
    projection = _cost_projection(uuid4(), [], task_status=task_status)

    assert projection.actual_cost_cents is None
    assert projection.reported_cost_usd is None
    assert projection.derived_cost_usd is None
    assert projection.cost_currency is None
    assert projection.cost_source is None
    assert projection.cost_evidence_ref is None


@pytest.mark.parametrize(
    "usage",
    [
        {
            "reported_by": "test-runtime",
            "derived_cost_usd": 0.125,
            "cost_source": "billing_receipt",
            "cost_evidence_ref": "billing:receipt:derived-only",
        },
        {
            "reported_by": "test-runtime",
            "reported_cost_usd": 0.125,
            "cost_source": "billing_receipt",
        },
        {
            "reported_by": "test-runtime",
            "reported_cost_usd": 0.125,
            "cost_source": "billing_receipt",
            "cost_evidence_ref": "   ",
        },
    ],
)
def test_billing_receipt_usage_requires_billed_amount_and_exact_evidence(
    usage: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="billing-receipt|canonical"):
        AttemptUsage.model_validate(usage)


def test_actual_cost_projection_uses_validated_billing_amount_and_receipt() -> None:
    work_id = uuid4()
    evidence_ref = "billing:provider-receipt:exact-1"
    attempt = AttemptRecord(
        id="att_billed",
        task_id=str(work_id),
        agent="builder_codex",
        harness="codex",
        provider="openai",
        status=AttemptStatus.SUCCEEDED,
        started_at=utc_now(),
        usage=AttemptUsage(
            reported_by="provider-billing-adapter",
            reported_cost_usd=1.235,
            cost_source="billing_receipt",
            cost_evidence_ref=evidence_ref,
        ),
    )

    projection = _cost_projection(
        work_id,
        [attempt],
        task_status=TaskStatus.COMPLETED,
    )

    assert projection.actual_cost_cents == 124
    assert projection.cost_source == "billing_receipt"
    assert projection.cost_evidence_ref == evidence_ref


@pytest.mark.parametrize(
    "unknown_usage",
    [
        None,
        AttemptUsage(
            reported_by="unpriced-runtime",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            cost_source="unknown",
        ),
    ],
)
def test_actual_cost_projection_requires_receipt_coverage_for_every_retained_attempt(
    unknown_usage: AttemptUsage | None,
) -> None:
    work_id = uuid4()
    attempts = [
        AttemptRecord(
            id="att_billed",
            task_id=str(work_id),
            agent="builder_codex",
            harness="codex",
            provider="openai",
            status=AttemptStatus.SUCCEEDED,
            started_at=utc_now(),
            usage=AttemptUsage(
                reported_by="provider-billing-adapter",
                reported_cost_usd=0.25,
                cost_source="billing_receipt",
                cost_evidence_ref="billing:provider-receipt:incomplete-aggregate",
            ),
        ),
        AttemptRecord(
            id="att_unpriced",
            task_id=str(work_id),
            agent="builder_codex",
            harness="codex",
            provider="openai",
            status=AttemptStatus.FAILED,
            started_at=utc_now(),
            usage=unknown_usage,
        ),
    ]

    projection = _cost_projection(work_id, attempts, task_status=TaskStatus.FAILED)

    assert projection.actual_cost_cents is None
    assert projection.cost_currency == "USD"
    assert projection.cost_source == "mixed_observed"
    assert projection.reported_cost_usd == 0.25
    assert projection.derived_cost_usd is None
    assert projection.cost_evidence_ref == (
        f"agent-os:attempt-usage:{work_id}:att_billed,att_unpriced"
    )


def test_actual_cost_projection_never_synthesizes_distinct_receipt_evidence() -> None:
    work_id = uuid4()
    attempts = [
        AttemptRecord(
            id=f"att_billed_{index}",
            task_id=str(work_id),
            agent="builder_codex",
            harness="codex",
            provider="openai",
            status=AttemptStatus.SUCCEEDED,
            started_at=utc_now(),
            usage=AttemptUsage(
                reported_by="provider-billing-adapter",
                reported_cost_usd=amount,
                cost_source="billing_receipt",
                cost_evidence_ref=f"billing:provider-receipt:exact-{index}",
            ),
        )
        for index, amount in enumerate((0.10, 0.20), start=1)
    ]

    with pytest.raises(ValueError, match="one exact aggregate receipt"):
        _cost_projection(work_id, attempts, task_status=TaskStatus.COMPLETED)


def test_actual_cost_projection_preserves_shared_aggregate_receipt_evidence() -> None:
    work_id = uuid4()
    evidence_ref = "billing:provider-receipt:aggregate-exact"
    attempts = [
        AttemptRecord(
            id=f"att_billed_{index}",
            task_id=str(work_id),
            agent="builder_codex",
            harness="codex",
            provider="openai",
            status=AttemptStatus.SUCCEEDED,
            started_at=utc_now(),
            usage=AttemptUsage(
                reported_by="provider-billing-adapter",
                reported_cost_usd=amount,
                cost_source="billing_receipt",
                cost_evidence_ref=evidence_ref,
            ),
        )
        for index, amount in enumerate((0.10, 0.20), start=1)
    ]

    projection = _cost_projection(
        work_id,
        attempts,
        task_status=TaskStatus.COMPLETED,
    )

    assert projection.actual_cost_cents == 30
    assert projection.cost_source == "billing_receipt"
    assert projection.cost_evidence_ref == evidence_ref


@pytest.mark.parametrize("token", [None, "", " token "])
def test_service_start_requires_a_canonical_token(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
) -> None:
    if token is None:
        monkeypatch.delenv(SERVICE_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(SERVICE_TOKEN_ENV, token)
    with pytest.raises(SystemExit, match=SERVICE_TOKEN_ENV):
        main([])


def test_http_service_requires_auth_and_refuses_execution_authority_fields(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(released=True)
    payload = _payload()
    with TestClient(_app(tmp_path, runner)) as client:
        unauthorized = client.post("/v1/work", json=payload)
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "authentication_required"
        unsafe = {**payload, "runtime": "opencode", "workspace": "/tmp/unsafe"}
        response = client.post("/v1/work", json=unsafe, headers=AUTHORIZATION)
        assert response.status_code == 422
        assert response.json() == {
            "error": {
                "code": "invalid_request",
                "message": "The request does not match the Agent OS work contract.",
                "next_action": "send only the documented canonical fields and types",
            }
        }
        assert runner.calls == 0


def test_prelaunch_preparation_failure_reconciles_attempt_and_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_preparation(_runtime_dir: Path, *, review: bool) -> None:
        assert review is False
        raise RuntimeError("injected codex preparation failure")

    monkeypatch.setattr(runner_module, "_prepare_codex_runtime", fail_preparation)

    def governed_runner(
        store: TaskStore,
        task_id: str,
        bundle_dir: Path,
        *,
        runtime: str,
        timeout_seconds: int,
        cancel_event: Event,
    ) -> object:
        return runner_module.run_task(
            store,
            task_id,
            bundle_dir,
            runtime=runtime,
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
            codex_command="must-not-launch",
        )

    payload = _payload()
    work_id = str(payload["idempotency_key"])
    app = create_app(
        state_dir=tmp_path / "state",
        workspace_root=tmp_path / "workspaces",
        bundle_dir=tmp_path / "bundle",
        runtime="codex",
        timeout_seconds=30,
        bearer_token=TOKEN,
        runner=governed_runner,
    )
    with TestClient(app) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202

        projection = _wait_for_status(client, work_id, "failed")
        evidence = client.get(f"/v1/work/{work_id}/evidence", headers=AUTHORIZATION)

    assert projection["cost_source"] == "unknown"
    assert evidence.status_code == 200
    attempts = evidence.json()["attempts"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed"
    assert "injected codex preparation failure" in attempts[0]["summary"]
    assert not any(
        attempt.status is AttemptStatus.RUNNING
        for attempt in app.state.supervisor.store.list_attempts(work_id)
    )


def test_post_is_idempotent_and_owns_a_private_git_workspace(tmp_path: Path) -> None:
    runner = FakeRunner()
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    app = _app(tmp_path, runner)
    with TestClient(app) as client:
        created = client.post("/v1/work", json=payload, headers=AUTHORIZATION)
        assert created.status_code == 202
        assert runner.started.wait(timeout=2)

        replay = client.post("/v1/work", json=payload, headers=AUTHORIZATION)
        assert replay.status_code == 200
        assert replay.json()["id"] == work_id
        assert replay.json()["work_id"] == work_id
        assert replay.json()["title"] == payload["title"]
        assert runner.calls == 1

        changed = {**payload, "objective": "Different immutable work."}
        conflict = client.post("/v1/work", json=changed, headers=AUTHORIZATION)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "work_conflict"
        assert runner.calls == 1

        workspace = tmp_path / "workspaces" / work_id
        assert workspace.stat().st_mode & 0o777 == 0o700
        assert (workspace / ".git").is_dir()
        assert (workspace / ARTIFACT_DIRECTORY).stat().st_mode & 0o777 == 0o700
        task = app.state.supervisor.store.get_task(work_id)
        institution = payload["institution"]
        assert isinstance(institution, dict)
        assert "caller" not in task.context
        assert task.context["institution_id"] == institution["id"]
        assert task.context["budget_cents"] == "500"
        runner.release.set()
        _wait_for_status(client, work_id, "needs_review")

        missing = client.get(f"/v1/work/{uuid4()}", headers=AUTHORIZATION)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "work_not_found"


def test_artifact_evidence_and_cost_endpoints_return_content_not_host_paths(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(released=True)
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    with TestClient(_app(tmp_path, runner)) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        status_payload = _wait_for_status(client, work_id, "needs_review")
        assert status_payload["outcome"] == "artifact produced; awaiting review"
        assert status_payload["actual_cost_cents"] is None
        assert status_payload["cost_currency"] == "USD"
        assert status_payload["cost_source"] == "runtime_reported"
        assert status_payload["reported_cost_usd"] == 0.42
        assert status_payload["derived_cost_usd"] is None
        cost_evidence_ref = status_payload["cost_evidence_ref"]
        assert isinstance(cost_evidence_ref, str)
        assert cost_evidence_ref.startswith(f"agent-os:attempt-usage:{work_id}:")
        assert status_payload["costs"] == [
            {
                "reported_by": "fake-runtime",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "cache_read_input_tokens": None,
                "cache_creation_input_tokens": None,
                "reported_cost_usd": 0.42,
                "derived_cost_usd": None,
                "cost_source": "runtime_reported",
                "cost_evidence_ref": None,
                "by_model": {},
            }
        ]
        assert "workspace" not in status_payload

        outside = tmp_path / "outside-secret.txt"
        outside.write_text("do not return me")
        artifact_dir = tmp_path / "workspaces" / work_id / ARTIFACT_DIRECTORY
        (artifact_dir / "outside-link").symlink_to(outside)
        artifacts = client.get(f"/v1/work/{work_id}/artifacts", headers=AUTHORIZATION).json()[
            "artifacts"
        ]
        assert len(artifacts) == 1
        assert artifacts[0]["name"] == "result.txt"
        assert artifacts[0]["sha256"] == hashlib.sha256(b"real artifact\n").hexdigest()
        assert artifacts[0]["download_url"].startswith(f"/v1/work/{work_id}/artifacts/")
        download = client.get(artifacts[0]["download_url"], headers=AUTHORIZATION)
        assert download.status_code == 200
        assert download.content == b"real artifact\n"
        assert download.headers["etag"] == f'"{artifacts[0]["sha256"]}"'

        evidence = client.get(f"/v1/work/{work_id}/evidence", headers=AUTHORIZATION).json()
        assert evidence["attempts"][0]["evidence_refs"] == [
            f"document:transcript:{evidence['attempts'][0]['id']}"
        ]
        assert len(evidence["documents"]) == 1
        assert evidence["documents"][0]["created_at"]
        assert base64.b64decode(evidence["documents"][0]["content_base64"]) == (
            b"bounded fake transcript\n"
        )
        assert "/private/" not in str(evidence)
        assert any(event["kind"] == "attempt.finished" for event in evidence["events"])

        (artifact_dir / "result.txt").unlink()
        (artifact_dir / "outside-link").unlink()
        artifact_dir.rmdir()
        artifact_dir.symlink_to(tmp_path, target_is_directory=True)
        refused_artifacts = client.get(
            f"/v1/work/{work_id}/artifacts",
            headers=AUTHORIZATION,
        )
        assert refused_artifacts.status_code == 409
        assert "outside-secret" not in refused_artifacts.text

        terminal_cancel = client.post(f"/v1/work/{work_id}/cancel", headers=AUTHORIZATION)
        assert terminal_cancel.status_code == 200
        assert terminal_cancel.json()["status"] == "needs_review"
        assert terminal_cancel.json()["cancellation_requested"] is False


def test_artifact_download_fails_closed_when_entry_is_swapped_after_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(released=True)
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    with TestClient(_app(tmp_path, runner)) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        _wait_for_status(client, work_id, "needs_review")
        artifact_listing = client.get(
            f"/v1/work/{work_id}/artifacts",
            headers=AUTHORIZATION,
        ).json()["artifacts"]
        download_url = artifact_listing[0]["download_url"]
        artifact_path = tmp_path / "workspaces" / work_id / ARTIFACT_DIRECTORY / "result.txt"
        outside = tmp_path / "outside-after-enumeration.txt"
        outside_content = b"outside bytes must never be returned"
        outside.write_bytes(outside_content)
        original_enumerator = http_service._artifact_relative_names

        def enumerate_then_swap(directory_fd: int) -> list[str]:
            names = original_enumerator(directory_fd)
            artifact_path.unlink()
            artifact_path.symlink_to(outside)
            return names

        monkeypatch.setattr(http_service, "_artifact_relative_names", enumerate_then_swap)

        download = client.get(download_url, headers=AUTHORIZATION)

    assert download.status_code == 409
    assert outside_content not in download.content


def test_evidence_read_fails_closed_when_entry_is_swapped_before_descriptor_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(released=True)
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    app = _app(tmp_path, runner)
    with TestClient(app) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        _wait_for_status(client, work_id, "needs_review")
        attempt = app.state.supervisor.store.list_attempts(work_id)[0]
        assert attempt.transcript_path is not None
        transcript_path = Path(attempt.transcript_path)
        outside = tmp_path / "outside-evidence.txt"
        outside_content = b"outside evidence bytes must never be returned"
        outside.write_bytes(outside_content)
        original_reader = http_service._read_regular_descendant
        swapped = False

        def swap_then_read(directory_fd: int, relative: str | Path) -> bytes:
            nonlocal swapped
            if not swapped and Path(relative).name == transcript_path.name:
                transcript_path.unlink()
                transcript_path.symlink_to(outside)
                swapped = True
            return original_reader(directory_fd, relative)

        monkeypatch.setattr(http_service, "_read_regular_descendant", swap_then_read)

        evidence = client.get(f"/v1/work/{work_id}/evidence", headers=AUTHORIZATION)

    assert evidence.status_code == 200
    assert evidence.json()["documents"] == []
    assert outside_content not in evidence.content


def test_evidence_documents_are_returned_when_store_exposes_a_relative_state_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative_state_dir = Path(".agent-os-service")
    runner = FakeRunner(released=True)
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    app = create_app(
        state_dir=relative_state_dir,
        workspace_root=tmp_path / "workspaces",
        bundle_dir=tmp_path / "bundle",
        runtime="codex",
        timeout_seconds=30,
        bearer_token=TOKEN,
        runner=runner,
    )
    with TestClient(app) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        _wait_for_status(client, work_id, "needs_review")
        app.state.supervisor.store.state_dir = relative_state_dir

        evidence = client.get(f"/v1/work/{work_id}/evidence", headers=AUTHORIZATION)

    assert evidence.status_code == 200
    documents = evidence.json()["documents"]
    assert len(documents) == 1
    assert base64.b64decode(documents[0]["content_base64"]) == b"bounded fake transcript\n"


@pytest.mark.parametrize(
    "task_status",
    [
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    ],
)
def test_cancel_returns_current_projection_when_work_reaches_terminal_before_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_status: TaskStatus,
) -> None:
    work_id = uuid4()
    terminal_task = TaskSpec(
        id=str(work_id),
        title="Terminal work",
        objective="Expose the terminal-before-cancel race.",
        workspace=tmp_path,
        acceptance_criteria=["The current projection is returned."],
        status=task_status,
    )
    queued_task = terminal_task.model_copy(update={"status": TaskStatus.QUEUED})
    projected_tasks = iter([queued_task, terminal_task])
    app = _app(tmp_path, FakeRunner())
    monkeypatch.setattr(
        app.state.supervisor.store,
        "get_task",
        lambda _task_id: next(projected_tasks, terminal_task),
    )

    def terminal_won_race(_task_id: str, *, reason: str) -> TaskSpec:
        del reason
        raise ValueError(f"task cannot be cancelled while {task_status.value}")

    monkeypatch.setattr(app.state.supervisor.store, "cancel_task", terminal_won_race)

    with TestClient(app) as client:
        response = client.post(f"/v1/work/{work_id}/cancel", headers=AUTHORIZATION)

    assert response.status_code == 200
    assert response.json()["work_id"] == str(work_id)
    assert response.json()["status"] == task_status.value
    assert response.json()["cancellation_requested"] is False


def test_reviewable_http_work_without_cost_observation_returns_explicit_unknown(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(released=True, include_cost=False)
    payload = _payload()
    work_id = str(payload["idempotency_key"])

    with TestClient(_app(tmp_path, runner)) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        projection = _wait_for_status(client, work_id, "needs_review")

    assert projection["actual_cost_cents"] is None
    assert projection["reported_cost_usd"] is None
    assert projection["derived_cost_usd"] is None
    assert projection["cost_currency"] is None
    assert projection["cost_source"] == "unknown"
    assert projection["cost_evidence_ref"] == f"agent-os:{work_id}:cost-unknown"


def test_cancel_is_governed_and_idempotent(tmp_path: Path) -> None:
    runner = FakeRunner()
    payload = _payload()
    work_id = str(payload["idempotency_key"])
    with TestClient(_app(tmp_path, runner)) as client:
        assert client.post("/v1/work", json=payload, headers=AUTHORIZATION).status_code == 202
        assert runner.started.wait(timeout=2)

        requested = client.post(f"/v1/work/{work_id}/cancel", headers=AUTHORIZATION)
        assert requested.status_code == 202
        assert requested.json()["work_id"] == work_id
        assert requested.json()["status"] == "running"
        assert requested.json()["cancellation_requested"] is True
        _wait_for_status(client, work_id, "cancelled")

        replay = client.post(f"/v1/work/{work_id}/cancel", headers=AUTHORIZATION)
        assert replay.status_code == 200
        assert replay.json()["status"] == "cancelled"
        assert replay.json()["cancellation_requested"] is False
