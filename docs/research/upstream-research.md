# Upstream research notes

Research was performed on 2026-08-09 against primary upstream repositories, documentation, source,
and checked-in examples.

## NVIDIA NOOA

- Repository: [NVIDIA-NeMo/labs-OO-Agents](https://github.com/NVIDIA-NeMo/labs-OO-Agents)
- Reviewed main commit: `10c6846f52c6fe67a62e1da0e1e7b60c8bc43e32`
- Stable package used: `nooa==0.0.8`
- Paper: [NVIDIA-labs OO Agents: Native Python Object-Oriented Agents](https://arxiv.org/abs/2607.20709)
- Architecture article: [Six Agent Harness Capabilities for Higher Model Performance](https://developer.nvidia.com/blog/six-agent-harness-capabilities-for-higher-model-performance/)

Files and examples read included `README.md`, `examples/README.md`, quickstarts 01-12, the memory
example, `src/nooa/agent.py`, event backend and context code, SQLite storage, and the nooa-memory
package surface.

Architectural intent:

- An agent is a Python object: fields are state, ordinary methods are deterministic capabilities,
  docstrings are prompts, and annotations are contracts.
- An ellipsis-bodied method is implemented at runtime by an LLM strategy. The default CodeAct loop
  writes Python against live objects and agent methods; `PredictStrategy` provides single-shot
  structured output.
- Typed returns are validated and retried by the framework.
- Context blocks, event history, summarization, tracing, skills, MCP, SQLite snapshots/events, and
  optional relational long-term memory are already framework capabilities.
- Pass-by-reference and model-callable harness APIs are intended to reduce repeated serialization
  and indiscriminate context growth.
- Static generated-code checks are defense in depth, not containment; upstream explicitly requires
  OS-level isolation for untrusted generated code.

## Omnigent

- Repository: [omnigent-ai/omnigent](https://github.com/omnigent-ai/omnigent)
- Reviewed main commit: `de8aee826c48d632ce335a702f2cca2f6240a6b9`
- Stable package used: `omnigent==0.8.2`
- Agent format: [Agent YAML spec](https://github.com/omnigent-ai/omnigent/blob/main/docs/AGENT_YAML_SPEC.md)
- Harness documentation: [Harnesses](https://omnigent.ai/docs/build/harnesses)

Files and examples read included `README.md`, `docs/AGENT_YAML_SPEC.md`, `docs/POLICIES.md`, the
harness plugin and conformance-bench designs, Python client docs, and the Polly, Debby, Scribe,
Sentinel, Remy, and Deep Research bundles.

Architectural intent:

- Agent images are declarative YAML plus optional instructions, skills, tools, and nested agents.
- Each agent or child chooses its own harness. Built-ins cover Claude Code, Codex, Cursor, Pi,
  OpenCode, and others, with a community plugin seam for additional harnesses.
- Multi-agent work is session-oriented: child dispatch, independent sessions, inbox notification,
  session history, fork/resume, interruption, and persistent server state are built in.
- Function tools, MCP, OS tools, terminals, sandbox providers, credential proxies, tool policies,
  cost budgets, and a browser/mobile collaboration surface are built in.
- The Polly example already demonstrates the most important requested pattern: plan, dispatch coding
  workers on different harnesses, then send each diff to a reviewer from another vendor.
- The Debby example demonstrates parallel fan-out and inbox-driven completion without polling.
- The Scribe example demonstrates a doer/reviewer split with a different-vendor reviewer.
- Remy demonstrates optional Hindsight-backed cross-session memory.

## Integration conclusion

Reimplementing a multi-agent event loop, harness adapter, sub-agent scheduler, terminal capture,
sandbox, policy engine, conversation database, or review fan-out would defeat the experiment.
Agent OS therefore compiles NOOA definitions to an Omnigent bundle and lets Omnigent run it.

The integration gap is semantic: NOOA and Omnigent do not share an agent-definition format. Their
persistence is also agent/session-centric rather than a project task ledger with acceptance and
review evidence. Those are the only load-bearing seams implemented here.
