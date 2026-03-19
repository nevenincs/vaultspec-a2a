# Permission Pipeline Fix — Phased Execution Plan

**Date**: 2026-03-19
**Status**: IN PROGRESS
**Scope**: Fix the broken supervised workflow (permission request → respond)
**Audit ref**: `docs/audits/2026-03-19-cli-usability-end-to-end-audit.md`
**Research ref**: `docs/research/2026-03-19-langgraph-control-plane-layer-mapping.md`

---

## Root Cause (proven)

Worker IPC bridge (`WorkerBridge`) posts events to `settings.mcp_api_base_url`
(default `http://localhost:8000`). Gateway can run on any port. Three unlinked
config keys. No error when they diverge. Permission events vanish silently.

---

## Phases

### Phase 0 — Fix Pre-existing Type Errors ← DONE

**Goal**: Clear 82 pre-existing `ty` type checker errors that block all
commits. The `ty` hook was added in commit `3e85310` but the errors were
never resolved.

**Files**: 11 files across api/, providers/, cli/, worker/, database/, utils/
**Errors**: LogRecord dynamic attribute access, dict.get() overload, Path|None
narrowing, return type mismatches
**Status**: [x] Fixed — agents dispatched, errors resolved

### Phase 1 — Normalize Config Foundation ← CURRENT

**Goal**: Align `config.py` defaults with `.env.example`, fix contradictions,
remove duplicates. No renames yet — just make the existing config correct.

**Discrepancies found**:

| # | Issue | config.py | .env.example | Resolution |
|---|-------|-----------|-------------|------------|
| D1 | `database_backend` default | `"postgres"` | `postgres` | → `"sqlite"` (ADR-035) |
| D2 | `checkpoint_backend` default | `"postgres"` | `postgres` | → `"sqlite"` (ADR-035) |
| D3 | `database_url` default | `postgresql+asyncpg://...` | `postgresql+asyncpg://...` | → `sqlite+aiosqlite:///vaultspec.db` |
| D4 | .env.example line 41-42 comment | n/a | "Postgres is default" | Fix comment to match ADR-035 |
| D5 | `provider_timeout_seconds` | `300` | `120` | → `120` (.env.example is operator-facing) |
| D6 | `VAULTSPEC_AUTO_SPAWN_WORKER` duplicate | n/a | lines 82 + 97 | Remove duplicate at line 97 |
| D7 | `mcp_api_base_url` section header | n/a | "MCP Server (standalone)" | Will be fixed in Phase 2 rename |
| D8 | `checkpoint_database_url` default | `None` | `postgresql://...` | → `None` (derive from database_url) |

**Files touched**: `config.py`, `.env.example`
**Status**: [x] Done

### Phase 2 — Rename `mcp_api_base_url` → `gateway_url`

**Goal**: Fix the misleading name. Add backward-compat alias. Update all
consumers.

**Rename map**:

| Old | New | Env var (new) | Env var (deprecated alias) |
|-----|-----|--------------|---------------------------|
| `mcp_api_base_url` | `gateway_url` | `VAULTSPEC_GATEWAY_URL` | `VAULTSPEC_MCP_API_BASE_URL` |

**Consumers** (from grep):

- `worker/app.py:98` — bridge constructor (1 occurrence)
- `protocols/mcp/server.py` — ~30 occurrences (REST calls to gateway)
- `cli/_mcp.py:42` — help text
- `protocols/mcp/__main__.py:12` — docstring
- `protocols/mcp/__init__.py:5` — docstring
- `.env.example:66` — env var definition
- `docker-compose.dev.yml:49` — env var
- `docker-compose.prod.yml:65` — env var
- `docker/prod.Dockerfile:86` — env var
- `docs/IDE_SETUP.md` — documentation
- `tests/conftest.py:365` — test fixture
- `tests/test_permission_durability_live.py:95` — test fixture
- `tests/test_mcp_e2e_live.py:64` — test fixture
- `tests/test_crash_recovery.py:76` — test fixture

**Files touched**: config.py, worker/app.py, protocols/mcp/server.py,
cli/\_mcp.py, protocols/mcp/\_\_main\_\_.py, protocols/mcp/\_\_init\_\_.py,
.env.example, docker-compose.\*.yml, Dockerfile, docs/IDE\_SETUP.md, 4 test files
**Status**: [ ] Not started

### Phase 3 — Auto-derive `gateway_url` and `worker_url`

**Goal**: When not explicitly set, derive from `host`+`port` and
`worker_host`+`worker_port` respectively. Eliminates the config mismatch
that is the root cause.

**Changes**:

- `gateway_url` default → `None`, derived via `@model_validator(mode="after")`
- `worker_url` default → `None`, derived via same validator
- Both retain explicit override capability

**Files touched**: `config.py`, `.env.example` (comment updates)
**Status**: [ ] Not started

### Phase 4 — IPC Failure Logging

**Goal**: Make gateway unreachability loud and obvious. Add startup
connectivity check to worker.

**Changes**:

- `worker/ipc.py`: ERROR on flush exhaustion, WARNING/ERROR on heartbeat
  failures, consecutive failure tracking
- `worker/app.py`: Startup gateway health probe (non-fatal, logs ERROR)

**Files touched**: `worker/ipc.py`, `worker/app.py`
**Status**: [ ] Not started

### Phase 5 — Permission ID Stability

**Goal**: Deterministic permission IDs derived from checkpoint data instead
of random UUIDs.

**Changes**:

- `core/aggregator.py`: Replace UUID fallback with
  `{thread_id}:task{N}:interrupt{M}`, add dedup guard

**Files touched**: `core/aggregator.py`
**Status**: [ ] Not started

### Phase 6 — Env Propagation on Auto-Spawn

**Goal**: Ensure gateway passes `VAULTSPEC_PORT` (or `VAULTSPEC_GATEWAY_URL`)
to auto-spawned worker subprocess.

**Needs investigation**: Locate `LazyWorkerSpawner` spawn code.

**Files touched**: TBD (likely `api/spawner.py` or similar)
**Status**: [ ] Not started

### Phase 7 — CLI Pre-flight Health Check

**Goal**: Warn users when gateway is up but worker is disconnected.

**Files touched**: `cli/_util.py`
**Status**: [ ] Not started

---

## Commit Log

| Commit | Phase | Description |
|--------|-------|-------------|
| `0eda0ef` | 0 | fix(types): resolve 82 pre-existing ty type checker errors |
| (pending) | 1 | fix(config): normalize defaults — sqlite for dev, align .env.example |

---

## Verification Plan (end-to-end, after all phases)

1. Clean start (no env vars) → gateway starts on SQLite, port 8000
2. `VAULTSPEC_PORT=8090` → worker auto-derives `gateway_url=http://127.0.0.1:8090`
3. Supervised workflow → permission visible in `team status`
4. `team status` polled 3× → same `request_id`
5. `team respond` → agent resumes
6. Worker started with gateway down → ERROR log visible
7. `VAULTSPEC_MCP_API_BASE_URL` → still works (deprecated alias)
