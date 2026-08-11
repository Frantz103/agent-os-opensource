"""Runtime policies that bind Omnigent child dispatches to durable task evidence."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_os.execution import execution_identity
from agent_os.models import AttemptKind, AttemptStatus
from agent_os.store import TaskStore

_ATTEMPT_ID = re.compile(r"\batt_[0-9a-f]+\b")


def _decision(result: str, reason: str | None = None) -> dict[str, str]:
    decision = {"result": result}
    if reason is not None:
        decision["reason"] = reason
    return decision


def attempt_before_dispatch() -> Callable[[dict[str, Any]], dict[str, str]]:
    """Require durable implementation and review evidence before child dispatch."""

    def evaluate(event: dict[str, Any]) -> dict[str, str]:
        if event.get("type") != "tool_call":
            return _decision("ALLOW")
        data = event.get("data")
        if not isinstance(data, dict) or data.get("name") != "sys_session_send":
            return _decision("ALLOW")
        arguments = data.get("arguments")
        if not isinstance(arguments, dict):
            return _decision("ALLOW")
        child_args = arguments.get("args")
        if not isinstance(child_args, dict):
            return _decision("ALLOW")
        purpose = child_args.get("purpose")
        if purpose not in {"implement", "review"}:
            return _decision("ALLOW")

        state_dir = os.environ.get("AGENT_OS_STATE_DIR")
        task_id = os.environ.get("AGENT_OS_TASK_ID")
        if not state_dir or not task_id:
            return _decision("DENY", "Agent OS task identity is unavailable; dispatch denied.")
        agent = arguments.get("agent")
        if not isinstance(agent, str):
            return _decision("DENY", "A named Agent OS child is required for governed dispatch.")

        try:
            store = TaskStore(Path(state_dir))
            attempts = store.list_attempts(task_id)
        except Exception as error:
            return _decision("DENY", f"Agent OS ledger could not be read: {type(error).__name__}.")

        prompt = child_args.get("input")
        attempt_ids = _ATTEMPT_ID.findall(prompt) if isinstance(prompt, str) else []

        if purpose == "implement":
            eligible = {
                attempt.id: attempt
                for attempt in attempts
                if attempt.agent == agent
                and attempt.kind is AttemptKind.IMPLEMENTATION
                and attempt.status is AttemptStatus.RUNNING
            }
            if len(attempt_ids) != 1 or attempt_ids[0] not in eligible:
                return _decision(
                    "DENY",
                    "Implementation dispatch must name exactly one matching running attempt id "
                    f"created by start_attempt for agent {agent!r}.",
                )
            return _decision("ALLOW")

        successful = {
            attempt.id: attempt
            for attempt in attempts
            if attempt.kind is AttemptKind.IMPLEMENTATION
            and attempt.status is AttemptStatus.SUCCEEDED
        }
        if len(attempt_ids) != 1 or attempt_ids[0] not in successful:
            return _decision(
                "DENY",
                "Review dispatch must name exactly one successful implementation attempt id.",
            )
        matched = successful[attempt_ids[0]]
        try:
            reviewer = execution_identity(agent)
        except ValueError:
            return _decision("DENY", f"Unknown review agent {agent!r}.")
        if reviewer.role != "reviewer":
            return _decision("DENY", f"Agent {agent!r} is not a registered reviewer.")
        if reviewer.provider == matched.provider:
            return _decision(
                "DENY",
                "Reviewer intelligence provider must differ from the implementation provider.",
            )
        return _decision("ALLOW")

    return evaluate
