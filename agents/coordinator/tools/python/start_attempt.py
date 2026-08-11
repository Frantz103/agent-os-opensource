"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


@tool
def start_attempt(
    task_id: str, agent: str, work_item: str = "primary"
) -> dict[str, str]:
    """Create an attributed attempt before child-agent dispatch."""
    return ledger.start_attempt(task_id, agent, work_item)
