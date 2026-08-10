# Agent OS Open Source

Agent OS is a deliberately thin multi-agent task system built to measure what
[NVIDIA NOOA](https://github.com/NVIDIA-NeMo/labs-OO-Agents) and
[Omnigent](https://github.com/omnigent-ai/omnigent) already provide. It also evaluates
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) as a persistent, long-running peer
runtime.

NOOA is the source of agent definitions: roles are Python classes, docstrings are prompts, and
typed generation methods are their contracts. A small compiler emits an Omnigent bundle. Omnigent
owns the Claude Code, Codex, and OpenCode multi-harness path, including child sessions, sandboxing,
policies, resume, and independent cross-provider review. OpenCode supplies both a cloud execution
path and an OpenAI-compatible bridge to local Ollama models. Prime Agent optionally owns persistent
goals, autonomous continuation, daemon supervision, IPython context, recursive agents, and recovery.

Agent OS adds only the missing domain layer: a task with an objective, workspace, constraints,
acceptance criteria, attempts, evidence, and review verdicts.

```text
Agent OS task/attempt/review evidence store
                     |
          NOOA typed role definitions
                     |
       +-------------+----------------+
       |                              |
       v                              v
Omnigent bundle                  Prime Agent
Claude + Codex + OpenCode        persistent goal/runtime
cloud + local Ollama             daemon + IPython + RLM
```

## What works

- Five NOOA role definitions, including runtime-specific Omnigent and Prime coordinators.
- Seven Omnigent execution variants, including native Claude Code, Codex, OpenCode, and local
  Ollama environments.
- A durable SQLite task model with explicit state transitions and append-only task events.
- Bounded task-context handoff that preserves the objective and acceptance contract.
- Omnigent function tools that record attempts, evidence, reviews, and closure while agents work.
- Cross-provider review: cloud OpenCode work is reviewed by Claude and local Ollama work by Codex,
  while the existing Claude/Codex pairing remains reciprocal.
- A one-command dry run and live run path with persisted transcripts.
- An optional bounded Prime Agent JSON runtime with persistent goals and autonomous limits.
- Generated-spec drift checking and validation through Omnigent's own loader.

## Install

Python 3.12-3.14, `uv`, Claude Code, and Codex are expected. OpenCode and Ollama are optional
additional environments. Framework versions are pinned to the stable releases studied here: NOOA
0.0.8 and Omnigent 0.8.2. Prime Agent is optional and installed separately; the evaluation used
version 0.7.1.

```bash
uv sync --dev
uv run agent-os init
uv run agent-os doctor
```

Omnigent 0.8.2 requires OpenCode `>=1.17.7,<1.18.0`; the verified installation is:

```bash
npm install --global opencode-ai@1.17.20
```

Omnigent can reuse existing Claude Code and Codex subscription logins. If neither is configured,
run `uv run omnigent setup`.

OpenCode cloud runs use the direct `openai/gpt-5.6-terra` model. Keep its key out of the repository
and inject it from the existing Doppler staging config:

```bash
doppler run --project web-data-projets --config stg -- \
  uv run agent-os run tsk_...
```

The local `builder_ollama` variant is pinned to `ollama/qwen3:14b` and does not need a cloud key.
OpenCode must have an `ollama` provider pointed at `http://localhost:11434/v1`; see
[Provider setup](docs/providers.md) for the exact non-secret config and verification commands.

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

Or use Prime Agent's persistent runtime with explicit limits:

```bash
uv run agent-os run tsk_... --runtime prime-agent \
  --token-budget 80000 --max-turns 12 --timeout-seconds 1800
```

Prime Agent emits JSONL into the attempt transcript and a successful process moves the task only to
`needs_review`. It does not bypass independent review. Prime Agent is not an OS sandbox; use the
Omnigent path or add external containment for untrusted work.

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
roles unusually testable and typed. Omnigent supplies native harness interoperability, sandboxing,
review routing, persistent sessions, policies, and UI. Prime Agent supplies the strongest
long-running local runtime: goals, supervision, schedules, heartbeats, direct messaging, recursive
agents, persistent Python, compaction, refinement, and recovery.

The main missing seam is an explicit unit-of-work model that survives across sessions and binds
acceptance criteria to attempts, review verdicts, and evidence. The second is a bridge from NOOA's
Python-object definitions to Omnigent's YAML agent images. Both are implemented here and measured in
the [custom infrastructure ledger](docs/research/custom-infrastructure-ledger.md).

See also:

- [Architecture](docs/architecture.md)
- [Framework capability map](docs/research/framework-capability-map.md)
- [Upstream research notes](docs/research/upstream-research.md)
- [Verification record](docs/research/verification.md)
- [Prime Agent evaluation](docs/research/prime-agent-evaluation.md)

## Status

This is an early, local-first experiment over two alpha/research frameworks. It is useful for
bounded repository tasks, but it is not a production control plane. In particular, it does not yet
provide distributed task leases, approval delegation, a hosted multi-tenant control plane, or a
protected merge/deploy workflow. Prime Agent's local workers recover, but that is distinct from
remote worker recovery or sandboxed execution.

## License

Apache-2.0.
