# Architecture

## Design rule

Use NOOA for the definition surface, Omnigent for native multi-harness execution and review, and
Prime Agent for persistent long-running execution. They are peer capabilities, not a mandatory
linear stack. Add code only when none has the domain concept Agent OS needs.

## Definition layer: NOOA

`src/agent_os/definitions.py` contains five `nooa.Agent` subclasses. The class docstring is the
role prompt. Ellipsis-bodied methods are typed generation contracts:

- `CoordinatorAgent.orchestrate(TaskSpec) -> FinalOutcome`
- `PrimeCoordinatorAgent.orchestrate(TaskSpec) -> FinalOutcome`
- `PlannerAgent.plan(TaskSpec) -> TaskPlan`
- `BuilderAgent.execute(TaskSpec, TaskPlan) -> WorkResult`
- `ReviewerAgent.review(TaskSpec, WorkResult) -> ReviewVerdict`

The methods can be executed directly by NOOA in another integration. In this system their more
important job is to make roles, prompts, and I/O contracts ordinary, inspectable Python.

## Compilation layer

`agent_os.specs` maps each NOOA role to one or more Omnigent harness variants and emits a normal
Omnigent agent-image directory. The mapping is intentionally mechanical:

| Variant | NOOA definition | Omnigent harness | Access |
| --- | --- | --- | --- |
| coordinator | `CoordinatorAgent` | `claude-sdk` | tools only |
| planner | `PlannerAgent` | `claude-sdk` | read-only |
| builder_claude | `BuilderAgent` | `claude-sdk` | workspace write |
| builder_codex | `BuilderAgent` | `codex`, `gpt-5.6-sol` | workspace write |
| builder_opencode | `BuilderAgent` | `opencode-native`, configurable cloud model | workspace write |
| builder_ollama | `BuilderAgent` | `opencode-native`, `ollama/qwen3:14b` | workspace write |
| reviewer_claude | `ReviewerAgent` | `claude-sdk` | read-only |
| reviewer_codex | `ReviewerAgent` | `codex`, `gpt-5.6-sol` | read-only |

Omnigent's loader is the schema validator. Agent OS does not implement a parallel YAML schema.

`builder_antigravity` is intentionally absent from this generated table. It is a direct Agent OS
runtime, not an Omnigent agent-image variant, because the CLI subscription session and Omnigent's
SDK/API-key harness have different authentication and containment boundaries.

## Execution and review: Omnigent

The coordinator receives a task id and uses ordinary Omnigent capabilities. This path uses the
Claude coordinator and `planner`. Fixed child variants make provider choice an inspectable
configuration fact instead of a prompt-dependent harness override.

1. A host function tool returns the authoritative task contract.
2. `sys_session_send` dispatches a read-only planner.
3. The coordinator records an implementation attempt, and a runtime policy rejects any builder
   dispatch without a matching running attempt.
4. The coordinator dispatches a Claude SDK, Codex, OpenCode cloud, or OpenCode/Ollama builder.
5. Omnigent persists each child session and delivers completion through its inbox. The ledger tool
   accepts `finish_attempt` only with an observed terminal Omnigent child-task status; `launching`
   and `in_progress` must remain running.
6. A host function collects bounded status and diff evidence for only the declared workspace, with
   Git configuration, hooks, external diff, text conversion, submodule recursion, locks, and prompts
   disabled. That evidence and the result go to a reviewer on a different intelligence provider;
   `.git` history stays outside model sandboxes. The runtime policy requires the dispatch prompt to
   name exactly one successful implementation attempt and rejects a reviewer backed by the same
   provider.
7. One focused rework is allowed after `request_changes`; remaining material issues block closure.
8. Host function tools record attempts, evidence, review, and final status.

Conversation history, child lifecycle, streaming, interruption, inbox wakeups, policies, sandboxes,
and resume stay inside Omnigent.

## Persistent execution: Prime Agent

`agent-os run --runtime prime-agent` is a separate execution branch. It combines the NOOA
`PrimeCoordinatorAgent` docstring with the authoritative task envelope and invokes Prime Agent in
JSON mode with a persistent goal and explicit autonomous bounds. Prime owns its session JSONL,
artifacts, context compaction, IPython kernel, recursive agents, messaging, and recovery. Agent OS
records the outer attempt and transcript path.

The integration currently uses one-shot JSON rather than RPC. This proves a useful process boundary
without adding a custom daemon client. RPC is deferred until detached task control is needed because
it requires version/capability negotiation, request correlation, and event normalization.

Prime Agent is not placed underneath Omnigent. Omnigent remains the path for Claude SDK, Codex,
and OpenCode harness selection, sandboxed workspace execution, and different-provider
review. Prime is the path for work that benefits from persistent goals, programmatic context,
recursive agents, and background recovery.

## Execution: direct Codex and Antigravity CLIs

The direct Codex and Antigravity branches are bounded implementation seams beside Omnigent and
Prime Agent. Codex uses `codex exec --ephemeral` with a workspace-write sandbox and approval
escalation disabled; Antigravity uses its native sandbox and the additional policy below:

1. The host resolves `agy>=1.1.6`, records a Google implementation attempt, and creates a private
   state-owned runtime directory.
2. The runtime writes a fixed custom builder under that directory; it does not modify the target
   repository's agent configuration. For the process lifetime it also installs a named global
   Antigravity plugin with a per-run activation token, because the tested 1.1 CLI does not discover
   workspace-local hooks in headless mode. An existing same-name plugin fails closed.
