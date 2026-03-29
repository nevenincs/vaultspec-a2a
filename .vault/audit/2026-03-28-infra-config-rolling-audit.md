---
tags:
  - '#audit'
  - '#infra-config'
date: '2026-03-28'
related:
  - '[[2026-03-28-infra-config-adr]]'
  - '[[2026-03-28-infra-config-plan]]'
  - '[[2026-03-28-infra-config-summary]]'
  - '[[2026-03-28-layer2d-rolling-audit]]'
---

# `infra-config` rolling audit — post layer 3

Consolidated deferred-item ledger after Layer 3 (PR #16). Reconciles
all items from the Layer 2d rolling audit against Layer 3 execution.

## Resolved in PR #15 (Layer 2d)

- Unified RPC handler signatures to `(rpc_id, params, ctx, config)`
- Typed `permission_callback` as `PermissionCallback` protocol
- Removed dead `send_notification` from `_acp_session.py`

## Resolved in PR #16 (Layer 3)

- Settings god-object footprint reduced: 37 → 30 prod files (19%)
- Stale tapes volume mount fixed: `core/` → `team/`
- Orphan `docker-compose.postgres.yml` deleted
- `.dockerignore` gaps closed (6 exclusions added)
- `.env.example` aligned with InfraConfig (ACP timeout + Vertex/Gemini)
- Justfile `preps` comments corrected
- `permissions.py` inline import hoisted to module level (review finding)

## Active deferrals — carry forward to service layer

| ID | Item | Severity | Trigger | Origin |
|----|------|----------|---------|--------|
| D-01 | `_last_auth_url` dual-write: remove `ctx.last_auth_url`, keep `self._last_auth_url`, pass as parameter | LOW | Opportunistic | Layer 2d P2 |
| D-02 | Make all service functions keyword-only after `db` parameter | LOW | Service layer | Layer 2d P2 |
| D-03 | Define `DispatchContext` dataclass to replace 15-arg `create_and_dispatch_thread` | MEDIUM | Service layer | Layer 2d P3 |
| D-04 | Split `_acp_session.py` → `_acp_types.py` / `_acp_auth.py` / `_acp_session.py` | LOW | When file exceeds 850L (currently 714L) | Layer 2d |
| D-05 | Add protocol-shape assertions to `_MinimalSessionContext` and 6 LangGraph shadow-type test classes | MEDIUM | Service layer or next provider work | Layer 2d P1 |
| D-06 | Resolve `_StubProviderFactory` + `FakeChatModel` in `graph/tests/conftest.py` — confirm VidaiMock coverage or replace | HIGH | Service layer | Layer 2d |
| D-07 | Verify `RpcHandlerMap` type annotation upgraded after handler unification | MEDIUM | Immediate (next PR) | Layer 2d |
| D-08 | Justfile structural cleanup: service topology extraction, stop/kill dedup | LOW | Service layer | Layer 3 ADR |
| D-09 | `docker-compose.prod.postgres.yml` hardcoded `vaultspec:vaultspec` credentials | MEDIUM | Service layer | Layer 3 ADR |
| D-10 | `max_concurrent_threads` relocation from InfraConfig to DomainConfig | LOW | Service layer | Layer 3 ADR |

## Closed — not carried forward

| Item | Resolution |
|------|-----------|
| Unify RPC handler signatures | RESOLVED PR #15 |
| Type `permission_callback` | RESOLVED PR #15 |
| Remove dead `send_notification` | RESOLVED PR #15 |
| Settings god-object concern | RESOLVED PR #16 — 30-file footprint confirmed legitimate |
| `InfraConfig` sub-config decomposition | CLOSED as non-issue by Layer 3 ADR |
