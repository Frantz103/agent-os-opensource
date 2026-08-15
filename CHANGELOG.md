# Changelog

This project follows Semantic Versioning. Alpha releases may still contain documented breaking
changes.

## Unreleased

## 0.1.0a4 - 2026-08-15

### Added

- Provider-reported token usage and runtime-reported dollar observations now survive the Agent OS
  runner boundary on immutable attempt records, including per-model Omnigent subtree usage and
  direct Codex terminal-event usage. These observations remain explicitly distinct from estimated
  cost and authoritative billed cost.
- Usage collection is failure-contained: an unreadable runtime usage database records an evidence
  warning without masking the execution result or leaving the attempt running.

- A runtime conformance probe. `agent-os probe --runtime RUNTIME` runs one authorized attempt that
  tries to write outside its workspace, reach the network, and push to a Git remote, then reports
  which of the three the runtime actually allowed. `doctor` establishes that a runtime is present
  and supported; this establishes what it permits. Every target is private and offline — a canary
  directory beside the provisioned workspace, a loopback listener on an ephemeral port, and a local
  bare repository — and a run touches nothing outside `STATE_DIR/probes/<probe_id>`.

  A crossing is only ever established by the host observing its effect. The runtime's own
  `probe-attempts.json` is read solely to separate `blocked` from `not_attempted`, and never to
  establish success. `blocked` requires both halves — a reported attempt and the refusal it
  produced — because a runtime reporting an attempt with no refusal is claiming the action
  succeeded, and the host saw no trace of it. `--require-denied` rejects `not_attempted` exactly
  as it rejects `crossed`,
  because a boundary that was never tested has not been shown to hold; a run in which nothing was
  attempted exits non-zero as inconclusive rather than reporting three quiet denials. The probe
  verifies its own loopback listener still answers before reading a refused connection as a denial,
  since a dead listener refuses connections exactly the way a sandbox does, and it measures after a
  wall-clock timeout rather than discarding the evidence with the run.

  Measured on the first live runs: direct Codex denied all three with probe state under `$HOME`,
  but reported `push` crossed with state under `$TMPDIR`, because `workspace-write` grants the
  temporary directory as a writable root. A report from a temporary directory now carries that
  warning. A direct OpenCode run on local `qwen3:14b` claimed all three succeeded while nothing
  reached any target, which is what made requiring the refusal half of `blocked` necessary.

- An owner review path. `agent-os review TASK --attempt ATT --verdict approve|request_changes`
  records the operator's own verdict through the registered `reviewer_owner` identity, whose
  provider is `operator`. Because that differs from every model provider, the independence gate is
  satisfied rather than bypassed, and the existing rules still hold: the verdict binds to one exact
  implementation attempt, an approval without evidence is refused, and `request_changes` blocks the
  task. A local `builder_ollama` implementation reviewed by the owner completes a task without any
  non-local call, which a second model reviewer cannot do.

## 0.1.0a3 - 2026-08-13

### Fixed

- A model override that names a different intelligence provider than its harness is now refused
  instead of being recorded. `execution_identity` previously stored the pair unchecked, so an
  attempt could carry `openai` provenance beside an `anthropic` model name. Attempt provenance and
  the review-independence check both read that provider, so the contradiction is rejected before it
  becomes evidence. Only a `PROVIDER/MODEL` name carries a comparable claim; a bare model name
  remains the harness's own namespace.

- A supervisor cancelling Agent OS with `SIGTERM` no longer orphans the child harness. The default
  disposition ended the process immediately, so no `finally` block ran: the detached harness kept
  working on the workspace after the cancelling supervisor considered the run stopped, and the
  implementation attempt stayed `running` until a later reconcile. `SIGTERM` and `SIGHUP` now raise
  `RuntimeTerminated`, which unwinds through the existing governed cleanup, terminates the child
  process group, fails running child attempts, closes the attempt, and exits `143`. `SIGINT`
  behavior is unchanged. `SIGKILL` cannot be intercepted; a supervisor that escalates to it must
  terminate the recorded attempt process group itself.

