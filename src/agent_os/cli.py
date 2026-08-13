"""Command-line interface for task records, bundle generation, and execution."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from omnigent.opencode_native_app_server import (
    OpenCodeVersionError,
    check_opencode_version,
    resolve_opencode_version,
)

from agent_os import __version__
from agent_os.context import build_task_context
from agent_os.models import TaskStatus
from agent_os.runner import (
    RunPlan,
    check_antigravity_version,
    find_antigravity_cli,
    find_omnigent_cli,
    find_prime_agent_cli,
    resolve_antigravity_version,
    run_task,
)
from agent_os.specs import VARIANTS, check_specs, sync_specs, validate_bundle
from agent_os.store import TaskStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--state-dir", type=Path, help="State directory (default: .agent-os)")
    parser.add_argument(
        "--bundle",
        type=Path,
        help="Generated bundle directory (default: STATE_DIR/bundles/coordinator)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize state and generate the Omnigent bundle")
    sub.add_parser("agents", help="List NOOA-defined runtime agent variants")
    sub.add_parser("doctor", help="Check framework CLIs and validate the bundle")

    spec = sub.add_parser("spec", help="Manage generated Omnigent agent specs")
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    spec_sub.add_parser("sync")
    spec_sub.add_parser("check")

    task = sub.add_parser("task", help="Create and inspect durable tasks")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    create = task_sub.add_parser("create")
    create.add_argument("--title", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument("--workspace", required=True, type=Path)
    create.add_argument("--accept", action="append", required=True, dest="acceptance")
    create.add_argument("--constraint", action="append", default=[])
    create.add_argument("--context", action="append", default=[], metavar="KEY=VALUE")
    listing = task_sub.add_parser("list")
    listing.add_argument("--status", choices=[status.value for status in TaskStatus])
    show = task_sub.add_parser("show")
    show.add_argument("task_id")
    reconcile = task_sub.add_parser("reconcile")
    reconcile.add_argument("--older-than-seconds", type=int, default=3600)
    reconcile.add_argument("--force", action="store_true")

    context = sub.add_parser("context", help="Render the task context envelope")
    context.add_argument("task_id")
    run = sub.add_parser(
        "run", help="Execute through Omnigent, OpenCode, Codex, Antigravity, or Prime Agent"
    )
    run.add_argument("task_id")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--runtime",
        choices=[
            "omnigent",
            "opencode",
            "antigravity",
            "codex",
            "codex-review",
            "prime-agent",
        ],
        default="omnigent",
    )
    run.add_argument(
        "--provider",
        help="OpenCode or Prime Agent intelligence provider (required for Prime)",
    )
    run.add_argument(
        "--model", help="OpenCode, Prime Agent, Antigravity, or Codex model identifier"
    )
    run.add_argument(
        "--show-prompt",
        action="store_true",
        help="Include sensitive task context in dry-run command output",
    )
    run.add_argument("--token-budget", type=int, default=80_000, help="Prime Agent token budget")
    run.add_argument("--max-turns", type=int, default=12, help="Prime Agent turn limit")
    run.add_argument(
        "--timeout-seconds",
        type=int,
        default=1_800,
        help="Wall-clock timeout (Omnigent 0.8.2 maximum: 1800 seconds)",
    )
    return parser


def _parse_context(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"context must use KEY=VALUE: {value}")
        key, item = value.split("=", 1)
        result[key.strip()] = item.strip()
    return result


def _task_json(store: TaskStore, task_id: str) -> str:
    task = store.get_task(task_id)
    payload = task.model_dump(mode="json")
    payload["attempts"] = [item.model_dump(mode="json") for item in store.list_attempts(task_id)]
    payload["reviews"] = [item.model_dump(mode="json") for item in store.list_reviews(task_id)]
    payload["events"] = store.list_events(task_id)
    return json.dumps(payload, indent=2)


def _doctor(bundle: Path) -> int:
    failures: list[str] = []
    checks = {
        "omnigent": find_omnigent_cli(),
        "claude": shutil.which("claude"),
        "codex": shutil.which("codex"),
    }
    for name, path in checks.items():
        print(f"{name:10} {'OK ' + path if path else 'MISSING'}")
        if path is None:
            failures.append(f"{name} is required and was not found on PATH")
    opencode = shutil.which("opencode")
    if opencode:
        try:
            version = resolve_opencode_version(opencode)
            check_opencode_version(version)
            print(f"{'opencode':10} OK {opencode} ({version})")
        except (OSError, OpenCodeVersionError) as error:
            failures.append(f"opencode is installed but unusable: {error}")
            print(f"{'opencode':10} INCOMPATIBLE {error}")
    else:
        print(f"{'opencode':10} OPTIONAL MISSING")

    antigravity = find_antigravity_cli()
    if antigravity:
        try:
            version = resolve_antigravity_version(antigravity)
            check_antigravity_version(version)
            rendered = ".".join(str(part) for part in version)
            print(f"{'antigravity':10} OK {antigravity} ({rendered})")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(f"antigravity is installed but unusable: {error}")
            print(f"{'antigravity':10} INCOMPATIBLE {error}")
    else:
        print(f"{'antigravity':10} OPTIONAL MISSING")

    optional_checks = {
        "prime-agent": find_prime_agent_cli(),
        "ollama": shutil.which("ollama"),
        "doppler": shutil.which("doppler"),
    }
    for name, path in optional_checks.items():
        print(f"{name:10} {'OK ' + path if path else 'OPTIONAL MISSING'}")
    try:
        validate_bundle(bundle)
        print(f"bundle     OK {bundle}")
    except Exception as error:
        failures.append(f"bundle {bundle} did not validate: {type(error).__name__}: {error}")
        print(f"bundle     INVALID {type(error).__name__}: {error}")

    if not failures:
        return 0
    print()
    print("doctor failed:")
    for item in failures:
        print(f"  - {item}")
    print(
        "An optional runtime is safe to leave uninstalled, but one that is installed must also be "
        "a supported version, because Agent OS may route work to it. Remove it or install a "
        "supported release; see docs/providers.md."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = TaskStore(args.state_dir)
    bundle = args.bundle or store.state_dir / "bundles" / "coordinator"

    try:
        if args.command == "init":
            store.initialize()
            written = sync_specs(bundle)
            validate_bundle(bundle)
            print(f"state: {store.db_path}")
            print(f"bundle: {bundle} ({len(written)} file(s) written)")
            return 0

        if args.command == "agents":
            print("coordinator\tclaude-sdk\tNOOA CoordinatorAgent")
            print("prime_coordinator\tprime-agent\tNOOA PrimeCoordinatorAgent")
            print("builder_antigravity\tantigravity-cli\tNOOA BuilderAgent")
            for variant in VARIANTS:
                print(f"{variant.name}\t{variant.harness}\tNOOA {variant.definition.__name__}")
            return 0

        if args.command == "doctor":
            return _doctor(bundle)

        if args.command == "spec":
            if args.spec_command == "sync":
                written = sync_specs(bundle)
                validate_bundle(bundle)
                print(f"synced {len(written)} file(s); Omnigent validation passed")
                return 0
            drifted = check_specs(bundle)
            if drifted:
                print("generated specs are stale:")
                for path in drifted:
                    print(path)
                return 1
            validate_bundle(bundle)
            print("generated specs match NOOA definitions; Omnigent validation passed")
            return 0

        if args.command == "task":
            if args.task_command == "create":
                task = store.create_task(
                    title=args.title,
                    objective=args.objective,
                    workspace=args.workspace,
                    acceptance_criteria=args.acceptance,
                    constraints=args.constraint,
                    context=_parse_context(args.context),
                )
                print(task.id)
                return 0
            if args.task_command == "list":
                status = TaskStatus(args.status) if args.status else None
                for task in store.list_tasks(status):
                    print(f"{task.id}\t{task.status.value}\t{task.title}\t{task.workspace}")
                return 0
            if args.task_command == "reconcile":
                reconciled = store.reconcile_stale_attempts(
                    older_than_seconds=args.older_than_seconds,
                    force=args.force,
                )
                for attempt in reconciled:
                    print(f"{attempt.id}\t{attempt.task_id}\t{attempt.status.value}")
                print(f"reconciled {len(reconciled)} attempt(s)")
                return 0
            print(_task_json(store, args.task_id))
            return 0

        if args.command == "context":
            print(build_task_context(store, args.task_id), end="")
            return 0

        if args.command == "run":
            result = run_task(
                store,
                args.task_id,
                bundle,
                dry_run=args.dry_run,
                runtime=args.runtime,
                token_budget=args.token_budget,
                max_turns=args.max_turns,
                timeout_seconds=args.timeout_seconds,
                provider=args.provider,
                model=args.model,
            )
            if isinstance(result, RunPlan):
                print(f"cwd: {result.cwd}")
                print(f"runtime: {result.runtime}")
                print(f"identity: {result.agent}/{result.harness}/{result.provider}")
                print(f"model: {result.model or 'runtime default'}")
                print(f"command: {result.shell_command(reveal_context=args.show_prompt)}")
                return 0
            return result
    except (KeyError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
