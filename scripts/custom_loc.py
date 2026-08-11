"""Report source LOC for each manual-infrastructure seam in the experiment ledger."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEAMS = {
    "execution identity registry": ["src/agent_os/execution.py"],
    "typed task contracts": ["src/agent_os/models.py"],
    "domain task persistence": ["src/agent_os/store.py"],
    "cross-session context envelope": ["src/agent_os/context.py"],
    "NOOA-to-Omnigent compiler": ["src/agent_os/specs.py"],
    "Omnigent task tool bridge": ["src/agent_os/tools.py"],
    "governed child-dispatch policy": ["src/agent_os/policies.py"],
    "Antigravity pre-tool policy": ["src/agent_os/antigravity_policy.py"],
    "multi-runtime process launcher": ["src/agent_os/runner.py"],
    "operator task CLI": ["src/agent_os/cli.py"],
    "gap measurement": ["scripts/custom_loc.py"],
}


def source_lines(path: Path) -> int:
    return sum(
        1
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def main() -> None:
    print("| Manual seam | Source LOC | Paths |")
    print("| --- | ---: | --- |")
    total = 0
    for seam, paths in SEAMS.items():
        count = sum(source_lines(ROOT / path) for path in paths)
        total += count
        print(f"| {seam} | {count} | {', '.join(f'`{path}`' for path in paths)} |")
    print(f"| **Total** | **{total}** | |")


if __name__ == "__main__":
    main()
