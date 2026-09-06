---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:ea4af383ee545ac72126290464d14a6c1ddeeda683d0d2b35d096115d38daca1'
step_id: 'S11'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Prove current provider catalog behavior, exact frozen restart and typed retirement refusal

## Scope

- `src/vaultspec_a2a/providers/`
- `src/vaultspec_a2a/api/`
- `src/vaultspec_a2a/control/`
- `src/vaultspec_a2a/worker/`
- `src/vaultspec_a2a/streaming/`
- `src/vaultspec_a2a/thread/`
- `src/vaultspec_a2a/service_tests/`
- `openapi.json`

## Changes

### Implementation and review chain

- `7d8c04df06299dc58ae8fd1a5f4092291f3042ab` was the original S11 implementation. It corrected ER19 by asserting each host's observed OpenAI and Z.AI catalog availability while retaining independent health, exact-mode admission and selectability checks. Its original focused behavior set passed 49 tests.
- `16066b83983a90a6a7dc067f98510e3fc5c040fc` was the original formal FAIL review. It found two HIGH lifecycle/evidence defects: the then-required legacy restart was not exercised through production, and S11 had closed before prerequisite S10.
- `194f4fa6e469a9d849719f3ff8a2e8adaa604712` reopened P01.S11 through Core and preserved the valid 49-test ER19/current behavior subset while the architecture and prerequisite were corrected.
- `41519f11bd093311cebedc0f34bd575a845eac30` amended the governing architecture under the user's approved strict no-legacy direction: retired provider/model/profile state must be refused and must never restart, redispatch, translate, migrate or substitute. Expanded curation passed at `45a0a0093cfc38d7595583b8289d2c744429bd7a`.
- S10 then implemented the superseding current-only boundary and closed at `0c47e4c5758995d7bc55ef924b6547c11c07fa08`; lifecycle review `bc0d59984946789e8eaf6fcbd4ec40708fa79d67` passed before S11 resumed.
- `ba9f70bd4d280ca95a3f31131443949317a0ae9d` added the current-only behavior proofs: ACP discovery consumes `configOptions` only; retired provider/model/profile input and durable state fail closed; provider health remains separate from admission; served selection validates and freezes exact values; same-ID replay is stable; current schema-v1 restart is exercised.
- `a93ab85292667e5c170df20914059d8790434f8c` found that the restart test bypassed the production worker and that retired-input assertions did not prove the bounded typed refusal.
- `550f26fc944182eca92d5afe007f925dd3e9d388` drove restart through a fresh production gateway and production worker over real loopback transport, bound the full canonical assignment and digest to durable/checkpoint/worker evidence, and bounded request-validation responses without reflecting rejected input.
- `d8c7668fc9c860ea3f7140cc45b4d3be66db9d59` found incomplete full-assignment consumption evidence.
- `aae2ac389ddb63a891b90c77b9236b6bb6e7db29` put the canonical assignment digest in `GraphCacheKey`, partitioned graphs by exact frozen authority, and scoped streamed node metadata to thread identity.
- `454a3db6d475d77a644129076aed4d43c3e8aa8e` found that later re-entry paths and durable thread binding could still escape the exact authority boundary.
- `3ee6529d2eb533ba7088e871b90169560bbb4880` routed message, permission, clarification, verdict, direct-recovery and redispatch entry through one current-schema resolver; added atomic thread-to-digest binding; validated checkpoint evidence and descriptors at read; and made team-status association explicitly thread scoped.
- `6c3e6fcbb3cf62b14de06e5de206bcbb2e4616a6` found gaps in retired-root ordering, precompile capacity, terminal identity cleanup and cross-thread graph compilation single-flight.
- `3f5ef6e7d401506fb9a5ee3fb471162af6e8fe91` checks every retired root sentinel before current freeze parsing; reserves bounded capacity before scheduling, checkpoint reads or graph compilation; applies one total checkpoint deadline; releases terminal thread identity; retains interrupted identity; and single-flights exact cache keys with cleanup.
- `fdd23ce18b8086b1c33205ba5f2daed22e73e105` found the thread-ID ABA capacity-release race.
- `bded79c79ba3437fc9f34bcbf82ab1d8d395797c` replaced bare thread reservations with opaque, monotonic, identity-checked dispatch-generation tokens and proved stale cleanup cannot release a newer owner.
- `c13e5a1feac160c0fc3c9468e0c2bfab54dceac0` found the final concurrent duplicate-response ordering defect.
- `6db8cd3b384872b8cdb8b5b731fa4495fd4d7bbd` rechecks the exact admitted dispatch ID after awaited capacity refusal, so concurrent identical ingest/resume returns the established 200 response once while distinct IDs and true capacity exhaustion remain typed 429.
- `3578151f3b5e5f18cba2eb17967755be3cd120cc` is the formal PASS review. It found no CRITICAL, HIGH or review-blocking MEDIUM issue and authorized separate lifecycle closure.

