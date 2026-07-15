---
tags:
  - '#adr'
  - '#layer-2d'
date: '2026-03-28'
modified: '2026-07-15'
related:
  - '[[2026-03-28-layer2d-file-size-mcp-research]]'
  - '[[2026-03-28-post-layer2c-boundary-audit]]'
  - '[[2026-03-28-database-layer-adr]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
---

# `layer-2d` adr: `file-size-violations-mcp-handler-decomposition` | (**status:** `accepted`)

**Prerequisite:** PR #11 (Layer 2c database rework + handler extraction)
merged to `main`.

## Problem Statement

Two modules exceed the project's 1,000-line mandate:

- `providers/acp_chat_model.py` (1,821 lines, 82% over) — mixes 6
  responsibilities in a single class: ACP subprocess management, streaming,
  JSON-RPC protocol dispatch, permission bridge, session lifecycle, and
  public API methods.

- `protocols/mcp/server.py` (1,045 lines, 4.5% over) — 11 MCP tool
  handlers with 186 lines of duplicated httpx error-handling boilerplate
  (identical 4-branch try/except × 11 handlers).

Both were explicitly deferred from Layer 2c and tracked in the post-Layer
2c boundary audit.

## Considerations

- The MCP server is a **standalone process** (stdio/HTTP transport for IDE
  integrations like Cursor, Windsurf), NOT embedded in the FastAPI gateway.
  All 11 tool handlers communicate via HTTP loopback to
  `settings.gateway_url`. Direct service function adoption would require
  duplicating the entire gateway infrastructure (database, circuit breaker,
  worker spawner) in the MCP process — disproportionate complexity for no
  user-facing benefit. The HTTP loopback is preserved.

- The ACP chat model methods that move to free-standing functions access
  15+ read-only config attributes via `self` (provider identity, workspace
  root, agent config, command metadata, etc.) and mutable session state
  (`_tool_calls`, `_agent_modes`). A naive extraction would produce
  functions with 10+ parameters. Two structural decisions address this:
  a frozen `_AcpModelConfig` dataclass carries read-only config, and
  session-scoped mutables (`_tool_calls`, `_agent_modes`) move to
  `_AcpSessionContext`.

- `_runtime_log_extra()` is called in 9+ methods across all proposed
  modules. It reads 11 self attributes for structured logging. Keeping it
  on the class forces every extracted function to hold a reference to the
  model instance. Making it a free function that takes `_AcpModelConfig`
  plus optional overrides cleanly decouples it.

- `_setup_session` writes to 6 `PrivateAttr` fields on the class
  (`_active_session_id`, `_agent_modes`, `_tool_calls`, `_process`,
  `_stdin`, `_stdin_lock`, `_response_futures`). Rather than passing `self`
  to the extracted function, it returns a result dataclass that the class
  method unpacks. Same pattern for `_initialize_session` returning
  `(agent_capabilities, auth_methods)`.

- The MCP `_mcp_request()` helper must return parsed JSON (not formatted
  string) because 9 of 11 handlers do custom response parsing. The
  helper's scope is HTTP transport + exception mapping only. It accepts
  an optional `not_found_msg` for 404 handling and re-raises
  `HTTPStatusError` for other codes (e.g., 409 in `archive_thread`).

- `_get_known_presets()` has fundamentally different error semantics
  (catches all exceptions, falls back to empty frozenset with warning)
  and must NOT use the shared helper.

- `respond_to_permission` belongs with `get_pending_permissions` in the
  discovery module — they share the permission domain (discover pending
  requests, resolve them). Not in messaging (different endpoint, different
  concern).

- `send_message`'s `Field(max_length=settings.mcp_max_initial_message_chars)`
  is evaluated at import time. This is a pre-existing coupling, not
  introduced by the split. Acknowledged but not changed.

## Constraints

- Test baseline: `pytest -m core` >= 520, `pytest -m middleware` >= 574,
  full suite >= 1,094. Each phase must preserve a green suite.
- No backwards-compat re-export shims. Old import paths break loudly.
  Test imports must be updated to new module paths.
