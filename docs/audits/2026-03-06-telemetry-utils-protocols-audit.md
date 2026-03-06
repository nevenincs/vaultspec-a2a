# Telemetry, Utils, and Protocols Module Audit — 2026-03-06

**Auditor:** codebase-researcher (automated)
**Scope:** `src/vaultspec_a2a/telemetry/` (3 source files), `src/vaultspec_a2a/utils/` (4 source files), `src/vaultspec_a2a/protocols/` (4 source files, 2 stubs)
**Baseline:** Last audited 2026-02-28 (Third-Pass Deep Audit Fix Sprint)

---

## Telemetry Module — Cycle 1

### CRITICAL Findings

*None identified.* The telemetry module is well-designed with proper SDK/no-op fallback, lazy tracer initialization, and comprehensive W3C TraceContext propagation.

### HIGH Findings

*None identified.*

### MEDIUM Findings

#### TEL-MED-01: `instrumentation.py` docstring references `LANGCHAIN_*` as env vars but `LANGSMITH_*` are canonical

**File:** `instrumentation.py:11-12, 26-27`

```
LangSmith tracing is configured separately via environment variables
(``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_API_KEY``)
```

And lines 78-83:
```python
_LANGSMITH_ENABLED = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in (...)
_LANGSMITH_PROJECT = os.environ.get("LANGCHAIN_PROJECT", "default")
```

The code reads `LANGCHAIN_TRACING_V2` and `LANGCHAIN_PROJECT` but the INFRA sprint established `LANGSMITH_*` as the canonical names. The Settings class in `config.py` uses `AliasChoices` to accept both, but this module reads `os.environ` directly (accepted exception per ENV-BYPASS policy) and only checks the legacy names. If a user sets only `LANGSMITH_TRACING=true`, this module won't detect it.

#### TEL-MED-02: `middleware.py` imports private `_SDK_DISABLED` from `instrumentation.py`

**File:** `middleware.py:38`

```python
from .instrumentation import _SDK_DISABLED, get_tracer
```

Importing a private constant (leading underscore) from a sibling module. This should be made public or exposed via the facade.

#### TEL-MED-03: `middleware.py` exception handler references `span` variable from `with` block scope

**File:** `middleware.py:150-154`

```python
with _get_tracer().start_as_current_span(...) as span:
    ...
    return response
except Exception as exc:
    span.set_status(StatusCode.ERROR, str(exc))  # span from with block
```

The `except` block at line 150 catches exceptions from outside the `with` block (after the context manager has exited). If the `with` block's `__exit__` raises, `span` would still be in scope but the span may already be ended. In practice this works because OTel spans are lenient about post-end operations, but it's architecturally fragile.

### LOW Findings

#### TEL-LOW-01: `_SERVICE_VERSION` hardcoded as `"0.1.0"` in two places

**File:** `instrumentation.py:61`

```python
_SERVICE_VERSION = os.environ.get("OTEL_SERVICE_VERSION", "0.1.0")
```

Same hardcoded version as `websocket.py:83`. Should use `importlib.metadata.version()` for consistency.

---

## Utils Module — Cycle 1

### CRITICAL Findings

*None identified.*

### HIGH Findings

*None identified.*

### MEDIUM Findings

#### UTIL-MED-01: `trace.py` uses `time.sleep()` (blocking) in an async-adjacent context

**File:** `trace.py:96`

```python
time.sleep(2)
```

`print_trace_summary()` is a synchronous function that blocks with `time.sleep(2)` in a polling loop (up to 10s total). While this function is designed for CLI runner scripts (not async contexts), if called from an async context it would block the event loop.

#### UTIL-MED-02: `trace.py` constructs LangSmith filter string via f-string interpolation

**File:** `trace.py:66`

```python
filter=f'eq(metadata_key, "thread_id") and eq(metadata_value, "{thread_id}")',
```

The `thread_id` is interpolated directly into the filter string. If `thread_id` contains special characters (quotes, parentheses), this could break the filter syntax or potentially inject filter predicates. Thread IDs are typically hex UUIDs so practical risk is low, but this is not sanitized.

#### UTIL-MED-03: `utils/__init__.py` does not export `trace.py` functions

**File:** `utils/__init__.py`

The facade exports enums and logging but not `print_trace_summary` from `trace.py`. The function is only used by `scripts/` runner scripts, so this may be intentional, but it breaks the facade pattern.

#### UTIL-MED-04: `JSONFormatter` in `logging.py` does not export from utils facade

**File:** `logging.py:13`

`__all__ = ["JSONFormatter", "setup_logging"]` declares `JSONFormatter` as public, but `utils/__init__.py` only imports `setup_logging`, not `JSONFormatter`. Consumers must deep-import.

### LOW Findings

#### UTIL-LOW-01: `enums.py` MODEL_MAP comment says "as of February 2026"

**File:** `enums.py:69`

```python
# Concrete model name mapping as of February 2026
```

This date comment will grow stale. The mapping itself is fine but the date stamp suggests it should be reviewed periodically.

