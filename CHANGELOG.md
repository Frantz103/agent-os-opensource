# Changelog

This project follows Semantic Versioning. Alpha releases may still contain documented breaking
changes.

## Unreleased

### Fixed

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
