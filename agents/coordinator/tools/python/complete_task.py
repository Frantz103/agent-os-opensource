"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def complete_task(task_id: str, status: str, summary: str) -> dict[str, str]:
    """Close a reviewed task with a truthful terminal outcome."""
    return ledger.complete_task(task_id, status, summary)
