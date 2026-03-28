---
tags:
  - '#plan'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-adr]]'
  - '[[2026-03-28-layer2d-file-size-mcp-research]]'
  - '[[2026-03-28-post-layer2c-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `layer-2d` implementation plan — **STATUS: COMPLETE**

Break up the two remaining file-size violations identified in the
post-Layer 2c boundary audit: `protocols/mcp/server.py` (1,045 lines)
and `providers/acp_chat_model.py` (1,821 lines). Implements ADR
decisions D-01 through D-07 across two independent tracks.

## Proposed Changes

**Track A (MCP handler decomposition):** Extract shared HTTP helper,
split 11 tool handlers into domain-grouped modules, slim `server.py`
to a registration stub. Per ADR D-01/D-02/D-03.

**Track B (ACP chat model decomposition):** Introduce `_AcpModelConfig`
frozen dataclass and extend `_AcpSessionContext` with session-scoped
mutables. Extract session lifecycle, JSON-RPC protocol dispatch, and
RPC handlers into free-standing module functions. Slim
`acp_chat_model.py` to LangChain interface. Per ADR D-04/D-05/D-06/D-07.

## Tasks

- **Phase 1 — MCP shared HTTP helper (ADR D-01)**
  1. Create `protocols/mcp/_http.py` with:
     - `logger = logging.getLogger(__name__)` (needed by
       `_get_known_presets` warning log)
     - Shared httpx client lifecycle: `_shared_client`, `_get_client()`,
       `_reset_client()`
     - HTTP constants: `_HTTP_OK`, `_HTTP_NOT_FOUND`, `_HTTP_CONFLICT`
     - Preset cache: `_known_presets_cache`, `_get_known_presets()`,
       `_reset_known_presets()` (retains its own catch-all error semantics,
       does NOT use `_mcp_request`)
  1. Implement `_mcp_request(method, path, *, json=None, params=None,
     timeout, not_found_msg=None)` coroutine:
     - Build URL from `settings.gateway_url` + path
     - Call via `_get_client().request(method, url, json=json,
       params=params, timeout=timeout)` to support GET/POST/DELETE
     - Map 4 httpx exception branches to `ToolError` with
       credential-stripped gateway URL in error messages
     - On `HTTPStatusError`: if 404 and `not_found_msg` is provided,
       raise `ToolError(not_found_msg)`. Otherwise re-raise the
       `HTTPStatusError` for handler-specific processing (e.g., 409)
     - Return `resp.json()` on success (parsed dict)
  1. Add credential-stripping utility for `gateway_url` in error messages
     (reuse logic from `_ws_url_from_api_base` — strip userinfo from
     netloc)
  1. Remove moved symbols from `server.py` (client, cache, constants).
     Verify `server.py` still imports from `_http` and functions correctly
  1. Run `pytest -m middleware` — green suite required before proceeding

