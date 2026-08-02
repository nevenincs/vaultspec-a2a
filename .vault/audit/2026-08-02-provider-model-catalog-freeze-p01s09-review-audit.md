---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c451516424b9bd2d4193ea7ebb4a0c0e69ec5a2df5575781ea3bc59e4bd198fc'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
---

# `provider-model-catalog` audit: `P01.S09 exact freeze review`

## Scope

Formal review of schema-v1 catalog selection freezing, exact provider-native
execution through compiler and factory boundaries, ordered fallbacks, modern
restart without catalog discovery, public frozen-assignment disclosure, and
same-run recovery behavior.

## Findings

### frozen-disclosure-replay-gap | medium | Resolved

Initial review found that direct same-ID replay and insert-race winner recovery
returned no modern frozen assignment even when durable metadata contained the
authoritative selection. Both paths now reconstruct the validated persisted
record without live discovery and project the same schema-v1 envelope as new
start, commit replay, and status. A real SQLite race and subsequent direct
replay assert one identical non-null digest-bearing envelope.

### invalid-modern-restart-aborts-sweep | medium | Resolved

Modern persisted selection validation initially happened outside the per-thread
restart fault boundary. One malformed or digest-invalid record could therefore
abort reconciliation of every later thread. The corrupt run is now failed with
a bounded static reason, classified as `invalid_frozen_assignment`, and the
sweep continues. A real database regression places the malformed record first
and proves the next valid thread reaches circuit-breaker handling.

### metadata-enrichment-changes-replay-identity | medium | Resolved

The new replay regression exposed that `process_metadata` mutated the request's
metadata with a generated nickname before the accepted digest was computed.
The same later request had not undergone that enrichment when replay identity
was checked and was refused as a different body. Metadata enrichment now uses a
deep copy: durable metadata retains its nickname and context while the request
fingerprint continues to describe caller input.

### generated-nickname-masks-same-id-race | medium | Resolved

The same regression exposed that SQLite may report the generated nickname
unique constraint before the primary-key constraint when two modern requests
race on one run ID. Explicit-ID inserts now defer nickname classification until
the gateway rolls back and checks for the durable run ID. A present winner uses
normal replay identity and disclosure; an absent winner with a genuine nickname
collision remains a 409.

### different-id-nickname-race-regression | low | Resolved

Remediation review requested proof that deferring explicit-ID nickname
classification did not weaken a genuine different-ID, same-nickname collision.
The real SQLite concurrency test now runs that inverse race on the same modern
catalog path: exactly one run starts and dispatches, while the other receives
the bounded nickname 409 with no second dispatch.

## Verification

- The dedicated remediation boundary passes four tests: one forced modern
  same-ID insert race plus direct replay and an inverse different-ID nickname
  race, one corrupt-first restart isolation case, and both existing
  reconciliation failure-ladder regressions.
- Ruff passes on the five touched replay and reconciliation boundary files.
- BasedPyright reports zero errors and warnings on gateway, dispatch, and their
  dedicated regression files.
- The broader S09 boundary previously passed 135 focused tests; 80 additional
  provider runtime tests passed with one intentional live-provider deselection.
- Isolated locked-project OpenAPI verification passes six tests at version
  `0.3.0`; the shared environment's installed distribution metadata remains
  stale at `0.2.0` and is not used as artifact evidence.

## Recommendations

- P01.S11 should retain the real same-ID race and corrupt-first restart cases in
  its assembled proof rather than replacing them with helper-only assertions.
- P03 consumers should compare the returned frozen digest and exact lane values
  across start, replay, and status without inferring provider values from labels
  or catalog order.
