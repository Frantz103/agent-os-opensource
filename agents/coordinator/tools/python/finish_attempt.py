"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def finish_attempt(
    attempt_id: str,
    status: str,
    summary: str,
    child_task_status: str,
    evidence: list[str] | None = None,
) -> dict[str, str]:
    """Finalize an attempt after its child task reaches a terminal status."""
    return ledger.finish_attempt(
        attempt_id, status, summary, child_task_status, evidence
    )
