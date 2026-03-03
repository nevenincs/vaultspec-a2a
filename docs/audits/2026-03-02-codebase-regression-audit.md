# Codebase Regression & Gap Audit — 2026-03-02

**Scope**: Full `lib/` tree (~115 Python files)

**Audited by**: codebase-researcher (langgraph-hardening team)

**Method**: Direct file reads, grep sweeps for TODO/FIXME/HACK, `type: ignore`
annotations, bare agent IDs, unconstrained fields, import chains, `__all__`
completeness, and cross-referencing task list completions against live code.

---

## Executive Summary

Five sprints of parallel changes (TOML wave, agent prefix rename, MCP hardening,
worker/executor, API fixes) have left a coherent codebase with several residual
gaps. No import errors found. `__all__` coverage is complete across all modules.
The most impactful regressions are:

- **MCP-05 regression**: shared httpx client task was marked completed but
  server.py creates 7 inline `AsyncClient()` instances — the fix was not applied.
- **`vaultspec-continuous-audit` preset invisible to REST + MCP**: the TOML
  exists but neither `_BUNDLED_TEAM_PRESETS` (endpoints.py) nor
  `_HARDCODED_PRESETS` (mcp/server.py fallback) include it.
- **`lib/worker/health.py` is an empty stub**: `HealthCheck` class has no
  methods — health check endpoint and heartbeat emission are not implemented.
- **`supervisor.py` asyncio regression**: task T19 (`asyncio.get_event_loop()`)
  was fixed in nodes/supervisor.py but `lib/api/supervisor.py` still uses
  `asyncio.wait_for` and `asyncio.get_running_loop()` instead of anyio
  equivalents.
- **Bare "supervisor" agent IDs in graph.py and websocket.py**: the agent prefix
  rename (AGENT-PREFIX task) replaced named worker IDs but left the graph-internal
  LangGraph node name "supervisor" hardcoded — this is likely intentional (it is
  a graph node name, not an agent config ID), but the websocket.py fallback at
  line 305 also hardcodes `"supervisor"` as an agent_id sent over the wire,
  which may confuse the frontend if the supervisor agent config is loaded as
  `vaultspec-supervisor`.

---

## Findings by Severity

| ID | Severity | Module | Summary |
|----|----------|--------|---------|
| REG-01 | HIGH | `lib/protocols/mcp/server.py` | MCP-05 marked complete but inline `AsyncClient()` still created per-call in all 7 tools |
| REG-02 | HIGH | `lib/api/endpoints.py` + `lib/protocols/mcp/server.py` | `vaultspec-continuous-audit` preset exists as TOML but absent from both hardcoded preset lists |
| REG-03 | MEDIUM | `lib/worker/health.py` | `HealthCheck` class is an empty stub with no methods |
| REG-04 | MEDIUM | `lib/api/supervisor.py` | Uses `asyncio.wait_for` and `asyncio.get_running_loop()` — anyio convention violation (T29 fix only targeted nodes/supervisor.py) |
| REG-05 | MEDIUM | `lib/api/websocket.py:305` | Hardcoded `agent_id="supervisor"` fallback in follow-up message dispatch — should be `"vaultspec-supervisor"` to match renamed preset |
| REG-06 | MEDIUM | `lib/api/schemas/internal.py:action` | `DispatchRequest.action: str` is unconstrained — should be `Literal["ingest", "resume", "cancel"]` (SCH-05, still open) |
| REG-07 | LOW | `lib/api/schemas/internal.py:agent_id` | `DispatchRequest.agent_id` defaults to `"supervisor"` (bare, not `"vaultspec-supervisor"`) |
| REG-08 | LOW | `lib/api/auth.py` | `authenticate_request` is a no-op stub; not wired to any endpoint — documented as intentional but not tracked |
| REG-09 | LOW | `lib/core/team_config.py` | `TeamGraphConfig`, `TeamPermissionsConfig`, `TeamPersonaConfig` exported in `__all__` but missing from `lib/core/__init__.py` exports |
| REG-10 | LOW | `lib/protocols/mcp/server.py` | `list_team_presets` MCP tool still missing (task MCP-R2 in_progress) |
| REG-11 | LOW | `lib/protocols/mcp/server.py` | `cancel_thread` MCP tool still missing (task MCP-R3 in_progress) |
| REG-12 | INFO | `lib/api/endpoints.py:519` | `# type: ignore[arg-type]` on `minimal_state` — may indicate improper ThreadStateSnapshot construction for legacy threads |
| REG-13 | INFO | `lib/api/tests/test_endpoints.py:323` | Comment confirms `pending_permissions` always empty (wiring TODO) — correct per architecture but still a gap |

