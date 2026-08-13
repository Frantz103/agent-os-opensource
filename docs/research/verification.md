# Verification record

Current release-candidate checks were run locally on 2026-08-13 for `0.1.0a2`. Earlier framework
probes below are retained as dated experimental evidence and are not substitutes for the alpha
release gate.

## 0.1.0a2 release gate (2026-08-13)

Both bounded runs used disposable fixtures outside this repository and reached durable completion
through a provider-independent review.

- Local provider. Task `tsk_7405bed94032` required one exact edit to `message.txt`. Implementation
  attempt `att_ea4ed373c371` recorded `builder_ollama/opencode-native/ollama` with model
  `ollama/gemma4:26b` and changed only that file. Direct Codex review attempt `att_66b80a164368`
  recorded `reviewer_codex/codex/openai` with `gpt-5.6-sol` and produced review `rev_3931aceabf7f`
  with an evidence-bearing `approve`, moving the task to `completed`.
- Cloud provider. Task `tsk_131f35cfeb88` required one exact edit to `value.py`. Implementation
  attempt `att_0ca1d4d176a9` recorded `builder_antigravity/antigravity-cli/google` with
  `gemini-3.6-flash-high`. Review attempt `att_5fb45f543145` produced `rev_d3552e98088e` with
  `approve`, moving the task to `completed`.

Two fail-closed behaviors were exercised as part of the same gate and are recorded because they
demonstrate the completion contract rather than a defect:

- A first local review returned `blocked` because the read-only review environment exposed no
  usable temporary directory, so `pytest` could not initialize. The task moved to `blocked` rather
  than `completed`, and a re-review of the same attempt was refused because that attempt already
  carried a review record.
- On task `tsk_39709164df1e`, an Antigravity attempt exited `SUCCESS` while changing nothing. The
  task stopped at `needs_review`, and Codex review returned `request_changes` citing a clean
  `git status` and an empty diff for attempt `att_df8764cfbfad`. A successful process and a model
  claim did not complete the task.

### Antigravity CLI compatibility note

Verified against `agy` 1.1.12. Under `--sandbox`, that version restricts terminal execution: a
`run_command` call for `python3 -m pytest` was denied by the CLI's own permission layer, not by the
Agent OS `PreToolUse` policy, which independently evaluates the same call as `allow`. A later
attempt reached the workspace Python but failed with `ModuleNotFoundError: No module named
'encodings'`. `git status` and `git diff` executed normally.

The practical consequence is that a direct Antigravity builder should not be given an acceptance
criterion that requires it to run the test suite itself; verification belongs to the independent
reviewer, which is not sandbox-restricted in the same way. The dated `agy` 1.1.6 evidence below,
in which an Antigravity attempt did run the requested pytest, reflects the older CLI and is not
current behavior.

## Codex model refresh and Antigravity direct runtime (2026-08-11)

- Active Codex implementation/review defaults now use `gpt-5.6-sol`; Terra and Luna remain explicit
  overrides. Historical `gpt-5.4` results below remain dated evidence, not current configuration.
- Omnigent 0.8.2's documented Antigravity harness targets the `google-antigravity` SDK, whose
  published authentication contract requires `GEMINI_API_KEY` or Vertex credentials. It does not
  consume an Antigravity CLI subscription session. The earlier Omnigent-native experiment remains a
  failed compatibility result: it rejected a custom coordinator bundle and did not preserve the
  declared child specification in a disposable integrated run.
- Antigravity CLI documentation and changelog verification established that `agy>=1.1.6` supports
  structured `stream-json` output, custom Markdown agents, native sandboxing, and `PreToolUse` hooks.
  Agent OS therefore implements Antigravity as a direct Google-backed implementation runtime rather
  than an Omnigent variant.
- A correctly ordered headless smoke using `--output-format stream-json`, `--mode plan`,
  `--sandbox`, an explicit Gemini model, and `--print=<prompt>` emitted a stable init event and
  terminal `SUCCESS` result. The `--print` option consumes its prompt value, so all other flags must
  precede it.
- Disposable task `tsk_d16900653b66` changed exactly one fixture file, ran the requested pytest,
  emitted terminal `SUCCESS`, and recorded implementation attempt `att_2757b91ae97b` as
  `builder_antigravity/antigravity-cli/google` with model `gemini-3.6-flash-high`. It moved the
  durable task only to `needs_review`.
- The first integrated run also proved that custom-agent frontmatter alone does not reduce every
  main-agent built-in tool: `manage_task` remained advertised and was used. Two live probes then
  showed that the tested CLI did not discover a documented workspace-local hook in headless mode;
  `search_web` executed. The supported runtime now installs a temporary activation-scoped global
  plugin for the child-process lifetime. A subsequent live probe produced an `error_message` whose
  reason named the Agent OS policy denial, did not execute the web tool, changed no workspace file,
  and removed the plugin after exit. Regression tests cover plugin collision/cleanup, allowed
  workspace operations, network/MCP tools, destructive commands, and outside paths.
- Three attempts to use Omnigent 0.8.2 with a root Codex coordinator entered its tmux-based
  interactive startup path, produced no useful headless output, and were terminated within the
  declared bounds. The failed attempts remained recorded and did not approve the implementation.
