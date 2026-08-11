# Custom infrastructure ledger

This ledger records every manual seam added after checking the three framework surfaces. Source LOC
means nonblank, non-comment physical lines, measured by `scripts/custom_loc.py`. Tests, generated
YAML, docs, and the NOOA role definitions themselves are excluded.

| Manual seam | What was missing | Why it was necessary | Code |
| --- | --- | --- | --- |
| Execution identity registry | The frameworks identify harnesses, but the product must enforce reviewer independence by actual provider and model | Provider, model, and harness must remain separate, allowlisted facts at every execution and review boundary | `src/agent_os/execution.py` |
| Typed task contracts | Neither framework defines this product's task, attempt, evidence, or review record | A stable acceptance contract must survive and be inspectable outside one model conversation | `src/agent_os/models.py` |
| Domain task persistence | NOOA persists one agent's events/snapshots; Omnigent persists sessions/conversations | Real work needs a project-level unit of work joining several harness sessions to acceptance and review, with terminal task states rejecting running implementation attempts | `src/agent_os/store.py` |
| Cross-session context envelope | Both frameworks manage context within their own agent/session boundary | A fresh coordinator session needs durable task truth and bounded prior evidence without copying whole transcripts | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | NOOA has no Omnigent exporter and Omnigent has no NOOA importer | The requested split requires NOOA to remain definition authority while Omnigent executes | `src/agent_os/specs.py` |
| Omnigent task tool bridge | Omnigent function tools can call Python, but it cannot infer this task schema | The coordinator must persist attempt/review outcomes while using framework-native child sessions and may finalize work only after observing a terminal child-task status | `src/agent_os/tools.py` |
| Governed child-dispatch policy | Omnigent dispatches child sessions but does not know whether this product recorded the matching task attempt | Implementation dispatch must require a matching running attempt; review dispatch must bind one successful attempt and a different provider | `src/agent_os/policies.py` |
| Antigravity pre-tool policy | Antigravity custom-agent frontmatter does not remove every built-in tool from a main agent | Direct CLI subscription work needs a fail-closed pre-execution gate for ambient, outward, destructive, and out-of-workspace calls | `src/agent_os/antigravity_policy.py` |
| Multi-runtime process launcher | Omnigent, Prime Agent, Antigravity, and direct Codex each run sessions but know nothing about an Agent OS task id, status, or review gate | One command must bind task/workspace/context and bounds to any runtime, retain transcript/result references, and never confuse process success with approval | `src/agent_os/runner.py` |
| Operator task CLI | Omnigent's CLI is session-oriented and NOOA's CLI is agent/eval-oriented | Operators need create/list/show/context/run commands for the explicit task model | `src/agent_os/cli.py` |
| Gap measurement | Neither framework measures application-owned glue | The experiment requires current, reproducible code-size evidence for every manual seam | `scripts/custom_loc.py` |

The Prime integration reuses the existing launcher and CLI rather than adding a daemon, scheduler,
RPC stack, message bus, context compactor, kernel manager, or refinement store. No existing seam can
yet be deleted without losing the task acceptance/review contract or Omnigent's sandboxed
cross-provider harness path.

The OpenCode/Ollama integration remains declarative. Omnigent supplies `opencode-native`; OpenCode
supplies its OpenAI-compatible Ollama provider; the operator supplies launch-time secrets. The live
probe exposed that `sandbox.type: auto` passes Omnigent's schema but is not a runtime backend in
0.8.2. Removing that value lets Omnigent select its built-in platform backend without custom
sandbox code.

The distribution also pins compatible prerelease floors for Omnigent's three OpenTelemetry
instrumentation dependencies. Omnigent declares them as `>=0,<1`, while the published versions use
beta version numbers that plain pip otherwise excludes. This is a packaging constraint only; no
telemetry adapter or instrumentation implementation is maintained here.

Agent OS reuses Omnigent's own OpenCode version resolver and validator to expose compatibility
failures during `doctor`. No parallel compatibility logic is maintained here.

The direct Antigravity path is one deliberate provider-specific adapter in this release. It is
small because `agy` already supplies subscription authentication, structured streaming, custom
agents, and the native OS sandbox. Agent OS adds version validation, durable task attribution,
state-owned configuration, terminal-result parsing, and the pre-tool hook required by the product's
outward-mutation boundary. It does not implement a Google API client or credential store.

The other direct seam invokes Codex for either workspace-write implementation or read-only review.
Omnigent 0.8.2's root Codex launch entered an interactive tmux flow in headless probes, so the
launcher invokes `codex exec` ephemerally, disables approval escalation, and gives it an
attempt-scoped writable home. The review role additionally validates one small schema and records
the result against exact implementation attempts. The temporary home reuses a file-backed
subscription login only for the process lifetime and is then destroyed; this remains lifecycle
isolation rather than a model API client, persistent credential store, or general review engine.

## Current measured size

Verified on 2026-08-11:

| Manual seam | Source LOC | Paths |
| --- | ---: | --- |
| execution identity registry | 152 | `src/agent_os/execution.py` |
| typed task contracts | 103 | `src/agent_os/models.py` |
| domain task persistence | 772 | `src/agent_os/store.py` |
| cross-session context envelope | 62 | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | 276 | `src/agent_os/specs.py` |
| Omnigent task tool bridge | 147 | `src/agent_os/tools.py` |
| governed child-dispatch policy | 87 | `src/agent_os/policies.py` |
| Antigravity pre-tool policy | 105 | `src/agent_os/antigravity_policy.py` |
| multi-runtime process launcher | 1032 | `src/agent_os/runner.py` |
| operator task CLI | 249 | `src/agent_os/cli.py` |
| gap measurement | 34 | `scripts/custom_loc.py` |
| **Total** | **3,019** | |

Refresh with:

```bash
uv run python scripts/custom_loc.py
```

## Infrastructure deliberately not built

- No custom agent loop.
- No custom Claude or Codex model API client or credential adapter.
- No custom OpenCode or Ollama adapter.
- No custom Google API client or Antigravity credential adapter.
- No custom API-key loader or checked-in provider credential.
- No child-agent scheduler or polling loop.
- No custom conversation/transcript database.
- No custom sandbox, general policy engine, cost limiter, terminal bridge, or UI; the small
  Antigravity hook only enforces this product's fixed direct-runtime boundary.
- No vector store or automatic memory layer.
- No separate review engine.
- No background daemon, scheduler, heartbeat loop, worker supervisor, or attachment registry.
- No custom intra-Prime messaging bus, recursive-agent registry, IPython manager, or context compactor.
- No custom continual-refinement store, snapshot mechanism, or rollback engine.

Those are already provided by NOOA, Omnigent, or Prime Agent, or are unnecessary for this bounded
task layer.
