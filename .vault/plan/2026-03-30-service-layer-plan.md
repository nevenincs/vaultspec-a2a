---
tags:
- '#plan'
- '#service-layer'
date: '2026-03-30'
related:
- '[[2026-03-30-service-layer-rolling-audit]]'
- '[[2026-03-30-service-layer-research]]'
- '[[2026-03-20-service-lifecycle-architecture-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `service-layer` plan

Resolve ALL 57 audit violations across 4 cycles. Every violation ID
(V1.1–V47, L3.1–L3.8, C1.4, T6.1, T6.3) has a plan step. Grouped
by dependency chain and risk.

## Proposed Changes

Grounded in the rolling audit. No ADR — direct action items.

## Tasks

- **Phase 1 — Delete live-test infrastructure**
  NOTE: conftest cleanups MUST execute BEFORE deleting `tests/conftest.py`
  — `telemetry/tests/conftest.py` line 13 imports `pytest_runtest_setup`
  from it. Deleting first causes `ImportError` during test collection.
  1. Clean `telemetry/tests/conftest.py`: remove cross-import
     `from ...tests.conftest import pytest_runtest_setup`, Jaeger
     fixtures, `_INFRA_MARKERS` — preserve `pytest_collection_modifyitems`
  1. Clean `providers/tests/conftest.py`: remove `requires_acp`
     fail-fast hook, `_INFRA_MARKERS` — preserve middleware auto-marker
  1. Clean `graph/tests/conftest.py`: remove `requires_vidaimock`
     fail-fast, `resolve_vidaimock_base_url()`, `_INFRA_MARKERS` —
     preserve core+unit auto-marker, `_StubProviderFactory`/`pf` fixture
  1. Clean `database/tests/conftest.py`: remove `requires_postgres`
     fail-fast, `_INFRA_MARKERS` — preserve middleware auto-marker,
     `runtime_dir` fixture
  1. NOW safe: delete `src/vaultspec_a2a/tests/` top-level (conftest,
     9 test files, `__init__.py`)
  1. Delete `src/vaultspec_a2a/tests/preps/` directory (V33)
  1. Delete `src/vaultspec_a2a/tests/evals/` directory (V33)
  1. Delete `src/vaultspec_a2a/providers/probes/` directory
  1. Delete `src/vaultspec_a2a/cli/` directory
  1. Delete `src/vaultspec_a2a/control/verify.py`
  1. Delete `src/vaultspec_a2a/control/doctor.py` (V27 partial)
  1. Delete `docker/run.py`, `docker/vidaimock.Dockerfile`
  1. Delete `.github/workflows/eval.yml`,
     `.github/workflows/prodlike-docker.yml`
  1. Remove `vaultspec` from `[project.scripts]` (keep `vaultspec-mcp`)
  1. Remove `[project.optional-dependencies].eval`
  1. Remove 5 live markers from pytest markers
  1. Simplify `addopts` — drop negated live marker expressions
  1. Remove dev deps: `psutil`, `testcontainers[generic]`
  1. Update `control/__init__.py`: remove `"doctor"` and `"verify"`
     from `__all__` and docstring
  1. Remove `mock-seeder` target from `docker/dev.Dockerfile`
  1. Remove Justfile recipes: all jaeger/vidaimock lifecycle, live/smoke/
     tracing/mock/verify test recipes, probe, prod-team/prod-agent,
     preps/preps-list
  1. Update `_dev-service-dispatch` `$devTargets` to empty array
  1. Delete `docker-compose.integration.yml`
  1. Delete `docker-compose.prod.providers.yml`
  1. Run tests, lint, commit

