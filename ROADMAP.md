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
