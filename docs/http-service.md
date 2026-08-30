# Local HTTP service

The HTTP service lets a non-Python program submit bounded work to Agent OS. It is a local,
single-operator adapter. It is not a remote execution, authentication, or multi-tenant service.

## Start

Set a bearer token in the process environment, then start the service:

```bash
export AGENT_OS_SERVICE_TOKEN="replace-with-a-secret-manager-value"
agent-os-service \
  --state-dir .agent-os-service \
  --workspace-root .agent-os-workspaces \
  --runtime codex
```

The server binds only to `127.0.0.1`. It does not accept a host override. The caller sends the
token as `Authorization: Bearer TOKEN` on every request.

The public adapter supports the direct Codex runtime. Provider, model, commands, credentials, and
host paths are service configuration. They are not request fields. Each work id receives a durable
mode-`0700` workspace under the configured workspace root. The service initializes that workspace
as a Git repository and reserves its `artifacts/` directory for returned files.

## Create work

`POST /v1/work`

```json
{
  "idempotency_key": "6632fe46-7825-4e4e-9f96-310aaab17d8a",
  "title": "Institutional deliverable",
  "objective": "Create the requested deliverable.",
  "required_outcome": "artifacts/result.txt contains the final result.",
  "constraints": ["Do not contact external systems"],
  "institution": {"id": "2426206d-f178-4c1b-bbc2-7d4615bb84b3", "name": "Holding"},
  "company": {"id": "4bfd8503-631e-43a9-ad07-dd2380a9f83d", "name": "Agency"},
  "project": {"id": "3200f004-b4d3-4ec1-a70e-87c035f84f2c", "name": "Project"},
  "owner": {"id": "a7e01458-1511-4111-ad78-de5e8144483b", "name": "Owner"},
  "budget": {"amount_cents": 500, "currency": "USD"}
}
```

The organization and budget fields become immutable task context. They do not grant Agent OS
authority and do not claim that Agent OS enforces the institution's budget.

The first accepted request returns `202`. An identical replay returns `200` and the same work. A
reused key with different immutable semantics returns `409` and does not start another run.

## Read work

- `GET /v1/work/{work_id}` returns the task, latest attempt, exact observed usage and cost
  provenance, and the latest outcome summary.
- `GET /v1/work/{work_id}/status` returns the smaller polling projection.
- `GET /v1/work/{work_id}/artifacts` returns regular files from `artifacts/`, including media type,
  byte count, SHA-256 digest, and an authenticated service-relative download URL. The URL returns
  the exact bytes. Symlinks are never followed.
- `GET /v1/work/{work_id}/evidence` returns attempts, exact transcript/stderr bytes, reviews, and
  task events. It does not expose or dereference host paths.

Status is raw Agent OS execution truth:

```text
queued | running | needs_review | blocked | completed | failed | cancelled
```

A higher-level institution can project those values into its own lifecycle. For example,
`queued/running` can mean executing, `needs_review/completed` can mean returned,
`blocked/failed` can mean refused, and `cancelled` remains cancelled. That projection does not
change Agent OS state.

Cost remains observation, not estimation. The response preserves runtime-reported and
provider-rate-derived amounts, their source, and their evidence reference separately. It populates
`actual_cost_cents` only when every retained attempt has a billed amount covered by one exact
aggregate billing receipt; reported or derived dollars do not become actual billing. A mix of billed
and unpriced attempts keeps the observed dollars, returns `cost_source: "mixed_observed"`, and leaves
actual cost null. When reviewable or terminal work has no observed amount, the service returns
`cost_source: "unknown"` and the stable status evidence reference
`agent-os:{work_id}:cost-unknown`; actual, reported, and derived amounts remain null. Queued or
running work with no observation keeps the entire cost projection null. Unknown cost is never
returned as zero.

Every refusal uses `error.code`, `error.message`, and `error.next_action`. Invalid JSON fields,
including caller-selected runtimes, models, providers, commands, credentials, or paths, fail with
`422 invalid_request`.

## Cancel work

`POST /v1/work/{work_id}/cancel`

A running request returns `202` while Agent OS stops its owned Codex process group. Only a process
group that reaches a terminal state becomes `cancelled`. An ambiguous teardown becomes `blocked`;
the service does not claim that unverified resources are gone. Repeating cancellation after a
confirmed cancel returns `200`. Cancellation after another terminal or reviewable outcome also
returns `200` with that current projection and does not claim that cancellation was requested.

The service keeps execution handles in one process. Use one server worker. Durable distributed
scheduling, remote caller authority, and restartable workflow execution remain outside this local
contract.
