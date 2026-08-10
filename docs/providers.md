# Execution providers

Agent OS separates the coding harness from the model provider. The two new execution choices both
reuse Omnigent's `opencode-native` harness:

| Agent | Harness | Intelligence provider | Credential path |
| --- | --- | --- | --- |
| `builder_opencode` | OpenCode | `openai/gpt-5.6-terra` | Doppler `web-data-projets/stg` |
| `builder_ollama` | OpenCode | `ollama/qwen3:14b` | local Ollama; no cloud key |

Only the builder inference is local. The current Omnigent coordinator and planner still use
`claude-sdk`, and the independent review uses Claude or Codex. Do not describe a complete Agent OS
run as offline or private merely because `builder_ollama` was selected.

## Cloud execution through Doppler

The staging config is the non-production config containing the full provider set. Launch Agent OS
under Doppler so the native OpenCode server inherits `OPENAI_API_KEY` without writing it to a file:

```bash
doppler run --project web-data-projets --config stg -- \
  uv run agent-os run tsk_...
```

The verified secret names in `stg` are `ANTHROPIC_API_KEY`, `CEREBRAS_API_KEY`,
`GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENAI_API_KEY`, and
`OPENROUTER_API_KEY`. This document intentionally contains no values. Omnigent 0.8.2 passes the
`OPENAI_`, `ANTHROPIC_`, `GEMINI_`, and `GOOGLE_` families into its isolated native OpenCode
server. The pinned cloud variant therefore uses the direct OpenAI provider rather than requiring a
custom OpenRouter environment bridge.

## Local Ollama through OpenCode

Omnigent 0.8.2 rejects OpenCode versions outside `>=1.17.7,<1.18.0`. Install the newest compatible
release and use `agent-os doctor` to detect drift before a session starts:

```bash
npm install --global opencode-ai@1.17.20
```

Add this non-secret provider block to `~/.config/opencode/opencode.json`, preserving any existing
keys such as `mcp`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama (local)",
      "options": {
        "baseURL": "http://localhost:11434/v1"
      },
      "models": {
        "qwen3:14b": { "name": "Qwen 3 14B (local)" },
        "gemma4:26b": { "name": "Gemma 4 26B (local)" }
      }
    }
  }
}
```

The generated Agent OS variant pins `qwen3:14b` because it is the smaller general-purpose local
coding model currently installed. `gemma4:26b` remains available for manual OpenCode selection.
Embedding and function-specialist models are intentionally not exposed as coding agents.

Verify registration and run a local-only smoke test:

```bash
ollama list
opencode models ollama
opencode run --pure --model ollama/qwen3:14b \
  "Return exactly OLLAMA_OPENCODE_OK and nothing else."
```

Omnigent merges user-defined OpenCode providers into each per-session isolated config. That
upstream behavior is the reason Agent OS needs only a model pin in generated YAML and no custom
Ollama process or HTTP code.
