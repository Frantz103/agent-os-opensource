# Agent OS Open Source

Agent OS is a deliberately thin multi-agent task system built to measure what
[NVIDIA NOOA](https://github.com/NVIDIA-NeMo/labs-OO-Agents) and
[Omnigent](https://github.com/omnigent-ai/omnigent) already provide.

NOOA is the source of agent definitions: roles are Python classes, docstrings are prompts, and
typed generation methods are their contracts. A small compiler emits an Omnigent bundle. Omnigent
then owns the agent runtime: Claude Code and Codex harnesses, child sessions, inbox delivery,
sandboxing, policies, conversation persistence, resume, and independent cross-vendor review.

Agent OS adds only the missing domain layer: a task with an objective, workspace, constraints,
acceptance criteria, attempts, evidence, and review verdicts.

```text
NOOA classes and typed methods
             |
             | agent-os spec sync
             v
Omnigent coordinator bundle
      |            |
      |            +--> Claude Code builder/reviewer
      +----------------> Codex builder/reviewer
             |
             v
Omnigent sessions + sandbox + policies + resume
             |
             v
Agent OS task/attempt/review evidence store
```

## What works

- Four NOOA role definitions: coordinator, planner, builder, and reviewer.
- Five Omnigent execution variants, including native Claude Code and Codex environments.
- A durable SQLite task model with explicit state transitions and append-only task events.
- Bounded task-context handoff that preserves the objective and acceptance contract.
- Omnigent function tools that record attempts, evidence, reviews, and closure while agents work.
- Cross-vendor review: Claude work is reviewed by Codex and Codex work by Claude.
- A one-command dry run and live run path with persisted transcripts.
- Generated-spec drift checking and validation through Omnigent's own loader.

## Install

Python 3.12-3.14, `uv`, Claude Code, and Codex are expected. Framework versions are pinned to the
stable releases studied here: NOOA 0.0.8 and Omnigent 0.8.2.

```bash
uv sync --dev
uv run agent-os init
uv run agent-os doctor
```

Omnigent can reuse existing Claude Code and Codex subscription logins. If neither is configured,
run `uv run omnigent setup`.

## Create and run a real task

```bash
uv run agent-os task create \
  --title "Add a repository health command" \
  --objective "Add a read-only command that reports config and test readiness." \
  --workspace /path/to/target/repository \
  --accept "The command exits zero when required tools are present" \
  --accept "Tests cover ready and missing-tool cases" \
  --constraint "Do not push, merge, deploy, or contact external services"
```

The command prints a task id. Inspect exactly what the coordinator will receive:

```bash
uv run agent-os context tsk_...
uv run agent-os run tsk_... --dry-run
```

Start the real Omnigent session:

```bash
uv run agent-os run tsk_...
uv run agent-os task show tsk_...
```

Native child harnesses run with Omnigent's automation mode inside an OS sandbox restricted to the
declared workspace and with network disabled. The prompts also prohibit push, merge, deployment,
external mutation, and broad deletion. Change those defaults only after reviewing the generated
bundle under `agents/coordinator/`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run agent-os spec check
uv run python scripts/custom_loc.py
```

`agents/**/config.yaml` is generated. Edit `src/agent_os/definitions.py` or the compiler and run
`uv run agent-os spec sync`; do not hand-edit the bundle.

## Experiment findings

The short answer is that the frameworks provide most agent and harness infrastructure. NOOA makes
roles unusually testable and typed. Omnigent supplies far more multi-agent runtime than a new
project should rebuild: harness adapters, persistent sessions, child delivery, policies, sandboxing,
resume, streaming, and UI.

The main missing seam is an explicit unit-of-work model that survives across sessions and binds
acceptance criteria to attempts, review verdicts, and evidence. The second is a bridge from NOOA's
Python-object definitions to Omnigent's YAML agent images. Both are implemented here and measured in
the [custom infrastructure ledger](docs/research/custom-infrastructure-ledger.md).

See also:

- [Architecture](docs/architecture.md)
- [Framework capability map](docs/research/framework-capability-map.md)
- [Upstream research notes](docs/research/upstream-research.md)
- [Verification record](docs/research/verification.md)

## Status

This is an early, local-first experiment over two alpha/research frameworks. It is useful for
bounded repository tasks, but it is not a production control plane. In particular, it does not yet
provide leases, distributed scheduling, approval delegation, remote worker recovery, or a protected
merge/deploy workflow.

## License

Apache-2.0.
