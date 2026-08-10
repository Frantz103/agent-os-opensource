"""Command-line interface for task records, bundle generation, and execution."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from agent_os.context import build_task_context
from agent_os.models import TaskStatus
from agent_os.runner import RunPlan, find_omnigent_cli, run_task
from agent_os.specs import VARIANTS, check_specs, sync_specs, validate_bundle
from agent_os.store import TaskStore

DEFAULT_BUNDLE = Path(__file__).resolve().parents[2] / "agents" / "coordinator"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-os", description=__doc__)
    parser.add_argument("--state-dir", type=Path, help="State directory (default: .agent-os)")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize state and generate the Omnigent bundle")
    sub.add_parser("agents", help="List NOOA-defined Omnigent agent variants")
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

    context = sub.add_parser("context", help="Render the task context envelope")
    context.add_argument("task_id")
    run = sub.add_parser("run", help="Execute a task through Omnigent")
    run.add_argument("task_id")
    run.add_argument("--dry-run", action="store_true")
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
    checks = {
        "omnigent": find_omnigent_cli(),
        "claude": shutil.which("claude"),
        "codex": shutil.which("codex"),
    }
    ok = True
    for name, path in checks.items():
        print(f"{name:10} {'OK ' + path if path else 'MISSING'}")
        ok = ok and path is not None
    try:
        validate_bundle(bundle)
        print(f"bundle     OK {bundle}")
    except Exception as error:
        ok = False
        print(f"bundle     INVALID {type(error).__name__}: {error}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = TaskStore(args.state_dir)

    try:
        if args.command == "init":
            store.initialize()
            written = sync_specs(args.bundle)
            validate_bundle(args.bundle)
            print(f"state: {store.db_path}")
            print(f"bundle: {args.bundle} ({len(written)} file(s) written)")
            return 0

        if args.command == "agents":
            print("coordinator\tclaude-sdk\tNOOA CoordinatorAgent")
            for variant in VARIANTS:
                print(f"{variant.name}\t{variant.harness}\tNOOA {variant.definition.__name__}")
            return 0

        if args.command == "doctor":
            return _doctor(args.bundle)

        if args.command == "spec":
            if args.spec_command == "sync":
                written = sync_specs(args.bundle)
                validate_bundle(args.bundle)
                print(f"synced {len(written)} file(s); Omnigent validation passed")
                return 0
            drifted = check_specs(args.bundle)
            if drifted:
                print("generated specs are stale:")
                for path in drifted:
                    print(path)
                return 1
            validate_bundle(args.bundle)
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
            print(_task_json(store, args.task_id))
            return 0

        if args.command == "context":
            print(build_task_context(store, args.task_id), end="")
            return 0

        if args.command == "run":
            result = run_task(store, args.task_id, args.bundle, dry_run=args.dry_run)
            if isinstance(result, RunPlan):
                print(f"cwd: {result.cwd}")
                print(f"command: {result.shell_command()}")
                return 0
            return result
    except (KeyError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
