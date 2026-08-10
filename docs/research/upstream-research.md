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

## OpenCode and Ollama extension

- OpenCode repository: [anomalyco/opencode](https://github.com/anomalyco/opencode)
- Provider documentation source:
  [`providers.mdx`](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/providers.mdx)
- Ollama OpenAI compatibility:
  [official API documentation](https://docs.ollama.com/api/openai-compatibility)

OpenCode's provider layer is powered by AI SDK providers and explicitly documents Ollama as an
OpenAI-compatible custom provider at `http://localhost:11434/v1`. Omnigent 0.8.2 already ships an
`opencode-native` harness and merges user-defined OpenCode provider blocks into its isolated
per-session configuration. Its native server also passes supported provider environment families,
including `OPENAI_`, from the launch process. These observed capabilities make both new paths
declarative: an Omnigent executor model pin chooses direct OpenAI or local Ollama, while OpenCode
continues to own provider calls, permissions, and session behavior.

The local catalog was first inspected with OpenCode 1.18.4 and then reverified with Omnigent's
compatible OpenCode 1.17.20 and Ollama 0.32.5. The selected `qwen3:14b` model advertises tool support
and a 40,960-token context window. `gemma4:26b` is also registered but is not the default because
its installed footprint and runtime demand are substantially larger.

## Integration conclusion

Reimplementing a multi-agent event loop, harness adapter, sub-agent scheduler, terminal capture,
sandbox, policy engine, conversation database, or review fan-out would defeat the experiment.
Agent OS therefore compiles NOOA definitions to an Omnigent bundle and lets Omnigent run it.

The integration gap is semantic: NOOA and Omnigent do not share an agent-definition format. Their
persistence is also agent/session-centric rather than a project task ledger with acceptance and
review evidence. Those are the only load-bearing seams implemented here.

## Prime Agent

- Repository: [PrimeIntellect-ai/prime-agent](https://github.com/PrimeIntellect-ai/prime-agent)
- Reviewed main commit: `a18809e00ea30638584d87b3afea7285a9d7296c`
- Package evaluated: `0.7.1`
- Architecture: [coding-agent architecture](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/architecture.md)
- Long-running runtime: [long-running agents](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/long-running-agents.md)
- Recursive execution: [RLM](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rlm.md)
- Machine interfaces: [JSON](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/json.md) and [RPC](https://github.com/PrimeIntellect-ai/prime-agent/blob/main/packages/coding-agent/docs/rpc.md)

Files read included the root README and `AGENTS.md`; architecture, daemon, long-running-agent, RLM,
runtime, compaction, session, JSON, RPC, and agent-connection documentation; CLI parsers and RPC
types; daemon supervisor/worker protocols; kernel bootstrap/snapshot code; goal and autonomous-run
code; scheduling and heartbeats; agent messaging; and Continual Harness implementation/tests.

Architectural intent:

- The UI/client is disposable; persistent root workers own agent sessions, schedules, kernels, and
  descendants behind a local daemon supervisor.
- Goals and autonomous limits make long work explicit. Heartbeats and schedules deliver prompts to
  durable roots without requiring an attached terminal.
- IPython is a persistent control environment. `rlm(...)` admits a recursive child, and explicit
  messages or artifacts carry results back rather than blocking on a nested return value.
- Context is treated as programmatic data. Automatic compaction, snapshots, child registries, and
  session restoration prevent every working detail from remaining in one chat window.
- The Continual Harness stores mutable, evidence-linked prompt/memory/skill/subagent overlays
  separately from the immutable base system prompt and records snapshots for rollback.
- JSON is a useful one-shot event boundary. RPC is the richer local integration protocol; it is not
  a complete hosted control plane or security boundary.

The full evidence, limitations, and per-capability decisions are in the
[Prime Agent evaluation](prime-agent-evaluation.md). The conclusion is to add Prime as a peer runtime,
adopt its long-running mechanics rather than rebuilding them, keep Omnigent for native sandboxed
Claude/Codex interoperability, and retain Agent OS's product-level task/review ledger.