## Result

- ACP catalog discovery accepts current `configOptions` model declarations only. The retired `models.availableModels` payload has no fallback or compatibility path.
- The supported provider and provider/execution-mode inventories contain only the seven current external lanes plus the explicit in-process deterministic and mock lanes. The retired Gemini provider, mode, configuration, construction, catalog, settings and auth surfaces are absent and nonconstructible.
- New selections validate against the served catalog, freeze the complete current schema-v1 assignment, preserve exact nested role, entry, provider, mode, model, controls, fallbacks, provenance and display fields, and use its canonical semantic digest for durable binding, cache identity and restart.
- Fresh production gateway/worker recovery consumes the persisted current assignment without catalog re-resolution, substitution or translation. Every execution re-entry resolves the same exact authority before worker contact.
- Retired request fields and stored metadata return bounded typed `retired` or incompatible-state outcomes before provider construction, checkpoint interpretation or dispatch; rejected values are not reflected.
- Provider configuration, transport, authentication, catalog freshness, exact-mode admission and selectability remain separate. The ER19 assertions use observed OpenAI and Z.AI catalog availability while preserving exact-mode deny-by-default admission.
- Graphs, checkpoint evidence, streamed metadata and team-status evidence are isolated by thread and canonical assignment digest. Same exact keys single-flight and reuse; different digests remain partitioned.
- Capacity admission is bounded before all precompile work. Generation ownership prevents ABA release, terminal runs release thread identity, interrupted/reconciling runs retain it, and concurrent identical endpoint replay schedules once and returns the same response.

## Findings and disposition

- Resolved by approved architectural supersession: `p01-s11-legacy-restart-proof-absent`. The original contract required supported legacy redispatch; the user's strict no-legacy decision and amended architecture instead require typed zero-contact refusal. S10 removed the compatibility path, and the final S11 production tests prove refusal with no translation, migration, substitution or restart. The historical HIGH remains valid for the superseded contract and is not recast as if a legacy restart was implemented.
- Resolved by lifecycle sequencing: `p01-s11-premature-plan-closure`. Core reopened S11 at `194f4fa6e469a9d849719f3ff8a2e8adaa604712`, S10 completed and passed lifecycle review first, and S11 closed only after the full current-only implementation chain and final PASS review.
- Resolved HIGH: production restart bypass; incomplete full frozen-assignment proof; graph cache omitted assignment digest; node metadata was global by node name; execution re-entry omitted frozen authority; durable thread binding depended on cache residency; pre-resume state update could invalidate interrupts; clarification fast replay could lose the accepted result; retired root sentinels were checked too late; checkpoint reads bypassed capacity; terminal identity was unbounded; and capacity cleanup had an ABA ownership race.
- Resolved MEDIUM: refusal typing; validation-error input reflection; checkpoint authority/digest validation; descriptor closure at read; current checkpoint reconciliation; team-status thread association; exact-key compile single-flight; and concurrent duplicate false-429 ordering.
- Resolved LOW: obsolete cross-thread agent metadata access. Full-assignment isolation positive controls were independently verified.
- Open nonblocking environment/tooling findings remain queued under their existing owners: MCP server data-plane pin drift and the cold catalog shutdown timeout; eight server-profile environment failures, desktop fixture drift, the Starlette `BlockingPortal` alias deprecation and the secondary closed-pipe warning remain classified baseline/environment evidence. None creates a deprecated compatibility path or invalidates the formal S11 behavior proof.
- Remediation `W01.P02.S05` remains open and receives this closed catalog prerequisite as input; no remediation row is closed here.

## Verification

- Original `7d8c04df` focused catalog behavior set -> `49 passed`; this remains evidence for the ER19 observed-availability correction and the then-current subset, while its legacy assertions are historical rather than supported authority.
- `pytest` focused exact-authority, redispatch, cache-identity, endpoint-admission, executor and state-projection set -> `145 passed`.
- `pytest` expanded provider/control/worker behavior set -> `585 passed, 9 deselected`, with `8` classified server-profile environment failures outside the S11 implementation boundary.
- `pytest src/vaultspec_a2a/worker/tests` on the final correction -> `133 passed, 2 deselected`.
- `pytest` final dispatch-admission plus full Executor review selection -> `64 passed`.
- `pytest src/vaultspec_a2a/api/tests/test_openapi_artifact.py src/vaultspec_a2a/providers/tests/test_no_legacy_model_authority.py` -> `12 passed`.
- Ruff check and format, Ty on changed runtime paths, `git diff --check`, and provider-model-catalog Core feature checks -> pass.
- Known warning: Starlette's `anyio.abc.BlockingPortal` alias deprecation, already queued.

## Review

Formal review PASS: `3578151f3b5e5f18cba2eb17967755be3cd120cc`. P01.S11 is evidence-complete under the accepted strict current-only architecture. No compatibility, migration, translation, substitution or deprecated provider/model/profile authority is supported.