- **Phase 2 — MCP handler split + server slim (ADR D-02, D-03)**
  1. Create `protocols/mcp/tools/__init__.py` (empty)
  1. Create `protocols/mcp/tools/thread_lifecycle.py`: move `start_thread`,
     `cancel_thread`, `delete_thread`, `archive_thread`. Each handler
     imports `mcp` from `..server` and `_mcp_request`/`_get_known_presets`
     from `.._http`. Replace inline httpx try/except with `_mcp_request()`
     calls. `archive_thread` retains its 409-specific handling after
     catching re-raised `HTTPStatusError`. `start_thread` retains
     pre-HTTP validation (message length, preset check).
     **Settings imports needed:** `settings.mcp_max_initial_message_chars`
     (message length validation), `settings.mcp_create_timeout_seconds`
     (passed to `_mcp_request`), `settings.gateway_url` (embedded in
     response text: `f"Monitor: {settings.gateway_url}/\n"`)
  1. Create `protocols/mcp/tools/thread_query.py`: move `get_thread_status`,
     `list_threads`, `_ws_url_from_api_base`. Replace httpx boilerplate
     with `_mcp_request()` calls.
     **Settings imports needed:** `settings.gateway_url` (for
     `_ws_url_from_api_base` in `get_thread_status`),
     `settings.mcp_preview_truncate_len` (message preview truncation)
  1. Create `protocols/mcp/tools/messaging.py`: move `send_message`.
     Replace httpx boilerplate with `_mcp_request()` call.
     **Settings imports needed:** `settings.mcp_max_initial_message_chars`
     (in `Field(max_length=...)` — evaluated at import time, pre-existing
     coupling, acknowledged but not changed)
  1. Create `protocols/mcp/tools/discovery.py`: move `get_team_status`,
     `get_pending_permissions`, `respond_to_permission`,
     `list_team_presets`. Replace httpx boilerplate with `_mcp_request()`
     calls. **No direct `settings` imports needed** — all settings access
     goes through `_mcp_request`
  1. Slim `server.py` to: FastMCP instance creation with instructions
     string + side-effect registration imports
     (`from .tools import discovery, messaging, thread_lifecycle, thread_query`).
     `mcp = FastMCP(...)` must be defined BEFORE the `from .tools` imports
     so tool modules can import the `mcp` object. `__all__ = ["mcp"]`
     unchanged. Target < 100 lines
  1. Update `protocols/mcp/tests/test_server.py` imports — 14 import
     sites total (13 top-level at lines 46-60 + 1 inline at line 824):
     - `_reset_client`, `_reset_known_presets` → from `.._http`
     - `_ws_url_from_api_base` → from `..tools.thread_query`
     - `start_thread`, `cancel_thread`, `delete_thread`, `archive_thread`
       → from `..tools.thread_lifecycle`
     - `get_thread_status`, `list_threads` → from `..tools.thread_query`
     - `send_message` → from `..tools.messaging`
     - `respond_to_permission`, `get_team_status`,
       `get_pending_permissions`, `list_team_presets` → from
       `..tools.discovery`
     - Inline import at line 824: `_get_known_presets` → from `.._http`.
       Also update the `sys.modules` manipulation in that test to target
       the `_http` module namespace instead of `server`
     - Autouse `_reset_shared_state` fixture: imports from `.._http`
  1. Update `tests/test_mcp_e2e_live.py` if it imports from
     `protocols.mcp.server` directly
  1. `__init__.py` continues to re-export `mcp` from `server` — unchanged.
     `__main__.py` unchanged
  1. Run `pytest -m middleware` — green suite required
  1. Run `wc -l` on all files in `protocols/mcp/` — verify all under
     1,000 lines and `server.py` < 100 lines
  1. Verify zero `httpx` imports in `protocols/mcp/tools/*.py` — all HTTP
     goes through `_http.py`
  1. Commit Track A