- No re-export hubs — one canonical import path per symbol.
- No file over 1,000 lines after completion.
- No mocks, stubs, fakes, patches, skips.
- Merge commits only. Squash/rebase disabled.
- Scope: `protocols/mcp/` (handler split), `providers/` (ACP
  decomposition). Does NOT touch Layer 1, `database/`, `api/routes/`,
  `control/`, Layer 3 infrastructure.

## Implementation

Seven architectural decisions organized into two independent tracks.

### Track A: MCP handler decomposition

**D-01: Extract shared httpx helper `_http.py`.**

Create `protocols/mcp/_http.py` containing:
- `_shared_client`, `_get_client()`, `_reset_client()` — shared httpx
  client lifecycle
- `_known_presets_cache`, `_get_known_presets()`,
  `_reset_known_presets()` — preset cache (separate from the helper,
  retains its own error semantics)
- HTTP constants (`_HTTP_OK`, `_HTTP_NOT_FOUND`, `_HTTP_CONFLICT`)
- `_mcp_request(method, path, *, json=None, params=None, timeout,
  not_found_msg=None)` — shared coroutine that:
  - Builds URL from `settings.gateway_url` + path
  - Makes the httpx call via `_get_client()`
  - Maps 4 exception branches to `ToolError` with credential-stripped
    gateway URL in error messages
  - On `HTTPStatusError`: if 404 and `not_found_msg` is provided,
    raises `ToolError(not_found_msg)`. Otherwise re-raises the
    `HTTPStatusError` for handler-specific processing (e.g., 409).
  - Returns `resp.json()` on success (parsed dict, not formatted string)
- `_get_known_presets()` does NOT use `_mcp_request()` — it has different
  error semantics (catch-all fallback to empty frozenset).

**D-02: Split 11 handlers into `protocols/mcp/tools/`.**

Create 4 tool modules grouped by domain:

- `tools/thread_lifecycle.py` — `start_thread`, `cancel_thread`,
  `delete_thread`, `archive_thread`
- `tools/thread_query.py` — `get_thread_status`, `list_threads`,
  `_ws_url_from_api_base` (used only by `get_thread_status`)
- `tools/messaging.py` — `send_message`
- `tools/discovery.py` — `get_team_status`, `get_pending_permissions`,
  `respond_to_permission`, `list_team_presets`

Each module imports `mcp` from `..server` and `_mcp_request` (plus
other helpers) from `.._http`. Each handler:
- Retains its `@mcp.tool()` decorator, Annotated field definitions, and
  docstrings
- Calls `_mcp_request()` for the HTTP transport
- Handles any non-standard status codes (409) itself
- Formats the JSON response into MCP tool output text

`respond_to_permission` groups with `discovery.py` because it shares
the permission domain with `get_pending_permissions` (discover → resolve
pair), not with `send_message`.

**D-03: Slim `server.py` to registration module.**

After extraction, `server.py` contains only:
- `FastMCP` instance creation with instructions string
- Side-effect imports to trigger `@mcp.tool()` registration:
  `from .tools import discovery, messaging, thread_lifecycle, thread_query`

Target: < 100 lines.

`__init__.py` continues to re-export `mcp` from `server`. `__main__.py`
unchanged.

### Track B: ACP chat model decomposition

**D-04: Extract `providers/_acp_session.py`.**

Contents:
- `_AcpSessionContext` dataclass (extended with `tool_calls: dict`,
  `agent_modes: dict`, and `last_auth_url: str | None` — session-scoped
  mutables moved off the class). Note: `_last_auth_url` also remains as
  a PrivateAttr on the class because the `authenticate()` public method
  is called outside `_astream` when no `ctx` exists. Both `ctx` and
  `self` are written during `_capture_auth_progress` — this dual-write
  is a pragmatic compromise documented during code review.
- `_AcpModelConfig` frozen dataclass — carries 15+ read-only config
  fields that extracted functions need: `agent_config`,
  `permission_callback`, `workspace_root`, `cwd`, `command`, `env_vars`,
  `session_id`, `mcp_servers`, `use_exec`, `provider`,
  `runtime_authority`, `acp_backend`, `command_origin`, `command_kind`,
  `command_executable`, `command_target`, `auth_mode`
- `runtime_log_extra(config, **overrides)` — free function replacing
  `self._runtime_log_extra()`, takes `_AcpModelConfig` + optional
  keyword overrides (process, handshake_step, timeout, etc.)
