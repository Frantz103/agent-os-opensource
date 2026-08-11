# Custom infrastructure ledger

This ledger records every manual seam added after checking the three framework surfaces. Source LOC
means nonblank, non-comment physical lines, measured by `scripts/custom_loc.py`. Tests, generated
YAML, docs, and the NOOA role definitions themselves are excluded.

| Manual seam | What was missing | Why it was necessary | Code |
| --- | --- | --- | --- |
| Execution identity registry | The frameworks identify harnesses, but the product must enforce reviewer independence by actual provider and model | Provider, model, and harness must remain separate, allowlisted facts at every execution and review boundary | `src/agent_os/execution.py` |
| Typed task contracts | Neither framework defines this product's task, attempt, evidence, or review record | A stable acceptance contract must survive and be inspectable outside one model conversation | `src/agent_os/models.py` |
| Domain task persistence | NOOA persists one agent's events/snapshots; Omnigent persists sessions/conversations | Real work needs a project-level unit of work joining several harness sessions to acceptance and review | `src/agent_os/store.py` |
| Cross-session context envelope | Both frameworks manage context within their own agent/session boundary | A fresh coordinator session needs durable task truth and bounded prior evidence without copying whole transcripts | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | NOOA has no Omnigent exporter and Omnigent has no NOOA importer | The requested split requires NOOA to remain definition authority while Omnigent executes | `src/agent_os/specs.py` |
| Omnigent task tool bridge | Omnigent function tools can call Python, but it cannot infer this task schema | The coordinator must persist attempt/review outcomes while using framework-native child sessions | `src/agent_os/tools.py` |
| Multi-runtime process launcher | Omnigent and Prime Agent each run sessions but know nothing about an Agent OS task id, status, or review gate | One command must bind task/workspace/context and bounds to either runtime, retain the transcript reference, and never confuse process success with approval | `src/agent_os/runner.py` |
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

## Current measured size

Verified on 2026-08-10:

| Manual seam | Source LOC | Paths |
| --- | ---: | --- |
| execution identity registry | 130 | `src/agent_os/execution.py` |
| typed task contracts | 98 | `src/agent_os/models.py` |
| domain task persistence | 759 | `src/agent_os/store.py` |
| cross-session context envelope | 62 | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | 239 | `src/agent_os/specs.py` |
| Omnigent task tool bridge | 70 | `src/agent_os/tools.py` |
| multi-runtime process launcher | 366 | `src/agent_os/runner.py` |
| operator task CLI | 213 | `src/agent_os/cli.py` |
| gap measurement | 32 | `scripts/custom_loc.py` |
| **Total** | **1,969** | |

Refresh with:

```bash
uv run python scripts/custom_loc.py
```

## Infrastructure deliberately not built

- No custom agent loop.
- No custom Claude Code or Codex adapter.
- No custom OpenCode or Ollama adapter.
- No custom API-key loader or checked-in provider credential.
- No child-agent scheduler or polling loop.
- No custom conversation/transcript database.
- No custom sandbox, policy engine, cost limiter, terminal bridge, or UI.
- No vector store or automatic memory layer.
- No separate review engine.
- No background daemon, scheduler, heartbeat loop, worker supervisor, or attachment registry.
- No custom intra-Prime messaging bus, recursive-agent registry, IPython manager, or context compactor.
- No custom continual-refinement store, snapshot mechanism, or rollback engine.

Those are already provided by NOOA, Omnigent, or Prime Agent, or are unnecessary for this bounded
task layer.
