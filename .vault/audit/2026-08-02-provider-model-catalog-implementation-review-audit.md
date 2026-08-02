---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8214203bf490f563a414443e1ec621351168069242bfc545cb3c7207b3fcffd3'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# `provider-model-catalog` audit: `implementation review`

## Scope

Review S01's normalized catalog contracts, canonical selection identity,
structured health, TTL refresh behavior, and direct production-import tests
against the accepted provider-owned catalog decision.

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

## Recommendations

Keep the catalog normalization, invalidation fence, resource ceilings, provider
expiry bound, and single-flight refresh invariants in focused tests as provider
adapters are added. No open critical, high, medium, or low S01 finding remains
after remediation.