- **Phase 3 — ACP session + config extraction (ADR D-04)**
  1. Create `providers/_acp_session.py`. Define `_AcpModelConfig` frozen
     dataclass with all 17 read-only config fields: `agent_config`,
     `permission_callback`, `workspace_root`, `cwd`, `command`,
     `env_vars`, `session_id`, `mcp_servers`, `use_exec`, `provider`,
     `runtime_authority`, `acp_backend`, `command_origin`, `command_kind`,
     `command_executable`, `command_target`, `auth_mode`
  1. Move `_AcpSessionContext` dataclass from `acp_chat_model.py` to
     `_acp_session.py`. Add three new fields:
     - `tool_calls: dict[str, Any]` (default `dict`)
     - `agent_modes: dict[str, Any]` (default `dict`)
     - `last_auth_url: str | None` (default `None`)
     Remove `_tool_calls`, `_agent_modes`, and `_last_auth_url` from
     `AcpChatModel` `PrivateAttr` declarations. `_auth_methods` stays
     as a PrivateAttr on the class (needed for `authenticate()` public
     method and direct test access)
  1. Implement `runtime_log_extra(config, **overrides)` free function
     replacing `self._runtime_log_extra()`. Takes `_AcpModelConfig` plus
     optional keyword args (process, handshake_step, timeout_seconds,
     session_id, stderr_event_count, exit_code, kill_strategy)
  1. Move `_log_task_exception()` and `_AuthResponseCancelledError` to
     `_acp_session.py`
  1. Extract session lifecycle functions to `_acp_session.py`:
     - `initialize_session(ctx, config)` → returns
       `InitializeResult(agent_capabilities, auth_methods)` frozen
       dataclass
     - `setup_session(ctx, config, agent_capabilities, auth_methods)` →
       returns `SessionSetupResult(session_id, agent_modes, process,
       stdin, stdin_lock, response_futures)` frozen dataclass. Writes
       session-scoped state to `ctx` internally (tool_calls, agent_modes).
       The caller unpacks model-level state from the result
     - `authenticate_rpc(ctx, config, env, *, auth_methods, stdin,
       stdin_lock, response_futures, process=None,
       stderr_event_count=None, auth_url=None)` → returns auth result
       dict. Receives `auth_methods` explicitly (not from self)
     - `wait_for_authenticate_response(*, response_future, process,
       timeout_seconds)` → returns response dict
     - `setup_prompt(ctx, config, blocks)` → returns Future
     - `send_notification(ctx, method, params)` → None
  1. Extract auth helpers as free functions:
     - `auth_hint(config)` — provider-specific auth hint
     - `auth_url_hint(auth_url, last_auth_url)` — browser-auth URL hint
       (was `self._auth_url_hint`, reads `_last_auth_url`)
     - `select_auth_method_id(auth_methods, env)` — best auth method
     - `is_auth_required_error(error)` — static check
     - `is_auth_cancelled_error(error)` — static check
     - `is_auth_rejected_error(error)` — static check
     - `raise_auth_outcome_error(*, message, code, auth_outcome,
       auth_url=None, last_auth_url=None)` — raises `AcpAuthError`
  1. Update `acp_chat_model.py`:
     - Add `model_post_init` logic to build `self._config: _AcpModelConfig`
       from Pydantic fields (new PrivateAttr)
     - Update `_astream`: create `_AcpSessionContext` with
       `tool_calls={}`, `agent_modes={}`, `last_auth_url=None`
     - Replace `self._initialize_session(ctx)` with
       `init_result = await initialize_session(ctx, self._config)`;
       store `self._auth_methods = init_result.auth_methods`
     - Replace `self._setup_session(ctx)` with
       `result = await setup_session(ctx, self._config, init_result.agent_capabilities, init_result.auth_methods)`;
       unpack into PrivateAttrs: `self._active_session_id = result.session_id`,
       `self._process = ctx.process`, `self._stdin = ctx.stdin`,
       `self._stdin_lock = ctx.stdin_lock`,
       `self._response_futures = ctx.response_futures`
     - Replace `self._setup_prompt(blocks, ctx)` with
       `await setup_prompt(ctx, self._config, blocks)`
  1. Update `providers/tests/test_acp_chat_model.py`:
     - Change `_AcpSessionContext` import from `..acp_chat_model` to
       `.._acp_session`
     - Tests that set `model._auth_methods` directly continue to work
       (`_auth_methods` stays as PrivateAttr)
     - Tests that call `model._authenticate_rpc(...)` or
       `model._wait_for_authenticate_response(...)` as instance methods
       must be rewritten to call free functions from `_acp_session` with
       appropriate `ctx`/`config` parameters
     - Tests for `_auth_hint`, `_auth_url_hint`, `_select_auth_method_id`,
       `_is_auth_required_error` etc. must be updated to call the free
       function equivalents
  1. Run `pytest -m middleware` — green suite required before proceeding

- **Phase 4 — ACP protocol dispatch extraction (ADR D-05)**
  1. Create `providers/_acp_protocol.py`. Move `_CAPABILITY_REQUIREMENTS`
     constant
  1. Extract `process_stdout_loop(ctx, config, rpc_handler_map)` — the
     readline loop with JSON parsing and dispatch. Receives a handler map
     dict parameter built by the caller to avoid circular imports
     (`_acp_protocol` does NOT import from `_acp_rpc_handlers`)
  1. Extract `dispatch_packet(data, ctx, config, rpc_handler_map)` —
     routes responses vs server RPCs vs notifications
  1. Extract `handle_client_response(data, ctx)` — resolves response
     futures, detects end_turn, enqueues error sentinels
  1. Extract `handle_server_rpc(method, rpc_id, params, ctx, config,
     rpc_handler_map)` — capability check using `config.agent_config`,
     dispatches to handler functions via the map, writes JSON-RPC response
     to `ctx.stdin`
  1. Extract `handle_session_update(params, ctx)` — dispatches all
     session update notification types:
     - `agent_message_chunk` / `agent_thought_chunk` → enqueue text chunk
     - `tool_call_chunk` → enqueue streaming tool call chunk (stays inline)
     - `tool_call` → `on_tool_call(update, ctx)` (extracted alongside)
     - `tool_call_update` → `on_tool_call_update(update, ctx)` (extracted)
     - `current_mode_update` → writes to `ctx.agent_modes["currentModeId"]`
     - `available_commands_update` → writes to
       `ctx.agent_modes["availableCommands"]`
     - `plan` → debug log only
     All writes go to `ctx.tool_calls` / `ctx.agent_modes` (not self)
  1. Update `acp_chat_model.py`: replace
     `asyncio.create_task(self._process_stdout_loop(ctx))` with
     `asyncio.create_task(process_stdout_loop(ctx, self._config, rpc_map))`.
     Build `rpc_map` dict in `_astream` mapping method names to handler
     functions imported from `_acp_rpc_handlers`:
     ```
     rpc_map = {
         "session/request_permission": on_request_permission,
         "fs/read_text_file": on_fs_read_text_file,
         ...
     }
     ```
  1. Run `pytest -m middleware` — green suite required

