# Threat model

## Scope

Agent OS is a local, single-operator task ledger that launches third-party agent runtimes against a
declared workspace. It is not an authentication, tenancy, or remote-execution service.

## Assets

- Source code and Git history in the declared workspace.
- Provider credentials and subscription sessions available to runtime processes.
- Task objectives, constraints, acceptance criteria, evidence, and transcripts.
- Integrity of attempt attribution, review independence, and completion state.

## Trust boundaries

- The operator and local operating-system account are trusted.
- Task text, repository content, model output, and tool output are untrusted input.
- NOOA, Omnigent, Prime Agent, coding harnesses, model providers, and local models are dependencies,
  not Agent OS security boundaries.
- Omnigent's OS sandbox is the supported containment boundary for implementation workers.
- Antigravity's native OS sandbox is the containment boundary for direct Antigravity workers; the
  state-owned pre-tool policy is an additional fail-closed control.
- Codex's workspace-write sandbox is the containment boundary for direct fallback workers; its
  read-only sandbox separately contains direct reviews.
- Prime Agent is unsandboxed unless the operator supplies a container, VM, or equivalent boundary.

## Required controls

- Builders receive only the declared workspace as writable and have arbitrary tool network access
  disabled. Claude SDK provider traffic stays outside the worker OS helper; Omnigent disables native
  Claude tools and routes file and shell calls through sandboxed `sys_os_*` helpers.
- Codex provider traffic uses Omnigent's subprocess harness with its native shell and web search
  disabled; repository access stays in the same sandboxed dynamic tools.
- Push, deploy, destructive infrastructure, and broad deletion commands are denied by policy.
- Runtime environment propagation is allowlisted; unrelated variables are excluded.
- Review diff evidence is collected by a bounded host tool with Git configuration, hooks, external
  diff, text conversion, submodule recursion, locks, and prompts disabled. Oversized evidence fails
  closed instead of being truncated or sent to a reviewer.
- OpenCode builders deny ambient host skills at the model-facing tool boundary without modifying
  the operator's global configuration.
- Direct Antigravity builders run with a state-owned custom agent, slash commands and auto-update
  disabled, empty Git configuration, and a temporary activation-scoped global plugin whose wildcard
  pre-tool hook denies ambient web, browser, MCP, subagent, outward, destructive, and
  out-of-workspace calls. An existing same-name plugin fails closed and is never overwritten.
- Direct Codex workers and reviews use ephemeral mode, ignore user config/rules, receive prompts by
  stdin, and disable approval escalation. Workers receive only workspace-write; reviewers receive a
  bounded host diff, remain read-only, and must return a schema-valid verdict with nonempty
  evidence. Reviews reject same-provider OpenAI implementation attempts before launch. Codex
  receives a unique mode-`0700` `CODEX_HOME` under private Agent OS state; a
  file-backed login is copied mode `0600` only for the child lifetime and removed with that home.
- Prime Agent receives the concrete provider/model on its actual CLI invocation. Governed launches
  disable ambient extensions, skills, prompt templates, themes, and automatic context-file
  discovery, then explicitly load only Prime's bundled `goal` skill; local Ollama startup is
  offline. Prime's built-in tools and kernels still inherit the invoking user account and therefore
  remain outside an Agent OS containment boundary.
- State and transcript paths are private to the local user.
- Execution provider/model identity is persisted when work begins.
- Approval must name the exact successful attempt and come from a different provider.
- Attempt finalization requires a terminal Omnigent child-task status; terminal task transitions
  reject running implementation attempts.
- Completion validates the newest attempt for every work item inside one database transaction.
- Schema changes create a private backup and fail closed on unknown versions.

## Residual risks

- A compromised dependency or harness running outside the worker sandbox can access the invoking
  account's files and explicitly allowed credentials.
- Omnigent 0.8.2 may materialize an injected provider key in a child-process argument. Treat process
  listings and diagnostic captures as sensitive, and prefer short-lived credentials until this
  upstream behavior is mitigated.
- Model providers receive the prompts and repository context sent through their harnesses.
- Local SQLite state is not tamper-proof against the owning operating-system user.
- Tool-command policies are defense in depth and cannot replace OS containment.
- A machine crash can interrupt work between external side effects and ledger updates; outward
  mutations are therefore outside the supported alpha workflow.
- OpenCode 1.17 still enumerates `~/.agents/skills` metadata locally even when the model-facing skill
  tool is denied; local runtime logs can therefore contain skill names.
- Antigravity owns its subscription session and provider transport outside Agent OS state. A
  compromised CLI or hook host process still runs as the invoking user and can access user-owned
  files; the native sandbox and policy reduce worker-tool authority but do not sandbox the CLI
  executable itself.
- Codex likewise owns its subscription session and provider transport. Read-only sandboxing limits
  review writes but does not sandbox the CLI executable itself from the invoking user's account. A
  process or dependency able to read the temporary Codex home during its lifetime can read a
  file-backed subscription credential.
