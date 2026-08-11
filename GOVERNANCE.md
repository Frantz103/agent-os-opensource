# Governance

Agent OS is maintained by Frantz Studio under a maintainer-led model.

The maintainer sets release scope, reviews changes, manages security disclosures, and may appoint
additional maintainers after sustained contribution. Architectural decisions must preserve the
thin-layer rule: application code exists only for task/evidence concepts the upstream frameworks do
not own.

Changes to the security boundary, task closure invariants, schema migrations, provider attribution,
or release automation require a pull request, green exact-head CI, and explicit maintainer review.
Force pushes and branch deletion on `main` are prohibited.
