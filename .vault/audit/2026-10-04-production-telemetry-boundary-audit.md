---
tags:
  - '#audit'
  - '#production-telemetry-boundary'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:b98f0a8ab5809beee11400ea179e2fa6a430ed8f4aebe979cce0defe75f4177c'
related:
  - "[[2026-03-20-service-lifecycle-architecture-adr]]"
  - "[[2026-07-19-observability-lanes-adr]]"
  - "[[2026-09-24-architecture-review-audit]]"
---
# `production-telemetry-boundary` audit: `Jaeger security remediation`

## Scope

User-authorized remediation on 2026-10-04 of the medium security finding
reported against revision b973403: production Jaeger publishes unauthenticated
collector, query UI, and health ports to all host interfaces. Review covers
`service/docker-compose.prod.yml`, the production section of
`service/README.md`, and the focused Compose profile regression tests.

This bounded change needs no durable implementation plan or new costly
decision. Accepted service-lifecycle and observability-lanes decisions retain
Compose health and OTLP tracing, without requiring public collector access.
The related architecture-review audit's beyond-loopback-hardening entry remains
historical evidence; this pass resolves its production Jaeger portion only.

## Findings

### production-jaeger-publication | medium | production telemetry host exposure fixed

Type: security/network boundary. Status: fixed and verified.
`service/docker-compose.prod.yml:114` publishes only the query UI on explicit
127.0.0.1. Collector ports 4317/4318 and health port 13133 have no host mappings.
Gateway and worker still export to `http://jaeger:4317`; Jaeger health runs
inside the container. Trace URLs, routes, server addresses, and thread IDs in
`src/vaultspec_a2a/telemetry/middleware.py:129` and `:199` remain diagnostic data
behind this boundary. UI port customization remains supported. Remote access
requires an authenticated TLS proxy, access controls, and resource limits.

### integration-jaeger-publication | medium | integration telemetry remains published on all host interfaces

Type: security/network boundary. Status: open follow-up, outside production fix.
`service/docker-compose.integration.yml:135` publishes OTLP and the query UI
without loopback binding. The infrastructure recipes use this file too
(`Justfile:105`). Host-started certification processes use the published OTLP
endpoint (`src/vaultspec_a2a/service_tests/harness.py:457`), so removal would
break that workflow. Follow-up: bind these host publications to loopback and
prove host export and querying in the integration certification lane.

### telemetry-full-url-credential-claim | low | query-string privacy needs a separate investigation

Type: privacy/documentation contract. Status: open investigation; credential
exfiltration is not established. The module promises that span attributes
contain no secrets, but `src/vaultspec_a2a/telemetry/middleware.py:139` records
the complete request URL, including any caller-supplied query string. This
pass does not establish a legitimate credential-bearing query workflow.
Follow-up: trace actual callers and decide on a URL attribute redaction policy
if sensitive query parameters are supported.

### compose-test-prerequisite-comment | low | regression section now states its CLI requirement

Type: documentation/test prerequisites. Status: fixed during review.
The regression section heading now distinguishes configuration checks requiring
the Compose CLI from checks requiring a running Docker daemon.

### production-remediation-review | low | focused security and compatibility checks passed

Type: implementation review. Status: PASS. A fresh read-only reviewer found
no concrete bypass or behavior regression in the candidate production changes.
Resolved SQLite and PostgreSQL configurations publish only the loopback UI,
including custom UI ports; legacy OTLP port overrides cannot restore host
publication. Docker Engine 29.8.1 and Compose v5.5.1 supplied live evidence.

Verification against the final configuration and tests:

- `uv run --no-sync --frozen python -m pytest src/vaultspec_a2a/service_tests/test_compose_profile_regression.py -m service -k 'test_prod or test_dev or test_integration or test_resolved' -q`: 15 passed, seven unrelated full-stack cases deselected.
- `uv run --no-sync --frozen python -m pytest src/vaultspec_a2a/control/tests/test_deployment_names.py -q`: seven passed.
- Locked Ruff lint/format, Ty, and basedpyright checks on the changed regression module: PASS. `git diff --check`: PASS.
- Live isolated production Jaeger project started with `up -d --no-deps --wait jaeger`. Docker inspection showed only 16686/tcp bound to 127.0.0.1, with no collector or health host publication. Jaeger was healthy.
- A real peer container connected to internal gRPC 4317, queried internal health 13133, and submitted a unique OTLP HTTP span on 4318. The host loopback UI returned that trace through its query API. This proves internal ingestion, health, and local diagnostic querying remain functional.
- Compose rejected UI port values containing `0.0.0.0:26686` or `[::]:26686`, rather than allowing host-address injection. The isolated project was removed successfully.

No full gateway/worker rebuild or unchanged live integration suite was required
for this host-publication-only change. Remote-host packet testing was not run;
the exposure result is based on actual Docker publication inventory. Deployment
assumes the default NAT bridge, not administrator-enabled direct routing or
unprotected gateway modes. Docker's port-publishing documentation describes
loopback exposure to same-segment peers before Engine 28.0.0; the service README
states the supported minimum for this boundary.

Semantic discovery returned `index_unverifiable`; server status confirmed
failed indexing. Grounding continued through focused source searches and Core
ADR listing/search. This is a discovery limitation, not a passing search result.

### remediation-commit-concurrent-work | medium | repository hooks block the scoped commit

Type: tooling/integration workflow. Status: open verification/commit blocker.
The scoped five-file commit attempt ran enabled hooks and was rejected. Whole-
repository Ty reported 15 diagnostics in concurrent untracked or temporarily
stashed work, including the POSIX-only MCP probe, authoring state-layout use,
and desktop ACL test import. Global vault gates reported an unresolved ADR
status and annotations in concurrent workspace/worker records. Scoped lint,
format, type, Markdown, and production-telemetry-boundary vault checks pass.
The hooks restored concurrent changes; no hook was bypassed and no unrelated
file was repaired. Retry the scoped commit once the other work is coherent.
The patch remains locally implemented and verified; commit completion is pending.

### remediation-commit-blocker-follow-up | low | prior validation failures repaired

Type: tooling/integration workflow. Status: resolved for the scoped production
patch. The user confirmed the hook was uninstalled and authorized fixing the
failures. Absence of the active pre-commit hook was verified; it was not
reinstalled. Concrete listener typing, context-manager types, payload inference,
formatting, and vault scaffold drift were repaired and reviewed in
`2026-10-04-acp-read-remediation-audit`. Full-tree Ruff lint/format, Ty, and
Basedpyright passed; 74 targeted tests passed. The original failure report is
retained above as history. Concurrent feature source remains in the shared
checkout for its owning commits; this pass commits only the production Jaeger
configuration, regression coverage, documentation, audit, and index.

## Recommendations

Retain the production publication and internal-export regression checks.
Apply the integration follow-up under its own verified scope. Investigate URL
privacy before proposing a costly redaction or telemetry-schema decision.
