---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5c35900cbc97b3a6954e06013885a0a675378a530b875359a264aef026740193'
step_id: 'S07'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Serve bounded workspace provider catalogs through v1

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/provider_catalog.py`
- `src/vaultspec_a2a/providers/provider_catalog_service.py`
- workspace-aware catalog registration and exact-lane admission evidence
- direct authenticated ASGI, cache-bound, DTO, attach, OpenAPI, and provider regression tests

## Description

- Add authenticated `GET /v1/provider-catalog?workspace_root=...` with strict single-query input, absolute existing-directory validation, and canonical workspace identity.
- Serve all seven registered external provider and execution-mode lanes in deterministic registry order through the Dashboard/Rust wire DTO, omitting both internal provider-value fields.
- Partition S01 refresh caches by canonical workspace under a bounded sixteen-scope service, preserve per-lane single-flight refresh and stale fallback, refuse unsafe in-flight scope eviction, and expose the effective cache expiry.
- Carry configuration and transport evidence independently from authentication, catalog availability, exact-lane completed-turn admission, and derived selectability.
- Bind completed-turn proof to exact `ProviderCatalogKey` identities for catalog serving so an alternate execution mode never inherits another mode's proof.
- Enforce the Rust edge's public 512-character opaque identifier and 128-character control identifier bounds before a catalog enters the cache.

## Outcome

The gateway now serves the exact accepted cross-project provider catalog contract with `api_version: v1`, per-catalog `schema_version: 1`, structured health axes, revision and freshness timestamps, provider-owned model entries, native controls, safe reasons, and fail-closed selectability. Discovery is prompt-free and workspace-scoped. Unknown query parameters and caller-selected refresh are rejected; missing, relative, nonexistent, or file workspace roots are rejected before service creation or adapter spawn.

Factory registrations now receive the canonical active workspace for adapter cwd and environment resolution instead of closing over global `settings.project_root`. Configuration and transport evidence ride each discovery result separately. Only Codex app-server carries exact completed-turn proof because its citation is intrinsically mode-specific. Claude and Z.AI provider-level citations do not capture the runtime-configurable execution mode, so every current Claude and Z.AI catalog lane remains not admitted until an explicit exact-mode proof is recorded. Z.AI and Zhipu remain registered with empty unavailable catalogs because neither has a verified prompt-free enumeration surface.

The bounded workspace registry admits no more than sixteen canonical scopes. Active scopes cannot be evicted; saturated concurrent churn receives a static 503 instead of creating an unbounded or duplicate in-flight scope. Within a scope, one failing or overlong provider lane becomes a safe unavailable record or a stale retained snapshot without failing the seven-lane response.

## Verification

- Ruff: pass on every owned Python file.
- BasedPyright: 0 errors, 0 warnings, 0 notes on the owned implementation and direct tests.
- ty: pass on the owned implementation.
- Focused route, attach, provider factory, exact admission, S01 cache, and installed registration suite: 118 passed; four billable/live-provider cases were deselected by the repository's normal marker policy.
- Direct authenticated real ASGI catalog request: seven ordered external lanes returned in about 15 seconds without a completion; Z.AI and Zhipu were independently unavailable rather than collapsing the response.
- Generated OpenAPI artifact: 6 passed, exact live-document equality.
- Scoped diff check: clean.
- Independent closure review: PASS with zero open findings after the high-severity exact-mode evidence correction; reviewer reran 11 focused tests, Ruff, BasedPyright, and diff-check without editing or staging.

## Notes

The legacy served-profile admission API remains provider-shaped because current profiles do not yet carry execution mode. Catalog serving uses the new exact-key declaration now; P01.S10 owns migrating/removing the legacy provider/model policy after frozen selection lands. Claude and Z.AI exact-mode admission is deferred to the explicit all-low assembled proof in P03.S19; S07 did not run or infer a billable turn.

Reference audit also found Dashboard cross-scope placeholder reuse, absent expiry-driven refetch, and an obsolete Rust loopback fixture. These are queued to P03.S20/P03.S22 and do not weaken the A2A producer contract. P01.S08 remains the run-start consumer of served selection.
