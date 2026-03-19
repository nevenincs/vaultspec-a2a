# Protocols Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/protocols/` — 4 source files (protocols/**init**.py, mcp/**init**.py, mcp/server.py, a2a/**init**.py, adapter/**init**.py)
**Baseline:** No prior dedicated audit. Tasks #16 and #17 reference previously identified findings.

---

## Cycle 1 — Full Module Scan

### CRITICAL Findings

*None identified.*

---

### HIGH Findings

#### HIGH-01: `_reset_client` uses `_transport.__del__()` — unsafe resource cleanup

**File:** `mcp/server.py:74-78`

```python
def _reset_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        try:
            _shared_client._transport.__del__()
        except Exception:
            pass
    _shared_client = None
```text

`_transport.__del__()` is a CPython implementation detail, not a public API. The correct approach is `await _shared_client.aclose()` (async) or restructuring so the client lifecycle is tied to the FastAPI lifespan. The `__del__` call can silently fail or leave socket handles open.

**Status:** Task #17 tracks this. Still OPEN.

#### HIGH-02: No `thread_id` UUID validation before URL interpolation

**Files:** `mcp/server.py` — lines 474, 592, 841

```python
f"{settings.mcp_api_base_url}/api/threads/{thread_id}/state"
f"{settings.mcp_api_base_url}/api/threads/{thread_id}/messages"
f"{settings.mcp_api_base_url}/api/threads/{thread_id}/cancel"
```python

`thread_id` is a raw string from MCP tool input, interpolated directly into URL paths without UUID format validation. While the REST API would return 404 for invalid IDs, a crafted `thread_id` like `../../admin` could cause path traversal in the URL. httpx would normalize this, but defense-in-depth says validate at the boundary.

#### HIGH-03: Massive error handling boilerplate — 9 identical try/except blocks

**File:** `mcp/server.py` — all 9 tool functions

Every tool function has a nearly identical 15-20 line try/except block catching `ConnectError`, `TimeoutException`, `HTTPStatusError`, and `RequestError`. This is ~150 lines of duplicated code. A shared `_call_api()` wrapper would reduce the file from ~867 lines to ~550 lines and ensure consistent error formatting.

#### HIGH-04: `_KNOWN_PRESETS` evaluated at import time — no hot reload

**File:** `mcp/server.py:94`

```python
_KNOWN_PRESETS: frozenset[str] = discover_team_preset_ids()
```python

`discover_team_preset_ids()` globs the filesystem for `*.toml` files at import time. Adding or removing a preset TOML file requires restarting the MCP server. For a development tool, this is a significant UX issue.

---

### MEDIUM Findings

#### MED-01: `start_thread` payload structure may diverge from `CreateThreadRequest` schema

**File:** `mcp/server.py:212-219`

```python
payload: dict[str, object] = {
    "title": initial_message[:80],
    "initial_message": initial_message,
    "team_preset": preset,
    "autonomous": autonomous,
}
if workspace_root is not None:
    payload["workspace_root"] = workspace_root
```text

The payload is constructed as a raw dict, not via the Pydantic `CreateThreadRequest` model. If `CreateThreadRequest` adds required fields or renames existing ones, this tool will silently send invalid payloads. This mirrors the dual dispatch path issue identified in the API module audit (HIGH-06).

**Status:** Task #16 tracks workspace_root placement specifically.

#### MED-02: `respond_to_permission` option_id field description lists incorrect values

**File:** `mcp/server.py:359-363`

```python
Field(
    description=(
        "The chosen option ID from the permission request, "
        "e.g. 'allow', 'deny', 'allow_always'."
    ),
),
```text

The actual permission option kinds per the schema are `allow_once`, `allow_always`, `reject_once`, `reject_always` — not `allow`, `deny`, `allow_always`. The description will mislead MCP clients.

#### MED-03: `_ws_url_from_api_base` not used in any tool output meaningfully

**File:** `mcp/server.py:117-131`

`_ws_url_from_api_base` is called in `get_thread_status` (line 470) to derive a WebSocket URL, but MCP clients (IDEs like Cursor) cannot connect to raw WebSocket URLs. The `Live: ws://...` line in the tool output is informational noise that MCP clients cannot act on.

#### MED-04: `_get_client()` creates client with no base_url or headers

