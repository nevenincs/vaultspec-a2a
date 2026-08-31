---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0ee67ccaf3a654cd80f2937da911bdc4d279cde3a235eb0edbaee3de6b3de0b6'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `gateway P01.S07 review`

## Scope

Formal review of P01.S07's authenticated provider-catalog route, exact wire DTO, canonical workspace and refresh-cache composition, independent health evidence, exact execution-lane admission, redaction and bounds, direct real-behavior tests, and cross-project contract drift.

## Findings

### missing-provider-catalog-producer | critical | Resolved: A2A now serves the committed consumer contract

Dashboard and Rust had shipped a provider-catalog consumer before A2A exposed the route. The authenticated `/v1/provider-catalog` producer now returns the exact reconciled envelope and is present in the reviewed attach whitelist and generated OpenAPI artifact.

### provider-wide-admission-inheritance | high | Resolved for catalog serving; legacy migration queued to P01.S10

The durable completed-turn registry was keyed only by `Provider`, while catalogs are keyed by provider plus execution mode. A future transport could therefore inherit proof it never earned. Catalog health now consults an explicit immutable `ProviderCatalogKey` proof declaration. Only Codex app-server remains admitted because its cited acceptance proof is intrinsically app-server-specific. Claude and Z.AI citations do not capture their runtime-configurable execution mode, so those exact catalog lanes remain not admitted. Direct tests prove Codex app-server admission and deny both Claude node and a same-provider future transport. Provider-shaped legacy profile consumers remain unchanged until P01.S10 removes their static policy authority.

### workspace-ignored-by-registration | high | Resolved: canonical active workspace reaches every cwd-sensitive adapter

S06 callbacks closed over `settings.project_root`, so a route query could claim one scope while discovering another. Registration composition now accepts the validated canonical root and supplies it to environment resolution and adapter cwd. Alias-equivalence tests prove one canonical cache identity.

### workspace-cache-cross-contamination | high | Resolved: bounded cache per canonical workspace

S01 cache identity intentionally contains only provider and execution mode. The service now owns a bounded mapping from canonical workspace identity to one S01 cache. Sixteen scopes are retained at most; only inactive scopes can be evicted. Concurrent saturation fails with a static 503, and real concurrency coverage proves capacity is not exceeded.

### collapsed-readiness-health | high | Resolved: registrations carry independent facts

`ProviderReadiness` combines credential and launch-command checks and cannot truthfully populate configuration and transport separately. S07 does not consume it. Discovery results now carry typed configured and transport evidence alongside authentication and catalog state: missing command affects transport only, explicit credential or temporary definitions affect configuration only, and absent evidence remains unknown.

### rust-public-bound-mismatch | high | Resolved: unsafe lane is rejected before caching

Internal catalog strings allow up to 1,024 characters while Rust accepts public opaque identifiers up to 512 and control identifiers up to 128. The public DTO enforces Rust's bounds, printable nonblank identifiers, collection maxima, and strict enums. Service validation occurs per lane before cache insertion so an overlong lane is isolated as unavailable rather than failing the response.

### provider-value-leakage | high | Resolved: projection contains references only

Internal model and option `provider_value` fields are deliberately absent from the response. Direct projection tests use sentinel execution values and prove neither field name nor value reaches serialized JSON. Exact execution values remain A2A-local until P01.S08/P01.S09 validation and freezing.

### raw-provider-error-leakage | high | Resolved: static categories only

Per-lane refresh exceptions are caught independently. Logs carry provider ID, execution mode, and exception type only; responses use static bounded categories and never raw exception text, HTTP bodies, stderr, URLs, credentials, environment values, or filesystem paths. Existing stale entries remain visible with stale state and cannot be selected.

### dashboard-cross-scope-placeholder | medium | Open: queued to P03.S20/P03.S22

Dashboard query keys include workspace scope, but `placeholderData: keepPreviousData` can temporarily display the prior scope's catalog during a switch. Consumer work must remove cross-key placeholder reuse or carry and verify scope identity before rendering or selection.

### dashboard-expiry-refetch-gap | medium | Open: queued to P03.S20/P03.S22

Dashboard correctly refuses expired catalogs but has no expiry-driven refetch interval. A mounted view can remain stale until focus, remount, or manual refresh. Cross-project refresh proof must add an A2A-evidence-driven refetch schedule without inventing browser freshness.

### rust-loopback-fixture-drift | medium | Open: queued to P03.S22

The Rust pass-through route is compatible because it forwards the envelope verbatim, but its loopback fixture still uses obsolete `entries`, `controls`, boolean health fields, and `authenticated`. Update it to `catalog.models`,
ative_controls`, enum health axes, `api_version`, and `schema_version` during the owning Dashboard/Rust review.

### s06-exec-commit-control-character | low | Open: lifecycle repair queued to P03.S23

The S06 execution record contains a control character before the Dashboard S17 commit fragment, introduced by PowerShell backtick interpretation. It does not alter product behavior but should be repaired during final lifecycle reconciliation.

## Verification

- Ruff, BasedPyright, and ty pass on the S07 implementation boundary.
- 118 focused route, attach, provider, exact-admission, cache, and installed-registration tests pass; four live-provider cases are normally deselected.
- One real authenticated ASGI request returns all seven registered external lanes in deterministic order without issuing a completion.
- OpenAPI generation and exact artifact checks pass 6/6.
- Direct tests cover invalid workspace roots, unsupported refresh/unknown input, canonical aliases, concurrent scope saturation, exact-mode denial, public-ID bounds, schema versions, and provider-value omission.
- Independent closure review returned PASS with zero open findings after the high-severity exact-mode correction; its 11 focused tests, Ruff, BasedPyright, and scoped diff-check passed without edits or staging.

## Recommendations

- P01.S08/P01.S09 must validate and freeze server-local entry and option references without exposing provider values.
- P01.S10 should migrate remaining provider-shaped admission consumers to execution-mode-aware frozen selection before retiring static provider/model policy.
- P03.S19 should earn any Claude or Z.AI exact-mode admission only through the explicit all-low assembled proof; no provider-level citation or billable S07 rerun may substitute.
- P03.S20/P03.S22 should repair Dashboard scope/refetch behavior and Rust fixture drift, then run the assembled cross-project stale and selection proofs.
- P03.S23 should repair the S06 lifecycle control character and reconcile all review records.
