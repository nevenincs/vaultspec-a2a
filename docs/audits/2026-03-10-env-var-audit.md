# Environment Variable Audit — Living Document

**Created:** 2026-03-10
**Last updated:** 2026-03-10 (cycle 2 — full constants + env bypass scan)
**Status:** ACTIVE — update on every audit cycle

**Policy (non-negotiable):**

- `Settings` is the single authoritative source for all configuration. Direct `os.environ` reads in app code are bugs.
- No re-declarations. Call `settings.x` directly — no intermediate `_CONST = settings.x`.
- No legacy aliasing. Every variable has exactly one canonical name.
- Every operator-tunable constant must be a `VAULTSPEC_`-prefixed `Settings` field with a documented default.
- `.env.example` must document every variable the project supports.

---

## DRIFT REGISTER

### D-01 — `VAULTSPEC_AUTO_MIGRATE` orphaned in `.env.example`

**File:** `.env.example`
**Status:** 🔧 FIXED this cycle — `VAULTSPEC_AUTO_MIGRATE=true` line deleted; no Settings field or code reference exists.

---

### D-02 — `INTERNAL_TOKEN` bare alias (legacy)

**File:** `core/config.py`
**Status:** 🔧 FIXED this cycle — `AliasChoices("VAULTSPEC_INTERNAL_TOKEN", "INTERNAL_TOKEN")` → single alias `VAULTSPEC_INTERNAL_TOKEN`

---

### D-03 — `LANGCHAIN_*` legacy aliases throughout Settings and code

**Files:** `core/config.py`, `telemetry/instrumentation.py`, `utils/trace.py`
**Status:** 🔧 FIXED this cycle

- Removed `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_ENDPOINT` aliases from Settings
- `telemetry/instrumentation.py`: `LANGCHAIN_TRACING_V2` → `LANGSMITH_TRACING`, `LANGCHAIN_PROJECT` → `LANGSMITH_PROJECT`
- `utils/trace.py`: all LANGCHAIN_ fallbacks removed

---

### D-04 — `VAULTSPEC_*` secondary aliases on provider API keys (legacy)

**File:** `core/config.py`
**Status:** 🔧 FIXED this cycle — removed `VAULTSPEC_ANTHROPIC_API_KEY`, `VAULTSPEC_OPENAI_API_KEY`, `VAULTSPEC_GEMINI_API_KEY`, `VAULTSPEC_GOOGLE_API_KEY`, `VAULTSPEC_ZHIPU_API_KEY`, `VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN`. Bare ecosystem names are canonical.

---

### D-05 — `VAULTSPEC_UI_BUILD_DIR` naked `os.environ` read

**File:** `api/app.py`
**Status:** 🔧 FIXED this cycle — added `Settings.ui_build_dir` field; all `_UI_BUILD_DIR` re-declarations replaced with `settings.ui_build_dir`

---

### D-06 — `VAULTSPEC_PROJECT_ROOT` naked `os.environ` read

**File:** `providers/factory.py`
**Status:** 🔧 FIXED this cycle — added `Settings.project_root` field; `_PROJECT_ROOT` module-level re-declaration removed; `settings.project_root` used inline. Unused `os` import removed.

---

### D-07 — `MOCK_API_BASE` naked `os.environ` read

**File:** `providers/mock_chat_model.py`
**Status:** 🔧 FIXED this cycle — added `Settings.mock_api_base` field; `os.environ.get("MOCK_API_BASE")` replaced with `settings.mock_api_base`. Unused `os` import removed.

---

### D-08 — `VAULTSPEC_PORT/WORKER_PORT/WORKER_URL` naked reads in logging statement

**File:** `api/app.py:444-446`
**Status:** 🔧 FIXED this cycle — replaced `os.environ.get("VAULTSPEC_PORT")` etc. with `settings.port`, `settings.worker_port`, `settings.worker_url`

---

### D-09 — `utils/trace.py` still reads `LANGSMITH_*` via `os.environ`

**File:** `utils/trace.py`
**Status:** 🔧 FIXED this cycle — all `os.environ.get("LANGSMITH_*")` reads replaced with `settings.langsmith_api_key`, `settings.langsmith_tracing`, `settings.langsmith_project`; unused `import os` removed.

---

### D-10 — `_WORKER_HEARTBEAT_TIMEOUT = 90.0` hardcoded constant

**File:** `api/app.py`
**Status:** 🔧 FIXED this cycle — removed; `settings.worker_heartbeat_timeout_seconds` used inline.

---

### D-11 — Circuit breaker thresholds hardcoded

**File:** `api/app.py`
**Status:** 🔧 FIXED this cycle — removed `_CB_FAILURE_THRESHOLD`, `_CB_RECOVERY_TIMEOUT`; `WorkerCircuitBreaker` call site passes `settings.cb_failure_threshold` / `settings.cb_recovery_timeout_seconds`.

