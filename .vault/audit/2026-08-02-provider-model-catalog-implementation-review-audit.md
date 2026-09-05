---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-09-05'
body_schema: 'body-v1'
body_hash: 'sha256:f8305803712736028c338d4656cfcd4b6ae61c4889b3a913019c14343ce25c1f'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `implementation review`

## Scope

Review S01's normalized catalog contracts, canonical selection identity,
structured health, TTL refresh behavior, S02's prompt-free ACP discovery,
S03's Codex app-server catalog discovery, and S13's Dashboard catalog
adapter/composer migration against the accepted provider-owned catalog
decision.

## Findings

### provider-expiry | high | Local TTL initially outlived provider catalog expiry

Resolved in S01. Cache publication now clamps its monotonic deadline and served
expiry to the provider catalog's earlier expiry, and immediately treats a
provider-stale result as stale. Direct coverage proves a long local TTL cannot
make an expired provider catalog fresh.

### forced-single-flight | medium | Concurrent forced callers initially refreshed serially

Resolved in S01. Forced callers now retain the entry generation observed before
waiting and reuse a peer's completed refresh, preserving one discovery call per
concurrent refresh wave. Direct coverage exercises twelve concurrent forced
callers.

### shallow-immutability | high | Caller-owned lists could mutate frozen contracts

Resolved in S01. Every sequence-bearing contract now detaches caller-owned
inputs into tuples during construction. Direct coverage mutates the original
model, capability, native-control option, control, and selection lists and
proves the normalized records remain unchanged.

### invalidation-fence | high | In-flight discovery could overwrite invalidation

Resolved in S01. Per-lane generations now fence refresh publication and raise a
typed invalidation error when the lane changes during discovery. Direct
concurrency coverage invalidates a blocked refresh and proves no result is
published.

### resource-bounds | medium | Catalog payloads and cache indexes were unbounded

Resolved in S01. Catalog text and sequence fields now enforce explicit ceilings.
The cache has a configured lane ceiling, evicts expired inactive lane state, and
refuses growth when no safe eviction candidate exists. Direct coverage proves
display metadata rejection and expired-lane eviction.

### s12-provider-catalog-loopback | medium | Catalog route was only structurally tested

Resolved in S12. The Rust route now has a real TCP loopback proof through the
public handler: it performs discovery and health probing, forwards the bounded
catalog read, and preserves opaque provider, entry, native-control, and
structured-health values inside the Dashboard envelope. The focused Rust suite
passes 30 tests after this proof was added.

### s13-legacy-run-projection | medium | Direct migration initially hid existing legacy assignments

Resolved in S13. `run-status` now reads legacy persisted `assignments` only
when no current `frozen_assignment` is present, retaining a separate read-only
projection for existing-run roster/restart inspection. The legacy row cannot
produce a new provider catalog selection.

### s13-unneeded-catalog-query | medium | Catalog discovery initially ran outside team mode

Resolved in S13. The Dashboard catalog query now requires both a resolved
workspace and an active selected team preset; single-agent authoring does not
trigger provider discovery or refresh.

### s13-wire-regression-proof | medium | Direct provider-catalog wire coverage was initially incomplete

Resolved in S13. Raw-envelope adapter tests now prove unknown/omitted and
stale health fails closed, revision/control drift invalidates a held selection,
and legacy status stays readable. The Composer feature render path asserts the
exact opaque `selection` body that reaches run start.

### acp-error-redaction | high | Provider diagnostic text crossed the safe discovery boundary

Resolved in S02. ACP JSON-RPC errors are classified into static local messages
without retaining provider-controlled diagnostic text. Direct coverage proves a
credential-like value in an error message cannot escape.

### acp-output-budget | medium | Discovery output was not bounded across the operation

Resolved in S02. Stdout and stderr share one one-MiB operation budget. Oversized
stdout fails closed and oversized stderr terminates the contained provider tree
before surfacing a protocol error. Per-frame and response-count bounds remain.

### acp-lifecycle-proof | medium | Normalization tests did not exercise discovery cleanup