---

## Protocols Module — Cycle 1

### CRITICAL Findings

*None identified.*

### HIGH Findings

#### PROTO-HIGH-01: `_reset_client()` uses `_transport.__del__()` for cleanup

**File:** `mcp/server.py:75`

```python
_shared_client._transport.__del__()  # type: ignore[union-attr]
```

This was previously flagged in LG-030 (LangGraph Alignment Sprint) for the MCP server module. Calling `__del__()` directly is fragile and non-standard. The correct cleanup is `await _shared_client.aclose()` in an async context, or `_shared_client.close()` in a sync context.

The comment says "Synchronous close is fine in test teardown" but `__del__` is not the same as `close()`. `__del__` may not properly flush pending requests or release connections.

#### PROTO-HIGH-02: `_KNOWN_PRESETS` is computed at import time and never refreshed

**File:** `mcp/server.py:94`

```python
_KNOWN_PRESETS: frozenset[str] = discover_team_preset_ids()
```

This runs `discover_team_preset_ids()` at module import time, which globs `presets/teams/*.toml`. If presets are added/removed at runtime (e.g., workspace-local presets), the MCP server won't see them until the process restarts. The `start_thread` tool rejects unknown presets based on this stale set.

#### PROTO-HIGH-03: `start_thread` sends `workspace_root` as a string but not wrapped in `metadata`

**File:** `mcp/server.py:218-219`

```python
if workspace_root is not None:
    payload["workspace_root"] = workspace_root
```

The `CreateThreadRequest` Pydantic model expects `workspace_root` inside a `metadata` object (as part of `ThreadMetadata`), not as a top-level field. However, looking at the model:

```python
class CreateThreadRequest(BaseModel):
    metadata: ThreadMetadata | None = None
```

The `workspace_root` at the top level would be silently ignored by Pydantic (it's not a declared field). The MCP server's `start_thread` tool therefore never properly sends `workspace_root` to the API, meaning vault context injection is broken when starting threads via MCP.

### MEDIUM Findings

#### PROTO-MED-01: `a2a/__init__.py` and `adapter/__init__.py` are empty stubs

**Files:** `protocols/a2a/__init__.py`, `protocols/adapter/__init__.py`

Both are placeholder modules with `__all__: list[str] = []`. They add directory structure but no functionality. If they're planned for future implementation, they should have TODO comments. If not, they're dead code.

#### PROTO-MED-02: MCP error handling is heavily duplicated across all 9 tool functions

**File:** `mcp/server.py` (throughout)

Every tool function has an identical 4-branch `except` block handling `ConnectError`, `TimeoutException`, `HTTPStatusError`, and `RequestError`. This ~16-line error handler is repeated 9 times (144 lines of duplicated boilerplate). A shared helper function would reduce this.

#### PROTO-MED-03: `sse_app()` not exported from protocols facade

**File:** `protocols/mcp/__init__.py` exports only `mcp` (the FastMCP instance). The `sse_app()` method is called directly from `api/app.py:379`:

```python
app.mount("/mcp", mcp_server.sse_app())
```

This works because `mcp_server.sse_app()` calls `mcp.sse_app()` on the FastMCP instance. But the import path `from ..protocols import mcp as mcp_server` means the consumer accesses the FastMCP instance directly. The facade exports are correct for this pattern, but it could be made more explicit.

### LOW Findings

#### PROTO-LOW-01: `mcp/server.py` has no `__main__.py` for standalone testing

No way to run the MCP server in isolation for debugging without the full FastAPI app.

---

## Combined Summary

| Module | CRIT | HIGH | MED | LOW |
|--------|------|------|-----|-----|
| Telemetry | 0 | 0 | 3 | 1 |
| Utils | 0 | 0 | 4 | 1 |
| Protocols | 0 | 3 | 3 | 1 |
| **Total** | **0** | **3** | **10** | **3** |

### Assessment

All three modules are small and well-focused. The telemetry module's OTel integration is particularly clean, with proper lazy initialization and no-op fallbacks.

The main concerns:
1. **PROTO-HIGH-03**: MCP `start_thread` tool sends `workspace_root` as a top-level field instead of inside `metadata`, breaking vault context injection for MCP-initiated threads. This is a functional bug.
2. **PROTO-HIGH-01**: `_transport.__del__()` cleanup is fragile and non-standard.
3. **TEL-MED-01**: LangSmith detection only checks legacy `LANGCHAIN_*` env vars, missing the canonical `LANGSMITH_*` names.

### Recommended Fix Priority

1. **PROTO-HIGH-03**: Fix `start_thread` to wrap `workspace_root` in a `metadata` dict per the `CreateThreadRequest` schema.
2. **PROTO-HIGH-01**: Replace `_transport.__del__()` with proper `close()` call.
3. **TEL-MED-01**: Add `LANGSMITH_TRACING` and `LANGSMITH_PROJECT` fallback checks alongside the existing `LANGCHAIN_*` ones.
4. **PROTO-MED-02**: Extract shared error handler for MCP tool functions.
