# Execution providers

Agent OS records the coding harness, model, and intelligence provider separately. Provider identity
is part of the review gate: an implementation cannot be approved by a reviewer backed by the same
provider.

| Agent | Harness | Default model/provider | Credential path |
| --- | --- | --- | --- |
| `coordinator` / `planner` | Claude SDK | Claude/Anthropic | Claude subscription OAuth |
| `builder_claude` / `reviewer_claude` | Claude SDK | Claude/Anthropic | Claude subscription OAuth |
| `builder_codex` / `reviewer_codex` | Codex | `gpt-5.6-sol`/OpenAI | Codex subscription login |
| `builder_opencode` | OpenCode | `openai/gpt-5` | `OPENAI_API_KEY` or OpenCode auth |
| `builder_ollama` | OpenCode | `ollama/qwen3:14b` | local Ollama; no cloud key |
| `builder_antigravity` | Antigravity CLI | `gemini-3.6-flash-high`/Google | Antigravity CLI subscription login |

Only builder inference is local when `builder_ollama` is selected. An Omnigent run still uses its
Claude-backed coordinator and planner, while a direct OpenCode run removes that dependency.
Independent review may still use Codex. Do not describe a complete run as offline merely because
its builder was local. Codex is available as a generated implementation/review child, a direct
workspace-write builder, and a direct read-only reviewer.

## Claude-capacity fallback and model tiers

Agent OS never retries automatically after a usage-limit failure. An automatic retry could
duplicate durable child work already launched by the first coordinator. Inspect the task and
reconcile any running attempt. If no implementation succeeded, use a direct builder. Use the Codex
reviewer only for a non-OpenAI implementation:

```bash
uv run agent-os run tsk_... --runtime opencode \
  --provider ollama --model ollama/gemma4:26b
uv run agent-os run tsk_... --runtime codex-review

# Subscription-backed alternatives:
uv run agent-os run tsk_... --runtime codex
# or, for a Google implementation that Codex can independently review:
uv run agent-os run tsk_... --runtime antigravity
uv run agent-os run tsk_... --runtime codex-review
```

Direct Codex implementation runs with `workspace-write`; direct Codex review remains `read-only`.
Both are ephemeral, ignore ambient Codex configuration and repository rules, disable approval
escalation, and use an attempt-scoped private `CODEX_HOME` for writable CLI state. A Codex-built
attempt still needs a later reviewer from a non-OpenAI provider.

Active Codex implementation and review defaults use `gpt-5.6-sol`. Terra and Luna remain available
through explicit model overrides for measured workloads. Keep generated-child overrides exported
while running so attempt attribution matches the generated spec:

```bash
export AGENT_OS_CODEX_BUILDER_MODEL="gpt-5.6-sol"
export AGENT_OS_CODEX_REVIEWER_MODEL="gpt-5.6-sol"
uv run agent-os --bundle agents/coordinator spec sync
```

## Direct OpenCode fallback

`--runtime opencode` invokes the pinned OpenCode CLI directly, without Claude or Omnigent
coordination. Supply the full model identifier; Agent OS infers the provider from it and rejects a
conflicting `--provider`. For local work, start Ollama and select an installed model:

```bash
ollama list
uv run agent-os run tsk_... --runtime opencode \
  --provider ollama --model ollama/gemma4:26b --timeout-seconds 300
uv run agent-os run tsk_... --runtime codex-review
```

If `--model` is omitted, the direct path uses `AGENT_OS_OLLAMA_MODEL`, then the generated local
builder default `ollama/qwen3:14b`. The explicit `gemma4:26b` command above is the locally verified
end-to-end path; model availability and performance remain machine-specific.

For each task, Agent OS creates a private `STATE_DIR/runtime/opencode-direct/TASK_ID` tree, isolates
OpenCode's config and XDG directories, disables Claude compatibility discovery, uses an explicit
loopback Ollama provider block, and supplies empty Git global/system configuration. The model-facing
policy uses OpenCode's documented [permission rules](https://opencode.ai/docs/permissions/) to deny
external-directory access, web tools, subagents, skills, questions, outward Git/SSH commands,
publication, container commands, downloads, broad deletion, and file transfer. Exit zero is
insufficient: the JSON stream must also contain a terminal `step_finish` event with reason `stop`.

These OpenCode permissions are a tool-layer control, not an OS sandbox. The OpenCode process still
runs as the invoking user. Use Omnigent's platform sandbox, a container, or a VM for untrusted code.
A local Ollama attempt records `builder_ollama/opencode-native/ollama` and can be independently
reviewed by direct Codex. A cloud OpenCode attempt backed by OpenAI cannot be reviewed by Codex;
choose a reviewer backed by another provider.

## Antigravity subscription fallback

Agent OS supports Antigravity as a direct implementation runtime, not as a generated Omnigent
coordinator or child variant. This distinction is intentional. Omnigent 0.8.2's documented
`executor.harness: antigravity` path uses the `google-antigravity` SDK, which authenticates with a
Gemini API key or Vertex credentials. The direct `agy` runtime instead reuses the operator's
existing Antigravity CLI subscription login.

Requirements and workflow:

```bash
agy --version  # 1.1.6 or newer
uv run agent-os run tsk_... --runtime antigravity
uv run agent-os run tsk_... --runtime codex-review
```

The first command launches a state-owned `agent-os-builder` definition with structured JSON
streaming, native OS sandboxing, slash commands disabled, auto-update disabled, and only the task
workspace added. Antigravity 1.1 does not load a workspace-local hook during a headless run on the
tested release, so Agent OS installs one temporary named plugin under
`~/.gemini/config/plugins/agent-os-runtime-boundary` for the process lifetime. Its fail-closed
`PreToolUse` hook is activated by a per-run random token and denies ambient web, browser, MCP,
subagent, outward, destructive, and out-of-workspace calls before execution. The directory is
removed after the child exits; an existing directory with that name causes the run to fail without
overwriting it. Git uses an empty global/system configuration and cannot prompt. Stdout and stderr
are retained as separate private transcripts. Exit zero without a terminal `SUCCESS` result is
treated as failure.