- **Phase 2 — Move Docker/compose to `service/`** (L3.2, L3.6, L3.7)
  1. Create `service/` directory
  1. `git mv` compose files into `service/`
  1. `git mv docker/ service/docker/`
  1. `git mv .env.example service/.env.example`
  1. Update compose `build.context`: `.` → `..` (all 3 files)
  1. Update compose `build.dockerfile`: `docker/X` → `service/docker/X`
     (resolves relative to build context = repo root)
  1. Update volume bind mounts in `docker-compose.dev.yml`:
     `./src/ui` → `../src/ui` (paths resolve from compose file dir,
     not repo root)
  1. Update all Justfile compose file references: add `service/` prefix
  1. Update Justfile `_dev-build-docker-prod`: `docker/prod.Dockerfile`
     → `service/docker/prod.Dockerfile`
  1. Add `**/tests/` to `.dockerignore` (L3.1, L3.6 — test code out
     of images. Note: Dockerfile COPY scope is NOT narrowed; the
     `.dockerignore` exclusion is the control. `COPY src/vaultspec_a2a/`
     still copies the full package tree minus tests.)
  1. Create `service/README.md`: document standalone vs overlay compose
     files, invocation examples (L3.7)
  1. Remove zombie `FIGMA_ACCESS_TOKEN` from `service/.env.example`
     (L3.5)
  1. Document undocumented alias env vars `GOOGLE_CLOUD_PROJECT_ID`,
     `VAULTSPEC_MCP_API_BASE_URL` in `service/.env.example` (L3.5)
  1. Run tests, lint, commit

- **Phase 3 — DomainConfig Layer 1 independence** (V1.1, V1.3-A,
  V1.3-B, C1.4, V39, V40)
  1. Convert `DomainConfig` from `BaseSettings` to `pydantic.BaseModel`
  1. Remove `env_file`, `env_file_encoding`, `env_prefix` and all
     redundant `alias=` declarations from `DomainConfig` (V39)
  1. Remove module-level `domain_config = DomainConfig()` singleton
  1. Create `DomainSettingsConfig(BaseSettings, DomainConfig)` in
     `control/config.py` with `env_file=".env"`, `env_prefix="VAULTSPEC_"`
  1. Update `Settings` MRO: `Settings(DomainSettingsConfig, InfraConfig)`
     — `Settings` keeps its own `model_config` to prevent MRO ambiguity
  1. Instantiate `domain_config = DomainSettingsConfig()` in
     `control/config.py` alongside `settings` (V40 — single parse)
  1. Update ALL modules that import `from ..domain_config import
     domain_config` — change to `from ..control.config import
     domain_config`. This affects ~15 production modules (12 Layer 1
     + `api/ws_dispatch.py`, 4 route files, `control/dispatch.py`,
     `worker/executor.py`, `worker/graph_lifecycle.py`). NOTE: this
     temporarily couples Layer 1 to `control.config` — acceptable as
     intermediate state; the long-term pattern is parameter injection
  1. Update test files that import the singleton:
     `context/tests/test_anchoring.py`, `context/tests/test_metadata.py`,
     `context/tests/test_token_budget.py` — change to import from
     `control.config`
  1. Update `domain_config.py` `__all__` to export only the `BaseModel`
     class
  1. Run `pytest -m core` — must pass without `.env` or env vars (C1.4)
  1. Run lint, commit

- **Phase 4 — Layer 1 constants and enum enforcement** (V22, V23,
  V26, V28, V31, V34, V35)
  1. Create `thread/constants.py` with `DEFAULT_SUPERVISOR_ID` (V26)
  1. Add `REJECT_OPTION_IDS` frozenset to `graph/enums.py` (V34)
  1. Add `STARTUP_REPAIR_REASON` constant to
     `lifecycle/reconciliation.py`
  1. Replace 20+ bare `ThreadStatus` string literals with enum refs in
     `worker/executor.py`, `streaming/ingest.py`,
     `worker/state_projection.py` (V22)
  1. Replace 12 bare `ControlActionType` string literals with enum refs
     in `worker/executor.py`, `control/*_service.py`,
     `api/ws_dispatch.py` (V23). Keep `ipc/schemas.py` `action` as
     `Literal["ingest","resume","cancel"]` — do NOT widen to full enum
     (V28 — intentional non-fix per review: 10-member enum too broad)
  1. Replace 4 bare `ApprovalStatus` string literals in
     `graph/nodes/supervisor.py`, `control/projection.py` (V31)
  1. Replace 8 `"vaultspec-supervisor"` literals with
     `DEFAULT_SUPERVISOR_ID` (V26)
  1. Replace `startswith("reject")` with `REJECT_OPTION_IDS` check in
     `event_handlers.py` (V34)
  1. Update `TERMINAL_STATUS_MAP` to use enum keys (V35)
  1. Replace inline `TERMINAL_STATUSES` re-definitions in
     `worker/state_projection.py` with import from `thread/enums`
  1. Run tests, lint, commit

