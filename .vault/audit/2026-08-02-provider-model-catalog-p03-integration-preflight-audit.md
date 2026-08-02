---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:012bd19d4bdc7faca42b62d1e3418fa4f4e3820b82c7e2ed0ccf6960c0df4f5b'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-adr]]"
---
# `provider-model-catalog` audit: `P03 integration preflight preparation review`

## Scope

Preflight review of the P03.S19 and P03.S20 cross-project proof path: Dashboard client and Rust broker boundaries, the current A2A gateway and durable recovery evidence, and narrow real-loopback Rust guards for catalog and frozen run-status forwarding. This audit records preparatory evidence only. P01.S07 now serves provider catalogs, but P01.S08-S11 remain unchecked; this does not close either P03 step or claim a selected run start, prompt setup, restart, or replay has run end to end.

## Findings

### producer-contract-incomplete | critical | The live P03 start path remains blocked until A2A P01.S08-S11 land

P01.S07 supplies the catalog route, structured health, and schema-versioned catalog envelopes. The current proof boundary still lacks P01.S08 selected-run admission and P01.S09 compilation-time frozen provenance, so the Dashboard/Rust preparation cannot start a provider-selected run through prompt setup at current heads. P03.S19 and P03.S20 therefore remain open.

### cross-scope-catalog-authority | medium | Resolved by independent remediation re-review

The first independent review found that Dashboard's query key used the workspace scope while its request omitted it; Rust then selected whichever active cell existed at arrival. A delayed A-scope query after a switch to B could therefore cache B's catalog under A. The fix sends `expected_scope` with the Dashboard catalog read, has Rust validate it against the captured active cell before deriving the engine-owned `workspace_root`, and consumes it before the A2A request. The real local Dashboard transport test proves the browser sends the fence; Rust same-, missing-, and mismatched-scope tests prove admission/refusal; the real TCP broker test proves A2A still receives only `workspace_root`. The independent remediation re-review passed with no findings and confirmed this is a Rust-only generation fence, not new A2A authority.

### scope-isolation | medium | Resolved in the Dashboard query client

The provider-catalog query no longer retains a prior scope's snapshot while a new workspace scope is loading. Query identity remains scoped, and the consumer fails closed to an empty catalog unless the complete response carries top-level `api_version: "v1"` and every provider lane has `catalog.schema_version: 1`.

### expiry-refetch | medium | Resolved with bounded served-expiry scheduling

Refresh now schedules from the earliest served catalog expiry, clamped to a one-millisecond minimum and one-hour maximum. When no expiry is served, retry cadence backs off from five to sixty seconds. The client does not invent a catalog freshness deadline; selection admission still belongs to A2A.

### rust-loopback-fixture-and-comment | medium | Resolved with the current wire envelope

The real local TCP listener now serves the current `api_version: "v1"` and lane `schema_version: 1` DTOs, and the public broker handler must preserve the complete frozen run-status envelope unchanged. The obsolete eight-verb comment was corrected to describe the reviewed fixed whitelist. This proves Rust transport and forwarding behavior only, not an A2A-produced frozen assignment.

### version-admission | high | Resolved at each Dashboard/Rust selection boundary

Dashboard rejects an absent or unknown catalog or selection schema version. Rust has a non-default `schema_version` field and rejects versions other than one before forwarding. Real DTO-derived wire tests prove omission is not defaulted and version two is refused for the whole-team selection, every role override, and every fallback.

### frozen-status-broker-coverage | medium | Resolved at the Rust transport boundary

A real socket guard covers discovery, health, blocking transport, and the public run-status handler for a complete frozen assignment. It requires the schema, digest, provider/model values, native controls, ordered fallback, and provenance to arrive unchanged. A loopback listener proves broker transport behavior only; P03 still needs an A2A producer to emit and persist that contract.

### legacy-proof-shapes | high | Existing lost-ack, execution-agreement, and restart proofs still assert retired profile assignments

`test_engine_broker_lost_ack_live.py`, `test_dispatch_assignment_agreement.py`, and `test_model_profiles_evidence.py` supply real production-process, worker-execution, and durable-restart patterns, but their requests and assertions still use `profile_id` and legacy `assignments`. They cannot certify provider-catalog selection, exact frozen values, stale refusal, or current-catalog-independent replay until the P01.S08-S11 producer contract changes.

## Verification boundary

- A broad Rust broker rerun exceeded 64 seconds without a result and remains unverified. After the scope-fence repair, the same/missing/mismatched catalog-scope unit test and real TCP catalog forwarding test each passed; they confirm the expected scope is never forwarded to A2A.
- Dashboard provider-catalog, transport, model-picker, expert-selection, and composer render suites previously passed 59 tests against the local engine transport. After the scope-fence repair, the real local transport test passed and `a2aTeam.test.ts` passed 43 tests.
- A temporary P03-only TypeScript configuration excluding only the unrelated untracked `clarificationResolution.test.ts` passed, then was removed. The full typecheck remains blocked solely by that peer-owned file's missing export and unused `@ts-expect-error` directives.
- Exact changed-path Prettier, ESLint, localization, Rust formatting, and `git diff --check` gates passed.

## Recommendations

- Keep P03.S19 and P03.S20 unchecked. After P01.S08-S11 land, drive one served selectable catalog entry and native control through Dashboard, Rust, A2A admission, prompt setup, run status, and a fresh-process restart; compare the exact persisted frozen snapshot, not a catalog re-resolution.
- Convert the existing production lost-ack relay to submit one served selection and prove identical replay without duplicate dispatch or renewed catalog membership lookup.
- Reuse the existing worker-execution agreement harness to compare the frozen provider/model/control values consumed at prompt setup with the values returned by run status, and add controlled stale, unauthenticated, unavailable, and unadmitted catalog cases at the real A2A producer boundary.
- Independent Dashboard/Rust remediation re-review passed with no findings. `cross-scope-catalog-authority` is resolved; retain its focused proof boundary and do not treat it as live A2A end-to-end evidence.
