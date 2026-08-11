"""Generated Agent OS ledger tools for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def get_task_context(task_id: str) -> str:
    """Load the authoritative task contract and prior evidence."""
    return ledger.get_task_context(task_id)


@tool
def start_attempt(task_id: str, agent: str, work_item: str = "primary") -> dict[str, str]:
    """Create an attributed attempt before child-agent dispatch."""
    return ledger.start_attempt(task_id, agent, work_item)


@tool
def finish_attempt(
    attempt_id: str,
    status: str,
    summary: str,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Finalize a child attempt with status, summary, and evidence."""
    return ledger.finish_attempt(attempt_id, status, summary, evidence)


@tool
def record_review(
    task_id: str,
    attempt_id: str,
    reviewer: str,
    verdict: str,
    summary: str,
    issues: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Persist an independent review verdict and its evidence."""
    return ledger.record_review(
        task_id,
        reviewer,
        verdict,
        summary,
        attempt_id,
        issues,
        evidence,
    )


@tool
def complete_task(task_id: str, status: str, summary: str) -> dict[str, str]:
    """Close a reviewed task with a truthful terminal outcome."""
    return ledger.complete_task(task_id, status, summary)