## 0.1.0a2 - 2026-08-13

### Added

- A documented PyPI install path. `agent-os-opensource` publishes the `agent-os` command, and the
  README now covers `uv tool install`, `pip install`, and `uv pip install` alongside the existing
  from-source workflow.
- Regression coverage for the documented quickstart: `task create`, `task show`, `task list`,
  `context`, and `run --dry-run` are now exercised through `main()`, including the dry-run
  redaction of task context.
- Regression coverage for `doctor` failure paths: missing required CLIs and an invalid bundle.

### Changed

- `doctor` now ends a failing run with an explicit summary naming each failed check and stating
  that an optional runtime may be absent but must be a supported version when installed. The exit
  status is unchanged: an installed but incompatible optional runtime still fails.

## 0.1.0a1 - 2026-08-11

### Added

- Provider-aware execution identity and attempt-bound independent review.
- SQLite schema migration with private pre-migration backup.
- Atomic completion checks, concurrent work-item exclusion, stale-attempt reconciliation, and
  process attribution.
- Runtime environment allowlisting, private transcripts, safe dry-run output, and denied outward
  mutations.
- Installed-wheel bundle generation, supported-Python metadata, expanded CI, and public governance
  documentation.
- GPT-5.6 Sol defaults for Codex implementation/review, with explicit Terra or Luna overrides.
- A direct Antigravity CLI subscription runtime for Google-backed implementation, followed by
  direct, ephemeral, provider-independent Codex review when Claude capacity is unavailable.
- A direct Codex subscription runtime with the same workspace-write implementation baseline as
  Antigravity, separate from the read-only Codex review role.
- A direct OpenCode fallback that can run local Ollama or a named cloud model without the
  Claude-backed coordinator, while preserving provider attribution and independent review.

### Changed

- Omnigent's SDK-backed Antigravity integration remains unsupported; Agent OS now uses the direct
  CLI so subscription OAuth and the generated Omnigent agent graph stay separate.
- The unsupported headless root-Codex coordinator path is replaced by an explicit
  `--runtime codex-review` boundary for reviewing an existing cross-provider implementation.
- Wall-clock timeouts now return a clean CLI error after governed attempt cleanup instead of a
  Python traceback.

### Security

- Completion no longer accepts an unbound or stale approval.
- Different harness names no longer satisfy review independence when the intelligence provider is
  the same.
- Unrelated operator environment variables are not copied into runtime processes by default.
- Explicit OpenCode/Ollama model-selection variables are preserved so runtime attribution matches
  the generated bundle.
- Child dispatch requires the exact durable attempt id, interrupted coordinators close orphaned
  child attempts, and the direct Codex fallback reviewer runs read-only.
- Direct Codex workers run with workspace-write, direct reviewers remain read-only, and both use
  ephemeral sessions, disabled approval escalation, and a private per-attempt CLI home.
- A coordinator cannot finalize a child before Omnigent reports a terminal child task status or
  close a task while an implementation attempt is still running.
- Omnigent run bounds above its fixed 30-minute headless ceiling are rejected before launch.
- Claude SDK builders and reviewers keep provider connectivity outside the network-denied OS tool
  helper; native Claude tools remain disabled.
- Codex builders and reviewers use the supported subprocess harness with native shell and web search
  disabled, avoiding the unstable native bridge while keeping repository I/O in sandboxed tools.
- OpenCode builders deny ambient host skills at the model-facing tool boundary.
- Reviewers receive bounded, workspace-scoped status/diff evidence from a hardened host tool rather
  than direct access to repository history or user Git configuration.
- Direct Antigravity work runs in the CLI sandbox under a state-owned agent and temporary,
  activation-scoped global `PreToolUse` plugin that denies ambient and outward tools before
  execution and is removed afterward.
- Direct OpenCode work uses private per-task config/XDG state, a fixed deny policy for ambient and
  outward tools, empty Git configuration, and terminal-stop validation. This policy is not an OS
  sandbox; untrusted code still requires external containment.