- **Phase 5 — Domain logic extraction to Layer 1** (V7, V13, V24, V25)
  1. Create `thread/terminal_effects.py`: pure function
     `compute_terminal_effects(status, latest_cancel_action) →
     TerminalEffects` dataclass
  1. Create `thread/permission_fsm.py`: pure functions for permission
     request, resolution, progress-applied inference
  1. Create `thread/dispatch_policy.py`: pure function
     `classify_dispatch_failure(failure_type) → FailureAction`.
     Consolidate inconsistent policies (V25)
  1. Create `thread/lifecycle_guards.py`: `can_delete(status)`,
     `can_archive(status)` (V4)
  1. Create `thread/message_policy.py`: `can_send_followup(status)` (V3)
  1. Create `thread/cancel_policy.py`: `can_cancel(status)`
  1. Create `thread/creation.py`: `resolve_autonomous(explicit,
     team_config)`, `resolve_nickname(...)`, `requires_dispatch(preset)`
     (V8 partial, V24)
  1. Create `thread/repair_policy.py`: `repair_state_for_action(
     action_type, phase)` — pure lookup replacing inline mappings in
     `control/repair_transitions.py` (V24)
  1. Create `thread/idempotency.py`: `default_cancel_key(thread_id)`,
     `default_message_key(thread_id, agent_id, content)` (V24)
  1. Extend `thread/snapshots.py`: checkpoint error → repair status
     mapping (V24)
  1. Update `event_handlers.py` to call new Layer 1 functions (V7, V13)
  1. Update `thread_service.py`, `cancel_service.py`,
     `message_service.py`, `permission_service.py` to call shared
     `dispatch_policy.classify_dispatch_failure` (V25)
  1. Update `api/routes/threads.py` delete/archive to call
     `lifecycle_guards` (V4)
  1. Run tests, lint, commit

- **Phase 6 — Typed service errors and handler cleanup** (V3, V14,
  V15, V16, V17, V1, V2, V8, V9)
  1. Add `FailureType` enum and `failure_type` field to
     `MessageResult`, `CancelResult`, `PermissionResult`,
     `ThreadCreationResult`. Services must populate it (V16)
  1. Update route handlers to use `result.failure_type` instead of
     `startswith(...)` string parsing (V3)
  1. Move `db.commit()` from 6 handler sites into service functions —
     services own transaction boundaries (V17)
  1. Extract `thread_state.py` 95-line orchestration into
     `control/thread_state_service.py` or extend
     `control/snapshot.py` (V14)
  1. Extract 3x copy-pasted event relay in `internal.py` into a
     single `relay_worker_event()` function (V15)
  1. Move `_process_metadata` from `api/routes/threads.py` into
     `control/thread_service.py` (V1)
  1. Move inline JSON metadata parsing from list endpoint into a
     response mapper or service function (V2)
  1. Move domain orchestration (context preamble, vault index,
     autonomous resolution) from `thread_service.py` into Layer 1
     functions created in Phase 5 (V8)
  1. Replace hardcoded business fallback in `ConnectionManager` with
     `DEFAULT_SUPERVISOR_ID` (V9)
  1. Run tests, lint, commit