---

### D-12 — Worker health-poll constants hardcoded

**File:** `api/app.py`
**Status:** 🔧 FIXED this cycle — removed `_POLL_*` constants; all four `settings.worker_poll_*` fields used inline.

---

### D-13 — Worker watchdog constants hardcoded

**File:** `api/app.py`
**Status:** 🔧 FIXED this cycle — removed `_WATCHDOG_*` constants; `settings.watchdog_*` fields used inline.

---

### D-14 — WebSocket frame/timeout constants hardcoded

**File:** `api/websocket.py`
**Status:** 🔧 FIXED this cycle — removed `_HEARTBEAT_INTERVAL`, `_DEAD_CLIENT_TIMEOUT`, `_MAX_WS_MESSAGE_BYTES`; `settings.ws_*` fields used inline.

---

### D-15 — Internal IPC frame/body size constants hardcoded

**File:** `api/internal.py`
**Status:** 🔧 FIXED this cycle — removed `_MAX_WS_FRAME_BYTES`, `_MAX_HTTP_BODY_BYTES`; `settings.internal_max_frame_bytes` / `settings.internal_max_http_body_bytes` used inline.

---

### D-16 — `_GRAPH_RECURSION_LIMIT = 100` duplicated across two files

**Files:** `api/endpoints.py`, `worker/executor.py`
**Status:** 🔧 FIXED this cycle — both constants removed; `settings.graph_recursion_limit` used at each call site.

---

### D-17 — `_DEFAULT_MAX_CONCURRENT_THREADS` re-declares `settings.max_concurrent_threads`

**File:** `worker/executor.py`
**Status:** 🔧 FIXED this cycle — constant deleted; `settings.max_concurrent_threads` used directly.

---

### D-18 — `_MAX_CACHED_GRAPHS = 32` hardcoded

**File:** `worker/executor.py`
**Status:** 🔧 FIXED this cycle — removed; `settings.max_cached_graphs` used inline.

---

### D-19 — IPC flush/retry/buffer constants hardcoded

**File:** `worker/ipc.py`
**Status:** 🔧 FIXED this cycle — removed `_FLUSH_INTERVAL`, `_MAX_FLUSH_RETRIES`, `_RETRY_BACKOFF_BASE`, `_MAX_EVENT_BUFFER`; `settings.ipc_*` fields used inline.

---

### D-20 — Aggregator debounce/buffer constants hardcoded

**File:** `core/aggregator.py`
**Status:** 🔧 FIXED this cycle — removed all 8 constants; `settings.*` fields used inline.

---

### D-21 — Context window constants hardcoded

**File:** `core/context.py`
**Status:** 🔧 FIXED this cycle — removed `CONTEXT_LIMIT`, `_CHARS_PER_TOKEN`; callers updated to use `settings.context_limit_tokens` / `settings.chars_per_token`.

---

### D-22 — Workspace/context ref caps hardcoded

**Files:** `core/anchoring.py`, `core/metadata.py`, `core/graph.py`, `core/nodes/mount.py`, `core/task_queue.py`
**Status:** 🔧 FIXED this cycle — all six constants removed; corresponding `settings.*` fields used inline.

---

### D-23 — ACP provider timeout hardcoded

**File:** `providers/acp_chat_model.py`
**Status:** 🔧 FIXED this cycle — `_ACP_STARTUP_TIMEOUT` removed; `settings.acp_startup_timeout_seconds` used inline.

---

### D-24 — ACP file read cap hardcoded

**File:** `providers/acp_chat_model.py`
**Status:** 🔧 FIXED this cycle — `_FS_READ_MAX_BYTES` removed; `settings.acp_fs_read_max_bytes` used inline.

---

### D-25 — OAuth token expiry buffer hardcoded

**File:** `providers/gemini_auth.py`
**Status:** 🔧 FIXED this cycle — `_EXPIRY_BUFFER_S` removed; `settings.oauth_expiry_buffer_seconds` used inline.

---

### D-26 — MCP server timeout/truncation constants hardcoded

**File:** `protocols/mcp/server.py`
**Status:** 🔧 FIXED this cycle — all four constants removed; `settings.mcp_*` fields used inline.

---

### D-27 — `McpSettings` duplicates core `Settings`

**File:** `protocols/mcp/server.py`
**Status:** 🔧 FIXED this cycle — `McpSettings` class eliminated entirely; `mcp_host`/`mcp_port` migrated to core `Settings`; `_get_api_base_url()` wrapper removed; all references use core `settings` directly.

---

### D-28 — `VAULTSPEC_MCP_AUTO_START_GATEWAY` ghost variable

