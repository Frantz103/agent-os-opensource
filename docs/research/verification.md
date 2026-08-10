# Verification record

Verified locally on 2026-08-09.

## Dependency and framework surface

- `uv sync --dev` resolved and installed 141 packages.
- Installed framework versions: `nooa==0.0.8`, `omnigent==0.8.2`.
- `agent-os doctor` found the repository Omnigent CLI plus compatible OpenCode 1.17.20, Ollama,
  Doppler, Claude Code, Codex, and Prime Agent CLIs.
- `agent-os spec check` confirmed generated files match the NOOA definitions.
- Omnigent's own `omnigent.spec.load()` accepted the complete generated agent-image directory.

## Automated checks

- `.venv/bin/pytest`: 18 tests passed.
- `.venv/bin/ruff check .`: passed.
- Tests cover NOOA inheritance/typed contracts, spec compilation and drift, Omnigent bundle loading,
  task state transitions, attempt and review persistence, context bounding, host function tools,
  cross-vendor review enforcement, the review closure gate, and a no-process dry run.

The added Prime tests verify its NOOA coordinator contract, exact bounded command construction,
runtime attribution, positive autonomous limits, and that dry runs do not create attempts.
The OpenCode extension test verifies the generated harness/model pins and that `doctor` fails loudly
when an installed OpenCode version is outside Omnigent's supported range.

## Bounded end-to-end attempt

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

## OpenCode, Ollama, and Doppler extension

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
- Doppler `web-data-projets/stg` was verified by secret name only; no values were printed or written
  to the repository. A direct cloud probe returned exactly `DOPPLER_OPENCODE_OK` from
  `openai/gpt-5.6-terra`, reporting a $0.0356675 model cost. The complete generated
  `builder_opencode` path then returned exactly `OMNIGENT_DOPPLER_OK`, proving that the key survives
  Doppler launch, Omnigent isolation, and native OpenCode provider execution.
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
