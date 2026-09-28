# Roadmap

Agent OS remains focused on bounded repository work across multiple AI coding runtimes. Roadmap items should preserve the durable task contract, evidence requirements, independent review, and fail-closed execution model.

## Current: stabilize the public alpha

- Harden task, attempt, evidence, and review lifecycle behavior.
- Improve containment and recovery across supported runtimes.
- Keep provider and model identity explicit.
- Avoid duplicating capabilities already owned by upstream harnesses.

## Next: durable cross-harness handoff

Allow one task to continue across multiple coding harnesses without making any harness session the source of truth.

A handoff should transfer only durable task state and relevant evidence, not a copied conversation transcript.

Target flow:

```text
task contract
→ harness A attempt
→ durable handoff
→ harness B continuation
→ independent review
→ final evidence
```

Required properties:

- Preserve objective, constraints, acceptance criteria, workspace, and task lineage across providers.
- Bind every contribution to an exact attempt, harness, provider, and model.
- Carry forward relevant evidence, unresolved work, and prior review findings without requiring the next runtime to reconstruct the entire previous session.
- Prevent duplicate or concurrent continuation of the same owned work unless explicitly allowed.
- Support explicit operator handoff first, with policy-driven routing only after the semantics are proven.
- Preserve independent review requirements across provider changes.
- Treat capacity failure, runtime failure, and deliberate specialization as valid reasons to hand work to another harness.

The task belongs to Agent OS. Claude, Codex, OpenCode, Ollama, Antigravity, Prime Agent, and future runtimes are execution environments that may contribute to it.

## Later: cooperative multi-harness execution

Explore one durable task whose phases are intentionally performed by different runtimes, for example:

```text
Claude planning
→ Codex implementation
→ local Ollama analysis
→ different-provider review
```

This should build on the handoff contract rather than introduce a separate agent-to-agent chat protocol.

## Under consideration: bring-your-own harness adapters

Not planned work. Recorded so the open questions are not rediscovered later.

Supported runtimes are currently first-class: six plan builders, twenty-six runtime branches, and
sixty-nine runtime-name literals, plus runtime-specific containment. Adding a harness therefore
costs a code change and a fresh security review, which is the real barrier rather than the command
line.

A declarative adapter would have to cover three surfaces:

- invocation, as an argument template with a declared prompt injection point and model flag;
- observation, as a declared rule for terminal success, because a harness can exit successfully
  without doing the work;
- containment, which is the unresolved one.

The open question is whether Agent OS owns an operating-system containment boundary around any
adapter process, or whether each adapter declares its own. If containment stays harness-specific,
every adapter needs an individual security review and the extension point does not honestly
generalize. If Agent OS owns it, harness policy becomes defense in depth, but nested sandboxing
limits already recorded in the verification record apply.

Two constraints hold regardless:

- Provider independence must compare resolved model identity rather than a declared provider,
  because an adapter author controls the declaration.
- An adapter must not be able to exempt itself from independent review.

A conformance task that must be denied a write outside the workspace, a network call, and a push
would be the admission evidence for any adapter.

A model-routing launcher such as OpenRouter's Ori is a decorator over an adapter rather than an
adapter itself: it prefixes the invocation and changes the backing model, so it would apply to
every adapter at once instead of being wired per runtime.