Antigravity records a Google-backed implementation attempt and moves the task only to
`needs_review`. The second command invokes an ephemeral, read-only Codex/Sol reviewer directly. It
receives bounded host-generated diff evidence, produces a schema-validated verdict, and records the
review against the exact Google implementation attempt. It refuses OpenAI-backed implementations
and cannot complete a task without nonempty review evidence.

Do not give a direct Antigravity builder an acceptance criterion that requires it to run the test
suite itself. Verified against `agy` 1.1.12, the CLI's own `--sandbox` terminal restrictions can
deny or break a `run_command` test invocation even though the Agent OS `PreToolUse` policy allows
it, and a builder that cannot verify will stop without editing. Write file-state criteria and let
the independent reviewer run verification; see the compatibility note in
[the verification record](research/verification.md).

Override the implementation model for one run with `--model`, or set the non-secret environment
default:

```bash
export AGENT_OS_ANTIGRAVITY_MODEL="gemini-3.6-flash-high"
uv run agent-os run tsk_... --runtime antigravity
```

The earlier Omnigent-native integration remains unsupported on 0.8.2: it rejected a custom
coordinator bundle and did not preserve the declared child specification in an integrated probe.
That failed bridge does not affect the direct CLI runtime.

## Cloud execution

Choose any provider/model supported by your OpenCode installation before generating the bundle:

```bash
export AGENT_OS_OPENCODE_MODEL="openai/gpt-5"
export OPENAI_API_KEY="..."  # inject with your secret manager; never commit it
uv run agent-os init
```

Agent OS passes only a small runtime environment allowlist. The built-in cloud path permits
`OPENAI_API_KEY`; additional variable names must be explicitly named in `AGENT_OS_ALLOWED_ENV`:

```bash
export AGENT_OS_ALLOWED_ENV="CUSTOM_PROVIDER_API_KEY"
```

This variable contains names, not secret values. Avoid launching Agent OS under an environment that
contains unrelated credentials.

Omnigent 0.8.2 may materialize an injected Anthropic API key in a Claude child-process argument.
Agent OS therefore removes `ANTHROPIC_API_KEY` from every Omnigent run, even when it appears in
`AGENT_OS_ALLOWED_ENV`. Authenticate the coordinator and Claude SDK workers with Claude's OAuth
login. Prime Agent runs may receive an Anthropic key when `--provider anthropic` is selected because
they do not traverse this Omnigent launch path.

## Local Ollama through OpenCode

Omnigent 0.8.2 requires OpenCode `>=1.17.7,<1.18.0`. Install a compatible release and use
`agent-os doctor` to detect drift:

```bash
npm install --global opencode-ai@1.17.20
```

Add a non-secret provider block to `~/.config/opencode/opencode.json`, preserving existing keys:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": {
        "qwen3:14b": { "name": "Qwen 3 14B (local)" }
      }
    }
  }
}
```

Select a different local model before bundle generation if needed:

```bash
export AGENT_OS_OLLAMA_MODEL="ollama/your-model"
uv run agent-os init
```

Keep the override exported when running the task. Agent OS forwards only these two non-secret
model-selection variables (`AGENT_OS_OLLAMA_MODEL` and `AGENT_OS_OPENCODE_MODEL`) so runtime
attempt attribution matches the generated bundle without opening general environment inheritance.

Omnigent 0.8.2's headless asynchronous-orchestrator drain has a fixed 30-minute ceiling. Agent OS
therefore rejects Omnigent `--timeout-seconds` values above `1800` instead of presenting a larger
outer timeout as effective. Choose a local model and task small enough to finish inside that bound;
use the Prime Agent runtime for longer-lived work.

Verify registration without involving Agent OS:

```bash
ollama list
opencode models ollama
opencode run --pure --model ollama/qwen3:14b \
  "Return exactly OLLAMA_OPENCODE_OK and nothing else."
```

Omnigent merges user-defined OpenCode providers into its isolated session configuration. Agent OS
does not implement a second provider adapter, key store, or model router.

## Local Ollama through Prime Agent

Prime Agent can also use Ollama directly for a bounded persistent run. Add the public provider
shape below to `~/.prime/agent/models.json`; the placeholder API key is required by Prime's schema
but is not a credential and Ollama ignores it:

```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:11434/v1",
      "api": "openai-completions",
      "apiKey": "ollama",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false
      },
      "models": [{ "id": "qwen3:14b" }]
    }
  }
}
```

Then select the concrete provider and model on the Agent OS command:

```bash
uv run agent-os run tsk_... --runtime prime-agent \
  --provider ollama --model qwen3:14b \
  --token-budget 12000 --max-turns 6 --timeout-seconds 600
```

Agent OS passes both selections to Prime's actual CLI and records the same values on the attempt.
For `ollama`, it also enables Prime's offline startup, requests non-thinking mode, and prefixes the
task with Qwen's `/no_think` compatibility hint. Offline startup prevents update checks from turning
a declared local inference run into external traffic. A model may ignore reasoning controls, so the
token, turn, and wall-clock limits remain the authoritative bounds. Governed Prime launches disable
ambient extensions,
skills, prompt templates, themes, and automatic context-file discovery, then explicitly load only
Prime's bundled `goal` skill so the bounded run can report completion through Prime's own goal API.
Prime still inherits the invoking user's OS permissions; use a container, VM, or other enforced
boundary for untrusted repositories.
