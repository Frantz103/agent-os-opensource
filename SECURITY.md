# Security policy

## Supported versions

Security fixes are provided for the latest published `0.1.x` alpha release. Unreleased branches and
older alpha builds are not supported.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** flow in the repository Security tab. Do not open a public
issue for suspected credential exposure, sandbox escape, authorization bypass, arbitrary code
execution, path traversal, or ledger-integrity failures.

Include the affected version or commit, operating system, runtime/harness, reproduction steps,
impact, and whether credentials or external systems were reached. Remove real secrets and private
repository content from reports.

The maintainer will acknowledge a complete report within five business days, coordinate a fix and
advisory, and credit reporters who want attribution. No bounty program is currently offered.

## Security boundary

The supported containment boundary is Omnigent's OS sandbox. NOOA's generated-code checks are
defense in depth, not containment. Prime Agent inherits the invoking user's permissions and must be
placed inside a separate container, VM, or OS sandbox for untrusted work. See
[`docs/threat-model.md`](docs/threat-model.md).