- **Phase 7 — WS dispatch delegation** (V5, V6, V10-V12, V21)
  DEPENDS ON: Phase 3 (DomainConfig import change in ws_dispatch.py),
  Phase 6 (typed error codes for WS error mapping).
  Both phases MUST complete before Phase 7 starts.
  1. Ensure `failure_type` field exists on `MessageResult` and
     `CancelResult` (Phase 6 step 1 creates these)
  1. Rewrite `_dispatch_message`: open session from `session_factory`,
     delegate to `message_service.send_followup_message`, commit.
     Map `result.failure_type` to `WebSocketCommandRejectedError`
     codes. NOTE: this is a behavioral change — WS path gains
     idempotency, control actions, repair state, status transitions
     it did not previously have. This is intentional (parity with REST).
  1. Rewrite `_dispatch_control`: delegate to
     `cancel_service.cancel_thread` for TERMINATE. Keep RESUME/PAUSE
     as WS-specific stubs
  1. Remove direct `get_thread` DB imports (V6)
  1. Preserve heartbeat: check `result.dispatched`, update
     `app_state.worker_last_heartbeat_ts`
  1. Verify parity: idempotency, control actions, repair state,
     status transitions all via service layer (V10-V12)
  1. Run tests, lint, commit

- **Phase 8 — Test marker correction** (V18-V20, V29-V30, V32-V33,
  V36, T6.1)
  1. Add `service` marker to `pyproject.toml`
  1. Add `not service` to `addopts`
  1. Create `graph/tests/nodes/conftest.py` — apply `middleware`
     marker to `test_worker_integration.py` (V18, V29, V36)
  1. Fix `utils/tests/test_logging.py` — override to `middleware` (V19,
     V30)
  1. Add `unit` marker to `thread/tests/conftest.py` (V20, V32)
  1. Audit ALL remaining conftest files: verify every module has a
     positive `core` or `middleware` marker via
     `pytest_collection_modifyitems`, not just negation (T6.1)
  1. Run `pytest -m core` — verify zero Layer 2 imports
  1. Run `pytest -m middleware` — verify zero Docker requirements
  1. Run tests, lint, commit

- **Phase 9 — Defensive library patterns** (V37, V38, V42-V47, V41,
  V44)
  1. Add `lazy="raise"` to ORM relationships in `database/models.py`.
     FIRST audit `session.delete()` sites for cascade breakage — add
     `selectinload()` or convert to DB-level `ON DELETE CASCADE` where
     needed (V43)
  1. Add `TracerProvider.shutdown()` and `MeterProvider.shutdown()` to
     gateway+worker lifespan via `await asyncio.to_thread(
     provider.shutdown)` (V45)
  1. Set `OTEL_SDK_DISABLED=true` in `pyproject.toml` pytest env (V47,
     T6.3)
  1. Remove dead span error-handling in `telemetry/middleware.py`
     lines 151-155 (V46)
  1. Remove redundant `graph.recursion_limit` in `compiler.py` (V37)
  1. Document `graph.step_timeout` with version-pin comment (V38)
  1. Replace `app.router.lifespan_context` in `api/tests/conftest.py`
     with test-specific app factory (V42)
  1. Fix `migrate.py` nested `asyncio.run()` — call async path
     directly (V44)
  1. Document mixed asyncio/anyio with explanatory comment (V41)
  1. Run tests, lint, commit

- **Phase 10 — Config consolidation and docs** (V27, L3.8)
  1. Remove hardcoded port fallbacks from Justfile — read from env
     vars only (V27)
  1. Remove redundant `VAULTSPEC_DATABASE_BACKEND: sqlite` and
     `VAULTSPEC_CHECKPOINT_BACKEND: sqlite` from compose files (L3.8)
  1. Remove hardcoded port fallbacks from compose files where they
     shadow `config.py` defaults (V27 — compose `:-8000` fallbacks)
  1. Update `src/vaultspec_a2a/README.md`: remove CLI, probes, verify,
     doctor, live tests from tree. Add `service/`. Update markers.
     Document new Layer 1 modules. Update boundary audit.
  1. Run tests, lint, commit

## Violation Coverage Matrix

