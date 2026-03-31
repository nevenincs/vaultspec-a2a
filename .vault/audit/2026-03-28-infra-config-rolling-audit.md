---
tags:
  - '#audit'
  - '#infra-config'
date: '2026-03-29'
related:
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-29-infra-config-phase2-adr]]'
  - '[[2026-03-28-infra-config-plan]]'
  - '[[2026-03-28-layer2d-rolling-audit]]'
---

# `infra-config` rolling audit — post layer 3

Consolidated deferred-item ledger after Layer 3 (PR #16). All items
from the Layer 2d rolling audit and Layer 3 deferrals are now resolved.

## Resolved in PR #15 (Layer 2d)

- Unified RPC handler signatures to `(rpc_id, params, ctx, config)`
- Typed `permission_callback` as `PermissionCallback` protocol
- Removed dead `send_notification` from `_acp_session.py`
- Upgraded `RpcHandlerMap` from `dict[str, Callable[..., Any]]` to fully
  typed `dict[str, Callable[[int | str, dict, ctx, config], Awaitable[...]]]`

## Resolved in PR #16 (Layer 3 — Phase 1)

- Settings god-object footprint reduced: 37 → 30 prod files (19%)
- Stale tapes volume mount fixed: `core/` → `team/`
- Orphan `docker-compose.postgres.yml` deleted
- `.dockerignore` gaps closed (6 exclusions added)
- `.env.example` aligned with InfraConfig (ACP timeout + Vertex/Gemini)
- Justfile `preps` comments corrected
- `permissions.py` inline import hoisted to module level

## Resolved in PR #16 (Layer 3 — Phase 2, deferred items)

- D-01: Removed `self._last_auth_url` PrivateAttr dual-write from
  `AcpChatModel`. `ctx.last_auth_url` is the sole source during sessions;
  `authenticate()` passes `auth_url=None` (minor error-message degradation,
  no correctness impact)
- D-02: Added keyword-only separator (`*,`) after `db` in `cancel_thread`,
  `send_followup_message`, and `respond_to_permission`
- D-03: Extracted `ThreadCreationRequest` frozen dataclass from 15-arg
  `create_and_dispatch_thread`. 9 request-data fields grouped; 5 infra
  dependency params remain as direct keyword args
- D-04: Split `_acp_session.py` (697L) → `_acp_types.py` (~75L) +
  `_acp_auth.py` (~230L) + `_acp_session.py` (~200L). No re-export shims.
- D-05: Added protocol-shape assertions to 7 shadow types:
  `StreamableGraph` made `@runtime_checkable`; `issubclass` guards on
  `_SilentGraph`, `_InterruptingGraph`, `_RecursingGraph`; `hasattr` guards
  on `_InterruptValue`, `_GraphTask`, `_GraphStateSnapshot`, `_WriteBuffer`
- D-06: Closed `_StubProviderFactory` + `FakeChatModel`. Confirmed
  structurally necessary for Layer 1 isolation (compile tests only,
  no execution; VidaiMock covers execution). Added
  `isinstance(factory, ProviderFactoryProtocol)` drift guard.
- D-08: Deduplicated Justfile kill recipes for gateway/worker/ui
  (delegate to stop — both already used `Stop-Process -Force`)
- D-09: Replaced hardcoded `vaultspec:vaultspec` in
  `docker-compose.prod.postgres.yml` with `${POSTGRES_PASSWORD:?}`.
  Added `POSTGRES_PASSWORD=` to `.env.example`
- D-10: Moved `max_concurrent_threads` from `InfraConfig` to `DomainConfig`
  (worker executor section). Removed `settings` import from `executor.py`
  entirely — module now imports only `domain_config`.

## Active deferrals

**None.** All items from the Layer 2d rolling audit and Layer 3 audit
cycle are resolved.

## Closed — not carried forward

| Item | Resolution |
|------|-----------|
| Unify RPC handler signatures | RESOLVED PR #15 |
| Type `permission_callback` | RESOLVED PR #15 |
| Remove dead `send_notification` | RESOLVED PR #15 |
| `RpcHandlerMap` type annotation | RESOLVED PR #15 |
| Settings god-object concern | RESOLVED PR #16 |
| `InfraConfig` sub-config decomposition | CLOSED as non-issue |
| D-01 `_last_auth_url` dual-write | RESOLVED PR #16 |
| D-02 keyword-only service functions | RESOLVED PR #16 |
| D-03 `ThreadCreationRequest` dataclass | RESOLVED PR #16 |
| D-04 `_acp_session.py` split | RESOLVED PR #16 |
| D-05 protocol-shape assertions | RESOLVED PR #16 |
| D-06 `_StubProviderFactory` closure | RESOLVED PR #16 |
| D-08 Justfile kill dedup | RESOLVED PR #16 |
| D-09 Postgres credentials | RESOLVED PR #16 |
| D-10 `max_concurrent_threads` relocation | RESOLVED PR #16 |