- Agent OS replaced that unsupported path with direct `codex exec --ephemeral` worker and review
  roles. The worker uses workspace-write; the reviewer remains read-only. Both ignore user
  config/rules, disable approval escalation, receive their task envelope through stdin, and use a
  private per-attempt `CODEX_HOME` that is destroyed after exit.
- A no-escalation probe inside the already Seatbelt-confined development host proved that the
  private home fixed Codex app-server startup, then failed when macOS rejected a second nested
  `sandbox-exec`. This is an outer-host nesting limit: the production launcher retains Codex's own
  sandbox instead of silently bypassing it. The bounded live probes therefore ran with permission
  at the outer development layer while retaining the inner Codex policies.
- A fresh direct-worker run with `gpt-5.6-sol` changed only `message.txt`, verified exact bytes and
  two pytest invocations, recorded `builder_codex/codex/openai`, and moved the durable task only to
  `needs_review`. Its final diff was the single requested line and its temporary Codex home was
  absent after exit.
- Direct Codex/Sol review attempt `att_4963624c4ac9` inspected that exact Google attempt read-only,
  verified the single-file diff and a passing pytest without modifying the fixture, and produced
  review `rev_0b32f74f9f56` with an evidence-bearing `approve`. The task moved from `needs_review`
  to `completed`. The recorded review names the exact attempt, file bytes, diff, command, exit code,
  provider identity, transcript scope, and expected read-only pytest cache warning. The local
  evidence directory retains the mode-`0600` database, stdout/stderr transcripts, review schema,
  and structured result.
- A failed process or zero exit without a structured terminal result fails the attempt and task.
  A successful implementation must still receive a different-provider review.

## Direct OpenCode/Ollama fallback (2026-08-11)

- Disposable task `tsk_10fd3653ec16` required one exact edit (`VALUE = 1` to `VALUE = 2`), one
  pytest, no other file changes, no network or outward mutation, local Ollama attribution, and
  independent review.
- The first Omnigent attempt (`att_b47bf8a0cfc5`) failed before model execution because the managed
  outer development sandbox denied Omnigent's global log path. The permission-adjusted retry
  (`att_bc5f214a67d5`) reached Claude authentication and failed on the subscription weekly limit.
  Both failures remained in the task ledger and neither produced approval.
- Direct OpenCode then ran the same task with `ollama/gemma4:26b`, private per-task config/XDG
  state, loopback Ollama registration, and the bounded tool policy. Attempt `att_ec9aa89ede1b`
  recorded `builder_ollama/opencode-native/ollama`, changed only `value.py`, ran
  `pytest test_value.py` with one pass, emitted the required terminal stop event, and moved the task
  only to `needs_review`. The stderr transcript retained a non-blocking macOS FSEvents warning from
  the managed outer sandbox.
- Direct Codex/Sol review attempt `att_dca7bdfe8203` ran read-only, verified the exact file bytes,
  single-file diff, implementation transcript, and an independent pytest pass. Review
  `rev_ab6893624919` approved the exact Ollama attempt with nonempty evidence and moved the task to
  `completed`.
- This is the bounded local implementation-and-independent-review release gate. It proves recovery
  from Claude capacity exhaustion without erasing the failed coordinator attempts. It does not
  turn direct OpenCode's tool permissions into OS containment or make Codex review local/offline.

## Dependency and framework surface

- `uv lock` resolved 162 packages for the supported Python range.
- Installed framework versions: `nooa==0.0.8`, `omnigent==0.8.2`.
- `agent-os doctor` found the repository Omnigent CLI plus compatible OpenCode 1.17.20, Ollama,
  Claude Code, Codex, and Prime Agent CLIs.
- `agent-os --bundle agents/coordinator spec check` confirmed the checked-in generated files match
  the NOOA definitions.
- Omnigent's own `omnigent.spec.load()` accepted the complete generated agent-image directory.

## Automated checks

