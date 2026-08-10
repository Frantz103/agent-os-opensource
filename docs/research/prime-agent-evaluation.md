# Prime Agent evaluation

Evaluated 2026-08-09 against
[`PrimeIntellect-ai/prime-agent`](https://github.com/PrimeIntellect-ai/prime-agent) commit
`a18809e00ea30638584d87b3afea7285a9d7296c` (package `0.7.1`). The repository documentation,
architecture, implementation, focused tests, and bounded live runs were examined before Agent OS
was changed.

## Executive decision

Prime Agent materially changes the runtime roadmap, but it does not replace NOOA or Omnigent.
Agent OS now exposes Prime Agent as an optional peer execution environment through
`agent-os run --runtime prime-agent`. It passes the task contract to a NOOA-defined Prime
coordinator and delegates session persistence, goals, autonomous limits, context compaction,
IPython, and recursive agents to Prime Agent.

```text
agent-os-opensource task and review contract
                |
                +-- NOOA: typed role definitions
                |
                +-- Omnigent: Claude Code/Codex harnesses, sandbox, cross-vendor review
                |
                +-- Prime Agent: persistent agent runtime, goals, daemon, RLM, refinement
```

The SQLite task/review ledger remains because Prime sessions and goals do not represent the same
product-level acceptance contract. Omnigent remains because Prime Agent is not an OS sandbox and
does not provide Omnigent's native Claude Code/Codex meta-harness or cross-vendor review policy.
Agent OS should not build its own background daemon, scheduler, heartbeat engine, intra-Prime
messaging bus, recursive-agent registry, kernel manager, context compactor, or harness-refinement
store.

## System summary

The Prime process is launched in JSON mode with a persistent goal and explicit token, turn,
continuation, and time limits. Its stdout JSONL is retained as the attempt transcript. A zero exit
marks the attempt successful and moves the task to `needs_review`; it never bypasses the existing
independent review gate. The current integration deliberately does not wrap the daemon RPC yet.

Prime's runtime has five relevant layers:

1. a client or machine-readable JSON/RPC frontend;
2. a daemon supervisor that owns routing, attachments, recovery, and command journaling;
3. a worker per root agent that owns the root session, schedules, kernels, and descendants;
4. `AgentSession` plus JSONL transcripts and session artifacts;
5. a persistent IPython kernel where `rlm(...)`, skills, and programmatic context operations live.

Primary references: [architecture](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md),
[daemon](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/daemon.md),
[long-running agents](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md),
[RLM](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md),
[RLM runtime](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm-runtime.md),
[JSON mode](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/json.md), and
[RPC mode](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rpc.md).

## Capability decisions

### 1. Persistence

Capability:
Persistence across process termination, terminal disconnection, and restoration.

Current implementation:
SQLite preserves tasks, attempts, reviews, and events. Omnigent preserves harness conversations.
Agent OS retains transcript paths but has no custom daemon or attachment model.

Prime Agent implementation:
Append-only JSONL sessions, session artifacts, durable harness state, kernel snapshots, detached
workers, leases, and daemon descriptors. A live root with an active schedule survived client EOF.
After the supervisor was killed with `SIGKILL`, its worker restarted the supervisor on the same
socket; a new client rediscovered and observed the same session and worker.

Prime Agent advantages:
It provides recovery and reattachment semantics Agent OS intentionally lacks, including child and
kernel ownership below a durable root.

Prime Agent limitations:
Its session state does not bind several heterogeneous attempts and independent reviews to one
acceptance contract. A session JSONL file observed in the probe was mode `0644`, while auth,
schedule, and lease files were `0600`; deployments should decide whether transcript permissions
need hardening.

Custom code eliminated:
No current task-ledger code. Future session daemons, attachment registries, worker recovery, and
kernel snapshot code are eliminated from the roadmap.

Custom code still required:
The task/attempt/review store and the link from an Agent OS attempt to a Prime transcript/session.

Decision:
EXTEND

### 2. Long running work

Capability:
Persistent goals, autonomous continuation, schedules, and heartbeats.

Current implementation:
A task survives, but progress requires another `agent-os run`; there is no background scheduler,
heartbeat, lease, or autonomous continuation controller.

Prime Agent implementation:
Goals preserve objective and usage. Autonomous runs are bounded by continuations, turns, tokens,
time, and optional gates. Workers own one-time or recurring schedules and heartbeats; a due tick is
claimed and advanced before delivery, uncertain ticks are not replayed, and missed ticks coalesce.

Prime Agent advantages:
This is substantially more complete than anything currently present and includes explicit failure
semantics: reaching a bound is not success.

Prime Agent limitations:
Schedules are prompts, not a distributed task queue with business-level leases or fencing. A live
RLM probe completed its requested exchange but the autonomous host exited nonzero after aggregate
usage reached `22,762/16,000` tokens. Budget/event interpretation must stay conservative.

Custom code eliminated:
Any proposed local daemon, cron registry, heartbeat loop, autonomous continuation loop, and worker
restart controller for Prime-owned work.

Custom code still required:
A policy mapping Agent OS status and acceptance evidence to Prime goal/gate outcomes, plus operator
controls for which tasks may run unattended.

Decision:
ADOPT

### 3. Agent communication

Capability:
Agent discovery, messaging, and coordination.

Current implementation:
Omnigent supplies child sessions and inbox delivery inside an Omnigent run. Agent OS has no custom
messaging layer and no communication across runtimes.

Prime Agent implementation:
The daemon routes direct messages, exposes agent discovery, records delivery, and supports parent,
child, and named-agent addressing. In the live RLM probe the parent saw the child transition from
`running` to `idle` with `repliedSinceTask=true`, and received a durable `agent_message` event.

Prime Agent advantages:
Communication, discovery, and recursive-family identity work without an Agent OS message table or
polling loop.

Prime Agent limitations:
The bus is local to Prime's runtime topology. It does not make a Codex-native Omnigent child a Prime
descendant, and it is not a remote multi-tenant control plane.

Custom code eliminated:
All intra-Prime discovery, inbox, parent/child routing, and delivery-state code.

Custom code still required:
Only an explicit bridge if future workflows truly need cross-runtime messages; no bridge is built
now.

Decision:
ADOPT

### 4. Subagents

Capability:
Parallel delegation and recursive problem solving through `rlm(...)`.

Current implementation:
Omnigent dispatches named Claude/Codex child agents. The NOOA coordinator chooses roles and enforces
different-vendor review.

Prime Agent implementation:
`await rlm(...)` returns an admission handle, not a blocking result. Children communicate by
`agent_message` or artifacts, remain registered through compaction/recovery, and default recursion
depth is one. The live probe spawned exactly one `eval-child`; it sent `RLM_CHILD_OK`, after which
the parent emitted `RLM_PARENT_OK`.

Prime Agent advantages:
Recursive agents are callable from persistent Python and do not require serializing all working
state back into one conversation.

Prime Agent limitations:
First-use kernel bootstrapping needs Python 3.11, package installation, network, and writable uv
paths. Under the evaluation sandbox, explicit writable kernel/cache/install directories were
required. The parent spent extra calls discovering how to observe a reply; bounded prompts and
examples matter.

Custom code eliminated:
A Prime-specific child registry, recursion limiter, admission handle, and parent/child message
protocol.

Custom code still required:
Task-specific delegation policy and evidence collation. Omnigent remains for explicit native
Claude/Codex selection and cross-vendor review.

Decision:
ADOPT

### 5. Context management

Capability:
Programmatic context, compaction, and recoverable working state.

Current implementation:
Agent OS renders a bounded task envelope for fresh sessions. Omnigent owns conversation context and
resume. No custom compactor exists.

Prime Agent implementation:
Automatic compaction is built in; IPython holds programmatic state and can load large data without
placing it all in chat. Kernel snapshots and the durable child registry survive restoration.

Prime Agent advantages:
It reduces pressure to encode active working state as prose and makes recursive calls ordinary
program operations.

Prime Agent limitations:
Compaction is not authoritative business state. Python kernels run with the user's OS permissions,
and restorable interpreter state cannot replace a validated task record.

Custom code eliminated:
Any planned Prime transcript summarizer, scratch-state serializer, compaction loop, or kernel state
manager.

Custom code still required:
The small task envelope that starts or restores work from authoritative acceptance criteria.

Decision:
EXTEND

### 6. Runtime learning

Capability:
Evidence-backed improvement through the Continual Harness.

Current implementation:
Prompts are versioned in NOOA definitions and generated bundles. There is no runtime learning loop.

Prime Agent implementation:
`refine` proposes scoped prompt, memory, skill, or reusable-subagent changes in supplemental
harness state while leaving the base system prompt immutable. Before/after snapshots support
rollback. In a controlled live A/B, a vague prose verification summary became the required strict
minified JSON in a new session after one global prompt-note refinement; rollback restored the prior
state.

Prime Agent advantages:
It supplies evidence references, scoped mutable overlays, persistence, and rollback rather than
silently rewriting the system prompt.

Prime Agent limitations:
The live result is one formatting task (`n=1`), not evidence of improved task quality. Global
refinements can propagate a bad local lesson, and direct RPC refinement was needed when model-led
IPython refinement hit the initial kernel blocker.

Custom code eliminated:
No custom mutable prompt-overlay store, refinement history, snapshot, or rollback mechanism should
be built.

Custom code still required:
Evaluation datasets, promotion criteria, provenance review, and an approval boundary for global
refinements.

Decision:
NEEDS MORE TESTING

### 7. Supervision and recovery

Capability:
Daemon, workers, kernels, attachment recovery, and health.

Current implementation:
The CLI starts one foreground process and records its transcript. A process crash ends the attempt;
there is no worker supervisor or session reattachment.

Prime Agent implementation:
The supervisor owns discovery and routing; a worker per root owns the session tree, scheduler, and
kernels. Command IDs, event cursors, snapshots, leases, and descriptors support reconnection and
idempotent control. The forced-crash probe demonstrated worker-led supervisor recovery and fresh
client observation of the same root.

Prime Agent advantages:
Recovery is an implemented runtime protocol rather than a promise inferred from persisted files.

Prime Agent limitations:
Workers and kernels are not security sandboxes. Public CLI handling of custom sockets is
inconsistent: `list --socket` worked, while `status`, `schedule list`, and `shutdown` rejected that
flag even though lower-level parsers contain socket support.

Custom code eliminated:
Supervisor election/restart, worker heartbeat, attachment bookkeeping, event replay cursor, and
session recovery code for Prime tasks.

Custom code still required:
External process policy, OS/container isolation where needed, and task-level stale-work decisions.

Decision:
ADOPT

### 8. Integration

Capability:
JSON and RPC boundaries independent of the terminal UI.

Current implementation:
Agent OS launches Omnigent as a subprocess and streams one transcript. There is no generic remote
control API.

Prime Agent implementation:
JSON mode emits one-shot JSONL events. RPC is strict line-delimited JSON with request IDs, async
events, state, prompt, compaction, refinement, shell, sessions, messages, schedules, heartbeats, and
observation. A clean RPC probe kept telemetry notices on stderr and protocol frames on stdout.

Prime Agent advantages:
The runtime can be wrapped without terminal scraping. Agent OS uses JSON mode now; RPC is a credible
future boundary for detached execution and reattachment.

Prime Agent limitations:
Responses can arrive out of request order, so callers must correlate IDs. `message_update` carries
both cumulative content and deltas, amplifying streams. Source reports protocol `7`/schema `14`
while current docs still mention protocol `4`; source also lacks a direct RPC goal-create command
and its `send_message` type omits the documented `deliveryMode`. The local protocol is not a hosted
API: upstream explicitly leaves authentication, authorization, sandbox identity, artifact transfer,
stable DTOs, multi-client ownership, and network compatibility to an external control plane.

Custom code eliminated:
Terminal screen scraping and an ad-hoc local daemon protocol.

Custom code still required:
A small version-negotiating RPC adapter, request correlation, event normalization, and the task
mapping. Remote service concerns remain external.

Decision:
WRAP

### 9. Custom infrastructure reduction

Capability:
Delete or avoid infrastructure Prime Agent already implements.

Current implementation:
The measured custom layer consists of typed task records, SQLite persistence, a bounded task
envelope, NOOA-to-Omnigent compilation, task tools, a process launcher, operator CLI, and LOC
measurement.

Prime Agent implementation:
It duplicates none of the acceptance/review domain model, but supersedes a large set of potential
runtime infrastructure: persistent sessions, goals, background supervision, schedules, heartbeats,
messaging, recursive children, kernel state, compaction, refinement, and recovery.

Prime Agent advantages:
Agent OS can stay a task-and-evidence layer and delegate long-running mechanics to a maintained
runtime.

Prime Agent limitations:
It cannot safely replace Omnigent's sandboxed native Claude/Codex harness path or Agent OS's
cross-runtime review truth. `npm install` reported 16 audit findings (11 high, 5 moderate, no
critical) in the evaluated dependency tree; this is an adoption risk to triage, not proof of an
exploitable application defect.

Custom code eliminated:
No existing file is deleted in this phase. The Omnigent-only launcher is generalized into one
multi-runtime launcher. Eleven categories of planned runtime code listed above are removed from
the roadmap.

Custom code still required:
All existing domain seams remain, plus the small Prime command builder. An RPC adapter is deferred
until detached Prime tasks are a concrete requirement.

Decision:
KEEP CURRENT

## Data flow and invariants

For Prime execution, the CLI reads durable task truth, renders the bounded envelope, prepends the
NOOA `PrimeCoordinatorAgent` role, and invokes Prime in JSON mode. Prime owns its session, goal,
context, kernel, children, and runtime events. Agent OS owns the outer attempt and transcript link.

Key invariants:

- a Prime process exit is attempt evidence, never task approval;
- successful execution transitions only to `needs_review`;
- autonomous budgets must be positive and explicit;
- Prime Agent never receives an Omnigent-only tool instruction;
- no Prime runtime feature is reimplemented in Agent OS;
- untrusted execution still requires an actual OS or container sandbox;
- immutable NOOA definitions remain distinct from mutable Continual Harness overlays.

## Failure modes and mitigations

| Failure | Mitigation |
| --- | --- |
| Prime CLI missing | Optional doctor result; Omnigent remains the default |
| First-use kernel bootstrap fails | Pre-provision Python/runtime packages and writable cache/venv paths |
| Autonomous limit reached after useful output | Trust exit status, preserve JSONL, review terminal events manually |
| Daemon/client protocol drift | Negotiate capabilities and versions before an RPC wrapper is adopted |
| Malicious generated Python or shell | Run Prime inside a separately enforced OS/container sandbox |
| Bad global refinement | Require evidence, snapshot, approval, and tested rollback |
| Cross-runtime message ambiguity | Keep runtimes separate until a concrete, typed bridge is justified |

## Suggested next steps

1. Use the JSON integration on bounded, egress-approved repository tasks and send the result through
   the existing different-vendor review path.
2. Run a multi-task Continual Harness experiment with held-out acceptance tests before allowing
   global automatic refinement.
3. Wrap RPC only when detached task control is needed; pin protocol capabilities and normalize the
   cumulative/delta event stream.
4. Package Prime behind a real sandbox before using it on untrusted repositories.
5. Reassess whether any launcher code can be deleted after Prime and Omnigent have comparable live
   task evidence; do not delete based on feature lists alone.