- **Phase 5 — ACP RPC handler extraction (ADR D-06)**
  1. Create `providers/_acp_rpc_handlers.py`. Move constants next to
     their consumers:
     - `_TERMINAL_COMMAND_ALLOWLIST` (used by `on_terminal_create`)
     - `_SHELL_METACHAR_RE` (used by `on_terminal_create`)
     - `_ENV_NAME_RE` (used by `on_terminal_create`)
  1. Extract `sandbox_path(path, config)` — uses
     `config.workspace_root` / `config.cwd`
  1. Extract `on_request_permission(rpc_id, params, ctx, config)` — uses
     `config.permission_callback` and `config.agent_config`. Accesses
     `ctx.interrupt_exc` and `ctx.chunk_queue`
  1. Extract filesystem handlers:
     - `on_fs_read_text_file(rpc_id, params, config)` — uses
       `sandbox_path(config)` and `settings.acp_fs_read_max_bytes`
       (direct `settings` import needed in this module)
     - `on_fs_write_text_file(rpc_id, params, config)` — uses
       `sandbox_path(config)` and imports `_git_mutex` from
       `..workspace.git_manager`
  1. Extract terminal handlers:
     - `on_terminal_create(rpc_id, params, ctx, config)` — uses
       `sandbox_path`, allowlist/metachar constants, and imports
       `resolve_env_vars` from `..workspace.environment`
     - `on_terminal_kill(rpc_id, params, ctx)`
     - `on_terminal_output(rpc_id, params, ctx)`
     - `on_terminal_wait_for_exit(rpc_id, params, ctx)`
     - `on_terminal_release(rpc_id, params, ctx)`
  1. Update `providers/tests/test_acp_security.py`: change imports of
     `_ENV_NAME_RE`, `_SHELL_METACHAR_RE`, `_TERMINAL_COMMAND_ALLOWLIST`
     from `..acp_chat_model` to `.._acp_rpc_handlers`. `AcpChatModel`
     import stays unchanged
  1. Run `pytest -m middleware` — green suite required

- **Phase 6 — Slim AcpChatModel (ADR D-07)**
  1. Remove all methods and constants that have been extracted in phases
     3-5 from `acp_chat_model.py`. Verify only the LangChain interface
     remains: field definitions, `model_post_init`, `_astream`,
     `_yield_chunks`, `_cleanup_session`, `_agenerate`, `_generate`,
     `_read_stderr_loop`, `_capture_auth_progress`, property methods,
     `_require_*` helpers, and public API methods (`fork_session`,
     `list_sessions`, `set_mode`, `set_model`, `set_config_option`,
     `authenticate`)
  1. Update ALL `self._runtime_log_extra(...)` calls remaining in the
     class to `runtime_log_extra(self._config, ...)`:
     - `_astream` (~1 call site, spawn metadata)
     - `_yield_chunks` (~1 call site, warning log)
     - `_cleanup_session` (~1 call site, kill metadata)
     - `_read_stderr_loop` (~1 call site, debug log)
     - `_capture_auth_progress` (~2 call sites, info logs)
     Remove the `_runtime_log_extra` method from the class entirely
  1. Update `_capture_auth_progress` to write `ctx.last_auth_url`
     instead of `self._last_auth_url`. This requires `ctx` to be
     accessible — pass it as a parameter or capture via closure
  1. Verify `authenticate()` calls `authenticate_rpc()` from
     `_acp_session` with explicit parameters: `ctx=None` (not available
     outside `_astream`), uses `self._require_stdin()`,
     `self._stdin_lock`, `self._require_response_futures()`,
     `self._auth_methods`, `self._process`, `self._last_auth_url` (read
     from model PrivateAttr if not in active `_astream` call)
  1. Verify `_cleanup_session` resets `ctx.tool_calls = {}` and
     `ctx.agent_modes = {}` (intentional consistent cleanup — current
     code only resets `_tool_calls`, adding `agent_modes` reset is
     deliberate new behavior for consistency)
  1. Update `graph/tests/nodes/test_worker_integration.py` if it imports
     internals (currently imports `AcpChatModel` only — should be fine)
  1. Run full boundary validation:
     - `wc -l` on all files in `providers/` — all under 1,000 lines,
       `acp_chat_model.py` < 600 lines
     - Zero `self._runtime_log_extra` calls in `_acp_*.py` modules AND
       in `acp_chat_model.py` (fully replaced by free function)
     - `_AcpSessionContext` has `tool_calls`, `agent_modes`, and
       `last_auth_url` fields
     - Zero `self._tool_calls` or `self._agent_modes` on `AcpChatModel`
  1. Run `pytest -m core` — >= 520 passed
  1. Run `pytest -m middleware` — >= 574 passed
  1. Run full `pytest` — >= 1,094 passed
  1. Commit Track B

