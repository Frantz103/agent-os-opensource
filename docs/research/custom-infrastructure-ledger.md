# Custom infrastructure ledger

This ledger records every manual seam added after checking the two framework surfaces. Source LOC
means nonblank, non-comment physical lines, measured by `scripts/custom_loc.py`. Tests, generated
YAML, docs, and the NOOA role definitions themselves are excluded.

| Manual seam | What was missing | Why it was necessary | Code |
| --- | --- | --- | --- |
| Typed task contracts | Neither framework defines this product's task, attempt, evidence, or review record | A stable acceptance contract must survive and be inspectable outside one model conversation | `src/agent_os/models.py` |
| Domain task persistence | NOOA persists one agent's events/snapshots; Omnigent persists sessions/conversations | Real work needs a project-level unit of work joining several harness sessions to acceptance and review | `src/agent_os/store.py` |
| Cross-session context envelope | Both frameworks manage context within their own agent/session boundary | A fresh coordinator session needs durable task truth and bounded prior evidence without copying whole transcripts | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | NOOA has no Omnigent exporter and Omnigent has no NOOA importer | The requested split requires NOOA to remain definition authority while Omnigent executes | `src/agent_os/specs.py` |
| Omnigent task tool bridge | Omnigent function tools can call Python, but it cannot infer this task schema | The coordinator must persist attempt/review outcomes while using framework-native child sessions | `src/agent_os/tools.py` |
| Omnigent process launcher | Omnigent runs an agent image but knows nothing about an Agent OS task id or state directory | One command must bind a task/workspace/context to the framework CLI and retain the transcript reference | `src/agent_os/runner.py` |
| Operator task CLI | Omnigent's CLI is session-oriented and NOOA's CLI is agent/eval-oriented | Operators need create/list/show/context/run commands for the explicit task model | `src/agent_os/cli.py` |
| Gap measurement | Neither framework measures application-owned glue | The experiment requires current, reproducible code-size evidence for every manual seam | `scripts/custom_loc.py` |

## Current measured size

Verified on 2026-08-09:

| Manual seam | Source LOC | Paths |
| --- | ---: | --- |
| typed task contracts | 89 | `src/agent_os/models.py` |
| domain task persistence | 432 | `src/agent_os/store.py` |
| cross-session context envelope | 57 | `src/agent_os/context.py` |
| NOOA-to-Omnigent compiler | 251 | `src/agent_os/specs.py` |
| Omnigent task tool bridge | 75 | `src/agent_os/tools.py` |
| Omnigent process launcher | 110 | `src/agent_os/runner.py` |
| operator task CLI | 144 | `src/agent_os/cli.py` |
| gap measurement | 31 | `scripts/custom_loc.py` |
| **Total** | **1,189** | |

Refresh with:

```bash
uv run python scripts/custom_loc.py
```

## Infrastructure deliberately not built

- No custom agent loop.
- No custom Claude Code or Codex adapter.
- No child-agent scheduler or polling loop.
- No custom conversation/transcript database.
- No custom sandbox, policy engine, cost limiter, terminal bridge, or UI.
- No vector store or automatic memory layer.
- No separate review engine.

Those are already provided by NOOA or Omnigent, or are unnecessary for this bounded task layer.
