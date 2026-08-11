"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def get_workspace_diff(task_id: str) -> str:
    """Collect bounded status and diff evidence for independent review."""
    return ledger.get_workspace_diff(task_id)