- **Phase 7 — Final boundary audit + README update**
  1. Run full boundary validation commands:
     - Layer 1 imports nothing from Layer 2+
     - `control/` has zero imports from `api/`
     - No file over 1,000 lines in `src/vaultspec_a2a/` (excluding tests)
     - Zero `httpx` imports in `protocols/mcp/tools/*.py`
     - MCP `server.py` < 100 lines
     - ACP `acp_chat_model.py` < 600 lines
  1. Update `src/vaultspec_a2a/README.md` architecture doc: update the
     `protocols/` section to reflect new `tools/` sub-package and
     `_http.py`. Update the `providers/` section to reflect new
     `_acp_session.py`, `_acp_protocol.py`, `_acp_rpc_handlers.py`.
     Update line counts
  1. Persist boundary audit to
     `.vault/audit/2026-03-28-post-layer2d-boundary-audit.md`
  1. Final commit

## Parallelization

Tracks A (phases 1-2) and B (phases 3-6) are fully independent — they
touch different packages (`protocols/mcp/` vs `providers/`) with zero
shared code. They can run as parallel sub-agents.

Within each track, phases are strictly sequential: each phase depends
on the prior phase's extractions being in place.

Phase 7 (final audit + README) depends on both tracks completing.

## Verification

**Automated verification:**
- `pytest -m core` >= 520 tests passed (Layer 1 unaffected)
- `pytest -m middleware` >= 574 tests passed (both tracks)
- Full `pytest` >= 1,094 tests passed
- Pre-commit hooks pass on all modified files (ruff, ty)

**Structural verification (boundary commands):**
- `grep -rn` Layer 1 → Layer 2+ imports = zero matches
- `grep -rn` control/ → api/ imports = zero matches
- `grep -rn httpx` in `protocols/mcp/tools/` = zero matches
- `grep -rn 'self._runtime_log_extra'` in ALL `providers/*.py` = zero
  (fully replaced by free function everywhere)
- `wc -l` on every touched `.py` file < 1,000 lines
- `protocols/mcp/server.py` < 100 lines
- `providers/acp_chat_model.py` < 600 lines

**Manual verification:**
- No backwards-compat re-export shims exist (old import paths break)
- `_AcpModelConfig` is frozen (immutable during session)
- `_AcpSessionContext` carries `tool_calls`, `agent_modes`, `last_auth_url`
- `_setup_session` and `_initialize_session` return result dataclasses
- `_auth_methods` stays as PrivateAttr on class (for `authenticate()`
  and test access)
- All test imports updated to canonical new paths
- External consumers (`AcpChatModel` from `providers/`, `mcp` from
  `protocols/mcp/server`) unchanged

**Honest assessment:** This is a mechanical refactor — no behavior changes
except the intentional addition of `ctx.agent_modes = {}` reset in
`_cleanup_session` (currently only `_tool_calls` is reset). The test
suite is the primary safety net. The risk is in import path breakage
and subtle state-flow errors in Track B where `self`-bound methods
become free functions. The boundary validation commands catch import
violations but cannot catch semantic errors in the
`_AcpModelConfig`/`_AcpSessionContext` state flow. The existing ACP
integration tests (`test_acp_chat_model.py`) exercise the full
`_astream` → session lifecycle → chunk yield path and will catch most
regressions. Track B auth-related tests (8+ test functions) require
the most careful migration due to the instance-method-to-free-function
conversion.
