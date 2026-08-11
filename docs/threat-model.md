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
- Prime Agent is unsandboxed unless the operator supplies a container, VM, or equivalent boundary.

## Required controls

- Builders receive only the declared workspace as writable and have tool-network access disabled.
- Push, deploy, destructive infrastructure, and broad deletion commands are denied by policy.
- Runtime environment propagation is allowlisted; unrelated variables are excluded.
- State and transcript paths are private to the local user.
- Execution provider/model identity is persisted when work begins.
- Approval must name the exact successful attempt and come from a different provider.
- Completion validates the newest attempt for every work item inside one database transaction.
- Schema changes create a private backup and fail closed on unknown versions.

## Residual risks

- A compromised dependency or harness running outside the worker sandbox can access the invoking
  account's files and explicitly allowed credentials.
- Model providers receive the prompts and repository context sent through their harnesses.
- Local SQLite state is not tamper-proof against the owning operating-system user.
- Tool-command policies are defense in depth and cannot replace OS containment.
- A machine crash can interrupt work between external side effects and ledger updates; outward
  mutations are therefore outside the supported alpha workflow.
