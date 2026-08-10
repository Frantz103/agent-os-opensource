"""SQLite task records that sit above Omnigent's conversation persistence."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_os.models import (
    AttemptRecord,
    AttemptStatus,
    ReviewRecord,
    TaskSpec,
    TaskStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_meta(version) VALUES (1);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    workspace TEXT NOT NULL,
    acceptance_json TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent TEXT NOT NULL,
    harness TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    transcript_path TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_task_started
    ON attempts(task_id, started_at);

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
    reviewer TEXT NOT NULL,
    harness TEXT NOT NULL,
    verdict TEXT NOT NULL,
    summary TEXT NOT NULL,
    issues_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_task_created
    ON reviews(task_id, created_at);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_events_task_id
    ON task_events(task_id, id);
"""


VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.NEEDS_REVIEW: {
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.BLOCKED: {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.QUEUED, TaskStatus.RUNNING},
    TaskStatus.COMPLETED: set(),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def harness_vendor(harness: str) -> str:
    normalized = harness.lower()
    if "claude" in normalized or "anthropic" in normalized:
        return "anthropic"
    if "codex" in normalized or "openai" in normalized:
        return "openai"
    return normalized.removesuffix("-native").removesuffix("-sdk")


def default_state_dir() -> Path:
    configured = os.environ.get("AGENT_OS_STATE_DIR")
    return Path(configured).expanduser().resolve() if configured else Path.cwd() / ".agent-os"


class TaskStore:
    """Small domain store for tasks, attempts, review verdicts, and evidence events."""

    def __init__(self, state_dir: Path | str | None = None) -> None:
        self.state_dir = Path(state_dir) if state_dir is not None else default_state_dir()
        self.state_dir = self.state_dir.expanduser().resolve()
        self.db_path = self.state_dir / "agent_os.db"

    def initialize(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_task(
        self,
        *,
        title: str,
        objective: str,
        workspace: Path | str,
        acceptance_criteria: list[str],
        constraints: list[str] | None = None,
        context: dict[str, str] | None = None,
    ) -> TaskSpec:
        self.initialize()
        task = TaskSpec(
            id=_id("tsk"),
            title=title,
            objective=objective,
            workspace=Path(workspace).expanduser().resolve(),
            acceptance_criteria=acceptance_criteria,
            constraints=constraints or [],
            context=context or {},
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(
                    id, title, objective, workspace, acceptance_json, constraints_json,
                    context_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.title,
                    task.objective,
                    str(task.workspace),
                    json.dumps(task.acceptance_criteria),
                    json.dumps(task.constraints),
                    json.dumps(task.context, sort_keys=True),
                    task.status.value,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                ),
            )
            self._append_event(connection, task.id, "task.created", {"title": task.title})
        return task

    def get_task(self, task_id: str) -> TaskSpec:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"task not found: {task_id}")
        return self._task_from_row(row)

    def list_tasks(self, status: TaskStatus | None = None) -> list[TaskSpec]:
        self.initialize()
        query = "SELECT * FROM tasks"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._task_from_row(row) for row in rows]

    def transition(self, task_id: str, target: TaskStatus | str, *, reason: str = "") -> TaskSpec:
        current = self.get_task(task_id)
        target = TaskStatus(target)
        if target == current.status:
            return current
        if target not in VALID_TRANSITIONS[current.status]:
            raise ValueError(f"invalid task transition: {current.status.value} -> {target.value}")
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (target.value, timestamp, task_id),
            )
            self._append_event(
                connection,
                task_id,
                "task.transitioned",
                {"from": current.status.value, "to": target.value, "reason": reason},
            )
        return self.get_task(task_id)

    def start_attempt(self, task_id: str, *, agent: str, harness: str) -> AttemptRecord:
        self.get_task(task_id)
        attempt = AttemptRecord(
            id=_id("att"),
            task_id=task_id,
            agent=agent,
            harness=harness,
            status=AttemptStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO attempts(
                    id, task_id, agent, harness, status, summary, evidence_json, started_at
                ) VALUES (?, ?, ?, ?, ?, '', '[]', ?)
                """,
                (
                    attempt.id,
                    task_id,
                    agent,
                    harness,
                    attempt.status.value,
                    attempt.started_at.isoformat(),
                ),
            )
            self._append_event(
                connection,
                task_id,
                "attempt.started",
                {"attempt_id": attempt.id, "agent": agent, "harness": harness},
            )
        return attempt

    def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: AttemptStatus | str,
        summary: str,
        evidence: list[str] | None = None,
        transcript_path: str | None = None,
    ) -> AttemptRecord:
        status = AttemptStatus(status)
        if status is AttemptStatus.RUNNING:
            raise ValueError("finish_attempt requires a terminal status")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_id FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"attempt not found: {attempt_id}")
            finished_at = _now()
            connection.execute(
                """
                UPDATE attempts
                SET status = ?, summary = ?, evidence_json = ?, transcript_path = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    summary,
                    json.dumps(evidence or []),
                    transcript_path,
                    finished_at,
                    attempt_id,
                ),
            )
            self._append_event(
                connection,
                row["task_id"],
                "attempt.finished",
                {"attempt_id": attempt_id, "status": status.value, "summary": summary},
            )
        return self.get_attempt(attempt_id)

    def get_attempt(self, attempt_id: str) -> AttemptRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"attempt not found: {attempt_id}")
        return self._attempt_from_row(row)

    def list_attempts(self, task_id: str) -> list[AttemptRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM attempts WHERE task_id = ? ORDER BY started_at", (task_id,)
            ).fetchall()
        return [self._attempt_from_row(row) for row in rows]

    def record_review(
        self,
        task_id: str,
        *,
        reviewer: str,
        harness: str,
        verdict: str,
        summary: str,
        attempt_id: str | None = None,
        issues: list[str] | None = None,
        evidence: list[str] | None = None,
    ) -> ReviewRecord:
        self.get_task(task_id)
        if attempt_id is not None:
            attempt = self.get_attempt(attempt_id)
            if attempt.task_id != task_id:
                raise ValueError("review attempt belongs to a different task")
            if harness_vendor(attempt.harness) == harness_vendor(harness):
                raise ValueError(
                    "review harness must be from a different vendor than the implementer"
                )
        review = ReviewRecord(
            id=_id("rev"),
            task_id=task_id,
            attempt_id=attempt_id,
            reviewer=reviewer,
            harness=harness,
            verdict=verdict,
            summary=summary,
            issues=issues or [],
            evidence=evidence or [],
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reviews(
                    id, task_id, attempt_id, reviewer, harness, verdict, summary,
                    issues_json, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    task_id,
                    attempt_id,
                    reviewer,
                    harness,
                    review.verdict,
                    summary,
                    json.dumps(review.issues),
                    json.dumps(review.evidence),
                    review.created_at.isoformat(),
                ),
            )
            self._append_event(
                connection,
                task_id,
                "review.recorded",
                {"review_id": review.id, "reviewer": reviewer, "verdict": review.verdict},
            )
        return review

    def list_reviews(self, task_id: str) -> list[ReviewRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY created_at", (task_id,)
            ).fetchall()
        return [self._review_from_row(row) for row in rows]

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT kind, payload_json, created_at FROM task_events "
                "WHERE task_id = ? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO task_events(task_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (task_id, kind, json.dumps(payload, sort_keys=True), _now()),
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskSpec:
        return TaskSpec(
            id=row["id"],
            title=row["title"],
            objective=row["objective"],
            workspace=Path(row["workspace"]),
            acceptance_criteria=json.loads(row["acceptance_json"]),
            constraints=json.loads(row["constraints_json"]),
            context=json.loads(row["context_json"]),
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> AttemptRecord:
        return AttemptRecord(
            id=row["id"],
            task_id=row["task_id"],
            agent=row["agent"],
            harness=row["harness"],
            status=AttemptStatus(row["status"]),
            summary=row["summary"],
            evidence=json.loads(row["evidence_json"]),
            transcript_path=row["transcript_path"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None
            ),
        )

    @staticmethod
    def _review_from_row(row: sqlite3.Row) -> ReviewRecord:
        return ReviewRecord(
            id=row["id"],
            task_id=row["task_id"],
            attempt_id=row["attempt_id"],
            reviewer=row["reviewer"],
            harness=row["harness"],
            verdict=row["verdict"],
            summary=row["summary"],
            issues=json.loads(row["issues_json"]),
            evidence=json.loads(row["evidence_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
