# Contributing

Agent OS is an experiment in using upstream framework capabilities before adding infrastructure.
Issues and focused pull requests are welcome.

## Development setup

```bash
git clone https://github.com/Frantz103/agent-os-opensource.git
cd agent-os-opensource
uv sync --locked --dev
uv run pytest
uv run ruff check .
uv run pyright
uv run agent-os --bundle agents/coordinator spec check
```

## Design constraints

- Keep NOOA role definitions in `src/agent_os/definitions.py`.
- Verify NOOA, Omnigent, or Prime Agent cannot already provide a capability before adding custom
  orchestration, persistence, sandbox, policy, or harness code.
- Record every new application-owned seam in `docs/research/custom-infrastructure-ledger.md`.
- Do not hand-edit generated `agents/**/config.yaml`; run
  `uv run agent-os --bundle agents/coordinator spec sync`.
- Tests must not launch paid or credential-backed model sessions. Mock the process boundary or use a
  dry run.
- Never commit credentials, private task transcripts, `.agent-os/` state, or user repository data.

## Pull requests

Keep changes scoped, add regression tests, update public documentation, and describe the exact
verification performed. Pull requests must pass CI and independent review. By contributing, you
agree that your work is licensed under Apache-2.0.
