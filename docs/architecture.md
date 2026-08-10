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
| builder_claude | `BuilderAgent` | `claude-native` | workspace write |
| builder_codex | `BuilderAgent` | `codex-native` | workspace write |
| builder_opencode | `BuilderAgent` | `opencode-native`, `openai/gpt-5.6-terra` | workspace write |
| builder_ollama | `BuilderAgent` | `opencode-native`, `ollama/qwen3:14b` | workspace write |
| reviewer_claude | `ReviewerAgent` | `claude-native` | read-only |
| reviewer_codex | `ReviewerAgent` | `codex-native` | read-only |

Omnigent's loader is the schema validator. Agent OS does not implement a parallel YAML schema.

## Execution and review: Omnigent

The coordinator receives a task id and uses ordinary Omnigent capabilities:

1. A host function tool returns the authoritative task contract.
2. `sys_session_send` dispatches a read-only planner.
3. The coordinator dispatches a Claude Code, Codex, OpenCode cloud, or OpenCode/Ollama builder.
4. Omnigent persists each child session and delivers completion through its inbox.
5. The result and actual diff go to a reviewer on a different intelligence provider.
6. One focused rework is allowed after `request_changes`; remaining material issues block closure.
7. Host function tools record attempts, evidence, review, and final status.

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

Prime Agent is not placed underneath Omnigent. Omnigent remains the path for native Claude Code,
Codex, and OpenCode harness selection, sandboxed workspace execution, and different-provider
review. Prime is the path for work that benefits from persistent goals, programmatic context,
recursive agents, and background recovery.

## Domain persistence

Omnigent and Prime Agent persist conversations and runtime events. NOOA persists an agent's event
history and snapshots. None provides a project-level task record that binds an objective and acceptance
criteria to work performed by several independent harness sessions. `TaskStore` fills only that
gap, using SQLite tables for tasks, attempts, reviews, and append-only task events.

The task database does not duplicate model transcripts. Agent OS stores only a transcript path;
Omnigent remains the session/history system.

## Context boundary

Omnigent and Prime Agent handle context inside their conversations, including history, compaction,
and resume. The custom context envelope handles a different boundary: starting a new session from
durable task truth. It always
preserves the objective, workspace, constraints, and acceptance criteria, then uses the remaining
character budget for the most recent attempts and reviews.

## Safety boundary

NOOA's in-process generated-code checks are not a containment boundary. Agent OS does not execute
NOOA-generated code in the host process. Work runs through Omnigent harnesses under the platform
sandbox, with write access limited to the task workspace and network disabled in the generated
bundle for agent tools. Provider calls are made by the harness outside that tool sandbox. Reviewers
receive no write paths. Prime Agent workers and kernels inherit user permissions; Prime tasks
involving untrusted code require a separately enforced OS/container sandbox.

## Provider boundary

Harness and intelligence provider are separate choices. Both new builders use Omnigent's existing
`opencode-native` harness. `builder_opencode` pins a direct OpenAI model and receives
`OPENAI_API_KEY` from the caller environment; `builder_ollama` pins the OpenCode provider model
`ollama/qwen3:14b`, which resolves to the local OpenAI-compatible endpoint. Agent OS adds no model
client, provider adapter, secret store, or fallback router.

Cloud credentials are injected only into the launch process with Doppler. The repository stores
the project/config names and required secret names, never values. Local Ollama registration lives
in the user's OpenCode config because Omnigent 0.8.2 already merges user provider definitions into
each isolated OpenCode session.
