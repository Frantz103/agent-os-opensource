# Verification record

Current release-candidate checks were run locally on 2026-08-10. Earlier framework probes below
are retained as dated experimental evidence and are not substitutes for the alpha release gate.

## Dependency and framework surface

- `uv lock` resolved 162 packages for the supported Python range.
- Installed framework versions: `nooa==0.0.8`, `omnigent==0.8.2`.
- `agent-os doctor` found the repository Omnigent CLI plus compatible OpenCode 1.17.20, Ollama,
  Claude Code, Codex, and Prime Agent CLIs.
- `agent-os spec check` confirmed generated files match the NOOA definitions.
- Omnigent's own `omnigent.spec.load()` accepted the complete generated agent-image directory.

## Automated checks

- `.venv/bin/pytest --cov=agent_os --cov-report=term-missing`: 39 tests passed with 85% total
  statement coverage.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/pyright`: passed with zero errors or warnings.
- `.venv/bin/pip-audit`: found no known third-party dependency vulnerabilities; the unpublished
  local `agent-os-opensource` distribution was the only skipped package.
- A wheel built from the source distribution installed with plain pip in a clean Python 3.13
  environment outside the checkout. That installed CLI initialized a state-owned bundle and passed
  Omnigent spec validation. The same wheel correctly rejected unsupported Python 3.14.
- Tests cover NOOA inheritance/typed contracts, spec compilation and drift, Omnigent bundle loading,
  task state transitions, schema migration and backup, crash reconciliation, concurrent work-item
  exclusion, attempt and review immutability, context bounding, host function tools, provider-aware
  review enforcement, the atomic closure gate, CLI reconciliation, and no-process dry runs.

A bounded local release probe also proved that Omnigent can emit an authentication failure while
exiting zero. Agent OS now recognizes the explicit fatal launcher message, records a failed attempt,
and returns nonzero; a fake-runtime regression test preserves that fail-closed behavior.

The same probe exposed two further release blockers. A provider credential was materialized by
Omnigent into a child process argument, and the local builder was dispatched without a durable
implementation-attempt record. The stalled process was interrupted after seven minutes; Agent OS
terminated the complete process group and recorded the failure. A wall-clock timeout now applies to
both supported runtimes, with regression coverage. Agent OS now strips `ANTHROPIC_API_KEY` from the
Omnigent environment even when an operator names it in the custom allowlist, and bundle validation
checks the real runtime tool registry. The exposed credential still must be rotated before another
provider run or public release.

A fresh local-provider release probe after restoring Claude OAuth reached Omnigent coordination but
the Claude subscription then reported its weekly usage limit. Omnigent surfaced that result as an
error while still exiting zero; the untouched workspace tests remained failing, no builder attempt
or review was recorded, and the host incorrectly moved the task to `needs_review`. Agent OS now
recognizes the observed usage-limit marker as fatal and records the coordinator attempt and task as
failed. The local end-to-end release gate therefore remains unpassed; the cloud gate was not
started.

The added Prime tests verify its NOOA coordinator contract, exact bounded command construction,
runtime attribution, positive autonomous limits, and that dry runs do not create attempts.
The OpenCode extension test verifies the generated harness/model pins and that `doctor` fails loudly
when an installed OpenCode version is outside Omnigent's supported range.

## Historical bounded end-to-end attempt (2026-08-09)

A durable read-only smoke task was created and its complete Omnigent command/context was rendered.
The first real invocation reached the installed Omnigent CLI but stopped before any model call
because the workspace sandbox prevented Omnigent from creating its standard `~/.omnigent` runtime
directory. Agent OS persisted the failed coordinator attempt and transcript path.

A request to rerun outside the workspace sandbox was denied because it would send repository
context to credential-backed external model services while the smoke task explicitly prohibited
network calls. No attempt was made to weaken or bypass that boundary.

Therefore the verified claim is **framework-loaded and process-boundary-ready**, not “live
multi-agent completion.” A live Claude/Codex round trip remains an explicit operator-authorized
integration check with an egress-approved task.

## OpenCode, Ollama, and secret-manager extension

- OpenCode's provider documentation and Omnigent's shipped `opencode-native` example/source were
  reviewed before implementation. The extension uses their existing provider and harness seams.
- The existing OpenCode config was backed up, then its MCP entries were preserved while a non-secret
  Ollama provider was added. `opencode models ollama` resolves `ollama/qwen3:14b` and
  `ollama/gemma4:26b`.
- A direct local probe returned exactly `OLLAMA_OPENCODE_OK`. It took roughly two minutes and the
  OpenCode event reported 15,304 total tokens, demonstrating meaningful prompt overhead even for a
  trivial local request.
- The first Omnigent probe exposed two fail-loud compatibility issues before useful execution:
  generated `sandbox.type: auto` is schema-valid but is not a runtime backend in Omnigent 0.8.2,
  and installed OpenCode 1.18.4 was outside Omnigent's required `>=1.17.7,<1.18.0` range. The
  compiler now omits sandbox type so Omnigent selects its platform backend, and OpenCode is pinned
  to the newest compatible 1.17.20 release. `agent-os doctor` now validates that version using
  Omnigent's own compatibility functions.
- The corrected generated `builder_ollama` path returned exactly `OMNIGENT_OLLAMA_OK` through
  Agent OS YAML, Omnigent, native OpenCode, and local `qwen3:14b`. The bounded response took about
  four minutes, so this path is useful for deliberate local work rather than latency-sensitive
  orchestration.
- A secret-manager-launched direct cloud probe returned exactly `CLOUD_OPENCODE_OK` from the
  configured OpenAI model. The complete generated `builder_opencode` path then returned exactly
  `OMNIGENT_CLOUD_OK`, proving that the selected key survives secret-manager launch, Omnigent
  isolation, and native OpenCode provider execution. No secret values or private secret-manager
  project identifiers are retained in this public record.
- No custom OpenCode adapter, Ollama client, API-key loader, model router, or process supervisor was
  added. The source delta is declarative variants, a model pin field, provider-aware routing text,
  and a doctor compatibility check inside the already-existing compiler/CLI seams.

## Prime Agent upstream verification

Prime Agent was cloned from live upstream at commit
`a18809e00ea30638584d87b3afea7285a9d7296c`, package version `0.7.1`.

- `npm install` completed with 354 packages added. npm audit reported 16 dependency findings: 11
  high, 5 moderate, and no critical findings.
- The Continual Harness Python suite passed 35/35 tests.
- Focused daemon protocol, agent-connection, and kernel-snapshot tests passed 92/92.
- A broader focused TypeScript group passed 217/219. The two failures were first-use kernel setup
  failures caused by this evaluation sandbox's home/cache restrictions; the same recursion path
  passed once writable uv, Python, cache, and kernel locations were supplied.

## Prime Agent live probes

- **Model path:** a no-session CLI call returned exactly `PRIME_AGENT_LIVE_OK`.
- **JSON/RPC:** RPC returned strict JSONL on stdout; the first-run telemetry notice stayed on stderr.
  Fresh-request responses arrived out of input order, confirming request IDs must be correlated.
- **Persistence:** a root with a one-time schedule remained detached after client EOF. After the
  supervisor received `SIGKILL`, its worker restarted the supervisor on the same socket; a fresh
  client rediscovered and observed the same root session and worker.
- **RLM and messaging:** a live parent admitted `eval-child`; the child became independently visible,
  sent `RLM_CHILD_OK` through `agent_message`, and the parent returned `RLM_PARENT_OK`. First-use
  kernel bootstrap required writable uv/cache/venv paths. The autonomous wrapper later exited
  nonzero because aggregate use reached `22,762/16,000` tokens, demonstrating that a useful final
  message does not override budget status.
- **Continual Harness:** before refinement, the model returned a prose test summary. A global,
  evidence-linked prompt note required strict minified JSON; a new session then returned exactly
  `{"status":"FAIL","passed":5,"failed":1,"evidence":"/tmp/probe-b.log"}`. Rollback by
  refinement id removed the entry and restored the prior snapshot. This proves mechanism and
  cross-session effect for one formatting task, not general quality improvement.
- **Custom socket CLI:** `list --socket` worked, while `status`, `schedule list`, and `shutdown`
  rejected the flag at public CLI validation despite lower-level parser support.

The bounded Prime JSON integration itself is covered by dry-run tests. A real Agent OS repository
task through Prime remains subject to the task's egress authorization and independent review gate.