| Violation | Phase | Step |
|-----------|-------|------|
| V1.1 | 3 | 1-3 |
| V1.3-A | 3 | 1-2 |
| V1.3-B | 3 | 3,7 |
| C1.4 | 3 | 10 |
| V1 | 6 | 6 |
| V2 | 6 | 7 |
| V3 | 5+6 | 5.5, 6.2 |
| V4 | 5 | 4,13 |
| V5 | 7 | 2-3 |
| V6 | 7 | 4 |
| V7 | 5 | 11 |
| V8 | 5+6 | 5.7, 6.8 |
| V9 | 6 | 9 |
| V10 | 7 | 6 |
| V11 | 7 | 3 |
| V12 | 7 | 6 |
| V13 | 5 | 2 |
| V14 | 6 | 4 |
| V15 | 6 | 5 |
| V16 | 6 | 1 |
| V17 | 6 | 3 |
| V18 | 8 | 3 |
| V19 | 8 | 4 |
| V20 | 8 | 5 |
| V21 | 7 | 2 |
| V22 | 4 | 4 |
| V23 | 4 | 5 |
| V24 | 5 | 1-10 |
| V25 | 5 | 3,12 |
| V26 | 4 | 1,7 |
| V27 | 1+10 | 1.11, 10.1, 10.3 |
| V28 | 4 | 5 (intentional non-fix — documented) |
| V29 | 8 | 3 |
| V30 | 8 | 4 |
| V31 | 4 | 6 |
| V32 | 8 | 5 |
| V33 | 1 | 6-7 |
| V34 | 4 | 2,8 |
| V35 | 4 | 9 |
| V36 | 8 | 3 |
| V37 | 9 | 5 |
| V38 | 9 | 6 |
| V39 | 3 | 2 |
| V40 | 3 | 6 |
| V41 | 9 | 9 |
| V42 | 9 | 7 |
| V43 | 9 | 1 |
| V44 | 9 | 8 |
| V45 | 9 | 2 |
| V46 | 9 | 4 |
| V47 | 9 | 3 |
| L3.1 | 2 | 10 (via .dockerignore; COPY scope not narrowed) |
| L3.2 | 2 | 1-6 |
| L3.5 | 2 | 12-13 |
| L3.6 | 2 | 10 |
| L3.7 | 2 | 11 |
| L3.8 | 10 | 2 |
| T6.1 | 8 | 6 |
| T6.3 | 9 | 3 |

## Parallelization

- Phase 1 FIRST (blocking — deletions, conftest cleanup)
- Phase 2 after Phase 1 (independent file set)
- Phase 3 after Phase 1 (DomainConfig conversion)
- Phase 4 after Phase 1 (enum enforcement)
- Phase 5 after Phase 4 (needs constants/enums)
- Phase 6 after Phase 5 (needs Layer 1 domain functions)
- Phase 7 after Phase 3 AND Phase 6 (both touch ws_dispatch.py;
  needs typed errors AND DomainConfig import change)
- Phase 8 after Phase 1 (marker cleanup)
- Phase 9 after Phase 1 (conftest cleanup)
- Phase 10 after ALL (docs reflect final state)

Phases 2, 3, 4, 8, 9 can run in parallel after Phase 1 — BUT Phase 3
and Phase 7 both touch `ws_dispatch.py`, so Phase 3 must complete
before Phase 7 starts.

## Verification

- `pytest -m core` passes without `.env` or env vars
- `pytest -m middleware` passes without Docker
- `pytest` total stable, zero OTLP noise
- Zero bare `ThreadStatus`/`ControlActionType`/`ApprovalStatus` string
  literals in production code
- Zero `from.*cli`, `from.*probes`, `from.*verify`, `from.*doctor`
- All compose/Docker under `service/`, zero at repo root
- `docker compose -f service/docker-compose.dev.yml config` validates
- `ws_dispatch.py` zero direct DB calls, delegates to service layer
- `event_handlers.py` domain logic replaced with Layer 1 calls
- `thread_state.py` reduced to service call + response mapping
- `internal.py` event relay deduplicated
- Service results use typed `failure_type`, no string prefixes
- Zero `db.commit()` in route handlers
- All test conftest files apply positive layer markers
- `ruff check .` and `ty check` pass
