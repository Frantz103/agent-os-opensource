# Data handling

Agent OS stores task state in `STATE_DIR/agent_os.db` and runtime output under
`STATE_DIR/transcripts/`. The default state directory is `.agent-os` in the directory where the CLI
is invoked. The directory is created with mode `0700`; databases, backups, and transcript files use
mode `0600` on POSIX systems.

Task objectives, acceptance criteria, context values, evidence strings, and model transcripts may
contain proprietary source or personal data. They are not automatically redacted. Dry-run command
output hides the objective and prompt unless `--show-prompt` is explicitly supplied.

Agent OS does not upload its SQLite database. A configured harness or model provider may receive the
task envelope and repository content needed for execution. A local Ollama builder does not make the
whole workflow offline because planning and review may still use cloud harnesses.

Reviewers may receive bounded working-tree status and diff evidence for the declared workspace. The
collector does not return repository history, user Git configuration, or credential files.

Raw Anthropic API keys are not forwarded to Omnigent 0.8.2 because that version may expose them in
child-process arguments. Use Claude OAuth for Omnigent runs. This restriction does not make process
inspection generally safe; treat runtime diagnostics as sensitive.

OpenCode runs receive a session-owned XDG configuration plus fixed inline policy that disables
Claude compatibility and denies the `skill` tool for the model-facing build agent. OpenCode may
still enumerate host `~/.agents/skills` metadata locally at startup; it is not made available to the
model. Agent OS does not rewrite the operator's global OpenCode configuration.

Direct Antigravity runs use the operator's existing CLI login, which remains owned by Antigravity
under its normal user state. Agent OS does not copy that credential into task state. It writes the
runtime's custom agent under `STATE_DIR/runtime/antigravity/`, retains stdout and stderr as separate
mode-`0600` transcripts, disables CLI auto-update, and uses empty Git global/system configuration.
For the child-process lifetime, it writes a mode-`0600`, activation-scoped policy plugin under
`~/.gemini/config/plugins/agent-os-runtime-boundary` and removes it afterward. It never copies the
Antigravity OAuth token. The Google provider receives the task prompt and repository content needed
for implementation.

Direct Codex workers and reviewers reuse the operator's Codex CLI login. They run ephemerally with
user configuration and repository rules ignored; workers receive workspace-write while reviewers
remain read-only, and neither can escalate for approval. Agent OS writes implementation output under
`STATE_DIR/runtime/codex/`, review schema/results under `STATE_DIR/runtime/codex-review/`, and retains
separate private stdout/stderr transcripts. Task envelopes and review diffs are sent over stdin
rather than the process argument list. OpenAI receives that context and repository content;
the operator's file-backed `auth.json`, when present, is copied mode `0600` into a unique private
`CODEX_HOME` for the child lifetime and the entire temporary home is removed afterward. Keyring-backed
logins need no file copy. The durable Agent OS state never retains a Codex credential.

Before sharing state or bug reports:

1. Remove credentials, private repository paths, customer data, and personal information.
2. Preserve only the minimum transcript excerpt needed to reproduce the issue.
3. Record hashes rather than copying large or sensitive evidence artifacts.
4. Delete local state according to the repository owner's retention policy.

Back up `agent_os.db` together with its `-wal` and `-shm` files while the application is stopped, or
use SQLite's backup API. Automatic schema migration creates a versioned database backup but is not a
general disaster-recovery system.
