from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from agent_os.models import AttemptKind, AttemptStatus, AttemptUsage, TaskStatus
from agent_os.store import SCHEMA, SCHEMA_VERSION, TaskStore


def make_task(store: TaskStore, workspace: Path):
    return store.create_task(
        title="Repair the parser",
        objective="Reject malformed headers without regressing valid input.",
        workspace=workspace,
        acceptance_criteria=["Malformed headers return a typed error", "Existing tests pass"],
        constraints=["No network access"],
        context={"issue": "ISSUE-123"},
    )


def test_task_attempt_review_and_event_lifecycle(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    assert task.status is TaskStatus.QUEUED

    store.transition(task.id, TaskStatus.RUNNING, reason="start")
    attempt = store.start_attempt(task.id, agent="builder_codex")
    finished = store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Added validation and regression tests",
        evidence=["pytest tests/test_parser.py: 12 passed"],
    )
    review = store.record_review(
        task.id,
        attempt_id=attempt.id,
        reviewer="reviewer_claude",
        verdict="approve",
        summary="Acceptance criteria verified",
        evidence=["src/parser.py:42", "12 passed"],
    )
    store.transition(task.id, TaskStatus.NEEDS_REVIEW, reason="reviewed")
    store.complete_task(task.id, summary="approved")

    assert finished.status is AttemptStatus.SUCCEEDED
    assert review.verdict == "approve"
    assert store.get_task(task.id).status is TaskStatus.COMPLETED
    assert [event["kind"] for event in store.list_events(task.id)] == [
        "task.created",
        "task.transitioned",
        "attempt.started",
        "attempt.finished",
        "review.recorded",
        "task.transitioned",
        "task.transitioned",
    ]


