# Agent OS contributor instructions

This repository is an experiment in using framework capability before adding infrastructure.

- Keep NOOA classes in `src/agent_os/definitions.py` as the source of agent role definitions.
- Keep generated Omnigent bundles under `agents/`; regenerate this repository's bundle with
  `agent-os --bundle agents/coordinator spec sync`.
- Do not hand-edit generated `agents/**/config.yaml` files.
- Before adding orchestration, persistence, context, review, sandbox, or harness code, verify that
  NOOA or Omnigent does not already provide it.
- Every custom infrastructure seam must be recorded in
  `docs/research/custom-infrastructure-ledger.md`, including why framework support was
  insufficient and the measured physical LOC.
- Tests must not launch model sessions. Mock or dry-run the Omnigent process boundary.
- A live model run is an explicit integration check and must use a bounded, non-destructive task.
