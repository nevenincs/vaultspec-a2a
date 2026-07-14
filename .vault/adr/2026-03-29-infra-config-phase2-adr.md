---
tags:
- '#adr'
- '#infra-config'
date: '2026-03-29'
modified: '2026-03-29'
related:
- '[[2026-03-28-infra-config-adr]]'
- '[[2026-03-28-infra-config-rolling-audit]]'
- '[[2026-03-28-infra-config-research]]'
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
