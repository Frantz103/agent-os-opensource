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

Before sharing state or bug reports:

1. Remove credentials, private repository paths, customer data, and personal information.
2. Preserve only the minimum transcript excerpt needed to reproduce the issue.
3. Record hashes rather than copying large or sensitive evidence artifacts.
4. Delete local state according to the repository owner's retention policy.

Back up `agent_os.db` together with its `-wal` and `-shm` files while the application is stopped, or
use SQLite's backup API. Automatic schema migration creates a versioned database backup but is not a
general disaster-recovery system.