---

## Detailed Findings

### REG-01 — HIGH: MCP-05 regression — inline httpx.AsyncClient in all 7 tools

**Task**: MCP-05 (status: completed in task list)
**Files**: `lib/protocols/mcp/server.py:156,216,282,333,423,465,525`

MCP-05 was supposed to share an `httpx.AsyncClient` across MCP tool calls to
avoid per-call connection overhead and TLS handshake cost. However, every one of
the 7 tool functions creates its own `async with httpx.AsyncClient() as client:`
inline. No module-level or lifespan-managed client exists.

The task was marked completed but the fix was either not applied or was reverted
during later coder additions (`get_team_status` and `get_pending_permissions` were
added after the task was closed and both use inline clients).

**Impact**: Each MCP tool call creates a new TCP connection + TLS handshake to
localhost. In a supervised workflow that calls `get_pending_permissions` +
`respond_to_permission` in rapid succession, this is 2 unnecessary connection
setups. Under concurrent load this creates connection pool pressure.

**Recommended fix**: Create a module-level `httpx.AsyncClient` using
`httpx.AsyncClient(base_url=settings.api_base_url)` and share it across all
tool functions, or use a FastMCP lifespan hook to create and dispose it.

---

### REG-02 — HIGH: `vaultspec-continuous-audit` preset invisible to REST + MCP

**Files**: `lib/api/endpoints.py:674-679`, `lib/protocols/mcp/server.py:58-60`

A fifth team preset TOML exists on disk:
```
lib/core/presets/teams/vaultspec-continuous-audit.toml
```

But neither hardcoded list includes it:
- `endpoints.py._BUNDLED_TEAM_PRESETS` = 4 entries (no `continuous-audit`)
- `mcp/server.py._HARDCODED_PRESETS` = 4 entries (no `continuous-audit`)

**Impact**:
- `GET /api/teams` returns only 4 presets — the continuous-audit preset is
  invisible to the UI team picker.
- `start_thread(team_preset="vaultspec-continuous-audit")` will fail MCP
  validation at line 142-146 if TOML discovery fails (packaged deployment), and
  succeed only in development where TOML glob works at import time.
- `_BUNDLED_TEAM_PRESETS` is the canonical source of truth for the REST listing
  — it is not auto-discovered, making this a silent gap.

**Recommended fix**: Add `"vaultspec-continuous-audit"` to both lists.

---

### REG-03 — MEDIUM: `lib/worker/health.py` is an empty stub

**File**: `lib/worker/health.py`

```python
class HealthCheck:
    """Periodic heartbeat emitter and /healthz endpoint handler."""
```

The `HealthCheck` class has no attributes, no methods, and no implementation.
The module docstring promises "health check endpoint and heartbeat emitter" but
neither exists. The class is imported and exported from `lib/worker/__init__.py`
but appears to be unused in `app.py` and `executor.py` (grep finds no usage).

**Impact**: The worker has no `/healthz` endpoint. The `WorkerSupervisor` in
`lib/api/supervisor.py` uses process `poll()` to determine liveness — HTTP
health probing is not wired. This is a correctness gap for production deployments
where health checks are needed.

---

### REG-04 — MEDIUM: `lib/api/supervisor.py` uses `asyncio` primitives (not anyio)

**File**: `lib/api/supervisor.py:71-80, 106-110`

```python
# Line 71
loop = asyncio.get_running_loop()
await asyncio.wait_for(
    loop.run_in_executor(None, self._process.wait),
    timeout=30,
)
# Lines 106-107
healthy_since = asyncio.get_running_loop().time()
elif asyncio.get_running_loop().time() - healthy_since > 60.0:
```

Task T19 ("Replace deprecated asyncio.get_event_loop() in supervisor.py") was
completed, but that task targeted `lib/core/nodes/supervisor.py`. The API-layer
`lib/api/supervisor.py` uses `asyncio.wait_for` and `asyncio.get_running_loop()`
instead of anyio equivalents. This violates the anyio convention documented in
architectural patterns.

