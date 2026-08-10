# Architecture

## Design rule

Use NOOA for the definition surface and Omnigent for execution. Add code only when neither framework
has the domain concept Agent OS needs.

## Definition layer: NOOA

`src/agent_os/definitions.py` contains four `nooa.Agent` subclasses. The class docstring is the
role prompt. Ellipsis-bodied methods are typed generation contracts:

- `CoordinatorAgent.orchestrate(TaskSpec) -> FinalOutcome`
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
| reviewer_claude | `ReviewerAgent` | `claude-native` | read-only |
| reviewer_codex | `ReviewerAgent` | `codex-native` | read-only |

Omnigent's loader is the schema validator. Agent OS does not implement a parallel YAML schema.

## Execution and review: Omnigent

The coordinator receives a task id and uses ordinary Omnigent capabilities:

1. A host function tool returns the authoritative task contract.
2. `sys_session_send` dispatches a read-only planner.
3. The coordinator dispatches a Claude Code or Codex builder.
4. Omnigent persists each child session and delivers completion through its inbox.
5. The result and actual diff go to a reviewer on the other vendor.
6. One focused rework is allowed after `request_changes`; remaining material issues block closure.
7. Host function tools record attempts, evidence, review, and final status.

Conversation history, child lifecycle, streaming, interruption, inbox wakeups, policies, sandboxes,
and resume stay inside Omnigent.

## Domain persistence

Omnigent persists conversations and runtime events. NOOA persists an agent's event history and
snapshots. Neither provides a project-level task record that binds an objective and acceptance
criteria to work performed by several independent harness sessions. `TaskStore` fills only that
gap, using SQLite tables for tasks, attempts, reviews, and append-only task events.

The task database does not duplicate model transcripts. Agent OS stores only a transcript path;
Omnigent remains the session/history system.

## Context boundary

Omnigent handles context inside a conversation, including history and resume. The custom context
envelope handles a different boundary: starting a new session from durable task truth. It always
preserves the objective, workspace, constraints, and acceptance criteria, then uses the remaining
character budget for the most recent attempts and reviews.

## Safety boundary

NOOA's in-process generated-code checks are not a containment boundary. Agent OS does not execute
NOOA-generated code in the host process. Work runs through Omnigent harnesses under the platform
sandbox, with write access limited to the task workspace and network disabled in the generated
bundle. Reviewers receive no write paths.