def test_invalid_transition_is_rejected(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    with pytest.raises(ValueError, match="must use complete_task"):
        store.transition(task.id, TaskStatus.COMPLETED)


def test_explicit_task_id_replays_only_the_same_immutable_task(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    fields = {
        "task_id": "institution-work-123",
        "title": "Produce the artifact",
        "objective": "Return a bounded result.",
        "workspace": tmp_path,
        "acceptance_criteria": ["The artifact exists"],
        "constraints": ["No network access"],
        "context": {"project": "stationery", "institution": "holding"},
    }
    created = store.create_task(**fields)
    store.transition(created.id, TaskStatus.RUNNING, reason="execution started")

    replay = store.create_task(**fields)

    assert replay.id == created.id
    assert replay.status is TaskStatus.RUNNING
    assert replay.created_at == created.created_at
    assert replay.updated_at != created.updated_at
    assert len(store.list_tasks()) == 1
    assert [event["kind"] for event in store.list_events(created.id)].count("task.created") == 1

    with pytest.raises(ValueError, match="different immutable fields"):
        store.create_task(**{**fields, "objective": "A different unit of work."})
    assert store.get_task(created.id) == replay


@pytest.mark.parametrize(
    "task_id",
    [
        "tsk_0123456789ab",
        "123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_explicit_task_id_accepts_supported_filename_safe_forms(
    tmp_path: Path,
    task_id: str,
) -> None:
    store = TaskStore(tmp_path / "state")

    task = store.create_task(
        task_id=task_id,
        title="Use a safe durable id",
        objective="Keep task paths inside Agent OS state.",
        workspace=tmp_path,
        acceptance_criteria=["The exact id is retained"],
    )

    assert task.id == task_id


@pytest.mark.parametrize(
    "task_id",
    [
        ".",
        "..",
        "../escape",
        r"..\escape",
        "nested/task",
        r"nested\task",
        "control\ncharacter",
        "control\x00character",
        "x" * 129,
    ],
)
def test_explicit_task_id_rejects_unsafe_path_components(
    tmp_path: Path,
    task_id: str,
) -> None:
    store = TaskStore(tmp_path / "state")

    with pytest.raises(ValueError, match="task_id must be"):
        store.create_task(
            task_id=task_id,
            title="Reject an unsafe id",
            objective="Keep task paths inside Agent OS state.",
            workspace=tmp_path,
            acceptance_criteria=["No task is created"],
        )

    assert store.list_tasks() == []


def test_explicit_task_id_is_idempotent_under_concurrency(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    store.initialize()
    barrier = Barrier(2)

    def create() -> str:
        barrier.wait()
        return store.create_task(
            task_id="institution-work-concurrent",
            title="Produce once",
            objective="Create one durable task.",
            workspace=tmp_path,
            acceptance_criteria=["One task exists"],
        ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: create(), range(2)))

    assert ids == ["institution-work-concurrent", "institution-work-concurrent"]
    assert len(store.list_tasks()) == 1
    assert len(store.list_events(ids[0])) == 1


def test_cancel_task_is_idempotent_and_cannot_be_bypassed_by_transition(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)

    cancelled = store.cancel_task(task.id, reason="operator cancelled queued work")
    replay = store.cancel_task(task.id, reason="duplicate request")

    assert cancelled.status is TaskStatus.CANCELLED
    assert replay == cancelled
    assert store.list_events(task.id)[-1]["payload"] == {
        "from": "queued",
        "reason": "operator cancelled queued work",
        "to": "cancelled",
    }
    with pytest.raises(ValueError, match="must use cancel_task"):
        store.transition(task.id, TaskStatus.CANCELLED)
    with pytest.raises(ValueError, match="invalid task transition"):
        store.transition(task.id, TaskStatus.RUNNING)


def test_cancel_task_requires_running_attempts_to_be_terminal(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex")

    with pytest.raises(ValueError, match="running attempts"):
        store.cancel_task(task.id, reason="process is not terminated")

    store.finish_attempt(
        attempt.id,
        status=AttemptStatus.CANCELLED,
        summary="process group terminated",
    )
    cancelled = store.cancel_task(task.id, reason="process group terminated")

    assert cancelled.status is TaskStatus.CANCELLED
    assert store.get_attempt(attempt.id).status is AttemptStatus.CANCELLED


def test_cancel_and_attempt_start_are_atomic_under_concurrency(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    barrier = Barrier(2)

    def start() -> tuple[str, str]:
        barrier.wait()
        try:
            return "attempt", store.start_attempt(task.id, agent="builder_codex").id
        except ValueError as error:
            return "start_error", str(error)

    def cancel() -> tuple[str, str]:
        barrier.wait()
        try:
            status = store.cancel_task(task.id, reason="concurrent cancellation").status
            return "cancelled", status.value
        except ValueError as error:
            return "cancel_error", str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        start_future = executor.submit(start)
        cancel_future = executor.submit(cancel)
        results = [start_future.result(), cancel_future.result()]

    current = store.get_task(task.id)
    attempts = store.list_attempts(task.id)
    if current.status is TaskStatus.CANCELLED:
        assert attempts == []
        assert {kind for kind, _value in results} == {"cancelled", "start_error"}
    else:
        assert current.status is TaskStatus.RUNNING
        assert len(attempts) == 1
        assert attempts[0].status is AttemptStatus.RUNNING
        assert {kind for kind, _value in results} == {"attempt", "cancel_error"}


@pytest.mark.parametrize("target", [TaskStatus.BLOCKED, TaskStatus.FAILED])
def test_terminal_task_transition_rejects_running_implementation(
    tmp_path: Path, target: TaskStatus
) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_ollama")

    with pytest.raises(ValueError, match="running implementation"):
        store.transition(task.id, target, reason="child looked slow")

    assert store.get_task(task.id).status is TaskStatus.RUNNING
    assert store.get_attempt(attempt.id).status is AttemptStatus.RUNNING


def test_review_must_use_a_different_vendor(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex")
    store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented",
        evidence=["pytest: passed"],
    )

    with pytest.raises(ValueError, match="intelligence provider"):
        store.record_review(
            task.id,
            attempt_id=attempt.id,
            reviewer="reviewer_codex",
            verdict="approve",
            summary="Self-family review",
            evidence=["reviewed diff"],
        )


def test_opencode_openai_cannot_be_reviewed_by_codex(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_opencode")
    store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented through OpenCode",
        evidence=["pytest: passed"],
    )

    assert attempt.harness == "opencode-native"
    assert attempt.provider == "openai"
    with pytest.raises(ValueError, match="intelligence provider"):
        store.record_review(
            task.id,
            attempt_id=attempt.id,
            reviewer="reviewer_codex",
            verdict="approve",
            summary="Same-provider review",
            evidence=["reviewed diff"],
        )


def test_rework_invalidates_approval_for_the_superseded_attempt(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    first = store.start_attempt(task.id, agent="builder_codex", work_item="parser")
    store.finish_attempt(
        first.id,
        status=AttemptStatus.SUCCEEDED,
        summary="First implementation",
        evidence=["pytest: passed"],
    )
    store.record_review(
        task.id,
        attempt_id=first.id,
        reviewer="reviewer_claude",
        verdict="approve",
        summary="First attempt approved",
        evidence=["reviewed first diff"],
    )
    store.transition(task.id, TaskStatus.NEEDS_REVIEW)
    store.transition(task.id, TaskStatus.RUNNING)

    second = store.start_attempt(task.id, agent="builder_codex", work_item="parser")
    store.finish_attempt(
        second.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Unreviewed rework",
        evidence=["pytest: passed again"],
    )
    store.transition(task.id, TaskStatus.NEEDS_REVIEW)

    with pytest.raises(ValueError, match="no independent review"):
        store.complete_task(task.id, summary="stale approval must not close")


def test_only_one_running_attempt_per_work_item_under_concurrency(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    barrier = Barrier(2)

    def start() -> str:
        barrier.wait()
        try:
            return store.start_attempt(
                task.id, agent="builder_codex", work_item="parser"
            ).id
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: start(), range(2)))

    assert sum(result.startswith("att_") for result in results) == 1
    assert sum("already has a running attempt" in result for result in results) == 1


def test_terminal_attempt_write_is_idempotent_but_not_mutable(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex")
    first = store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented",
        evidence=["pytest: passed"],
        usage=AttemptUsage(
            reported_by="codex",
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
        ),
    )
    repeated = store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented",
        evidence=["pytest: passed"],
        usage=AttemptUsage(
            reported_by="codex",
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
        ),
    )
    assert repeated == first
    assert repeated.usage is not None
    assert repeated.usage.total_tokens == 150

    with pytest.raises(ValueError, match="already terminal"):
        store.finish_attempt(
            attempt.id,
            status=AttemptStatus.FAILED,
            summary="Rewritten history",
        )


@pytest.mark.parametrize(
    "usage",
    [
        {
            "reported_by": "runtime",
            "reported_cost_usd": 0.25,
            "cost_source": "unknown",
        },
        {"reported_by": "runtime", "cost_source": "runtime_reported"},
        {
            "reported_by": "rate-table",
            "derived_cost_usd": 0.25,
            "cost_source": "provider_rate_derived",
        },
        {
            "reported_by": "billing-adapter",
            "reported_cost_usd": 0.25,
            "cost_source": "billing_receipt",
        },
        {
            "reported_by": "runtime",
            "reported_cost_usd": 0.25,
            "derived_cost_usd": 0.20,
            "cost_source": "runtime_reported",
        },
    ],
)
def test_attempt_usage_rejects_ambiguous_cost_provenance(usage: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AttemptUsage.model_validate(usage)


def test_attempt_usage_cost_provenance_round_trips_through_store(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_codex")
    usage = AttemptUsage(
        reported_by="provider-rate-table",
        input_tokens=40,
        output_tokens=10,
        derived_cost_usd=0.005,
        cost_source="provider_rate_derived",
        cost_evidence_ref="rate-snapshot:openai:test",
    )

    stored = store.finish_attempt(
        attempt.id,
        status=AttemptStatus.SUCCEEDED,
        summary="Implemented",
        evidence=["pytest: passed"],
        usage=usage,
    )

    assert stored.usage == usage
    assert stored.usage is not None
    assert stored.usage.reported_cost_usd is None
    assert stored.usage.derived_cost_usd == pytest.approx(0.005)


def test_legacy_reported_cost_is_loaded_as_runtime_reported() -> None:
    usage = AttemptUsage.model_validate({"reported_by": "omnigent", "reported_cost_usd": 0.5})

    assert usage.cost_source == "runtime_reported"
    assert usage.reported_cost_usd == pytest.approx(0.5)


def test_reconcile_fails_attempt_with_dead_process_lease(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="prime_coordinator", provider="openai")
    store.set_attempt_process(attempt.id, 2_000_000_000)

    reconciled = store.reconcile_stale_attempts(older_than_seconds=0)

    assert [item.id for item in reconciled] == [attempt.id]
    assert reconciled[0].status is AttemptStatus.FAILED
    assert store.get_task(task.id).status is TaskStatus.FAILED


def test_reconcile_preserves_attempt_owned_by_live_process(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="prime_coordinator", provider="openai")
    store.set_attempt_process(attempt.id, os.getpid())

    assert store.reconcile_stale_attempts(older_than_seconds=0) == []
    assert store.get_attempt(attempt.id).status is AttemptStatus.RUNNING


def test_v1_database_migrates_with_private_backup(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    database = state / "agent_os.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER PRIMARY KEY);
        INSERT INTO schema_meta(version) VALUES (1);
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, objective TEXT NOT NULL,
            workspace TEXT NOT NULL, acceptance_json TEXT NOT NULL,
            constraints_json TEXT NOT NULL, context_json TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE attempts (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            agent TEXT NOT NULL, harness TEXT NOT NULL, status TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '[]',
            transcript_path TEXT, started_at TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE reviews (
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
            reviewer TEXT NOT NULL, harness TEXT NOT NULL, verdict TEXT NOT NULL,
            summary TEXT NOT NULL, issues_json TEXT NOT NULL DEFAULT '[]',
            evidence_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """
    )
    connection.close()

    store = TaskStore(state)
    store.initialize()

    migrated = sqlite3.connect(database)
    version = migrated.execute(
        "SELECT version FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    columns = {row[1] for row in migrated.execute("PRAGMA table_info(attempts)")}
    migrated.close()
    assert version == SCHEMA_VERSION
    assert {"provider", "model", "kind", "work_item", "pid", "usage_json"} <= columns
    assert database.with_suffix(".db.v1.bak").exists()
    assert database.stat().st_mode & 0o777 == 0o600
    assert database.with_suffix(".db.v1.bak").stat().st_mode & 0o777 == 0o600


def test_v2_database_migrates_attempt_usage_with_private_backup(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    database = state / "agent_os.db"
    connection = sqlite3.connect(database)
    v2_schema = SCHEMA.replace(
        "VALUES ('schema_version', 3)", "VALUES ('schema_version', 2)"
    ).replace("    usage_json TEXT,\n", "")
    connection.executescript(v2_schema)
    connection.close()

    store = TaskStore(state)
    store.initialize()

    migrated = sqlite3.connect(database)
    version = migrated.execute(
        "SELECT version FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    columns = {row[1] for row in migrated.execute("PRAGMA table_info(attempts)")}
    migrated.close()
    assert version == SCHEMA_VERSION
    assert "usage_json" in columns
    assert database.with_suffix(".db.v2.bak").exists()
    assert database.with_suffix(".db.v2.bak").stat().st_mode & 0o777 == 0o600


def test_attempt_identity_records_kind_provider_and_model(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "state")
    task = make_task(store, tmp_path)
    store.transition(task.id, TaskStatus.RUNNING)
    attempt = store.start_attempt(task.id, agent="builder_ollama")

    assert attempt.kind is AttemptKind.IMPLEMENTATION
    assert attempt.provider == "ollama"
    assert attempt.model == "ollama/qwen3:14b"
