"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def get_task_context(task_id: str) -> str:
    """Load the authoritative task contract and prior evidence."""
    return ledger.get_task_context(task_id)