- `_log_task_exception()` callback
- `_AuthResponseCancelledError` sentinel
- Session lifecycle functions (all receive `ctx: _AcpSessionContext` and
  `config: _AcpModelConfig`):
  - `initialize_session(ctx, config)` → returns
    `(agent_capabilities, auth_methods)` result tuple
  - `setup_session(ctx, config, agent_capabilities, auth_methods)` →
    returns `SessionSetupResult` frozen dataclass (session_id,
    agent_modes). Process, stdin, stdin_lock, and response_futures
    are read from `ctx` by the caller (already set during setup)
  - `authenticate_rpc(ctx, config, env, ...)` → returns auth result dict
  - `wait_for_authenticate_response(...)` → returns response dict
  - `setup_prompt(ctx, config, blocks, active_session_id)` → returns
    Future
  - `send_notification(ctx, method, params)` → None
- Auth helpers as free functions: `auth_hint(config)`,
  `select_auth_method_id(auth_methods, env, auth_mode)`,
  `is_auth_required_error(error)`, `is_auth_cancelled_error(error)`,
  `is_auth_rejected_error(error)`, `raise_auth_outcome_error(...)`

**D-05: Extract `providers/_acp_protocol.py`.**

Contents:
- `_CAPABILITY_REQUIREMENTS` constant (used by `handle_server_rpc`)
- `process_stdout_loop(ctx)` — reads stdout, dispatches packets
- `dispatch_packet(data, ctx, config, rpc_handlers)` — routes responses
  vs server RPCs vs notifications
- `handle_client_response(data, ctx)` — resolves response futures,
  detects end_turn
- `handle_server_rpc(method, rpc_id, params, ctx, config, rpc_handlers)`
  — capability check using `config.agent_config`, dispatches to handler
  functions from `_acp_rpc_handlers`
- `handle_session_update(params, ctx)` — dispatches session update
  notifications
- `on_tool_call(update, ctx)` — writes to `ctx.tool_calls`
- `on_tool_call_update(update, ctx)` — writes to `ctx.tool_calls`

Import direction: `_acp_protocol` does NOT import from
`_acp_rpc_handlers`. Instead, `acp_chat_model.py` builds an
`rpc_handler_map` dict from `_acp_rpc_handlers` functions and passes
it to `process_stdout_loop` as a parameter. This avoids any circular
dependency between protocol and handler modules.

**D-06: Extract `providers/_acp_rpc_handlers.py`.**

Contents:
- `_TERMINAL_COMMAND_ALLOWLIST`, `_SHELL_METACHAR_RE`, `_ENV_NAME_RE`
  constants (placed next to their consumers)
- `sandbox_path(path, config)` — workspace sandboxing
- `on_request_permission(rpc_id, params, ctx, config)` — permission
  bridge (uses `config.permission_callback`, `config.agent_config`)
- `on_fs_read_text_file(rpc_id, params, config)` — file read with
  sandbox
- `on_fs_write_text_file(rpc_id, params, config)` — file write with
  git mutex
- `on_terminal_create(rpc_id, params, ctx, config)` — terminal spawn
  with allowlist + sandbox validation
- `on_terminal_kill(rpc_id, params, ctx)` — terminal kill
- `on_terminal_output(rpc_id, params, ctx)` — terminal output read
- `on_terminal_wait_for_exit(rpc_id, params, ctx)` — terminal wait
- `on_terminal_release(rpc_id, params, ctx)` — terminal cleanup

All functions receive `ctx` and/or `config` as parameters. No `self`
access.

**D-07: Slim `acp_chat_model.py` to LangChain interface.**

Remaining contents:
- Pydantic field definitions (~120L)
- `model_post_init` — builds `_AcpModelConfig` from fields
- `_astream` — spawns process, creates `ctx`, calls session lifecycle
  functions from `_acp_session`, creates stdout/stderr tasks with
  functions from `_acp_protocol`, yields chunks (~80L)
- `_yield_chunks` (~55L)
- `_cleanup_session` — kills terminals, cancels tasks, kills process
  (~58L)
