# Agent OS Open Source

Agent OS is a deliberately thin multi-agent task system built to measure what
[NVIDIA NOOA](https://github.com/NVIDIA-NeMo/labs-OO-Agents) and
[Omnigent](https://github.com/omnigent-ai/omnigent) already provide. It also evaluates
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) as a persistent, long-running peer
runtime.

NOOA is the source of agent definitions: roles are Python classes, docstrings are prompts, and
typed generation methods are their contracts. A small compiler emits an Omnigent bundle. Omnigent
owns the Claude SDK, Codex, and OpenCode multi-harness path, including child
sessions, sandboxing, policies, resume, and independent cross-provider review. OpenCode supplies both a cloud execution
path and an OpenAI-compatible bridge to local Ollama models. Prime Agent optionally owns persistent
goals, autonomous continuation, daemon supervision, IPython context, recursive agents, and recovery.
Agent OS also provides a bounded direct Antigravity CLI implementation path that reuses an existing
Google subscription login and hands the result to a direct, ephemeral Codex reviewer.

Agent OS adds only the missing domain layer: a task with an objective, workspace, constraints,
acceptance criteria, attempts, evidence, and review verdicts.

```text
Agent OS task/attempt/review evidence store
                     |
          NOOA typed role definitions
                     |
       +-------------+----------------+----------------+
       |                              |                |
       v                              v                v
Omnigent bundle             Prime Agent       Antigravity CLI
Claude + Codex              persistent goal   Google implementation
OpenCode + local Ollama     daemon + RLM       Codex review handoff
```

## What works

- Five NOOA role definitions, including runtime-specific Omnigent and Prime coordinators.
- Seven generated Omnigent child variants spanning Claude SDK, Codex subprocess, native OpenCode,
  and local Ollama environments.
- A durable SQLite task model with explicit state transitions and append-only task events.
- Bounded task-context handoff that preserves the objective and acceptance contract.
- Omnigent function tools that record attempts, evidence, reviews, and closure while agents work.
- Bounded host-generated status/diff evidence for reviewers, without exposing `.git` history or
  user Git configuration to model sandboxes.
- A fail-closed dispatch policy that requires recorded implementation attempts and exact-attempt,
  different-provider review before the corresponding child sessions can launch.
- OpenCode build sessions deny ambient host skills without changing global OpenCode configuration.
- Cross-provider review: cloud OpenCode work is reviewed by Claude and local Ollama work by Codex,
  while the existing Claude/Codex pairing remains reciprocal.
- A one-command dry run and live run path with persisted transcripts.
- An optional bounded Prime Agent JSON runtime with persistent goals and autonomous limits.
- A direct, subscription-backed Antigravity CLI implementation runtime with structured output,
  sandboxing, pre-tool policy enforcement, and durable Google provider attribution.
- Generated-spec drift checking and validation through Omnigent's own loader.

## Status

Agent OS `0.1.0a1` is a local-first public alpha for bounded repository work. It is not a hosted,
multi-tenant, or unattended production control plane. The task ledger, sandboxed Omnigent and
Antigravity paths, provider-independent review gate, and bounded Prime Agent path are the supported
surface.

## Install

Python 3.12-3.13, `uv`, Claude Code, and Codex are expected. OpenCode, Ollama, Antigravity CLI, and
Prime Agent are optional additional environments. Framework versions are pinned to the stable
releases studied here: NOOA 0.0.8 and Omnigent 0.8.2. Prime Agent is installed separately; the
evaluation used version 0.7.1. The direct Antigravity path requires `agy>=1.1.6` and an existing CLI
login.

```bash
uv sync --dev
uv run agent-os init
uv run agent-os doctor
```

Omnigent 0.8.2 requires OpenCode `>=1.17.7,<1.18.0`; the verified installation is:

```bash
npm install --global opencode-ai@1.17.20
```

Omnigent reuses Claude Code and Codex subscription logins. Agent OS intentionally does not forward
a raw Anthropic API key to Omnigent 0.8.2 because upstream may expose it in a process argument. Run
`claude` and use `/login` before the first live task; see [Provider setup](docs/providers.md).

OpenCode cloud runs default to `openai/gpt-5`. Select another public OpenCode provider/model before
generating the bundle with `AGENT_OS_OPENCODE_MODEL`, and inject only that provider's credential:

```bash
export AGENT_OS_OPENCODE_MODEL="openai/gpt-5"
export OPENAI_API_KEY="..."  # preferably injected by your secret manager
uv run agent-os init
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

The default coordinator and planner use Claude subscriptions. When Claude capacity is unavailable,
Codex or Antigravity can perform a direct implementation using an existing CLI subscription login.
Both record an implementation attempt and move the task to `needs_review`; neither approves its
own work. Direct Codex uses the same workspace-write baseline as Antigravity:

```bash
uv run agent-os run tsk_... --runtime codex
uv run agent-os run tsk_... --runtime antigravity
uv run agent-os run tsk_... --runtime codex-review
```

This is an explicit recovery workflow, not an automatic retry: Agent OS does not launch a second
runtime after a capacity failure because the first process may already have started durable child
work. An OpenAI-backed direct Codex implementation requires a later non-OpenAI reviewer. The direct
Codex reviewer is instead for successful non-OpenAI implementations; it uses Sol by default and can
be overridden to Terra or Luna with `--model` or `AGENT_OS_CODEX_REVIEWER_MODEL`.

This direct runtime deliberately does not use Omnigent's Antigravity SDK harness: that upstream
path requires a Gemini API key or Vertex credentials rather than the CLI subscription session. See
[Provider setup](docs/providers.md) for the sandbox, policy, model override, and compatibility
details.

Or use Prime Agent's persistent runtime with explicit limits:

```bash
uv run agent-os run tsk_... --runtime prime-agent \
  --provider openai --model openai/gpt-5 \
  --token-budget 80000 --max-turns 12 --timeout-seconds 1800
```

Prime Agent emits JSONL into the attempt transcript and a successful process moves the task only to
`needs_review`. It does not bypass independent review. Prime Agent is not an OS sandbox; use the
Omnigent path or add external containment for untrusted work.

Child harnesses run with Omnigent's automation mode and OS helpers restricted to the declared
workspace with arbitrary tool network egress denied. For Claude SDK children, Omnigent keeps the
provider client outside the OS helper, disables native Claude tools, and routes file and shell work
through its sandboxed `sys_os_*` helpers. Agent OS likewise disables Codex's native shell and web
search so Codex repository work uses those constrained dynamic tools.
The prompts also prohibit push, merge, deployment,
external mutation, and broad deletion. Change those defaults only after reviewing the generated
bundle under `agents/coordinator/`.

## Development

```bash
uv run pytest
uv run ruff check .
uv run agent-os --bundle agents/coordinator spec check
uv run python scripts/custom_loc.py
```

`agents/**/config.yaml` is generated. Edit `src/agent_os/definitions.py` or the compiler and run
`uv run agent-os --bundle agents/coordinator spec sync`; do not hand-edit the bundle.

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

## Safety and support

Read the [threat model](docs/threat-model.md), [data-handling contract](docs/data-handling.md),
[security policy](SECURITY.md), and [support policy](SUPPORT.md) before enabling a live model run.
Agent OS does not provide distributed leases, approval delegation, multi-tenant authentication, or
a protected merge/deploy workflow. Prime Agent inherits the invoking user's permissions and is not
an OS sandbox.

## License

Apache-2.0.
