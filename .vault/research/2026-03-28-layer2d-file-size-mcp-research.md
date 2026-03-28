---
tags:
  - '#research'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-post-layer2c-boundary-audit]]'
  - '[[2026-03-28-database-layer-adr]]'
  - '[[2026-03-28-database-layer-research]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `layer-2d` research: `file-size-violations-mcp-service-adoption`

Research for Layer 2d — the two remaining file-size violations
(`acp_chat_model.py` at 1,821 lines, `mcp/server.py` at 1,045 lines) and
MCP handler adoption of `control/` service functions. Conducted after
Layer 2c (PR #11) merged.

## Critical Finding: MCP Server Process Model

The handover document states "the MCP server runs in the same process as
the API." **This is incorrect.** The MCP server is a standalone process:

- `protocols/mcp/__main__.py` launches the server via
  `asyncio.run(mcp.run_stdio_async())` or
  `asyncio.run(mcp.run_streamable_http_async())`
- The Justfile recipe `mcp` runs `uv run vaultspec-mcp --transport {TRANSPORT}`
- There is no MCP mount or integration in `api/app.py`
- All 11 tool handlers use `httpx.AsyncClient` to call
  `settings.gateway_url` endpoints

**Consequence for Track A:** Direct service function adoption requires the
MCP server process to initialise its own database engine, session factory,
circuit breaker, worker client, and worker spawner — the same
infrastructure that `api/app.py` sets up during its lifespan. This is a
significant change compared to the handover's assumption of shared
in-process access.

### Option A1: MCP server initialises its own infrastructure

The MCP server would call `init_db()` at startup, create its own
`get_session_factory()`, instantiate `WorkerCircuitBreaker` and
`LazyWorkerSpawner`, and create an `httpx.AsyncClient` pointing at the
worker. Each tool handler would then call service functions directly.

**Pros:**
- Eliminates HTTP loopback entirely
- MCP handlers become thin protocol translators (same as API routes)
- Single code path for all operations

**Cons:**
- Duplicates the entire gateway infrastructure setup
- Two processes competing for the same SQLite file (WAL helps but adds
  complexity)
- Worker management becomes split across two processes — the worker spawner,
  circuit breaker, and health state would diverge
- The MCP server would need to know about the worker URL, manage worker
  health, and handle dispatch — all currently owned by the gateway
- Significant blast radius: touches infrastructure lifecycle, not just
  handler code

### Option A2: Embed MCP server in the FastAPI gateway process

Mount the MCP server as a sub-application within `api/app.py` using
FastMCP's ASGI integration. Tool handlers share the gateway's database
session, circuit breaker, and worker client via `app.state`.

**Pros:**
- Zero infrastructure duplication
- MCP handlers have direct access to all gateway services
- Single process, single database connection, single worker client
- Natural integration with FastAPI dependency injection
- MCP server benefits from gateway's health checks and lifecycle

**Cons:**
- MCP stdio transport (used by IDE integrations) cannot work in-process —
  stdio requires a standalone process
- Requires either dropping stdio support or maintaining two modes:
  embedded (HTTP) + standalone (stdio, HTTP loopback fallback)
- Architectural change to the deployment model

### Option A3: Keep HTTP loopback, decompose handlers only (recommended)

Retain the current architecture where the MCP server is a standalone
process communicating via HTTP. Focus on:
- Splitting the monolithic `server.py` into per-domain handler modules
- Extracting the duplicated httpx error-handling boilerplate
- Reducing handler sizes through shared formatting helpers

**Pros:**
- Zero blast radius on infrastructure — handlers are the only change
- The MCP process model is well-tested and stable
- IDE integrations (Cursor, Windsurf) rely on stdio transport which
  requires a standalone process
- Error handling and retry logic remain simple (HTTP semantics)
- File-size violation resolved by splitting into modules
- The service functions are still reusable by MCP if it is later embedded

**Cons:**
- Two code paths remain (HTTP loopback vs direct service call)
- Loopback overhead persists (negligible for human-interactive MCP calls)
- Does not achieve full entry-point thinness symmetry with API routes

### Recommendation

**Option A3** — decompose handlers only, keep HTTP loopback. Rationale:

- The MCP server's process isolation is a deliberate architectural choice
  that enables stdio transport for IDE integrations
- Initialising duplicate infrastructure (Option A1) creates operational
  complexity with no proportional benefit
- Embedding (Option A2) breaks stdio transport, which is the primary MCP
  use case
- The loopback overhead is negligible: MCP tool calls are human-interactive
  (seconds between calls), not high-frequency
- The file-size violation is resolved by module splitting regardless
- Service function adoption can happen later if/when the MCP server is
  embedded in the gateway (a future architectural decision)

## Track A: MCP Handler Decomposition

### Current state

`protocols/mcp/server.py` (1,045 lines) contains:
- Lines 1-131: module-level setup (shared httpx client, preset cache,
  constants)
- Lines 133-152: FastMCP instance + instructions
- Lines 155-170: URL helper
- Lines 172-313: `start_thread` (141 lines)
- Lines 315-399: `list_threads` (84 lines)
- Lines 402-483: `respond_to_permission` (81 lines)
- Lines 486-601: `get_thread_status` (115 lines)
- Lines 604-679: `send_message` (75 lines)
- Lines 682-751: `get_team_status` (69 lines)
- Lines 754-811: `get_pending_permissions` (57 lines)
- Lines 814-870: `list_team_presets` (56 lines)
- Lines 873-918: `delete_thread` (45 lines)
- Lines 921-981: `archive_thread` (60 lines)
- Lines 983-1045: `cancel_thread` (62 lines)

### Duplication analysis

Every handler contains an identical httpx error-handling try/except block
(4 branches: ConnectError, TimeoutException, HTTPStatusError,
RequestError). This block is 12-18 lines per handler × 11 handlers =
~150 lines of pure boilerplate.

Additionally, 6 handlers include a 404 check on HTTPStatusError with a
ToolError raise — a 3-line pattern repeated identically.

### Proposed module structure

```
protocols/mcp/
├── __init__.py          (re-export mcp instance)
├── __main__.py          (unchanged — standalone entry point)
├── server.py            (slim: FastMCP instance, shared client, register tools)
├── _http.py             (shared httpx helper: _mcp_request() with error mapping)
├── tools/
│   ├── __init__.py
│   ├── thread_lifecycle.py   (start_thread, cancel_thread, delete_thread, archive_thread)
│   ├── thread_query.py       (get_thread_status, list_threads)
│   ├── messaging.py          (send_message, respond_to_permission)
│   └── discovery.py          (get_team_status, get_pending_permissions, list_team_presets)
```

### Shared HTTP helper design

Extract a `_mcp_request()` coroutine in `_http.py` that:
- Accepts method (GET/POST/DELETE), URL path, optional JSON body, timeout
- Uses the shared `httpx.AsyncClient`
- Maps httpx exceptions to `ToolError` with consistent messages
- Returns the parsed JSON response
- Handles 404/409 status codes with optional custom messages

This reduces each handler from ~60-140 lines to ~15-40 lines (the
MCP-specific parameter annotations, docstrings, and response formatting).

## Track B: ACP Chat Model Decomposition

### Current state

`providers/acp_chat_model.py` (1,821 lines) contains the `AcpChatModel`
class with 6 responsibility clusters:

1. **Module-level constants + `_AcpSessionContext`** (lines 1-153, ~153
   lines): capability mappings, terminal allowlist, shell metachar regex,
   env name regex, session context dataclass
2. **LangChain interface** (lines 155-500, ~345 lines): `AcpChatModel`
   field definitions, `_astream`, `_agenerate`, `_generate`, property
   methods, session require helpers
3. **Runtime logging + stderr** (lines 511-617, ~106 lines):
   `_runtime_log_extra`, `_read_stderr_loop`, `_capture_auth_progress`,
   auth URL helpers, auth error classification statics
4. **JSON-RPC protocol dispatch** (lines 649-785, ~136 lines):
   `_process_stdout_loop`, `_dispatch_packet`, `_handle_client_response`,
   `_handle_server_rpc`
5. **RPC handlers — permission + filesystem + terminal** (lines 786-1256,
   ~470 lines): `_on_request_permission`, `_sandbox_path`,
   `_on_fs_read_text_file`, `_on_fs_write_text_file`,
   `_on_terminal_create/kill/output/wait_for_exit/release`,
   `_handle_session_update`, `_on_tool_call`, `_on_tool_call_update`
6. **Session lifecycle + public API** (lines 1257-1821, ~564 lines):
   `_initialize_session`, auth selection/hint methods,
   `_authenticate_rpc`, `_wait_for_authenticate_response`,
   `_setup_session`, `_setup_prompt`, `_send_notification`,
   `fork_session`, `list_sessions`, `set_mode`, `set_model`,
   `set_config_option`, `authenticate`

### Extraction options

**Option B1: Mixin classes**

Split responsibilities into mixin classes that `AcpChatModel` inherits:
`AcpProtocolMixin`, `AcpRpcHandlerMixin`, `AcpSessionMixin`. Mixins share
state via `self` since they're all mixed into the same class.

**Rejected** — mixins obscure the dependency graph and make it unclear
which mixin owns which state. Python MRO surprises are a maintenance risk.

**Option B2: Delegation to helper objects**

`AcpChatModel` instantiates helper objects:
- `_protocol: AcpProtocolHandler` — JSON-RPC dispatch, packet handling
- `_rpc_handlers: AcpRpcHandlers` — filesystem, terminal, permission RPCs

The helpers receive the `_AcpSessionContext` and config references they need
via constructor injection.

**Pros:**
- Clear ownership boundaries
- Helpers are independently testable
- `AcpChatModel` becomes a thin coordinator

**Cons:**
- Helpers need access to `AcpChatModel` state (agent_config, workspace_root,
  permission_callback, etc.)
- Tight coupling between helper and model makes the abstraction leaky

**Option B3: Free-standing module functions (recommended)**

Extract methods as module-level async functions that receive the
`_AcpSessionContext` and any needed config as parameters. The
`AcpChatModel` methods become thin wrappers that call these functions.

Proposed module structure:

```
providers/
├── acp_chat_model.py     (slimmed: LangChain interface, _astream,
│                          _yield_chunks, public API, delegates to modules)
├── _acp_protocol.py      (JSON-RPC dispatch: _process_stdout_loop,
│                          _dispatch_packet, _handle_client_response)
├── _acp_rpc_handlers.py  (RPC handlers: permission, filesystem, terminal)
├── _acp_session.py       (session lifecycle: initialize, setup, auth,
│                          cleanup, _AcpSessionContext)
├── _subprocess.py         (unchanged)
├── acp_exceptions.py     (unchanged)
```

**Pros:**
- Functions are independently testable with a mock context
- No new classes or inheritance
- Clear import graph: `acp_chat_model` imports from `_acp_*` modules
- Module-level constants naturally live in the module that uses them
- Aligns with Python convention of functions over methods when no
  polymorphism is needed

**Cons:**
- Some functions need 4-5 parameters (ctx, agent_config, workspace_root,
  permission_callback, etc.)
- The `_AcpSessionContext` dataclass becomes the central state carrier

### Recommendation

**Option B3** — free-standing module functions. The parameter count is
manageable since `_AcpSessionContext` already carries most session state,
and configuration parameters like `agent_config` and `workspace_root` are
read-only during a session.

### Estimated line counts after split

| Module | Lines | Content |
|--------|-------|---------|
| `acp_chat_model.py` | ~550 | Fields, `_astream`, `_yield_chunks`, `_cleanup_session`, public API |
| `_acp_protocol.py` | ~200 | stdout loop, dispatch, client response, server RPC routing |
| `_acp_rpc_handlers.py` | ~500 | permission, fs read/write, terminal CRUD, session update, tool call |
| `_acp_session.py` | ~550 | Context dataclass, constants, initialize, setup, auth, prompt |

All modules under the 1,000-line mandate. `_acp_rpc_handlers.py` at ~500
lines has headroom; if terminal handlers grow, they can split further.

## Phase Ordering

| Phase | Track | What | Touches |
|-------|-------|------|---------|
| 1 | A | Extract shared HTTP helper (`_http.py`) | `protocols/mcp/` |
| 2 | A | Split handlers into `tools/` modules | `protocols/mcp/` |
| 3 | A | Slim `server.py` to registration only | `protocols/mcp/` |
| 4 | B | Extract `_acp_session.py` (context + lifecycle) | `providers/` |
| 5 | B | Extract `_acp_protocol.py` (JSON-RPC dispatch) | `providers/` |
| 6 | B | Extract `_acp_rpc_handlers.py` (RPC handlers) | `providers/` |
| 7 | B | Slim `acp_chat_model.py` to LangChain interface | `providers/` |

Tracks A and B are independent and can run in parallel. Within each
track, phases are sequential because later phases depend on earlier
extractions.

## Risk Assessment

- **Low risk:** Module splits are mechanical refactors — no behavior
  changes, no new dependencies, no infrastructure changes
- **MCP test coverage:** Existing MCP tests exercise the tool handlers via
  HTTP; after splitting, the same tests validate the new module structure
- **ACP test coverage:** ACP tests exercise `AcpChatModel._astream`;
  extracted functions are called by the same code paths
- **Import breakage:** Internal `_acp_*` modules are private (underscore
  prefix). Only `acp_chat_model.py` imports from them. External consumers
  import `AcpChatModel` from `providers/` — no public API change.
- **MCP `_http.py` helper:** Centralises error handling but does not change
  HTTP semantics. Existing tests cover all error branches.

## Validation Criteria

After all phases:

- No file in `protocols/mcp/` or `providers/` exceeds 1,000 lines
- `protocols/mcp/server.py` contains only FastMCP instance + tool
  registration (< 100 lines)
- `providers/acp_chat_model.py` contains only LangChain interface +
  public API (< 600 lines)
- Zero httpx imports in `protocols/mcp/tools/*.py` (all go through
  `_http.py`)
- `pytest -m core` >= 520 passed
- `pytest -m middleware` >= 574 passed
- Full suite >= 1,094 passed
- No boundary violations (Layer 1 clean, control/ does not import api/)
- MCP handlers still use HTTP loopback (architectural constraint preserved)
