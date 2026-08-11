"""Generated Agent OS ledger tool for Omnigent runtime discovery."""

from omnigent_client.tools import tool

from agent_os import tools as ledger


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
