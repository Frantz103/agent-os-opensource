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

## Commands

    uv sync --dev --extra omnigent                 prepare the environment
    uv run pytest                                  the suite
    uv run pytest tests/test_release.py::test_name one test
    uv run ruff check .                            lint
    uv run ruff check . --fix                      lint, with fixes
    uv run pyright                                 types
    uv run agent-os --bundle agents/coordinator spec check   verify the bundle
    uv run agent-os --bundle agents/coordinator spec sync    regenerate it
    uv build                                       build the distribution
    uv run pip-audit                               dependency advisories

Before you finish: `pytest`, `ruff check .`, `pyright`, and `spec check`.

CI runs `spec check`, never `spec sync`. Sync regenerates the bundle; check
proves the bundle still matches `src/agent_os/definitions.py`. Sync, then
check.

`uv run agent-os doctor --runtime <name>` reports whether a child runtime is
admitted. Run it before you conclude a capability is missing.

Python 3.12 or 3.13. `uv` is the toolchain. Ruff enforces import order
(rules E, F, I, UP, B, SIM; line length 100); pyright covers `src` and
`tests`. `uv.lock` is generated: never hand-edit it.

## Terms

    NOOA        the role definitions in src/agent_os/definitions.py
    Omnigent    the process boundary that runs a bundle
    bundle      a generated agents/<name>/ tree; every config.yaml inside it
                is generated output
    spec        the bundle's declared contents
    admission   whether a child runtime may run; `doctor` evaluates it

## Evidence and review

`tests/test_release.py` enforces the infrastructure ledger. A custom seam
without a ledger row fails the suite.

`.github/pull_request_template.md` carries the evidence checklist and the
publication-boundary checks. Read it before you open a PR, not after.

## Which repository this is

This is the public repository. Assume every change here is published the
moment it lands. Private lab history, transcripts, scratch state, and
negative-result artifacts must never arrive in this tree.