Resolved in S02. Two service tests invoke `discover_acp_catalog` through the
production spawn path against the installed Claude ACP adapter. They prove the
initialize/session-new-only path returns after cleanup and cancellation also
completes containment cleanup; no provider prompt is sent.

### acp-bound-alignment | medium | Adapter limits exceeded the S01 contract limits

Resolved in S02. ACP normalization rejects more than 256 models, 32 native
controls, or 128 control options with `AcpCatalogProtocolError` before immutable
S01 construction. Direct coverage exercises the control and option ceilings.

### codex-failure-lifecycle-proof | medium | Failure cleanup initially lacked production-path evidence

Resolved in S03. Direct real-process tests now drive provider RPC failure with
credential-shaped diagnostic text and aggregate stderr exhaustion through
`discover_codex_catalog`, then prove the contained process tree is gone. The
output-budget failure is surfaced after independent cleanup rather than being
masked by the stdout EOF caused by terminating the over-budget process.

### codex-pagination-method-proof | low | Cursor forwarding and prompt-free sequencing were initially inspection-only

Resolved in S03. A bounded malformed-process fixture records the exact request
stream through a repeated-cursor failure. The proof observes `initialize`,
`initialized`, `account/read`, and cursor-bearing `model/list` only before
failure, with no thread, turn, prompt, or completion-bearing method; successful
installed runtime coverage continues through
`modelProvider/capabilities/read`.

### codex-control-scope | high | Model entries initially did not identify their applicable native controls

Resolved in S03. `ModelCatalogEntry` now carries immutable bounded
`native_control_ids`, and `ProviderCatalog` rejects any reference that does not
name an advertised control. ACP binds its session-wide controls to every model;
Codex binds only each model's own reasoning-effort and service-tier controls.
Catalog revisions cover the association, and direct tests prove both shared and
model-scoped behavior.

### kimi-secret-bearing-provider-list | high | Configured provider discovery exposes raw credential fields

Resolved in S04. The adapter consumes `kimi provider list --json` only inside
the discovery boundary, validates model references by provider-table membership,
and retains no provider record or diagnostic output. Static protocol errors and
installed-CLI coverage prove a configured API-key value does not cross the
normalized result boundary.

### kimi-pipe-drain-order | high | Waiting for process exit before draining output could deadlock

Resolved in S04 before final review. Stdout, stderr, and process exit are awaited
concurrently under one timeout and one aggregate one-MiB budget. A real spawned
process emits a valid response above a typical pipe capacity; discovery returns
and the process tree is reaped.

### kimi-current-env-contract-drift | medium | Existing factory variables do not configure the installed CLI catalog lane

Open and assigned to S06 registration/factory integration. The installed CLI
used for S04 recognizes the temporary configured-lane names
`KIMI_MODEL_API_KEY` and `KIMI_MODEL_BASE_URL`; the existing factory and
readiness path inject and gate on the older `KIMI_API_KEY` and `KIMI_BASE_URL`
contract. S04 remains truthful by reporting only what `provider list --json`
serves. S06 must reconcile launch, readiness, and catalog configuration against
one verified installed-CLI contract before the Kimi lane is registered.
### kimi-real-subprocess-boundary-proof | medium | Initial tests did not exercise both pipes, aggregate breach, or timeout cleanup

Resolved in S04 after independent review. Real spawned-process coverage now
writes above typical pipe capacity to both stdout and stderr, breaches the
shared one-MiB budget across the two streams, and hangs past the discovery
timeout. Each path proves its static failure where applicable and full process-
tree reaping; configured and unconfigured installed-CLI enumeration remain
separate prompt-free proofs.
### p01-s11-catalog-route-host-state | medium | Resolved: route evidence follows observed catalog state

