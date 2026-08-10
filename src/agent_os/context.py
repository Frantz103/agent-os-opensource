"""Deterministic task context handoff into an Omnigent session."""

from __future__ import annotations

import json

from agent_os.store import TaskStore

DEFAULT_MAX_CONTEXT_CHARS = 16_000


def build_task_context(
    store: TaskStore, task_id: str, *, max_chars: int = DEFAULT_MAX_CONTEXT_CHARS
) -> str:
    """Render stable task truth plus bounded recent attempt and review evidence."""
    task = store.get_task(task_id)
    criteria = "\n".join(f"- {item}" for item in task.acceptance_criteria)
    constraints = "\n".join(f"- {item}" for item in task.constraints) or "- None recorded"
    supplied_context = json.dumps(task.context, indent=2, sort_keys=True) if task.context else "{}"
    contract = f"""# Agent OS task contract

Task ID: {task.id}
Title: {task.title}
Status: {task.status.value}
Workspace: {task.workspace}

## Objective

{task.objective}

## Acceptance criteria

{criteria}

## Constraints

{constraints}

## Operator-supplied context

```json
{supplied_context}
```
"""
    history_parts: list[str] = []
    for attempt in store.list_attempts(task_id)[-8:]:
        evidence = "\n".join(f"  - {item}" for item in attempt.evidence) or "  - None"
        history_parts.append(
            f"### Attempt {attempt.id}\n"
            f"- Agent/harness: {attempt.agent} / {attempt.harness}\n"
            f"- Status: {attempt.status.value}\n"
            f"- Summary: {attempt.summary or 'No summary yet'}\n"
            f"- Evidence:\n{evidence}"
        )
    for review in store.list_reviews(task_id)[-8:]:
        issues = "\n".join(f"  - {item}" for item in review.issues) or "  - None"
        history_parts.append(
            f"### Review {review.id}\n"
            f"- Reviewer/harness: {review.reviewer} / {review.harness}\n"
            f"- Verdict: {review.verdict}\n"
            f"- Summary: {review.summary}\n"
            f"- Issues:\n{issues}"
        )

    if not history_parts:
        return contract + "\n## Prior attempts and reviews\n\nNone.\n"

    heading = "\n## Prior attempts and reviews\n\n"
    remaining = max(max_chars - len(contract) - len(heading), 0)
    kept: list[str] = []
    for part in reversed(history_parts):
        candidate = "\n\n".join(reversed([part, *kept]))
        if len(candidate) > remaining:
            break
        kept.insert(0, part)
    omitted = len(history_parts) - len(kept)
    prefix = f"{omitted} older record(s) omitted by the context budget.\n\n" if omitted else ""
    return contract + heading + prefix + "\n\n".join(kept) + "\n"
