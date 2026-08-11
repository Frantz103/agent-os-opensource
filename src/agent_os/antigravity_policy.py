"""Pre-tool boundary for the direct Antigravity CLI implementation runtime."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_FILE_ARGUMENTS = {
    "AbsolutePath",
    "Cwd",
    "DirectoryPath",
    "SearchDirectory",
    "SearchPath",
    "TargetFile",
}
_ALLOWED_TOOLS = {
    "command_status",
    "find_by_name",
    "finish",
    "grep_search",
    "list_dir",
    "manage_task",
    "multi_replace_file_content",
    "replace_file_content",
    "run_command",
    "view_file",
    "wait",
    "wait_5_seconds",
    "write_to_file",
}
_FORBIDDEN_COMMAND_FRAGMENTS = (
    "curl ",
    "docker push",
    "git clean",
    "git commit",
    "git merge",
    "git push",
    "git reset",
    "gh ",
    "kubectl ",
    "npm publish",
    "open ",
    "osascript",
    "rm -rf",
    "scp ",
    "ssh ",
    "sudo ",
    "terraform apply",
    "twine upload",
    "wget ",
    "wrangler ",
)


def _inside(path: str, workspace: Path) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        candidate.resolve(strict=False).relative_to(workspace)
    except ValueError:
        return False
    return True


def evaluate(payload: dict[str, Any], workspace: Path) -> dict[str, str]:
    """Return an Antigravity PreToolUse allow/deny decision."""
    workspace = workspace.expanduser().resolve(strict=True)
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return {"decision": "deny", "reason": "missing Agent OS tool-call envelope"}
    name = tool_call.get("name")
    arguments = tool_call.get("args")
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return {"decision": "deny", "reason": "invalid Agent OS tool-call envelope"}
    if name not in _ALLOWED_TOOLS:
        return {"decision": "deny", "reason": f"tool {name!r} is outside the Agent OS runtime"}
    if name == "manage_task" and arguments.get("Action") not in {"list", "status", "kill"}:
        return {"decision": "deny", "reason": "background task mutation is not allowed"}
    for key in _FILE_ARGUMENTS:
        value = arguments.get(key)
        if isinstance(value, str) and value and not _inside(value, workspace):
            return {
                "decision": "deny",
                "reason": f"{key} is outside the declared Agent OS workspace",
            }
    if name == "run_command":
        command = arguments.get("CommandLine")
        if not isinstance(command, str) or not command.strip():
            return {"decision": "deny", "reason": "empty command is not allowed"}
        normalized = f" {command.lower().strip()} "
        if any(fragment in normalized for fragment in _FORBIDDEN_COMMAND_FRAGMENTS):
            return {"decision": "deny", "reason": "outward or destructive command denied"}
    return {"decision": "allow", "reason": "allowed by the bounded Agent OS runtime"}


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"decision": "deny", "reason": "workspace argument required"}))
        return 2
    if os.environ.get("AGENT_OS_ANTIGRAVITY_POLICY_TOKEN") != sys.argv[2]:
        # The temporary global plugin may be discovered by a concurrently launched ordinary AGY
        # session. Empty output leaves that session's normal permission policy unchanged.
        return 0
    try:
        payload = json.load(sys.stdin)
        decision = evaluate(payload, Path(sys.argv[1]))
    except Exception as error:
        decision = {"decision": "deny", "reason": f"Agent OS policy error: {type(error).__name__}"}
    print(json.dumps(decision, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