`asyncio.wait_for` specifically cannot be safely cancelled by anyio cancel scopes
in all cases — it has its own internal cancellation state that can cause bugs
under anyio's task group model.

**Recommended fix**: Replace `asyncio.wait_for(...)` with `anyio.fail_after(30):`
context manager. Replace `asyncio.get_running_loop().time()` with
`anyio.current_time()`.

---

### REG-05 — MEDIUM: Bare `"supervisor"` agent_id fallback in websocket.py

**File**: `lib/api/websocket.py:305`

```python
agent_id=cmd.agent_id or "supervisor",
node_name="supervisor",
```

After the AGENT-PREFIX rename sprint, the supervisor agent config ID is
`"vaultspec-supervisor"`. When `cmd.agent_id` is empty (follow-up messages), the
websocket emits an `AgentStatusEvent` with `agent_id="supervisor"`. This bare ID
will not match any loaded agent config, and the frontend may show the event under
an unrecognized agent slot.

Note: The LangGraph graph node name `"supervisor"` in `graph.py` is a separate
concern — it is the graph topology node label, not the agent config ID, and does
not need to change.

**Recommended fix**: `agent_id=cmd.agent_id or "vaultspec-supervisor"`

---

### REG-06 — MEDIUM: `DispatchRequest.action` unconstrained string

**File**: `lib/api/schemas/internal.py:17`

```python
action: str = Field(description="'ingest' | 'resume' | 'cancel'")
```

Valid values are documented in the field description but not enforced by type.
A caller passing `action="ingst"` (typo) will be silently accepted by Pydantic
but will produce a silent no-op or KeyError in executor dispatch logic.

**Recommended fix**: `action: Literal["ingest", "resume", "cancel"]`

---

### REG-07 — LOW: `DispatchRequest.agent_id` defaults to bare `"supervisor"`

**File**: `lib/api/schemas/internal.py:19`

```python
agent_id: str = "supervisor"
```

Post-rename, the canonical ID is `"vaultspec-supervisor"`. This default is used
when no agent_id is specified — e.g. for initial ingest dispatch.

---

### REG-08 — LOW: `authenticate_request` no-op stub not wired to any endpoint

**File**: `lib/api/auth.py`

The `authenticate_request` function exists and has a well-documented TODO, but
is not wired as a `Depends(...)` on any endpoint. The comment says the API is
"intended for local use only" — acceptable for v1 but should be tracked as a
known security gap. The MCP server makes calls to the REST API on loopback with
no authentication, which is consistent with this design.

---

### REG-09 — LOW: `lib/core/__init__.py` missing 3 new TOML config exports

**File**: `lib/core/__init__.py`

`TeamGraphConfig`, `TeamPermissionsConfig`, and `TeamPersonaConfig` were added
to `lib/core/team_config.py` (TOML-02) and listed in that module's `__all__`,
but they are not imported or re-exported in `lib/core/__init__.py`.

Consumers following the ADR import convention (`from lib.core import X`) cannot
access these three types. They must use the non-preferred deep-import path
(`from lib.core.team_config import TeamGraphConfig`).

**Recommended fix**: Add to `lib/core/__init__.py`:
```python
from .team_config import TeamGraphConfig as TeamGraphConfig
from .team_config import TeamPermissionsConfig as TeamPermissionsConfig
from .team_config import TeamPersonaConfig as TeamPersonaConfig
```
And add to `__all__`.

---

### REG-10 — LOW: `list_team_presets` MCP tool absent (MCP-R2 in_progress)

**File**: `lib/protocols/mcp/server.py`

REST endpoint `GET /api/teams` exists and returns `TeamPresetsResponse`. No
corresponding MCP tool exists. Task MCP-R2 is in_progress — flagging here for
tracking. Until it lands, an MCP caller cannot discover preset names without
calling `start_thread` with an invalid preset and reading the error message.

---

### REG-11 — LOW: `cancel_thread` MCP tool and REST endpoint absent (MCP-R3 in_progress)

**File**: `lib/protocols/mcp/server.py`, `lib/api/endpoints.py`

No `POST /threads/{id}/cancel` endpoint exists on the REST API, and no
`cancel_thread` MCP tool. Task MCP-R3 is in_progress.