**File:** `mcp/server.py:65`

```python
_shared_client = httpx.AsyncClient()
```text

No `base_url`, no auth headers, no User-Agent. If the API ever requires authentication (auth.py stub, task LOW-02 in API audit), every tool will need individual header injection.

---

### LOW Findings

#### LOW-01: A2A and adapter stubs are empty placeholders

**Files:** `a2a/__init__.py`, `adapter/__init__.py`

Both are empty stub modules with no implementation. They should either be documented as future work (with a target ADR or timeline) or removed to avoid confusing navigation.

#### LOW-02: `protocols/__init__.py` only exports `mcp`

**File:** `protocols/__init__.py:9-12`

The facade only exports the `mcp` FastMCP instance. The `a2a` and `adapter` stubs are not exported (acceptable since they're empty).

#### LOW-03: No stale `lib.` path references

All imports use proper relative patterns. Clean migration.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 0     | -- |
| HIGH     | 4     | Unsafe cleanup, no input validation, massive duplication, import-time preset cache |
| MEDIUM   | 4     | Payload divergence, wrong option_id docs, unused WS URL, bare client |
| LOW      | 3     | Empty stubs, minimal facade, clean migration |

### Assessment

The MCP server is functionally complete with 9 well-documented tools covering the full orchestration lifecycle. Tool descriptions are excellent — clear about when to use, when not to use, return format, and side effects. The `instructions` string on the FastMCP instance provides good autonomous workflow guidance.

Main concerns:

1. **HIGH-03**: The ~150 lines of duplicated error handling is the biggest maintainability issue. A shared wrapper would cut the file by ~35%.
2. **HIGH-02**: UUID validation at the MCP boundary would prevent any path traversal via crafted thread IDs.
3. **MED-02**: The incorrect permission option_id examples could cause MCP clients to send invalid responses.

### Recommended Fix Priority

1. **HIGH-01**: Replace `_transport.__del__()` with proper async cleanup (task #17)
2. **HIGH-02**: Add UUID regex validation for thread_id parameters
3. **HIGH-03**: Extract shared `_call_api()` wrapper for error handling
4. **MED-02**: Fix option_id description to use `allow_once`/`reject_once`/`reject_always`

---

## Cycle 2 — Tool Correctness & Dual Aggregator Deep Dive (2026-03-06)

**Focus areas** (per team-lead brief):

1. Tool implementations correctness (are they sending/receiving the right data?)
2. Are MCP tools reading stale state (dual aggregator problem)?
3. Error handling on tool failures
4. Stale imports

---

### Stale `lib.` Paths

**ZERO stale `lib.` references** in `protocols/` module. All imports use proper relative patterns.

---

### NEW CRITICAL Findings

#### CRIT-01: `start_thread` sends `workspace_root` as top-level field — silently dropped by endpoint

**File:** `mcp/server.py:218-219`

```python
if workspace_root is not None:
    payload["workspace_root"] = workspace_root
```yaml

The MCP tool sends `workspace_root` as a top-level JSON field. But `CreateThreadRequest` (rest.py:35-55) expects `workspace_root` INSIDE a nested `metadata: ThreadMetadata` object:

```python
class CreateThreadRequest(BaseModel):
    metadata: ThreadMetadata | None = None  # ← workspace_root lives HERE
```text

Pydantic v2 defaults to `extra='ignore'`, so the top-level `workspace_root` is **silently dropped** during deserialization. The endpoint never receives it.

**Evidence:** The test `test_post_threads_with_workspace_root_returns_201` (test_server.py:221-234) sends `workspace_root` at the top level and gets 201 — but this only proves the endpoint doesn't crash, NOT that workspace_root is received.

**Impact:** Every MCP `start_thread` call with `workspace_root` runs WITHOUT project context:

- No `.vault/` document injection
- No feature_tag / context_refs discovery
- No workspace-scoped file operations
- ADR-014 context injection completely bypassed

**Correct payload structure:**

```python
payload = {
    "initial_message": initial_message,
    "team_preset": preset,
    "autonomous": autonomous,
    "metadata": {
        "workspace_root": workspace_root,
        "feature_tag": "",  # optional
    }
}
```text

**Status:** Task #16 tracks this. Escalated from HIGH to CRITICAL — this breaks the entire MCP→workspace integration.

---

### Dual Aggregator Impact on MCP Tools

All MCP tools operate via HTTP against the REST API. They inherit ALL dual aggregator issues from the API module audit (CRIT-01, HIGH-07, HIGH-08). Specific impacts:

| MCP Tool | REST Endpoint | Aggregator Dependency | Staleness Risk |
|----------|--------------|----------------------|----------------|
| `get_team_status` | `GET /api/team/status` | `get_node_summaries()`, `get_agent_states()`, `get_pending_permissions()` | **HIGH** — agents list empty until worker relays `graph_registered` event |
| `get_thread_status` | `GET /api/threads/{id}/state` | `get_sequence()`, `get_node_summaries()`, `get_pending_permissions()` | **HIGH** — `last_sequence` unreliable, agents empty |
| `get_pending_permissions` | `GET /api/team/status` | `get_pending_permissions()` | **MEDIUM** — works once `permission_request` events relayed |
| `list_threads` | `GET /api/threads` | None (DB only) | **NONE** — reads from DB directly |
| `start_thread` | `POST /api/threads` | None | **NONE** — creates in DB + dispatches |
| `send_message` | `POST /api/threads/{id}/messages` | None | **NONE** — dispatches to worker |
| `cancel_thread` | `POST /api/threads/{id}/cancel` | None | **NONE** — updates DB + dispatches |
| `respond_to_permission` | `POST /api/permissions/{id}/respond` | `resolve_permission()` | **LOW** — write path, not read |
| `list_team_presets` | `GET /api/teams` | None | **NONE** — reads from filesystem |

**Summary:** `get_team_status` and `get_thread_status` are the two MCP tools most affected by the dual aggregator problem. A freshly-started thread polled via `get_thread_status` will show 0 messages, empty agents list, empty plan, and sequence=0 until the worker relays events.

---

### Tool Correctness Verification

#### start_thread

| Check | Status | Notes |
|-------|--------|-------|
| Payload matches CreateThreadRequest | **BROKEN** | CRIT-01: workspace_root at wrong level, metadata not constructed |
| Oversized payload rejection | CORRECT | `_MAX_INITIAL_MESSAGE_CHARS = 32_000` checked at line 201 |
| Unknown preset rejection | CORRECT | `_KNOWN_PRESETS` validated at line 207 |
| Default preset | CORRECT | Falls back to `vaultspec-adaptive-coder` |
| Error handling | CORRECT | All 4 httpx exception types caught |

#### get_thread_status

| Check | Status | Notes |
|-------|--------|-------|
| Reads correct endpoint | CORRECT | `GET /api/threads/{thread_id}/state` |
| Formats plan entries | **PARTIAL** | Line 513: reads `entry.get("content")` — correct per PlanEntry schema |
| Formats agents | CORRECT | Uses `display_name` with `agent_id` fallback |
| Formats permissions | CORRECT | Lists request_ids |
| 404 handling | CORRECT | Returns ToolError for unknown thread |

#### respond_to_permission

| Check | Status | Notes |
|-------|--------|-------|
| Sends correct payload | CORRECT | `{"option_id": option_id}` matches `PermissionResponseRequest` |
| option_id description | **WRONG** | MED-02: says 'allow', 'deny' but actual values are 'allow_once', 'reject_once' etc. |
| 404 handling | CORRECT | Returns ToolError for unknown permission |

#### send_message

| Check | Status | Notes |
|-------|--------|-------|
| Sends correct payload | CORRECT | `{"content": message}` matches `SendMessageRequest` |
| Max length | CORRECT | `max_length=_MAX_INITIAL_MESSAGE_CHARS` on Field |
| 404 handling | CORRECT | Returns ToolError for unknown thread |

#### get_team_status / get_pending_permissions

| Check | Status | Notes |
|-------|--------|-------|
| Reads correct endpoint | CORRECT | `GET /api/team/status` |
| Formats agents | CORRECT | display_name + agent_id fallback |
| Formats permissions | CORRECT | request_id + thread_id + description |

#### list_threads

| Check | Status | Notes |
|-------|--------|-------|
| Pagination | CORRECT | Clamps limit to [1,200], offset >= 0 |
| Formatting | CORRECT | Shows status, preset, created, nickname, title |

#### list_team_presets

| Check | Status | Notes |
|-------|--------|-------|
| Reads correct endpoint | CORRECT | `GET /api/teams` |
| Formatting | CORRECT | id, display_name, topology, worker_count, description |

#### cancel_thread

| Check | Status | Notes |
|-------|--------|-------|
| Sends correct action | CORRECT | `POST /api/threads/{id}/cancel` |
| Already-cancelled handling | CORRECT | Returns "not cancelled (current status: ...)" |
| 404 handling | CORRECT | Returns ToolError for unknown thread |

---

### Error Handling Assessment

All 9 tools follow the same 4-tier error handling pattern:

1. `httpx.ConnectError` → "Network error: could not connect..."
2. `httpx.TimeoutException` → "Timeout: server did not respond..."
3. `httpx.HTTPStatusError` → "Server error: HTTP {status_code}" (with 404 special handling where applicable)
4. `httpx.RequestError` → "Connection error: {exc}"

**Assessment:** Error handling is CORRECT and comprehensive. All tools raise `ToolError` (not return strings), which FastMCP translates to `isError=true` in the MCP response. The duplication (HIGH-03) is a maintainability concern, not a correctness issue.

---

### Test Coverage Assessment

**File:** `tests/test_server.py` — 633 lines, 21 test cases

| Tool | Error path test | Success path test | Edge cases |
|------|----------------|-------------------|------------|
| start_thread | YES (unknown preset, server unavailable) | YES (3 variants: no autonomous, autonomous=true, workspace_root) | Missing: oversized message rejection |
| get_thread_status | YES (server unavailable) | YES (200 + 404) | — |
| send_message | YES (server unavailable) | YES (202 + 404) | — |
| respond_to_permission | YES (server unavailable) | YES (404 + dispatch) | — |
| get_team_status | YES (server unavailable) | YES (200) | — |
| get_pending_permissions | YES (server unavailable) | YES (empty list) | Missing: non-empty permissions |
| list_team_presets | YES (server unavailable) | YES (200 + field check) | — |
| list_threads | YES (server unavailable) | YES (empty + with thread + pagination) | — |
| cancel_thread | YES (server unavailable) | YES (404 + cancel + double-cancel) | — |

**Missing test coverage:**

- `start_thread` oversized message rejection (MCP-01)
- `start_thread` with workspace_root actually reaching the endpoint correctly (CRIT-01 — test passes but data is silently dropped)
- `get_pending_permissions` with actual pending permissions
- `_KNOWN_PRESETS` hotload behavior (HIGH-04)
- `_get_client` event loop recycling behavior

---

## Cycle 2 Summary

| Severity | New | Cycle 1 | Key Themes |
|----------|-----|---------|------------|
| CRITICAL | 1   | 0       | workspace_root silently dropped in start_thread |
| HIGH     | 0   | 4       | Transport cleanup, UUID validation, boilerplate, import-time cache |
| MEDIUM   | 0   | 4       | Payload divergence, wrong option_id docs, WS URL, bare client |
| LOW      | 0   | 3       | Empty stubs, minimal facade, clean migration |

**Total open: 1 CRIT, 4 HIGH, 4 MED, 3 LOW**

### Key Findings for Coder

1. **CRIT-01 (Task #16)**: The `start_thread` tool MUST construct a `metadata` object with `workspace_root` inside it, NOT send workspace_root at the top level. Without this fix, all MCP-initiated threads run without project context.

2. **Dual aggregator staleness**: `get_team_status` and `get_thread_status` return stale/empty data from the API aggregator. This is inherited from the API layer — no MCP-specific fix needed, but MCP tool descriptions should document the lag.

3. **MED-02**: The `option_id` description in `respond_to_permission` says 'allow'/'deny' but actual values are 'allow_once'/'reject_once'/'allow_always'/'reject_always'. This will cause MCP client failures.

### Recommended Fix Priority

1. **CRIT-01**: Fix `start_thread` payload to nest workspace_root in metadata (Task #16)
2. **MED-02**: Fix option_id description
3. **HIGH-01**: Replace `_transport.__del__()` (Task #17)
4. **HIGH-03**: Extract shared error handling wrapper (maintainability)