**Files:** `protocols/mcp/__main__.py`, `tests/test_mcp_e2e_live.py`
**Status:** 🔧 FIXED this cycle — feature was never implemented; no code reads this variable. Removed from docstring in `__main__.py` and removed the dead env entry from the test fixture (was a no-op).

---

### D-29 — TEL-M5 architectural exception (informational)

**File:** `telemetry/instrumentation.py:60-83`
**Status:** ℹ️ ACCEPTED EXCEPTION — OTel SDK must be configured at import time before any `get_tracer()` call at module scope. Routing through `Settings` would create a circular import (`telemetry` ← `core/aggregator` ← `core/config`). These `os.environ` reads are intentional and documented (TEL-M5). Changing requires significant architectural restructuring.
**Vars affected:** `OTEL_SERVICE_NAME`, `OTEL_SERVICE_VERSION`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_EXPORTER_CONSOLE`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`

---

### D-30 — `VAULTSPEC_DB_POOL_SIZE` / `VAULTSPEC_DB_POOL_MAX_OVERFLOW` missing from `.env.example`

**Status:** 🔧 FIXED this cycle — both fields added to `.env.example` under Worker Process section.

---

### D-31 — `VAULTSPEC_AUTO_SPAWN_WORKER`, `VAULTSPEC_REPAIR_ON_STARTUP`, `VAULTSPEC_REPAIR_STRATEGY` missing from `.env.example`

**Status:** 🔧 FIXED this cycle — all three fields added to `.env.example` under Worker Process section.

---

### D-32 — `docker-compose.prod.yml` uses SQLite despite being named "production"

**Status:** 🔧 FIXED this cycle — header comment updated to clearly identify this as a "single-node SQLite deployment" suitable for local container testing. Postgres overlay is explicitly called out as the recommended production path. SQLite config unchanged (intentional for single-node use).

---

## Fix Status Summary

| ID | Description | Status |
|---|---|---|
| D-01 | AUTO_MIGRATE orphan in .env.example | 🔧 FIXED |
| D-02 | INTERNAL_TOKEN bare alias | 🔧 FIXED |
| D-03 | LANGCHAIN_* legacy aliases | 🔧 FIXED |
| D-04 | VAULTSPEC_* secondary key aliases | 🔧 FIXED |
| D-05 | VAULTSPEC_UI_BUILD_DIR naked read | 🔧 FIXED |
| D-06 | VAULTSPEC_PROJECT_ROOT naked read | 🔧 FIXED |
| D-07 | MOCK_API_BASE naked read | 🔧 FIXED |
| D-08 | PORT/WORKER_PORT/WORKER_URL naked reads (logging) | 🔧 FIXED |
| D-09 | utils/trace.py LANGSMITH reads via os.environ | 🔧 FIXED |
| D-10 | _WORKER_HEARTBEAT_TIMEOUT hardcoded | 🔧 FIXED |
| D-11 | Circuit breaker thresholds hardcoded | 🔧 FIXED |
| D-12 | Worker poll constants hardcoded | 🔧 FIXED |
| D-13 | Watchdog constants hardcoded | 🔧 FIXED |
| D-14 | WebSocket constants hardcoded | 🔧 FIXED |
| D-15 | Internal IPC size constants hardcoded | 🔧 FIXED |
| D-16 | _GRAPH_RECURSION_LIMIT duplicated | 🔧 FIXED |
| D-17 | _DEFAULT_MAX_CONCURRENT_THREADS re-declares Settings | 🔧 FIXED |
| D-18 | _MAX_CACHED_GRAPHS hardcoded | 🔧 FIXED |
| D-19 | IPC flush/retry/buffer constants hardcoded | 🔧 FIXED |
| D-20 | Aggregator debounce/buffer constants hardcoded | 🔧 FIXED |
| D-21 | Context window constants hardcoded | 🔧 FIXED |
| D-22 | Workspace/context ref caps hardcoded | 🔧 FIXED |
| D-23 | ACP startup timeout hardcoded | 🔧 FIXED |
| D-24 | ACP file read cap hardcoded | 🔧 FIXED |
| D-25 | OAuth expiry buffer hardcoded | 🔧 FIXED |
| D-26 | MCP server timeout/truncation constants hardcoded | 🔧 FIXED |
| D-27 | McpSettings duplicates mcp_api_base_url | 🔧 FIXED |
| D-28 | MCP_AUTO_START_GATEWAY ghost variable | 🔧 FIXED |
| D-29 | TEL-M5 OTel import-time reads | ℹ️ ACCEPTED |
| D-30 | DB pool fields missing from .env.example | 🔧 FIXED |
| D-31 | Worker startup fields missing from .env.example | 🔧 FIXED |
| D-32 | docker-compose.prod.yml SQLite misnaming | 🔧 FIXED |
