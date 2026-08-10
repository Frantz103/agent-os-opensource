# Framework capability map

This map distinguishes directly observed upstream capability from infrastructure added by Agent OS.

| Concern | NOOA | Omnigent | Agent OS decision |
| --- | --- | --- | --- |
| Agent definition | Python classes, fields, methods, docstrings, typed contracts | YAML agent images | Author in NOOA; mechanically compile to Omnigent |
| Structured output | Validated Pydantic/dataclass/typed returns with retry | Harness-dependent response/tool schemas | Keep domain contracts in NOOA/Pydantic |
| Tools | Python methods, external tools, MCP, skills | Function tools, MCP, OS tools, terminals | Use Omnigent tools at runtime |
| Agent state | Explicit object fields and snapshots | Conversation/session state | Do not duplicate |
| Event history | Event manager plus in-memory/SQLite backends | Persistent session and runtime events | Do not duplicate transcripts |
| Context | Context blocks, pass-by-reference, summarization | Conversation history, child history, resume/fork | Add only cross-session task envelope |
| Long-term memory | Optional typed relational SQLite memory | Optional Hindsight memory | Not required for MVP task truth |
| Multi-agent dispatch | Python orchestration is possible, but no vendor meta-harness | Child sessions, inbox, async fan-out | Use Omnigent |
| Claude/Codex harnesses | Model-agnostic LiteLLM execution, not CLI meta-harnessing | Native and SDK harnesses | Use Omnigent native children |
| Review fan-out | Can be programmed as Python | Already demonstrated by Polly/Scribe | Use Omnigent child routing |
| Persistence/resume | Agent event/snapshot persistence | Server conversation persistence and resume | Use both for their native scope |
| Sandboxing | In-process checks; upstream says OS isolation is required | macOS Seatbelt, Linux bwrap, cloud providers | Use Omnigent sandbox |
| Policies/approvals | Middleware and hooks, no shared vendor policy plane | Tool policies, blast-radius guard, cost budgets, approvals | Use Omnigent |
| Observability | Tracing, OTLP, trace viewer, metrics | Sessions, events, UI, OTEL, harness bench | Use both; store evidence links only |
| Domain task model | No project task/acceptance graph | Session/chat oriented, no acceptance-linked unit of work | Add small SQLite task layer |
| NOOA-to-Omnigent bridge | No exporter | No NOOA importer | Add mechanical compiler |
| Distributed workflow leases | Not a core task scheduler | Sessions and runners, not task leases | Explicitly out of MVP scope |

## Prime Agent impact

Prime Agent is a peer runtime rather than another layer in the NOOA-to-Omnigent compilation path.

| Concern | Prime Agent | Agent OS decision |
| --- | --- | --- |
| Agent definition | System prompt plus supplemental prompts, memories, skills, and subagent specs | Keep immutable role authority in NOOA; allow governed supplemental refinement |
| Persistent execution | Durable root workers, sessions, artifacts, goals, and kernel snapshots | Optional `prime-agent` runtime |
| Long-running work | Autonomous limits, completion gates, schedules, and heartbeats | Adopt; do not build equivalents |
| Multi-agent dispatch | Recursive `rlm(...)`, descendant registry, and direct messaging | Adopt inside Prime; retain Omnigent for named Claude/Codex harnesses |
| Context | Persistent IPython, programmatic context, automatic compaction, restoration | Use with the authoritative cross-session task envelope |
| Runtime learning | Evidence-linked Continual Harness overlays with snapshots and rollback | Needs broader held-out testing and promotion governance |
| Supervision | Daemon, per-root worker, leases, attachment recovery, command journal | Adopt for Prime work; do not build a custom daemon |
| Integration | JSON event stream and local JSONL RPC | Use JSON now; wrap RPC only for detached task control |
| Sandboxing | None; workers and kernels inherit user permissions | Never treat Prime as containment |
| Domain task model | Persistent goals and sessions, but no acceptance-linked cross-runtime review record | Keep the SQLite task/review layer |

The detailed evidence and all nine decisions are in the
[Prime Agent evaluation](prime-agent-evaluation.md).

## What still has to be built for production

The experiment is intentionally not filling these gaps yet:

- distributed claims, leases, fencing, and idempotent recovery;
- task dependencies beyond the typed plan returned inside a session;
- durable automated cross-runtime review-to-rework scheduling after a process crash;
- artifact manifests and checksums beyond evidence strings/transcript paths;
- operator approval delegation and protected merge/deploy flows;
- cost attribution joined to task/attempt ids;
- remote worker health and multi-tenant stuck-session intervention.

Prime supplies local worker health and recovery. The remaining items are product or hosted
control-plane capabilities, not missing model or harness adapters.