3. `agy` receives the authoritative task envelope through `--print`, the repository only through
   `--add-dir`, and runs with structured streaming, native sandboxing, slash commands disabled, and
   auto-update disabled.
4. The policy permits bounded file, shell, and verification work in the declared workspace while
   denying ambient web, browser, MCP, subagent, destructive, and outward-mutation tools.
5. Only a terminal structured `SUCCESS` event marks the implementation attempt successful. The task
   then moves to `needs_review`, never directly to completion.
6. A later `--runtime codex-review` run starts an ephemeral, read-only Codex process, supplies
   bounded host-generated diff evidence, validates its structured verdict, binds approval to the
   exact Google attempt, and closes the task only when the review gate passes.

The Codex CLI branches are direct because Omnigent 0.8.2's root Codex path entered its interactive
tmux startup flow during headless live probes and produced no review output. Agent OS therefore
uses `codex exec --ephemeral` for the bounded builder and review seams; Omnigent still owns Codex
child builders and reviewers inside a Claude-coordinated run. The host gives each direct process a
private, per-attempt `CODEX_HOME` so its app-server state has the same writable runtime baseline as
the other harnesses without granting writes to the operator's global Codex directory.

## Domain persistence

Omnigent and Prime Agent persist conversations and runtime events. NOOA persists an agent's event
history and snapshots. None provides a project-level task record that binds an objective and acceptance
criteria to work performed by several independent harness sessions. `TaskStore` fills only that
gap, using SQLite tables for tasks, attempts, reviews, and append-only task events.

The task database does not duplicate model transcripts. Agent OS writes streamed output to a
private transcript file and stores only its path. Release-mode Omnigent runs use `--no-session`, so
the invoking process owns the complete lifetime and no detached daemon can outlive the attempt.

## Context boundary

Omnigent and Prime Agent handle context inside a conversation, including history and compaction;
Prime additionally supports persistent resume. The custom context envelope handles the boundary
between Agent OS attempts: starting a fresh session from durable task truth. It always
preserves the objective, workspace, constraints, and acceptance criteria, then uses the remaining
character budget for the most recent attempts and reviews.

## Safety boundary

NOOA's in-process generated-code checks are not a containment boundary. Agent OS does not execute
NOOA-generated code in the host process. Work runs through Omnigent harnesses under the platform
sandbox, with write access limited to the task workspace and arbitrary network access disabled.
The Claude SDK harness keeps the provider client outside the worker OS helper. With network access
disabled, Omnigent disables native Claude tools and routes file and shell calls through independently
sandboxed `sys_os_*` helpers. Agent OS applies the same boundary to the Codex subprocess harness by
disabling its native shell and web search, leaving repository work to Omnigent's dynamic tools.
Arbitrary tool egress remains denied, and reviewers receive no write paths. Prime Agent workers and
kernels inherit user permissions; Prime tasks involving untrusted code require a separately
enforced OS/container sandbox.

Antigravity is not registered as an Omnigent variant on 0.8.2. Omnigent's documented integration
uses the Google Antigravity SDK and API/Vertex credentials, while Agent OS targets an existing CLI
subscription session. The direct path uses Antigravity's native OS sandbox plus a wildcard
`PreToolUse` hook that evaluates calls before execution. The temporary plugin is removed after
the child exits. This hook is defense in depth around the CLI sandbox, not a replacement for it.

## Provider boundary

Harness and intelligence provider are separate choices. The two OpenCode builders use Omnigent's
existing `opencode-native` harness. `builder_opencode` defaults to `openai/gpt-5` and can be set with
`AGENT_OS_OPENCODE_MODEL`; `builder_ollama` defaults to `ollama/qwen3:14b`. Agent OS records the
resolved provider and model on every implementation attempt so the store can reject a same-provider
review even when two agents use different harnesses.

The launcher copies only an explicit environment allowlist and the credentials needed by built-in
providers. Additional provider variable names require `AGENT_OS_ALLOWED_ENV`. Agent OS adds no model
client, provider adapter, secret store, or fallback router. Local Ollama registration remains in the
user's OpenCode config because Omnigent already merges user provider definitions into each isolated
OpenCode session.

Generated agents declare `skills: none`; their NOOA role contracts are complete. For OpenCode
builders, the launcher also disables Claude-compatibility discovery and injects highest-precedence
configuration that denies the built-in `build` agent's skill tool. OpenCode 1.17 may still scan
`~/.agents/skills` metadata locally during startup, but the deny removes those skills from the
model-facing tool surface. The coordinator is assigned the same read-only OS environment as the
planner. Direct Codex workers use the CLI's workspace-write sandbox; direct Codex reviewers
separately use read-only. Both are ephemeral and disable approval escalation.

## Ledger integrity boundary

Schema migrations create a private backup before changing durable state. Task transitions use
compare-and-swap updates, terminal attempt writes are idempotent, and only one running attempt may
own a work item. Blocked and failed task transitions reject any running implementation attempt.
The coordinator-facing finish tool also rejects non-terminal Omnigent child-task statuses, so an
unchanged workspace or elapsed wall time cannot be recorded as child failure. Reviews bind to an
exact successful implementation attempt and record the reviewer provider. Completion is a
store-level transaction that requires evidence-backed approval for the latest attempt in every
work item; prompt compliance alone cannot bypass it.
