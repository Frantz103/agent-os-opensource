# Execution providers

Agent OS records the coding harness, model, and intelligence provider separately. Provider identity
is part of the review gate: an implementation cannot be approved by a reviewer backed by the same
provider.

| Agent | Harness | Default model/provider | Credential path |
| --- | --- | --- | --- |
| `builder_opencode` | OpenCode | `openai/gpt-5` | `OPENAI_API_KEY` or OpenCode auth |
| `builder_ollama` | OpenCode | `ollama/qwen3:14b` | local Ollama; no cloud key |

Only builder inference is local when `builder_ollama` is selected. The default coordinator and
planner still use Claude, and independent review uses Claude or Codex. Do not describe a complete
run as offline merely because its builder was local.

## Cloud execution

Choose any provider/model supported by your OpenCode installation before generating the bundle:

```bash
export AGENT_OS_OPENCODE_MODEL="openai/gpt-5"
export OPENAI_API_KEY="..."  # inject with your secret manager; never commit it
uv run agent-os init
```

Agent OS passes only a small runtime environment allowlist. The built-in cloud path permits
`OPENAI_API_KEY` and `ANTHROPIC_API_KEY`; additional variable names must be explicitly named in
`AGENT_OS_ALLOWED_ENV`:

```bash
export AGENT_OS_ALLOWED_ENV="CUSTOM_PROVIDER_API_KEY"
```

This variable contains names, not secret values. Avoid launching Agent OS under an environment that
contains unrelated credentials.

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

Verify registration without involving Agent OS:

```bash
ollama list
opencode models ollama
opencode run --pure --model ollama/qwen3:14b \
  "Return exactly OLLAMA_OPENCODE_OK and nothing else."
```

Omnigent merges user-defined OpenCode providers into its isolated session configuration. Agent OS
does not implement a second provider adapter, key store, or model router.
