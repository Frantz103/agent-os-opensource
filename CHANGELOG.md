# Changelog

This project follows Semantic Versioning. Alpha releases may still contain documented breaking
changes.

## 0.1.0a1 - Unreleased

### Added

- Provider-aware execution identity and attempt-bound independent review.
- SQLite schema migration with private pre-migration backup.
- Atomic completion checks, concurrent work-item exclusion, stale-attempt reconciliation, and
  process attribution.
- Runtime environment allowlisting, private transcripts, safe dry-run output, and denied outward
  mutations.
- Installed-wheel bundle generation, supported-Python metadata, expanded CI, and public governance
  documentation.

### Security

- Completion no longer accepts an unbound or stale approval.
- Different harness names no longer satisfy review independence when the intelligence provider is
  the same.
- Unrelated operator environment variables are not copied into runtime processes by default.
