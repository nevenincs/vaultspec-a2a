# Layer 2d — File-Size Violations + MCP Service Adoption — Handover

**GitHub repo:** wgergely/vaultspec-a2a
**GitHub Issue:** wgergely/vaultspec-a2a#12
**Prerequisite:** PR #11 (Layer 2c database rework + handler extraction) merged to `main`.
**Remote name:** `vaultspec-a2a` (NOT `origin`)
**Merge strategy:** Merge commits only. Squash and rebase are disabled.

## History

| PR | Layer | What it did | Status |
|----|-------|-------------|--------|
| #2 | Control layer | CLI/Justfile separation, `control/` package | MERGED |
| #3 | Layer 1 (core) | Decomposed monolithic `core/` into `thread/`, `context/`, `team/`, `graph/`, `streaming/`, `lifecycle/` | MERGED |
| #4 | Layer 2a (entry points) | Split `endpoints.py` into 8 route modules. Split `executor.py` into 3. Extracted `ipc/`, `control/` runtime modules | MERGED |
| #9 | Layer 2b (domain logic) | Extracted domain enums/transitions/snapshots to Layer 1. Split `crud.py`. Dependency-inverted `control/` → `api/` via Layer 1 dataclasses | MERGED |
| #11 | Layer 2c (database + handlers) | Renamed database modules to repository convention. Extracted 4 route handler orchestration flows to `control/` service functions. Decoupled `ipc/schemas.py` from settings | MERGED |
| **Next** | **Layer 2d** | **File-size violations + MCP service adoption** | **NOT STARTED** |

## What Layer 2c delivered

Layer 2c created 4 shared service functions in `control/` that encapsulate
the full orchestration for each domain operation:

- `control/thread_service.py` — `create_and_dispatch_thread()`
- `control/permission_service.py` — `respond_to_permission()`
- `control/message_service.py` — `send_followup_message()`
- `control/cancel_service.py` — `cancel_thread()`

Each service function:

- Receives `AsyncSession` from the caller (does NOT own commit)
- Returns a frozen result dataclass (does NOT raise HTTPException)
- Does NOT import from `api/`
- Uses `safe_dispatch()` from `control/dispatch.py` (no raw exception handling)
- Uses named repair-state transition functions from `control/repair_transitions.py`
- Receives `recursion_limit` as a parameter (no direct `settings` coupling)

The API route handlers (`api/routes/threads.py`, `permissions.py`, `messages.py`,
`cancel.py`) are now thin protocol translators: parse request, call service,
commit, adapt result to HTTP response.

**The MCP handlers do NOT use these service functions yet.** They still make
HTTP calls to the API's REST endpoints via `httpx.AsyncClient`. This means
thread creation, permission response, message send, and cancel have two
divergent code paths: the direct service path (API routes) and the HTTP
loopback path (MCP handlers).

## The problem: MCP handlers as HTTP proxies

`protocols/mcp/server.py` (1,045 lines) contains 11 MCP tool handlers that
implement the same operations as the API routes but via HTTP calls to
`settings.api_base_url`. For example, `start_thread` constructs an HTTP POST
to `/api/threads`, parses the JSON response, and reformats it as MCP tool
output. This is:

1. **Fragile** — changes to REST response shapes require updating both the
   route handler AND the MCP handler
2. **Slow** — every MCP operation makes a loopback HTTP call through the
   full middleware stack instead of calling the service directly
3. **Inconsistent** — error handling and retry logic diverge between the two
   code paths
4. **Thick** — each MCP handler is 60-140 lines of HTTP construction, response
   parsing, and error mapping

The fix: MCP handlers call the `control/` service functions directly, just
like the API route handlers do. They become thin MCP protocol translators.

## The problem: `acp_chat_model.py` at 1,821 lines

`providers/acp_chat_model.py` is 82% over the 1,000-line mandate. It contains
6 distinct responsibilities in a single class:

1. **ACP subprocess management** (~155L) — constants, capability mappings,
   `_AcpSessionContext`
2. **Streaming & message parsing** (~65L) — `_yield_chunks` AsyncIterator
3. **JSON-RPC protocol dispatch** (~85L) — `_process_stdout_loop`,
   `_dispatch_packet`, packet handlers
4. **Permission bridge** (~80L) — `_on_request_permission`, sandbox path
   handling
5. **Session lifecycle** (~410L) — `_initialize_session`, `_setup_session`,
   `_authenticate_rpc`, `_cleanup_session`
6. **Public API methods** (~130L) — `fork_session`, `list_sessions`,
   `set_mode`, `set_model`, `set_config_option`, `authenticate`

All sections are methods on the `AcpChatModel` class, so extraction requires
either mixin pattern or delegation to helper objects.

## Mandatory reading before starting

1. `src/vaultspec_a2a/README.md` — Living architecture doc (up to date as of
   Layer 2c)
2. `.vault/audit/2026-03-28-post-layer2c-boundary-audit.md` — Full boundary
   audit with outstanding items section
3. `.vault/adr/2026-03-28-database-layer-adr.md` — Layer 2c ADR for
   methodology reference
4. `src/vaultspec_a2a/protocols/mcp/server.py` — Current MCP server (the
   primary target)
5. `src/vaultspec_a2a/providers/acp_chat_model.py` — Current ACP model (the
   secondary target)
6. `src/vaultspec_a2a/control/thread_service.py` — Service function pattern
   to adopt in MCP handlers

## Rules (non-negotiable, learned from PRs #2-#11)

