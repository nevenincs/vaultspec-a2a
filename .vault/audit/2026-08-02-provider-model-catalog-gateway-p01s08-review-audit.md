---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2f8f381b1124d948aec6b219e2f28ec98ac8c2be3b70eb53b8c4f9ef4eb382e2'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-reference]]"
---

# `provider-model-catalog` audit: `P01.S08 explicit run selection review`

## Scope

Formal review of P01.S08 new-run admission after implementation and focused
verification. The pass covered the schema-v1 wire, current catalog validation,
required-role override authority, ordered fallbacks, authoritative control
defaults, prepare/commit/release identity, same-ID replay, safe refusal reasons,
and the legacy frozen-profile read boundary. Exact provider-native execution,
modern restart, and frozen-assignment disclosure remain assigned to P01.S09.

## Findings

### gateway-p01s08-review | medium | Release initially used the raw request against the canonical prepare binding

The first review found that prepare inserted authoritative catalog defaults
before hashing, while release hashed the original client request. A caller that
omitted an advertised default could therefore fail to release its reservation
and occupy capacity until expiry. Remediation stores a separate exact client
release digest beside the canonical commit digest, so release remains bound to
the prepared request without consulting a catalog that may have drifted. The
broker regression and selection-default regression pass. Status: resolved.

### gateway-p01s08-review | medium | Eligibility-failure cleanup initially reused the canonical commit digest

Remediation review found the same identity split on the internal cleanup path:
when live worker or provider eligibility failed before commit, the route tried to
release with the canonical commit digest although the broker now authorizes
release with the exact client-prepared digest. The route now centralizes all
release authority through `_release_binding_digest`; prepare storage, explicit
release, and eligibility-failure cleanup consume that one raw prepared identity.
Status: resolved.

### gateway-p01s08-review | low | Canonically equivalent prepare and commit representations could defer refusal cleanup

Final review found a narrower variant: prepare could omit an advertised default,
commit could explicitly supply that same default, and readiness could then drop.
The two requests share canonical commit identity but not raw release identity.
The broker now exposes a distinct internal `release_failed_commit` operation
authorized by the stored canonical binding, while public client release remains
strictly authorized by the raw prepared request. The route-level cleanup helper
and broker regressions cover this representation change. Status: resolved.

### gateway-p01s08-review | high | Modern exact execution and restart remain deferred to P01.S09

P01.S08 persists the normalized catalog selection and supplies the current
compiler seam with exact model values, but the compiler contract still drops
provider-native control values, fallback entry details, and execution modes.
Restart and status disclosure still read the legacy `model_profile` record.
This is the accepted P01.S09 boundary, not evidence that modern restart or
frozen-assignment disclosure works in this pass. Status: queued under P01.S09.

### gateway-p01s08-review | medium | Rust Unicode prompt budget drift was delegated to the Dashboard owner

Cross-project audit found that Rust bounded the forwarded prompt at 65,536
bytes while A2A admits 65,536 characters and publishes a 262,144-byte UTF-8
budget. The Dashboard owner accepted remediation and added the wider byte bound
and multibyte coverage in its P03 integration work. Status: delegated.

## Recommendations

- Keep canonical commit identity and exact client release identity separate in
  the admission broker; do not revalidate a release against live catalog state.
- Complete P01.S09 before claiming exact provider-native execution, restart, or
  frozen-assignment disclosure for modern catalog-backed runs.
- Retain the explicit all-low real-provider matrix in P03.S19 as the end-to-end
  proof boundary; focused S08 tests do not substitute for it.
