# Releasing

Agent OS uses PEP 440 alpha versions in Python metadata and human-readable SemVer labels in release
notes. `0.1.0a1` corresponds to `0.1.0-alpha.1`.

## Release gate

1. Update `CHANGELOG.md`, `pyproject.toml`, and `agent_os.__version__` together.
2. Run the full test, lint, type, generated-spec, dependency-audit, and wheel-install gates.
3. Run one bounded local-provider and one bounded cloud-provider task through implementation,
   independent review, and durable completion evidence.
4. Confirm no internal secret-manager names, credentials, private transcripts, or personal data are
   present in tracked files or release artifacts.
5. Require exact-head CI on the release commit.
6. Create a signed `v0.1.0-alpha.1` tag and GitHub prerelease.
7. Publish to PyPI through trusted publishing with artifact attestations; never use a long-lived API
   token in GitHub Actions.
8. Install the published wheel in a fresh environment and repeat the bundle-generation smoke test.

Do not describe an alpha as a hosted production control plane.