- `.venv/bin/pytest --cov=agent_os --cov-report=term-missing`: 82 tests passed with 87% total
  statement coverage.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/pyright`: passed with zero errors or warnings.
- `.venv/bin/pip-audit`: found no known third-party dependency vulnerabilities; the unpublished
  local `agent-os-opensource` distribution was the only skipped package.
- `detect-secrets` found no candidate secrets in the built wheel or source distribution. Its
  tracked-source scan reported only the documented non-secret Ollama placeholder and a synthetic
  test value; direct inspection confirmed both classifications. Targeted path/key-pattern scans
  also found no private task paths or credential values in either artifact.
- A wheel built from the source distribution installed with plain pip in a clean Python 3.13
  environment outside the checkout. That installed CLI initialized a state-owned bundle and passed
  Omnigent spec validation. The same wheel correctly rejected unsupported Python 3.14.
- Tests cover NOOA inheritance/typed contracts, spec compilation and drift, Omnigent bundle loading,
  task state transitions, schema migration and backup, crash reconciliation, concurrent work-item
  exclusion, attempt and review immutability, context bounding, host function tools, provider-aware
  review enforcement, the atomic closure gate, CLI reconciliation, and no-process dry runs.
- The first exact-head CI run after the direct-runtime expansion passed both macOS/Python jobs but
  exposed a missing Ubuntu system prerequisite: Omnigent refused to validate its Linux sandbox
  without `bwrap`. The workflow now installs Bubblewrap in every Linux test, quality, and installed-
  wheel job; disabling sandbox validation was not used as a workaround.

A bounded local release probe also proved that Omnigent can emit an authentication failure while
exiting zero. Agent OS now recognizes the explicit fatal launcher message, records a failed attempt,
and returns nonzero; a fake-runtime regression test preserves that fail-closed behavior.

The same probe exposed two further release blockers. A provider credential was materialized by
Omnigent into a child process argument, and the local builder was dispatched without a durable
implementation-attempt record. The stalled process was interrupted after seven minutes; Agent OS
terminated the complete process group and recorded the failure. A wall-clock timeout now applies to
both supported runtimes, with regression coverage. Agent OS now strips `ANTHROPIC_API_KEY` from the
Omnigent environment even when an operator names it in the custom allowlist, and bundle validation
checks the real runtime tool registry. The exposed credential still must be rotated before that key
is used again or the repository is released publicly.

A fresh local-provider release probe after restoring Claude OAuth reached Omnigent coordination but
the Claude subscription then reported its weekly usage limit. Omnigent surfaced that result as an
error while still exiting zero; the untouched workspace tests remained failing, no builder attempt
or review was recorded, and the host incorrectly moved the task to `needs_review`. Agent OS now
recognizes the observed usage-limit marker as fatal and records the coordinator attempt and task as
failed.

Subsequent bounded cloud probes exercised the hardened lifecycle and harness boundaries:

- A Claude SDK builder completed a real one-file implementation, reported terminal child status,
  and produced two passing tests. The coordinator independently verified the diff and evidence.
- The original `codex-native` builder and reviewer both failed with `Codex native bridge state is
  missing`. The task stayed blocked because the same-provider Claude reviewer was correctly denied.
- Agent OS therefore moved its Codex builder/reviewer variants to Omnigent's supported `codex`
  subprocess harness, pinned to `gpt-5.4`, with native shell and web search disabled. A direct run of
  the generated builder completed the same one-file task and passed both tests in about one minute,
  proving the replacement harness and sandboxed dynamic-tool path.
- A first direct run of the replacement Codex reviewer remained read-only and passed both tests, but
  correctly blocked because the macOS sandbox denied `.git` evidence. Agent OS now supplies bounded,
  workspace-scoped status/diff evidence through a hardened host function instead of exposing
  repository history to a child. The collector returned only `M slug.py` and the current patch in a
  live probe. Given that evidence, a fresh Codex reviewer independently read the source/tests, passed
  both tests, and returned `approve` without editing, reading `.git`, or using network tools.
  Automated tests cover command hardening and output bounds; the integrated review round trip is
  still pending.
- A fresh integrated run reached a recorded `builder_codex/codex/gpt-5.4` attempt, but the Claude
  coordinator then exhausted its weekly subscription allocation and Omnigent terminated the child.
  Agent OS closed both running attempts and failed the task; the fixture remained untouched.

At that historical checkpoint, the individual Claude SDK and Codex subprocess worker paths were
live-proven but the final different-provider round trip was still pending. The 2026-08-11
Antigravity-to-Codex run above now supplies that end-to-end evidence without Claude. The previously
exposed Anthropic credential remains deferred by operator decision and must be resolved before a
public release that could disclose it.

That probe also emitted Omnigent's `did not resolve in the parent spec` warning for the declared
`planner` child. Direct runner-log inspection showed this instance was a known Omnigent 0.8.2 false
positive rather than a parent-spec substitution: session creation had already cached the selected
child, and the turn path searched that child for itself a second time. The child's exposed tool set
was the planner tool set, not the coordinator's task-ledger surface. Upstream
[PR #4435](https://github.com/omnigent-ai/omnigent/pull/4435) documents and tests the same sequence;
it remains open, so 0.8.2 may still print the misleading warning. This warning alone is not accepted
as failure evidence, while an undeclared name or a child with the wrong tool/harness identity remains
a release-blocking failure.

The added Prime tests verify its NOOA coordinator contract, exact bounded command construction,
provider/model propagation to the real CLI, offline startup for Ollama, runtime attribution,
explicit loading of only Prime's bundled goal skill, positive autonomous limits, and that dry runs
do not create attempts.
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

On 2026-08-11, a disposable Ollama/Prime probe confirmed that Agent OS passes the real
`ollama`/`qwen3:14b` identity, offline mode, print-mode exit contract, isolated resource flags, and
bounded limits to Prime. A direct no-tool probe returned exactly `LOCAL_OK`. In task mode the model
did edit the disposable fixture and pass its test, but it did not call Prime's internal
`goal.complete()` before exhausting its token budget. Agent OS recorded the attempts as failed and
did not create an approval. This is useful failure evidence, not a passing Prime end-to-end gate;
the direct OpenCode/Ollama path above is the separately verified local fallback.