- No backwards-compat shims. Old import paths break loudly.
- No deferral. If the plan says decompose, decompose.
- Stay in scope. Define scope before starting.
- Modules over 1,000 lines must be split.
- No re-export shims. One canonical import path per symbol.
- Test for each phase. Preserve green test suite.
- No mocks, stubs, fakes, patches, skips.
- Commit after every phase. Push continuously.
- Merge commits only. Squash/rebase disabled.
- `ty` type checker uses `# ty: ignore[rule-name]` syntax. Lacks Pydantic
  plugin (astral-sh/ty#2403) — use `# ty: ignore[invalid-argument-type]`
  at Pydantic/Protocol call sites.
- No `# noqa` band-aids. Fix root causes.

## Suggested work plan

### Track A: MCP service adoption (priority)

1. MCP handlers currently use `httpx.AsyncClient` to call REST endpoints.
   They need to call `control/` service functions instead.
2. The MCP server runs in the same process as the API — it has direct access
   to the database session factory and all `control/` modules.
3. For each MCP tool handler that maps to a service function:
   - `start_thread` → `control.thread_service.create_and_dispatch_thread()`
   - `respond_to_permission` → `control.permission_service.respond_to_permission()`
   - `send_message` → `control.message_service.send_followup_message()`
   - `cancel_thread` → `control.cancel_service.cancel_thread()`
   - `delete_thread`, `archive_thread` — these are thin CRUD operations;
     call database functions directly (same pattern as API routes)
4. Read-only handlers (`list_threads`, `get_thread_status`, `get_team_status`,
   `get_pending_permissions`, `list_team_presets`) call database/control
   functions directly — no HTTP loopback needed.
5. The MCP server needs a database session. Currently it doesn't have one
   because it delegates to HTTP. After this change, it needs either:
   - Access to the session factory (call `get_session_factory()`)
   - Or a session-per-tool-call pattern
6. Split the 11 handlers into per-domain modules under `protocols/mcp/tools/`:
   - `thread_lifecycle.py` — start, cancel, delete, archive
   - `thread_status.py` — get_thread_status, list_threads
   - `messaging.py` — send_message, respond_to_permission
   - `discovery.py` — get_team_status, get_pending_permissions, list_team_presets
7. `protocols/mcp/server.py` becomes a thin registration module that imports
   handlers and registers them with the MCP server.

### Track B: ACP chat model decomposition

1. Split `acp_chat_model.py` into focused sub-modules under `providers/`:
   - `providers/acp_protocol.py` — JSON-RPC message types, packet dispatch,
     `_process_stdout_loop`, `_dispatch_packet`, `_handle_client_response`,
     `_handle_server_rpc`
   - `providers/acp_process.py` — subprocess management, `_AcpSessionContext`,
     process lifecycle, stdout/stderr handling
   - `providers/acp_chat_model.py` — slimmed to LangChain `BaseChatModel`
     interface, `_generate`, `_yield_chunks`, public API methods. Delegates
     to protocol and process modules.
2. Consider delegation pattern: `AcpChatModel` holds `_protocol: AcpProtocol`
   and `_process: AcpProcessManager` instances.
3. Permission bridge (`_on_request_permission`) stays with the chat model
   since it bridges LangGraph's interrupt mechanism.

## Test baseline targets

```bash
pytest -m core        → >= 520
pytest -m middleware   → >= 574
pytest                → >= 1,094
```

## Boundary validation commands

```bash
# Layer 1 must not import Layer 2+
grep -rn 'from.*api\.\|from.*cli\.\|from.*worker\.\|from.*database\.\|from.*providers\.\|from.*control\.' \
  src/vaultspec_a2a/thread/ src/vaultspec_a2a/context/ src/vaultspec_a2a/team/ \
  src/vaultspec_a2a/graph/ src/vaultspec_a2a/streaming/ src/vaultspec_a2a/lifecycle/ \
  --include='*.py' | grep -v '/tests/' | grep -v __pycache__

# control/ must not import from api/
grep -rn 'from.*api\.' src/vaultspec_a2a/control/ --include='*.py' \
  | grep -v tests/ | grep -v __pycache__

# No file over 1,000 lines (excluding tests)
find src/vaultspec_a2a -name '*.py' -not -path '*/tests/*' -exec wc -l {} + \
  | sort -rn | head -10

# MCP server should NOT use httpx for loopback (after Track A)
grep -rn 'httpx\|api_base_url' src/vaultspec_a2a/protocols/mcp/server.py \
  src/vaultspec_a2a/protocols/mcp/tools/ 2>/dev/null
```

## Scope boundary

Touches: `protocols/mcp/` (handler extraction + service adoption),
`providers/` (acp_chat_model decomposition).

Does NOT touch: Layer 1 (`thread/`, `context/`, `team/`, `graph/`,
`streaming/`, `lifecycle/`), `database/`, `api/routes/`, `control/`
(except possibly adding MCP-specific helpers), Layer 3 infrastructure.

## After this PR

- **Layer 3 infrastructure config** — Docker, compose, Justfile, `.dockerignore`,
  settings god-object reduction
- **Service layer** — the end goal. Once all entry points (API, MCP, CLI,
  worker) delegate to shared `control/` services through clean boundaries,
  the service lifecycle layer can be formalized: start/stop/health, registry,
  cross-service communication

## Process

Use the vaultspec framework: research → ADR → plan → execute → review. Run
the full boundary audit before starting research, and again after the final
phase to validate. Start with research.