Type: test contract drift. Status: resolved by `P01.S11`; formal review pending. The authenticated real-ASGI route test no longer assumes OpenAI and Z.AI enumeration are unavailable at fixed array positions. It keys the parsed v1 response by provider identity, accepts only an observed available or unavailable catalog result for those environment-dependent lanes, and validates the corresponding payload: catalog and health status agree; an available catalog has entries, revision, expiry, and authenticated evidence; an unavailable catalog has no entries and carries a bounded reason. Both exact lanes remain `not_admitted` and non-selectable regardless of catalog availability, so discovery cannot become completed-turn evidence. The focused 49-test behavior set passes across cold catalog discovery, stale and invalid selection refusal, independent health, served-entry validation and freeze, same-ID replay/conflict/race, durable modern restart, legacy frozen-profile disclosure, and exact frozen ACP backend reuse. No new finding surfaced.

### p01-s11-legacy-restart-proof-absent | high | The 49-test battery does not exercise a real legacy restart

Type: behavioral evidence completeness. Status: open; review-blocking for `P01.S11` at `7d8c04df06299dc58ae8fd1a5f4092291f3042ab` and therefore for remediation S05. P01.S11 explicitly requires legacy restart with real behavior. The selected live gateway test seeds a pre-catalog `model_profile` row and proves only run-status disclosure. `test_restart_prefers_modern_selection_over_legacy_profile` is a pure helper check that a modern selection wins when both metadata forms exist. No selected or repository test seeds a real legacy frozen assignment in durable stores, boots a fresh second gateway and worker, drives startup reconciliation/redispatch, and observes that provider construction uses the exact persisted legacy provider/model/control values without current catalog resolution. The Step Record and audit therefore overstate the 49-test battery as legacy-restart proof. Ownership: reopen P01.S11 and add the real persisted legacy restart/redispatch discriminator before review closure.

### p01-s11-premature-plan-closure | high | S11 is closed while its preceding policy-retirement implementation remains open

Type: plan sequencing and lifecycle accuracy. Status: open; review-blocking. Core reports P01.S10 open and next while P01.S11 is checked. S10 removes provider/model policy from new product presets and preserves legacy restart; S11 is the following proof step and cannot close its full served-validation and legacy-restart promise before that implementation boundary lands. The host-state route correction is independently valid, but closing the whole S11 row conflates one ER19 repair with the step's broader post-S10 verification contract. Ownership: reopen S11, complete or explicitly restructure the P01.S10/S11 dependency through Core, then close S11 only after its full real-behavior suite passes.

### p01-s11-formal-review | high | FAIL - host-independent route fix passes but S11 evidence is incomplete

Type: implementation review disposition. Status: open. The reviewed commit's exact parent is `f0e7fe9d4c6bd4422b0db45ca02ea4b388a02502`; its seven committed paths contain only the catalog test/lifecycle documentation and exclude the separately landed resource-lifetime work. The provider-keyed route assertion is deterministic across credentialed and uncredentialed OpenAI/Z.AI hosts: it accepts only typed available/unavailable catalog states, keeps catalog status synchronized with the catalog health axis, requires complete available or unavailable payload invariants, and independently requires exact-mode `not_admitted` plus `selectable=false`. The focused 49 tests pass and cover discovery/cache behavior, stale and invalid served-selection refusal, independent health, freeze/validation, replay/conflict/race, modern durable restart, legacy disclosure, and exact frozen ACP backend reuse. Dedicated coverage preserves deny-by-default, provider-plus-execution-mode identity and non-transferable admission. Ruff, ty and format checks are recorded, no deprecated API or option is introduced, and feature Core is clean. The two preceding HIGH findings mean the passing subset is not enough to close P01.S11 or unblock remediation S05.

## Recommendations

Keep catalog normalization, redaction, containment, aggregate output ceilings,
invalidation fencing, provider expiry, single-flight refresh, Dashboard
selection gating, and legacy-run read boundaries in focused tests. No open
critical, high, medium, or low S01/S02/S12/S13 finding remains after remediation.

- For `p01-s11-legacy-restart-proof-absent`, seed a real pre-migration frozen profile in durable stores, restart fresh gateway and worker instances, and prove redispatch constructs the exact persisted legacy assignment without catalog re-resolution.
- For `p01-s11-premature-plan-closure`, reopen S11 and preserve the valid ER19 route correction while P01.S10 and the missing real-behavior proof are completed.
