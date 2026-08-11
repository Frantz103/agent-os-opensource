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

from agent_os.execution import execution_identity
from agent_os.models import (
    AttemptKind,
    AttemptRecord,
    AttemptStatus,
    ReviewRecord,
    TaskSpec,
    TaskStatus,
)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY CHECK (key = 'schema_version'),
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, version) VALUES ('schema_version', 2);

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
    provider TEXT NOT NULL,
    model TEXT,
    kind TEXT NOT NULL,
    work_item TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    transcript_path TEXT,
    pid INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_attempts_task_started
    ON attempts(task_id, started_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_one_running_work_item
    ON attempts(task_id, work_item)
    WHERE kind = 'implementation' AND status = 'running';

CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
    reviewer TEXT NOT NULL,
    harness TEXT NOT NULL,
    provider TEXT NOT NULL,
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

MIGRATE_V1_TO_V2 = """
ALTER TABLE attempts ADD COLUMN provider TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE attempts ADD COLUMN model TEXT;
ALTER TABLE attempts ADD COLUMN kind TEXT NOT NULL DEFAULT 'implementation';
ALTER TABLE attempts ADD COLUMN work_item TEXT NOT NULL DEFAULT 'primary';
ALTER TABLE attempts ADD COLUMN pid INTEGER;
UPDATE attempts
SET provider = CASE
    WHEN lower(harness) LIKE '%claude%' OR lower(harness) LIKE '%anthropic%' THEN 'anthropic'
    WHEN lower(harness) LIKE '%codex%' OR lower(harness) LIKE '%openai%' THEN 'openai'
    WHEN lower(harness) LIKE '%ollama%' THEN 'ollama'
    ELSE lower(replace(replace(harness, '-native', ''), '-sdk', ''))
END;
UPDATE attempts SET kind = 'coordinator' WHERE agent = 'coordinator';
WITH ranked_running AS (
    SELECT id,
           row_number() OVER (PARTITION BY task_id ORDER BY started_at DESC, id DESC) AS rank
    FROM attempts
    WHERE kind = 'implementation' AND status = 'running'
)
UPDATE attempts
SET status = 'failed',
    summary = 'Reconciled duplicate running attempt during schema v2 migration',
    finished_at = CURRENT_TIMESTAMP
WHERE id IN (SELECT id FROM ranked_running WHERE rank > 1);

ALTER TABLE reviews ADD COLUMN provider TEXT NOT NULL DEFAULT 'unknown';
UPDATE reviews
SET provider = CASE
    WHEN lower(harness) LIKE '%claude%' OR lower(harness) LIKE '%anthropic%' THEN 'anthropic'
    WHEN lower(harness) LIKE '%codex%' OR lower(harness) LIKE '%openai%' THEN 'openai'
    ELSE lower(replace(replace(harness, '-native', ''), '-sdk', ''))
END;

CREATE UNIQUE INDEX IF NOT EXISTS idx_attempts_one_running_work_item
    ON attempts(task_id, work_item)
    WHERE kind = 'implementation' AND status = 'running';

ALTER TABLE schema_meta RENAME TO schema_meta_v1;
CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY CHECK (key = 'schema_version'),
    version INTEGER NOT NULL
);
INSERT INTO schema_meta(key, version) VALUES ('schema_version', 2);
DROP TABLE schema_meta_v1;
"""


VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.QUEUED: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.NEEDS_REVIEW,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
    },
    TaskStatus.NEEDS_REVIEW: {
        TaskStatus.RUNNING,
        TaskStatus.BLOCKED,
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
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        needs_migration = self.db_path.exists() and self._legacy_schema_version() == 1
        if needs_migration:
            self._backup_before_migration(1)
        with self._connect() as connection:
            if needs_migration:
                connection.executescript(MIGRATE_V1_TO_V2)
            connection.executescript(SCHEMA)
            row = connection.execute(
                "SELECT version FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None or row["version"] != SCHEMA_VERSION:
                found = None if row is None else row["version"]
                raise RuntimeError(
                    f"unsupported Agent OS schema version: {found}; expected {SCHEMA_VERSION}"
                )
        os.chmod(self.db_path, 0o600)
        self._secure_existing_state_files()

    def _secure_existing_state_files(self) -> None:
        transcripts = self.state_dir / "transcripts"
        if not transcripts.exists():
            return
        os.chmod(transcripts, 0o700)
        for path in transcripts.rglob("*"):
            os.chmod(path, 0o700 if path.is_dir() else 0o600)

    def _legacy_schema_version(self) -> int | None:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
            ).fetchone()
            if exists is None:
                return None
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(schema_meta)")
            }
            if columns == {"version"}:
                row = connection.execute(
                    "SELECT max(version) AS version FROM schema_meta"
                ).fetchone()
                return int(row["version"]) if row and row["version"] is not None else None
            return None
        finally:
            connection.close()

    def _backup_before_migration(self, version: int) -> None:
        backup_path = self.db_path.with_suffix(f".db.v{version}.bak")
        if backup_path.exists():
            return
        source = sqlite3.connect(self.db_path)
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        os.chmod(backup_path, 0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
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
        workspace_path = Path(workspace).expanduser().resolve(strict=True)
        if not workspace_path.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace_path}")
        task = TaskSpec(
            id=_id("tsk"),
            title=title,
            objective=objective,
            workspace=workspace_path,
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
        if target is TaskStatus.COMPLETED:
            raise ValueError("completed transitions must use complete_task")
        if target == current.status:
            return current
        if target not in VALID_TRANSITIONS[current.status]:
            raise ValueError(f"invalid task transition: {current.status.value} -> {target.value}")
        timestamp = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (target.value, timestamp, task_id, current.status.value),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"task changed concurrently: {task_id}")
            self._append_event(
                connection,
                task_id,
                "task.transitioned",
                {"from": current.status.value, "to": target.value, "reason": reason},
            )
        return self.get_task(task_id)

    def start_attempt(
        self,
        task_id: str,
        *,
        agent: str,
        work_item: str = "primary",
        provider: str | None = None,
        model: str | None = None,
    ) -> AttemptRecord:
        task = self.get_task(task_id)
        if task.status is not TaskStatus.RUNNING:
            raise ValueError("attempts may start only while the task is running")
        work_item = work_item.strip()
        if not work_item:
            raise ValueError("work_item must not be empty")
        identity = execution_identity(agent, provider=provider, model=model)
        assert identity.provider is not None
        attempt = AttemptRecord(
            id=_id("att"),
            task_id=task_id,
            agent=agent,
            harness=identity.harness,
            provider=identity.provider,
            model=identity.model,
            kind=identity.kind,
            work_item=work_item,
            status=AttemptStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO attempts(
                        id, task_id, agent, harness, provider, model, kind, work_item,
                        status, summary, evidence_json, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', '[]', ?)
                    """,
                    (
                        attempt.id,
                        task_id,
                        agent,
                        identity.harness,
                        identity.provider,
                        identity.model,
                        identity.kind.value,
                        work_item,
                        attempt.status.value,
                        attempt.started_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                if "idx_attempts_one_running_work_item" in str(error) or "UNIQUE" in str(error):
                    raise ValueError(
                        f"work item already has a running attempt: {work_item}"
                    ) from error
                raise
            self._append_event(
                connection,
                task_id,
                "attempt.started",
                {
                    "attempt_id": attempt.id,
                    "agent": agent,
                    "harness": identity.harness,
                    "provider": identity.provider,
                    "model": identity.model,
                    "kind": identity.kind.value,
                    "work_item": work_item,
                },
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
                "SELECT * FROM attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"attempt not found: {attempt_id}")
            current = self._attempt_from_row(row)
            desired_evidence = evidence or []
            if status is AttemptStatus.SUCCEEDED and not desired_evidence:
                raise ValueError("successful attempts require evidence")
            if current.status is not AttemptStatus.RUNNING:
                if (
                    current.status is status
                    and current.summary == summary
                    and current.evidence == desired_evidence
                    and current.transcript_path == transcript_path
                ):
                    return current
                raise ValueError(f"attempt is already terminal: {attempt_id}")
            finished_at = _now()
            cursor = connection.execute(
                """
                UPDATE attempts
                SET status = ?, summary = ?, evidence_json = ?, transcript_path = ?,
                    finished_at = ?, pid = NULL
                WHERE id = ? AND status = 'running'
                """,
                (
                    status.value,
                    summary,
                    json.dumps(desired_evidence),
                    transcript_path,
                    finished_at,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"attempt changed concurrently: {attempt_id}")
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

    def set_attempt_process(self, attempt_id: str, pid: int) -> AttemptRecord:
        if pid <= 0:
            raise ValueError("pid must be positive")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE attempts SET pid = ? WHERE id = ? AND status = 'running'",
                (pid, attempt_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"running attempt not found: {attempt_id}")
        return self.get_attempt(attempt_id)

    def reconcile_stale_attempts(
        self, *, older_than_seconds: int = 3600, force: bool = False
    ) -> list[AttemptRecord]:
        """Fail running attempts whose owning process is gone or whose lease is stale."""
        if older_than_seconds < 0:
            raise ValueError("older_than_seconds must not be negative")
        now = datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM attempts WHERE status = 'running' ORDER BY started_at"
            ).fetchall()
        reconciled: list[AttemptRecord] = []
        affected_tasks: set[str] = set()
        for row in rows:
            attempt = self._attempt_from_row(row)
            age = (now - attempt.started_at).total_seconds()
            process_alive = attempt.pid is not None and _pid_alive(attempt.pid)
            if not force and (process_alive or age < older_than_seconds):
                continue
            reason = "operator-forced reconciliation" if force else "stale process lease"
            reconciled.append(
                self.finish_attempt(
                    attempt.id,
                    status=AttemptStatus.FAILED,
                    summary=f"Attempt reconciled after {reason}",
                    evidence=[],
                    transcript_path=attempt.transcript_path,
                )
            )
            affected_tasks.add(attempt.task_id)

        for task_id in affected_tasks:
            task = self.get_task(task_id)
            if task.status is not TaskStatus.RUNNING:
                continue
            with self._connect() as connection:
                still_running = connection.execute(
                    "SELECT 1 FROM attempts WHERE task_id = ? AND status = 'running' LIMIT 1",
                    (task_id,),
                ).fetchone()
            if still_running is None:
                self.transition(task_id, TaskStatus.FAILED, reason="stale attempts reconciled")
        return reconciled

    def record_review(
        self,
        task_id: str,
        *,
        reviewer: str,
        verdict: str,
        summary: str,
        attempt_id: str,
        issues: list[str] | None = None,
        evidence: list[str] | None = None,
    ) -> ReviewRecord:
        self.get_task(task_id)
        identity = execution_identity(reviewer)
        assert identity.provider is not None
        if identity.role != "reviewer":
            raise ValueError(f"agent is not a registered reviewer: {reviewer}")
        attempt = self.get_attempt(attempt_id)
        if attempt.task_id != task_id:
            raise ValueError("review attempt belongs to a different task")
        if attempt.kind is not AttemptKind.IMPLEMENTATION:
            raise ValueError("reviews must target an implementation attempt")
        if attempt.status is not AttemptStatus.SUCCEEDED:
            raise ValueError("reviews may approve only a successful implementation attempt")
        if attempt.provider == identity.provider:
            raise ValueError(
                "review intelligence provider must differ from the implementation provider"
            )
        review_evidence = evidence or []
        if verdict == "approve" and not review_evidence:
            raise ValueError("approved reviews require evidence")
        review = ReviewRecord.model_validate(
            {
                "id": _id("rev"),
                "task_id": task_id,
                "attempt_id": attempt_id,
                "reviewer": reviewer,
                "harness": identity.harness,
                "provider": identity.provider,
                "verdict": verdict,
                "summary": summary,
                "issues": issues or [],
                "evidence": review_evidence,
            }
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reviews(
                    id, task_id, attempt_id, reviewer, harness, provider, verdict, summary,
                    issues_json, evidence_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    task_id,
                    attempt_id,
                    reviewer,
                    identity.harness,
                    identity.provider,
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

    def complete_task(self, task_id: str, *, summary: str) -> TaskSpec:
        """Atomically close a task whose latest work attempts all have independent approval."""
        task = self.get_task(task_id)
        if task.status is not TaskStatus.NEEDS_REVIEW:
            raise ValueError("completed tasks must be in needs_review")
        timestamp = _now()
        with self._connect() as connection:
            running = connection.execute(
                """
                SELECT id FROM attempts
                WHERE task_id = ? AND kind = 'implementation' AND status = 'running'
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if running is not None:
                raise ValueError("cannot complete a task with running implementation attempts")

            latest_attempts = connection.execute(
                """
                SELECT a.*
                FROM attempts AS a
                JOIN (
                    SELECT work_item, max(started_at || ':' || id) AS latest
                    FROM attempts
                    WHERE task_id = ? AND kind = 'implementation'
                    GROUP BY work_item
                ) AS latest
                  ON latest.work_item = a.work_item
                 AND latest.latest = a.started_at || ':' || a.id
                WHERE a.task_id = ?
                """,
                (task_id, task_id),
            ).fetchall()
            if not latest_attempts:
                raise ValueError("completed tasks require at least one implementation attempt")

            for attempt_row in latest_attempts:
                attempt = self._attempt_from_row(attempt_row)
                if attempt.status is not AttemptStatus.SUCCEEDED:
                    raise ValueError(
                        f"latest attempt for work item {attempt.work_item!r} did not succeed"
                    )
                review_row = connection.execute(
                    """
                    SELECT * FROM reviews
                    WHERE task_id = ? AND attempt_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (task_id, attempt.id),
                ).fetchone()
                if review_row is None:
                    raise ValueError(f"attempt has no independent review: {attempt.id}")
                review = self._review_from_row(review_row)
                if review.verdict != "approve" or not review.evidence:
                    raise ValueError(f"attempt lacks evidence-backed approval: {attempt.id}")
                if review.provider == attempt.provider:
                    raise ValueError(f"attempt review is not provider-independent: {attempt.id}")

            cursor = connection.execute(
                """
                UPDATE tasks SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    TaskStatus.COMPLETED.value,
                    timestamp,
                    task_id,
                    TaskStatus.NEEDS_REVIEW.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"task changed concurrently: {task_id}")
            self._append_event(
                connection,
                task_id,
                "task.transitioned",
                {
                    "from": TaskStatus.NEEDS_REVIEW.value,
                    "to": TaskStatus.COMPLETED.value,
                    "reason": summary,
                },
            )
        return self.get_task(task_id)

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
            provider=row["provider"],
            model=row["model"],
            kind=AttemptKind(row["kind"]),
            work_item=row["work_item"],
            status=AttemptStatus(row["status"]),
            summary=row["summary"],
            evidence=json.loads(row["evidence_json"]),
            transcript_path=row["transcript_path"],
            pid=row["pid"],
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
            provider=row["provider"],
            verdict=row["verdict"],
            summary=row["summary"],
            issues=json.loads(row["issues_json"]),
            evidence=json.loads(row["evidence_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
