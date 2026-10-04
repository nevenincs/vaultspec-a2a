---
tags:
  - '#audit'
  - '#production-telemetry-boundary'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:5cfeb0f781745ca6c1a0e445ba14ff741b69357d02e4f5473a92b39220003b58'
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

### final-shared-checkout-verification | medium | new ACP test drift belongs to the active migration

Type: integration/verification. Status: queued under S02 of
`2026-10-04-acp-read-remediation-plan`, which is actively changing the read
contract from offset to line. After the original failures were repaired and
full-tree Ty/Basedpyright passed, the current read helper began requiring
line. Two direct calls in `src/vaultspec_a2a/providers/tests/test_acp_fs_read_limits.py:128`
and `:139` still pass offset; latest Ty reports four diagnostics there. The
migration's tests also retain old offset expectations and need their complete
contract update, not a compatibility shim. No S02 status or implementation was
changed by this review. Its existing sequential plan owns the remaining work.

The reconciling-dispatch workspace helper initially lacked an import during
concurrent editing. It is now imported once, preserving workspace authority;
review found no altered refusal path. Three real redispatch/refusal suites
passed 24 tests. Together with the 74 engine/discovery/replay tests above,
98 targeted tests passed. Latest whole-tree Ruff lint/format, vault conformance,
and annotation checks passed. Full type-check completion for the newest shared
checkout awaits the S02 test migration; earlier passing evidence is retained
as history rather than presented as certification of newer code.

Production commit d4d4084b contains exactly the five scoped Jaeger files. The
active commit hook remains absent as requested. No unrelated work was reverted
or included in that commit.

## Recommendations

Retain the production publication and internal-export regression checks.
Apply the integration follow-up under its own verified scope. Investigate URL
privacy before proposing a costly redaction or telemetry-schema decision.
## Authorized dependency and validation follow-through, 2026-10-04

The user requested committing all current changes, fixing failures, and bumping
ACP. Existing provider-binary and client-wire decisions cover this maintenance.

### acp-current-release | low | resolved: adapter and lockfile updated

Type: dependency maintenance. Status: resolved. The official npm registry latest
stable is 0.85.1. The exact @agentclientprotocol/claude-agent-acp pin and npm
lockfile were updated from 0.84.0 to 0.85.1 using pinned Node 26.8.1/npm 11.19.0.
Seven installed packages changed; npm reports zero vulnerabilities. The lock now
supplies ACP SDK 1.6.0 and Claude SDK 0.3.286. Its installed Windows executable
reports Claude Code 2.1.286. The CI helper's stale 2.1.207 expectation now matches
2.1.286, and the real helper succeeds. This is CI binary identification, without
adding any provider admission or completed-turn proof. Claude and ZAI remain
unproven in the served eligibility declaration. No real model turn is claimed.
The real adapter handshake and installed SDK callback service tests both passed
after the update: two passed, 74 deselected.

### integrated-static-drift | low | resolved: concrete gate failures repaired

Type: verification and maintenance. Status: resolved. The owning ACP migration
fixed its overlong SDK test lines and synchronous-context-manager use under
async with. Windows ACL helpers now reject non-Windows invocation before using
Windows-only ctypes attributes, restoring cross-platform typing. Removed unused
public exports for the engine layout constant and workspace helper. Removed the
obsolete discovery view parser and its three implementation-only tests after
confirming no production consumers. Shared reading/freshness and real rejection
tests remain. Corrected a subsequent real-peer formatting change. Whole-tree
Ty platform checks and Basedpyright pass with zero diagnostics; unused-symbol
and unconsumed-export gates also pass. The engine connection proof validates
that HTTPcore supplies an AsyncNetworkStream before proving it, making the
explicit pinned runtime dependency and its fail-closed contract concrete.

### core-under-concurrent-load | low | resolved: audit write retried after Git timeout

Type: verification environment. Status: recovered. The first guarded audit write
failed with Cannot verify Git protection for local settings. Core's protection
probe has a five-second Git subprocess deadline; full static analysis and tests
were running concurrently. A subsequent vault check completed. No protection
check was disabled, no dependency source modified, and no unverified write used.
Final validation results are appended after their actual completion.
