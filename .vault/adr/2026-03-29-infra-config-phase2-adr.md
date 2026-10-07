---
tags:
- '#adr'
- '#infra-config'
date: '2026-03-29'
modified: '2026-10-07'
body_hash: 'sha256:7729a8fe80326be5ab6c781bd7c1fba14c62117886e236e1454984b0bb954aa2'
related:
- '[[2026-03-28-infra-config-adr]]'
- '[[2026-03-28-infra-config-rolling-audit]]'
- '[[2026-03-28-infra-config-research]]'
- '[[2026-10-07-codebase-remediation-fixture-lanes-adr]]'
- '[[2026-10-07-codebase-remediation-sqlite-only-adr]]'
- '[[2026-10-04-container-release-native-production-adr]]'
- '[[2026-10-06-codebase-remediation-audit]]'
---

# `infra-config` adr: deferred-item resolution | (**status:** `accepted`)

## Problem Statement

The Layer 3 rolling audit carries 9 active deferrals spanning providers,
control services, tests, Docker, and config. All must be resolved in this
PR — no further deferral.

## Implementation

### D-01: Remove `_last_auth_url` dual-write

Drop `self._last_auth_url` PrivateAttr from `AcpChatModel`. Remove the
dual-write in `_capture_auth_progress`. Change the `authenticate()`
public method to pass `auth_url=None` instead. The only loss is auth URL
in error messages from the rarely-called public `authenticate()` method
outside `_astream` — acceptable.

### D-02: Keyword-only service functions

Add `*,` after `db` parameter in `cancel_service.cancel_thread`,
`message_service.send_followup_message`, and
`permission_service.respond_to_permission`. `thread_service` already has
it. All callers already use keyword arguments.

### D-03: Extract `ThreadCreationRequest` dataclass

Extract the 9 request-data parameters from `create_and_dispatch_thread`
into a `ThreadCreationRequest` frozen dataclass in `thread_service.py`.
Keep the 5 infra dependency parameters as direct keyword args. Single
caller in `api/routes/threads.py` constructs the dataclass.

### D-04: Split `_acp_session.py` (697 lines)

Three-way split:
- `_acp_types.py` (~73L): `_AcpModelConfig`, `_AcpSessionContext`,
  `InitializeResult`, `SessionSetupResult`, `PermissionCallback`
- `_acp_auth.py` (~230L): auth helpers, `authenticate_rpc`,
  `wait_for_authenticate_response`, `_AuthResponseCancelledError`,
  `runtime_log_extra`
- `_acp_session.py` (~200L): `initialize_session`, `setup_session`,
  `setup_prompt`

Import direction: types ← auth ← session (no cycles).

### D-05: Protocol-shape assertions for shadow types

Add `isinstance` or structural assertions to test shadow types:
- `_MinimalSessionContext` already has dataclass field check — sufficient
- `_SilentGraph`, `_InterruptingGraph`, `_RecursingGraph`: add
  `isinstance(graph, StreamableGraph)` assertion
- `_InterruptValue`, `_GraphTask`, `_GraphStateSnapshot`: add attribute
  assertions against real LangGraph types where importable
- `_WriteBuffer`: add `WriteDrainable` protocol check
- `_ReadBuffer`: genuine subclass, no assertion needed

### D-06: Close `_StubProviderFactory` + `FakeChatModel`

Research confirms these are structurally necessary for Layer 1 isolation.
The stub is used only in compilation-structure tests (no execution);
VidaiMock covers execution paths. Add a `isinstance(pf, ProviderFactoryProtocol)`
assertion in the fixture to guard against protocol drift. Close the item.

### D-08: Justfile stop/kill dedup

For gateway, worker, and ui: the kill recipes are byte-identical to stop
(both use `Stop-Process -Force`). Replace kill recipe bodies with a
delegation to the corresponding stop recipe. Docker services (postgres,
jaeger, vidaimock) keep separate stop/kill since `docker stop` vs
`docker kill` are semantically different.

### D-09: Postgres compose credentials

Replace hardcoded `vaultspec:vaultspec` in `docker-compose.prod.postgres.yml`
with `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}`. Add
`POSTGRES_PASSWORD=` to `.env.example`.

### D-10: Move `max_concurrent_threads` to DomainConfig

Relocate from `InfraConfig` to `DomainConfig` (worker executor section).
This is a behavioral knob, not infra. `executor.py` is the sole consumer
and already imports `domain_config` — the `settings` import becomes
unused and can be removed.

## Rationale

All items are mechanical or well-scoped architectural changes. D-03 and
D-04 are the most substantial but have clear boundaries and single
callers. No item touches business logic.

## Consequences

- `_acp_session.py` splits into 3 files — all internal (`_` prefixed),
  no public API change
- `create_and_dispatch_thread` signature changes — single caller,
  backward-compat is irrelevant
- `executor.py` drops `settings` import entirely — clean domain boundary
- Kill recipes delegate to stop — no behavioral change for users

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

Two items are reconciled with decisions accepted on 2026-10-07.

- **D-06, reversed.** D-06 kept `_StubProviderFactory` and `FakeChatModel` because "VidaiMock covers execution paths". `2026-10-07-codebase-remediation-fixture-lanes-adr` removes VidaiMock. The deterministic lane, selected through the real `ProviderFactory`, replaces `_StubProviderFactory` (`src/vaultspec_a2a/graph/tests/conftest.py`) and the langchain fake chat models in tests. The protocol-drift assertion D-06 added goes with the stub. Grounding: R6-F3 and R6-F15 in `2026-10-06-codebase-remediation-audit`; decision D2 in `2026-10-06-codebase-remediation-plan`.
- **D-09, historical.** The Postgres Compose credentials item has no subject. `docker-compose.prod.postgres.yml` was retired under `2026-10-04-container-release-native-production-adr`, and `2026-10-07-codebase-remediation-sqlite-only-adr` supersedes `2026-03-10-postgres-dual-backend-adr` and makes SQLite the only store. `.env.example` carries no `POSTGRES_PASSWORD`, and its remaining Postgres block is removed under that record. Grounding: R3-F12 in `2026-10-06-codebase-remediation-audit`; decision D1 in `2026-10-06-codebase-remediation-plan`.

A third item is reconciled with the same decisions.

- **D-08, historical.** The item's premise has gone. "Docker services (postgres, jaeger, vidaimock) keep separate stop/kill since `docker stop` vs `docker kill` are semantically different": only Jaeger remains. `2026-10-04-container-release-native-production-adr` retired the Postgres Compose files, `2026-10-07-codebase-remediation-sqlite-only-adr` removes Postgres as a store, and `2026-10-07-codebase-remediation-fixture-lanes-adr` removes VidaiMock. Jaeger is a development and test fixture. The Justfile carries no per-service stop/kill pair for any of them. Compose projects stop through their `down` recipes (`Justfile:758,778`), and registered host processes are killed through `service-kill` (`Justfile:708`). The gateway, worker and ui kill-to-stop delegation the item added has no recipe left to apply to. Grounding: R6-F3 in `2026-10-06-codebase-remediation-audit`; decision D2 in `2026-10-06-codebase-remediation-plan`.
