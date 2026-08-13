# Agent OS Open Source

Agent OS is a local-first execution and review layer for teams using more than one AI coding
runtime. It lets Claude, Codex, OpenCode, Ollama, Antigravity, and Prime Agent work against one
durable task contract instead of leaving task state scattered across unrelated sessions.

Most coding harnesses optimize a single agent session. Agent OS is for work that must survive
provider limits, process crashes, runtime handoffs, and independent review without losing the
acceptance contract or confusing a model response with completed work.

Every task has an objective, workspace, constraints, acceptance criteria, attributed attempts,
evidence, and review verdicts. A successful process is not enough to close the task: the exact
implementation attempt must produce evidence and receive approval from a reviewer backed by a
different model provider.

Use Agent OS when you need to:

- switch runtimes when a provider is unavailable without losing task history or repeating work;
- combine local models with cloud coding agents while preserving the real provider/model identity;
- keep an inspectable audit trail of what changed, what was verified, and who approved it;
- recover cleanly from interrupted processes, stale attempts, and concurrent workers; or
- enforce bounded repository work without granting agents permission to push, merge, or deploy.

Under the hood, [NVIDIA NOOA](https://github.com/NVIDIA-NeMo/labs-OO-Agents) defines typed agent
roles, [Omnigent](https://github.com/omnigent-ai/omnigent) runs the sandboxed multi-harness graph,
and [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) provides an optional persistent
runtime. Agent OS joins those capabilities with the durable task ledger and independent review gate
needed to operate them as one workflow.

```text
Agent OS task/attempt/review evidence store
                     |
          NOOA typed role definitions
                     |
       +-------------+----------------+----------------+----------------+
       |                              |                |                |
       v                              v                v                v
Omnigent bundle             Prime Agent       OpenCode CLI     Codex / Antigravity
Claude + Codex              persistent goal   local or cloud   direct implementations
OpenCode + local Ollama     daemon + RLM       bounded worker   review handoff
```

## Why teams would use it

- **One source of task truth.** SQLite-backed tasks, attempts, reviews, and append-only events
  survive across harness sessions and provider changes.
- **Provider-independent approval.** The review gate binds a verdict to the exact implementation
  attempt and rejects reviewers backed by the same provider.
- **Practical fallback paths.** Move from Claude coordination to direct OpenCode/Ollama, Codex, or
  Antigravity execution without silently retrying or erasing earlier failures.
- **Evidence before completion.** Reviewers receive bounded working-tree evidence and verification
  results; an exit code or model claim cannot complete a task by itself.
- **Fail-closed recovery.** Private transcripts, crash reconciliation, concurrent work exclusion,
  terminal-event validation, and explicit state transitions prevent ambiguous completion.
- **Local and cloud choice.** Use a local Ollama builder, subscription-backed CLIs, or cloud models
  while recording the harness, provider, and model that actually performed the work.
- **Inspectable configuration.** Typed NOOA roles compile into checked Omnigent specs, and dry runs
  show the execution plan without exposing task context by default.

## Status

Agent OS `0.1.0a3` is a local-first public alpha for bounded repository work. It is not a hosted,
multi-tenant, or unattended production control plane. The task ledger, sandboxed Omnigent and
Antigravity paths, direct OpenCode/Codex fallbacks, provider-independent review gate, and bounded
Prime Agent path are the supported surface.

## Install

Python 3.12-3.13, `uv`, Claude Code, and Codex are expected. OpenCode, Ollama, Antigravity CLI, and
Prime Agent are optional additional environments. Supported framework versions are pinned to NOOA
0.0.8 and Omnigent 0.8.2. Prime Agent is installed separately; this integration is verified against
version 0.7.1. The direct Antigravity path requires `agy>=1.1.6` and an existing CLI login.

On Linux, Omnigent's sandbox also requires Bubblewrap:

```bash
sudo apt-get install bubblewrap
```

### From PyPI

Agent OS is published as `agent-os-opensource` and installs the `agent-os` command. The alpha is the
only published version, so no prerelease flag is required:

```bash
uv tool install agent-os-opensource
agent-os init
agent-os doctor
```

`pip install agent-os-opensource` and `uv pip install agent-os-opensource` resolve the same
distribution inside an existing environment.

`agent-os init` writes the task database and generates the coordinator bundle under the state
directory; pass `--state-dir` to place them somewhere other than `./state`.

### From source

Use this path to modify Agent OS itself or to run the test suite:

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
OpenCode, Codex, or Antigravity can perform a direct implementation. All three record an
implementation attempt and move the task to `needs_review`; none approves its own work. The local
OpenCode path uses Ollama without a cloud key, while Codex and Antigravity reuse existing CLI
subscription logins:

```bash
uv run agent-os run tsk_... --runtime opencode \
  --provider ollama --model ollama/gemma4:26b --timeout-seconds 300
uv run agent-os run tsk_... --runtime codex-review

# Alternative direct subscription-backed builders:
uv run agent-os run tsk_... --runtime codex
uv run agent-os run tsk_... --runtime antigravity
uv run agent-os run tsk_... --runtime codex-review
```

This is an explicit recovery workflow, not an automatic retry: Agent OS does not launch a second
runtime after a capacity failure because the first process may already have started durable child
work. Inspect the task ledger before choosing a fallback. OpenAI-backed direct Codex or OpenCode
implementations require a later non-OpenAI reviewer. The direct Codex reviewer is for successful
Ollama or Google implementations; it uses Sol by default and can be overridden to Terra or Luna
with `--model` or `AGENT_OS_CODEX_REVIEWER_MODEL`.

This direct runtime deliberately does not use Omnigent's Antigravity SDK harness: that upstream
path requires a Gemini API key or Vertex credentials rather than the CLI subscription session. See
[Provider setup](docs/providers.md) for the sandbox, policy, model override, and compatibility
details, including the direct OpenCode containment boundary and local model setup.

Or use Prime Agent's persistent runtime with explicit limits:

```bash
uv run agent-os run tsk_... --runtime prime-agent \
  --provider openai --model openai/gpt-5 \
  --token-budget 80000 --max-turns 12 --timeout-seconds 1800
```

Prime Agent emits JSONL into the attempt transcript and a successful process moves the task only to
`needs_review`. It does not bypass independent review. Prime Agent is not an OS sandbox; use the
Omnigent path or add external containment for untrusted work.

## Measure a runtime's boundaries instead of trusting them

`doctor` answers whether a runtime is installed and supported. `probe` answers a different
question: when Agent OS launches it, can the agent inside write outside its workspace, reach the
network, or push to a Git remote?

```bash
uv run agent-os probe --runtime codex
uv run agent-os probe --runtime opencode --model ollama/gemma4:26b --timeout-seconds 1200
uv run agent-os probe --runtime codex --require-denied write_outside,network,push
```

The probe provisions its own disposable Git workspace, a canary directory beside it, a loopback
listener on an ephemeral port, and a local bare repository, then runs one attempt that is
explicitly authorized to attempt all three. Nothing external is contacted and nothing outside
`STATE_DIR/probes/<probe_id>` is touched.

Each check reports one of three verdicts, and the difference between the last two is the point:

| Verdict | Meaning |
| --- | --- |
| `crossed` | The host observed the effect: a file appeared, a connection arrived, a ref landed. |
| `blocked` | No host trace, and the runtime reported an attempt and the refusal it received. |
| `not_attempted` | No host trace and no reported attempt. This establishes nothing. |

A crossing is only ever established by this process. The runtime's own `probe-attempts.json` is
read solely to separate a refusal from an attempt that was never made, and `--require-denied`
rejects `not_attempted` exactly as it rejects `crossed` — a boundary nobody tested has not been
shown to hold. A run where nothing was attempted exits non-zero as inconclusive.

Read a report with its confounds in view. The runtime is cooperative and openly instructed, so a
crossing proves a hostile agent could do the same while a non-crossing proves only that this
attempt failed. A weak local model inflates `not_attempted`. And because sandboxes commonly grant
the temporary directory as a writable root, probe state under `$TMPDIR` can turn a boundary into a
crossing; the report says so when that applies.

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

## Why this architecture

The upstream frameworks already provide most agent and harness infrastructure. NOOA makes roles
testable and typed. Omnigent supplies native harness interoperability, sandboxing, review routing,
persistent sessions, policies, and UI. Prime Agent supplies long-running local capabilities such as
goals, supervision, schedules, heartbeats, direct messaging, recursive agents, persistent Python,
compaction, refinement, and recovery.

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