- `_agenerate`, `_generate` (~25L)
- `_read_stderr_loop`, `_capture_auth_progress` (~45L)
- Property methods, `_require_*` helpers (~15L)
- Public API methods: `fork_session`, `list_sessions`, `set_mode`,
  `set_model`, `set_config_option` (~100L)
- `authenticate` — calls `authenticate_rpc()` from `_acp_session` (~20L)

`_setup_session` return value is unpacked into `PrivateAttr` fields:
```python
result = await setup_session(ctx, self._config, caps, auth_methods)
self._active_session_id = result.session_id
self._process = ctx.process
self._stdin = ctx.stdin
self._stdin_lock = ctx.stdin_lock
self._response_futures = ctx.response_futures
```

Target: ~550-590 lines.

## Phase Order

| Phase | Decisions | Packages touched |
|-------|-----------|-----------------|
| 1 | D-01 | `protocols/mcp/` (new `_http.py`) |
| 2 | D-02, D-03 | `protocols/mcp/` (new `tools/`, slim `server.py`) |
| 3 | D-04 | `providers/` (new `_acp_session.py`) |
| 4 | D-05 | `providers/` (new `_acp_protocol.py`) |
| 5 | D-06 | `providers/` (new `_acp_rpc_handlers.py`) |
| 6 | D-07 | `providers/acp_chat_model.py` (slim) |

Tracks A (phases 1-2) and B (phases 3-6) are independent and can run
in parallel. Within each track, phases are sequential.

**Test migration:** Each phase updates affected test imports to new
module paths. No re-export shims from old paths.

## Rationale

This ADR continues the layer isolation roadmap from PRs #2-#11. The
two file-size violations are the last outstanding items from the
post-Layer 2c boundary audit (excluding the settings god-object, which
is a Layer 3 concern).

Track A is a mechanical split — no behavior changes, no new
dependencies, no architecture changes. The HTTP loopback is preserved
because the MCP server's standalone process model is a deliberate
architectural choice that enables stdio transport for IDE integrations.
Service function adoption is deferred to a future decision about
gateway embedding.

Track B addresses a deeper structural problem: a 1,821-line class with
6 interleaved responsibilities. The `_AcpModelConfig` frozen dataclass
cleanly separates read-only config from mutable session state, enabling
free-standing functions without 10+ parameter lists. Session-scoped
mutables (`_tool_calls`, `_agent_modes`) move to `_AcpSessionContext`
where they belong. Session lifecycle functions return result dataclasses
rather than writing to class `PrivateAttr` fields, making the data flow
explicit.

## Consequences

- `protocols/mcp/server.py` shrinks from 1,045 to ~80 lines. Four new
  tool modules under `tools/` at ~120-200 lines each. One new `_http.py`
  at ~100 lines.

- `providers/acp_chat_model.py` shrinks from 1,821 to ~550-590 lines.
  Three new private modules at ~200-550 lines each. One new frozen
  dataclass (`_AcpModelConfig`) and one extended dataclass
  (`_AcpSessionContext` gains `tool_calls` and `agent_modes` fields).

- External consumers are unaffected: `AcpChatModel` is still imported
  from `providers/`, `mcp` is still imported from `protocols/mcp/server`.

- Test imports must be updated in both tracks. No re-export shims.

- MCP HTTP loopback preserved. Service function adoption is a separate
  future decision.

- The settings god-object footprint is unchanged. Tracked for Layer 3.

## Validation Criteria

After all phases:

- No file in `protocols/mcp/` or `providers/` exceeds 1,000 lines
- `protocols/mcp/server.py` < 100 lines (FastMCP + registration only)
- `providers/acp_chat_model.py` < 600 lines
- Zero `httpx` imports in `protocols/mcp/tools/*.py` (all via `_http.py`)
- Zero `self._runtime_log_extra` calls in extracted `_acp_*.py` modules
  (use free function `runtime_log_extra(config, ...)`)
- `_AcpSessionContext` carries `tool_calls` and `agent_modes` (not class
  PrivateAttrs)
- `_setup_session` and `_initialize_session` return result
  dataclasses (no writes to class PrivateAttrs from extracted functions)
- `control/` has zero imports from `api/`
- Layer 1 has zero imports from Layer 2+
- `pytest -m core` >= 520 passed
- `pytest -m middleware` >= 574 passed
- Full suite >= 1,094 passed
