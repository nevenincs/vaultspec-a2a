---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:91ca1883085dda08d0f79b34ca70ba1f274b229437716d2af9673faba2ae6a44'
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

## Recommendations

Keep catalog normalization, redaction, containment, aggregate output ceilings,
invalidation fencing, provider expiry, single-flight refresh, Dashboard
selection gating, and legacy-run read boundaries in focused tests. No open
critical, high, medium, or low S01/S02/S12/S13 finding remains after remediation.