---

### REG-12 — INFO: `type: ignore[arg-type]` on `minimal_state` in endpoints.py

**File**: `lib/api/endpoints.py:519`

```python
minimal_state,  # type: ignore[arg-type]
```

The `_enrich_snapshot_from_state` function at line 384 accepts `CheckpointTuple`
but a synthesized `minimal_state` dict is passed when the checkpointer returns
`None`. The type ignore suppresses what may be a legitimate type mismatch that
could surface as a runtime error for threads with no checkpoint state.

---

### REG-13 — INFO: `pending_permissions` always empty in test comment

**File**: `lib/api/tests/test_endpoints.py:323`

```python
# pending_permissions is always empty until wired (API-M8 TODO)
```

This confirms that `GET /api/team/status` always returns `pending_permissions=[]`
in tests. However, `lib/core/aggregator.py:801` implements `get_pending_permissions()`
and `endpoints.py:659` calls it — the wiring appears to exist in production code.
The test comment may be outdated (test fixtures don't trigger the aggregator path).

---

## Cross-Module Import & Export Audit

| Module | `__all__` | Imports complete | Issues |
|--------|-----------|-----------------|--------|
| `lib/api/__init__.py` | Yes | Yes | Intentionally partial (circular dep documented) |
| `lib/core/__init__.py` | Yes | Missing 3 TOML types (REG-09) | |
| `lib/database/__init__.py` | Yes | Yes | Clean |
| `lib/protocols/__init__.py` | Yes | Yes | Only MCP exported (a2a/adapter empty stubs) |
| `lib/providers/__init__.py` | Yes | Yes | Lazy imports correct |
| `lib/telemetry/__init__.py` | Yes | Yes | Clean |
| `lib/utils/__init__.py` | Yes | Yes | Clean |
| `lib/worker/__init__.py` | Yes | Yes | `HealthCheck` exported but stub |
| `lib/workspace/__init__.py` | Yes | Yes | Clean |

No import errors found. No circular import issues beyond the documented ones.

---

## TODO/FIXME Inventory (non-test, non-type-ignore)

| File | Line | Comment |
|------|------|---------|
| `lib/api/auth.py` | 38 | `TODO(vaultspec): implement authentication` — documented, acceptable for v1 |

No FIXME or HACK comments found in production code.

---

## Test Coverage Gaps

| Module | Test file exists | Notes |
|--------|-----------------|-------|
| `lib/worker/health.py` | None (only indirect via `test_internal.py`) | Stub has no testable surface |
| `lib/api/auth.py` | `test_auth.py` exists | Thin (stub only) |
| `lib/api/supervisor.py` | `test_supervisor.py` exists | Adequate |
| `lib/database/migrations/__init__.py` | Indirect via aggregator | Migration logic may be untested |
| `lib/protocols/mcp/server.py` | `test_server.py` exists | Tests exercise all 7 tools |

---

## Summary — Action Priority

| Priority | Finding | Recommended Action |
|----------|---------|-------------------|
| P0 | REG-01 MCP-05 regression | Re-apply shared httpx.AsyncClient fix — task was marked done but code unchanged |
| P0 | REG-02 continuous-audit preset invisible | Add to `_BUNDLED_TEAM_PRESETS` + `_HARDCODED_PRESETS` |
| P1 | REG-05 bare "supervisor" in websocket.py | Change to "vaultspec-supervisor" |
| P1 | REG-06 DispatchRequest.action unconstrained | Change to `Literal["ingest", "resume", "cancel"]` |
| P1 | REG-09 core/__init__.py missing 3 exports | Add TeamGraphConfig/Permissions/Persona to facade |
| P2 | REG-04 supervisor.py asyncio primitives | Migrate to anyio equivalents |
| P2 | REG-07 DispatchRequest.agent_id default | Change default to "vaultspec-supervisor" |
| P2 | REG-03 HealthCheck stub | Implement /healthz endpoint and heartbeat |
| Tracking | REG-10 list_team_presets MCP tool | Wait for MCP-R2 completion |
| Tracking | REG-11 cancel_thread | Wait for MCP-R3 completion |

---

*Audit completed: 2026-03-02. All file reads performed directly — no reliance on prior cached state.*
