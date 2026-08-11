from __future__ import annotations

from pathlib import Path

from agent_os.models import AttemptStatus, TaskStatus
from agent_os.policies import attempt_before_dispatch
from agent_os.store import TaskStore


def _dispatch(agent: str, purpose: str, prompt: str = "work") -> dict:
    return {
        "type": "tool_call",
        "data": {
            "name": "sys_session_send",
            "arguments": {
                "agent": agent,
                "args": {"purpose": purpose, "input": prompt},
            },
        },
    }


def _running_task(tmp_path: Path, monkeypatch) -> tuple[TaskStore, str]:
    state_dir = tmp_path / "state"
    store = TaskStore(state_dir)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    task = store.create_task(
        title="Govern dispatch",
        objective="Bind child work to durable evidence.",
        workspace=workspace,
        acceptance_criteria=["Dispatch is attributed"],
    )
    store.transition(task.id, TaskStatus.RUNNING)
    monkeypatch.setenv("AGENT_OS_STATE_DIR", str(state_dir))
    monkeypatch.setenv("AGENT_OS_TASK_ID", task.id)
    return store, task.id


def test_implementation_dispatch_requires_matching_running_attempt(tmp_path, monkeypatch) -> None:
    store, task_id = _running_task(tmp_path, monkeypatch)
    policy = attempt_before_dispatch()
    event = _dispatch("builder_ollama", "implement")

    denied = policy(event)
    assert denied["result"] == "DENY"
    assert "start_attempt" in denied["reason"]

    attempt = store.start_attempt(task_id, agent="builder_ollama", work_item="primary")
    prompt = f"Implement exact attempt {attempt.id}."
    assert policy(_dispatch("builder_ollama", "implement", prompt)) == {"result": "ALLOW"}
    assert policy(_dispatch("builder_codex", "implement", prompt))["result"] == "DENY"


def test_implementation_dispatch_rejects_ambiguous_attempt_ids(tmp_path, monkeypatch) -> None:
    store, task_id = _running_task(tmp_path, monkeypatch)
    first = store.start_attempt(task_id, agent="builder_ollama", work_item="first")
    second = store.start_attempt(task_id, agent="builder_ollama", work_item="second")
    event = _dispatch(
        "builder_ollama",
        "implement",
        f"Implement {first.id}; related attempt {second.id}.",
    )

    assert attempt_before_dispatch()(event)["result"] == "DENY"

    repeated = _dispatch(
        "builder_ollama",
        "implement",
        f"Implement {first.id}; evidence must also name {first.id}.",
    )
    assert attempt_before_dispatch()(repeated)["result"] == "DENY"


def test_review_dispatch_requires_exact_successful_cross_provider_attempt(
    tmp_path, monkeypatch
) -> None:
    store, task_id = _running_task(tmp_path, monkeypatch)
    implementation = store.start_attempt(
        task_id, agent="builder_ollama", work_item="primary"
    )
    store.finish_attempt(
        implementation.id,
        status=AttemptStatus.SUCCEEDED,
        summary="implemented",
        evidence=["tests passed"],
    )
    policy = attempt_before_dispatch()

    assert policy(_dispatch("reviewer_codex", "review"))["result"] == "DENY"
    prompt = f"Review exact implementation attempt {implementation.id}."
    assert policy(_dispatch("reviewer_codex", "review", prompt)) == {"result": "ALLOW"}
    assert policy(_dispatch("reviewer_claude", "review", prompt)) == {"result": "ALLOW"}


def test_review_dispatch_rejects_same_provider(tmp_path, monkeypatch) -> None:
    store, task_id = _running_task(tmp_path, monkeypatch)
    implementation = store.start_attempt(task_id, agent="builder_codex", work_item="primary")
    store.finish_attempt(
        implementation.id,
        status=AttemptStatus.SUCCEEDED,
        summary="implemented",
        evidence=["tests passed"],
    )
    event = _dispatch(
        "reviewer_codex",
        "review",
        f"Review exact implementation attempt {implementation.id}.",
    )

    denied = attempt_before_dispatch()(event)
    assert denied["result"] == "DENY"
    assert "provider must differ" in denied["reason"]
