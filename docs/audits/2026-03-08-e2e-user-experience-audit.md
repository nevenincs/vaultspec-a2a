# End-to-End User Experience Audit — 2026-03-08

## Scope

Walk through the complete user experience from zero to working MCP tool
invocation, documenting every friction point. Covers: install, IDE
configuration, first tool call, error scenarios, recovery, and observability.

**Audit method**: Code-level trace through every file in the critical path,
verified against actual source. No assumptions from training data.

---

## Step 1: Fresh Clone + Install

### What the user does

```bash
git clone <repo>
cd vaultspec-a2a
uv sync              # Python deps
cd src/ui && npm ci   # Frontend deps (optional — only for UI development)
```

### What `uv sync` sets up

- **Source**: `pyproject.toml` lines 32-34 define two console scripts:
  - `vaultspec` = `vaultspec_a2a.cli:cli` (Click CLI for service management)
  - `vaultspec-mcp` = `vaultspec_a2a.protocols.mcp.__main__:main` (MCP stdio server)
- **Python**: 3.13 (pinned in pyproject.toml)
- **Key deps**: langchain, langgraph, fastmcp, httpx, pydantic-settings, uvicorn, sqlalchemy

### Required environment variables

From `.env.example` (105 lines):
- **At least one LLM provider key** (ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN,
  OPENAI_API_KEY, GEMINI_API_KEY, ZHIPU_API_KEY, GOOGLE_API_KEY)
- **Optional**: LANGSMITH_API_KEY (tracing), VAULTSPEC_INTERNAL_TOKEN (prod auth),
  VAULTSPEC_ENVIRONMENT (default: development)
- **No key is truly mandatory** — system starts without any, fails silently at
  first LLM call

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-001 | `uv sync` installs 100+ packages including `torch` transitive deps from langchain. Takes 2-5 minutes on first run. | Fast install (<30s). | LOW — standard Python ML ecosystem. Document expected install time. |
| UX-002 | No post-install message telling the user what to do next. `uv sync` completes silently. | "Setup complete. Run `vaultspec service start` or configure your IDE." | MED — add a `uv run vaultspec --help` hint or post-install hook. |
| UX-003 | `.env.example` exists but user is not prompted to copy it. Missing API keys cause silent failures later. | Guided setup or error message listing missing keys. | MED — validate required API keys at startup, not at first provider call. |

### What works well

- `uv sync` is reproducible (lockfile)
- `pyproject.toml` defines `vaultspec` and `vaultspec-mcp` console scripts
- No build step required for the Python backend

---

## Step 2: IDE MCP Configuration

### What the user needs to know

- **Console script**: `vaultspec-mcp` (pyproject.toml:34)
- **Transport**: stdio (default) or streamable-http (`--transport streamable-http`)
- **Source**: `protocols/mcp/__main__.py` — argparse with `--transport`, `--host`, `--port`
- **Env vars for MCP** (from `protocols/mcp/server.py` `_MCPSettings`):
  - `VAULTSPEC_MCP_API_BASE_URL` — gateway URL (default: http://localhost:8000)
  - `VAULTSPEC_MCP_AUTO_START_GATEWAY` — auto-spawn gateway (default: true)
  - `VAULTSPEC_MCP_HOST` — bind host for streamable-http (default: 0.0.0.0)
  - `VAULTSPEC_MCP_PORT` — bind port for streamable-http (default: 8100)
- **No `docs/IDE_SETUP.md` exists** — verified (file not found)
- **No README IDE section** — verified (no matching content in README.md)

### Example configuration (Claude Desktop)

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "vaultspec-mcp"],
      "cwd": "/path/to/vaultspec-a2a"
    }
  }
}
```

### Example configuration (Cursor / Windsurf)

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "vaultspec-mcp"],
      "cwd": "/path/to/vaultspec-a2a"
    }
  }
}
```

### Streamable HTTP (alternative — for network clients)

```bash
uv run vaultspec-mcp --transport streamable-http --port 8100
```

Then configure IDE to connect to `http://localhost:8100/mcp`.

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-004 | No documentation on how to configure IDE integration. No `IDE_SETUP.md`, no README section, no `.well-known/mcp.json`. | Clear step-by-step guide for each supported IDE. | HIGH — critical missing documentation. User has to reverse-engineer the console script name and transport. |
| UX-005 | The `vaultspec-mcp` console script only works after `uv sync`. If the user installs globally via `pip install -e .`, the script may not find the venv correctly. | Works regardless of install method. | LOW — `uv run` is the documented approach. |
| UX-006 | No `--help` output on `vaultspec-mcp` explaining what it does. The `__main__.py` has `argparse` but the help text is minimal ("Vaultspec MCP server"). | Descriptive help with examples. | LOW |
| UX-007 | MCP server name is `vaultspec-orchestrator` (in FastMCP constructor at server.py:369) but the console script is `vaultspec-mcp`. The IDE shows the FastMCP name. Inconsistent naming. | Consistent name across all surfaces. | LOW — cosmetic. |

---

## Step 3: First Tool Invocation (Cold Start)

### Exact call chain: IDE -> MCP tool result

**Phase 1: MCP server lifespan** (server.py:324-366)

```
IDE spawns: uv run vaultspec-mcp     (__main__.py:47 → mcp.run_stdio_async())
  → _mcp_lifespan(server)             (server.py:325)
  → _mcp_settings.mcp_auto_start_gateway == True  (default)
  → _spawn_gateway(api_base)           (server.py:220-280)
    → asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.api.app:create_app", "--factory",
        "--host", "127.0.0.1", "--port", "8000",
        stdout=DEVNULL, stderr=DEVNULL     ← KEY: stderr is lost
      )
    → Polls _check_gateway_health() every 0.5s for 120 iterations (60s max)
```

**Phase 2: Gateway lifespan** (api/app.py:540-600)

```
uvicorn starts → create_app() → lifespan()
  → init_db()                    (database/migrate.py — Alembic auto-migrate)
  → backfill_checkpoint_fields() (database/session.py)
  → AsyncSqliteSaver.from_conn() (langgraph checkpointer)
  → EventAggregator()
  → ConnectionManager()
  → setup_logging()              (utils/logging.py:77)
  → configure_otel()             (telemetry setup)
  → httpx.AsyncClient()          (worker client)
  → LazyWorkerSpawner()          (app.py:435-503 — defers worker spawn)
  → /health responds 200         (MCP poll succeeds)
```

**Phase 3: First tool call** (e.g., `start_thread`)

```
IDE calls MCP tool "start_thread"
  → server.py:430 start_thread()
  → _require_gateway()          (server.py:408 — checks _gateway_connected flag)
  → _get_client().post(f"{api_base}/api/threads", json=payload)
  → Gateway endpoints.py:338 create_thread_endpoint()
    → crud.create_thread()      (DB INSERT)
    → dispatches POST to worker  (first dispatch → LazyWorkerSpawner triggers)
      → Worker auto-spawn:
        → asyncio.create_subprocess_exec(uvicorn, worker app)
        → Poll worker /health every 0.5s (up to 30s)
    → Worker executor.py ingest()
      → compile_graph()         (core/graph.py)
      → graph.astream()         (LangGraph — first LLM call happens HERE)
    → Returns thread_id to gateway → MCP → IDE
```

### Timing breakdown

| Phase | Duration | Source | Notes |
|-------|----------|--------|-------|
| MCP lifespan start | ~0.5s | __main__.py | Module imports, settings parse |
| Gateway subprocess spawn | ~2-3s | server.py:240 | Python interpreter + uvicorn startup |
| Gateway DB init + migrations | ~1-2s | lifespan | First run creates DB file |
| Gateway health poll | ~1-2s | server.py:256 | 0.5s intervals until /health 200 |
| MCP tools available | **~4-7s** | | **User can call read-only tools here** |
| `start_thread` call | ~0.5s | server.py:430 | HTTP POST to gateway |
| Worker lazy spawn | ~3-5s | app.py:435 | Only on first write-path dispatch |
| Worker health poll | ~1-3s | app.py:490 | 0.5s intervals until /health 200 |
| Graph compilation | ~1-2s | graph.py | LangGraph compile + checkpointer init |
| **Total: first tool result** | **~10-15s** | | **From IDE start to thread_id returned** |

### What stderr=DEVNULL means in practice

At `server.py:250-251`, `_spawn_gateway()` sets both stdout and stderr to
`asyncio.subprocess.DEVNULL`. This means:

1. If gateway fails to start (import error, port conflict, DB corruption),
   the error message is lost forever
2. MCP health poll loops for 60s then returns `None`
3. User sees a generic "Gateway not connected" — no clue WHY

**Exception**: If the process exits (returncode != None), `server.py:264-275`
attempts to read `process.stderr` — but stderr is DEVNULL, so this reads
nothing. The code handles this gracefully (empty bytes) but the error info is
still lost.

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-008 | 10-15 second delay before any tool is available. IDE shows "connecting" spinner. | Instant or <3s tool availability. | HIGH — Phase 1 tasks (#25/#26) address this: lazy worker spawn + read-only tool bypass. |
| UX-009 | During cold start, stdout/stderr from gateway and worker are sent to DEVNULL. If startup fails, the user sees nothing — just a timeout after 60s. | Clear error message explaining what failed. | MED — log startup output to a file or capture stderr for error reporting. |
| UX-010 | If the user doesn't have any LLM API keys configured (`.env` missing or empty ANTHROPIC_API_KEY), the MCP server starts successfully. Tools appear to work. Only when `start_thread` triggers an actual LLM call does the provider fail — deep inside the graph execution. The error message is a generic `ToolError("Server error: HTTP 502")`. | Validation at startup or at thread creation time: "No LLM API keys configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env." | HIGH — silent failure with poor error message. |
| UX-011 | On Windows, the process tree is: IDE → MCP → Gateway → Worker. Closing the IDE sends SIGTERM to MCP, which uses `taskkill /T /F` for cleanup. But if MCP crashes (OOM, panic), the gateway and worker processes are orphaned. No PID file, no watchdog. | Clean process cleanup on all exit paths. | MED — PID file + atexit handler would catch more cases. |

---

## Step 4: Successful Tool Usage

### `list_threads` (read-only, needs gateway only)

```
User: "List my threads"
→ MCP calls GET /api/threads
→ Returns thread list
```

**Current**: Works after cold start completes (~10-15s wait).
**After Phase 1**: Should work in <3s (no worker needed).

### `start_thread` (write, needs gateway + worker)

```
User: "Start a coding task: refactor the auth module"
→ MCP calls POST /api/threads with initial_message
→ Gateway dispatches to worker
→ Worker compiles graph, starts execution
→ Returns thread_id
```

**Current**: Works after cold start. Execution time depends on LLM provider.

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-012 | `start_thread` returns immediately with thread_id and REST URL. No WebSocket URL. User must poll `get_thread_status` to check progress. | Real-time streaming or at least a clear "poll with get_thread_status every 10s" instruction. | LOW — the MCP `instructions` text does explain polling. |
| UX-013 | `get_thread_status` returns a large JSON-like text blob with full message history. For long conversations, this can be 50KB+ of text injected into the LLM context. | Concise status summary with option to get full details. | MED — truncation or summary mode would help. |
| UX-014 | `list_team_presets` works but the preset names are opaque (`vaultspec-adaptive-coder`, `vaultspec-structured-coder`). No description of what each preset does. | Human-readable descriptions for each preset. | LOW — the team TOML configs have `display_name` but the MCP tool only shows the ID. |

---

## Step 5: Error Scenarios

### 5a. Gateway not running (auto-start disabled)

**Trigger**: `VAULTSPEC_MCP_AUTO_START_GATEWAY=false` and no manual gateway.

**What user sees**: Every tool call returns `ToolError("Gateway not connected. Start it with: vaultspec service start Or set VAULTSPEC_MCP_AUTO_START_GATEWAY=true")`.

**Assessment**: GOOD — clear, actionable error message (HIGH-02 fix).

### 5b. Worker crashed mid-execution

**Trigger**: Worker process crashes during graph execution.

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-015 | Thread stays in RUNNING state indefinitely. Gateway heartbeat timeout (90s) eventually marks worker as disconnected. Circuit breaker may open after 3 failed dispatches. But the stuck thread is never cleaned up. | Thread transitions to FAILED with error message. User can retry. | HIGH — no stale thread detection/cleanup on worker crash. The thread status is never updated because the worker's `_emit_terminal_status` never fires. |
| UX-016 | Gateway `/health` reports `worker_connected: false` after 90s. But MCP tools don't check this — they still try to dispatch and get network errors or 502s. | MCP tools check worker health before dispatching and give actionable error. | MED — MCP could check `/health` and report worker status proactively. |

### 5c. Database not initialized

**Trigger**: First run, no existing DB file.

**What happens**: Gateway lifespan calls `init_db()` which runs Alembic migrations automatically. This is transparent to the user.

**Assessment**: GOOD — fully automatic. No friction.

### 5d. Missing VAULTSPEC_INTERNAL_TOKEN

**Trigger**: `VAULTSPEC_ENVIRONMENT=production` without setting VAULTSPEC_INTERNAL_TOKEN.

**What user sees**: Gateway starts normally. Worker-to-gateway internal API calls
(event batches, heartbeats) hit `_verify_internal_token` (internal.py:112-138)
which raises HTTP 500: `"VAULTSPEC_INTERNAL_TOKEN must be set in production"`.
Worker logs show HTTP 500 errors on every event batch.

**Assessment**: Error message IS actionable — it names the exact variable. But it
only fires in production mode. In development mode (default), internal endpoints
have NO auth, which is a security concern documented in PROD-070.

### 5e. Missing or invalid `.env`

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-017 | No `.env` file → pydantic_settings uses defaults → `VAULTSPEC_ENVIRONMENT=development`, all API keys None, `LANGSMITH_TRACING=false`. System starts but no LLM calls can succeed. | Startup warning listing which API keys are configured. | MED — log a summary of configured providers at startup. |

### 5f. Port conflict

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-018 | Port 8000 already in use → Gateway uvicorn fails to bind → MCP health polling times out after 60s → "Gateway not connected" error. | Clear error: "Port 8000 is in use by another process. Stop the other process or set VAULTSPEC_PORT." | MED — capture gateway stderr and parse for EADDRINUSE. Currently stderr goes to DEVNULL (server.py:250-251). |

**Code path**: `_spawn_gateway()` (server.py:240) spawns uvicorn with
`stderr=DEVNULL`. When uvicorn fails to bind, the error `[Errno 10048]` (Windows)
or `[Errno 98]` (Linux) goes to /dev/null. `process.returncode` becomes non-zero,
the early-exit check at server.py:264 fires, but `process.stderr` is None
(DEVNULL), so the logged message is empty.

---

## Step 6: Recovery After Crash

### Available CLI recovery commands

From `cli/_service.py` (145 lines):

| Command | What it does | Source |
|---------|-------------|--------|
| `vaultspec service start` | Starts gateway (worker auto-spawns). Runs uvicorn in foreground. | _service.py:16-59 |
| `vaultspec service start backend` | Starts gateway only. | _service.py:44-51 |
| `vaultspec service start worker` | Starts worker only. | _service.py:52-59 |
| `vaultspec service stop` | Sends POST `/api/admin/shutdown` to both. | _service.py:62-89 |
| `vaultspec service stop backend` | Stops gateway only. | _service.py:77-78 |
| `vaultspec service kill backend` | Force-kills via `taskkill /T /F` (Windows powershell). | _service.py:92-122 |
| `vaultspec service status` | GET `/internal/health` (gateway) + GET `/health` (worker). | _service.py:125-144 |

**No `vaultspec service restart` exists.**

**`service kill` is Windows-only** — uses `powershell -Command Get-NetTCPConnection`
(line 107). Will fail on Linux/macOS.

**`service stop` uses `/api/admin/shutdown`** which may not exist on worker
(comment at line 76: "Worker has no shutdown endpoint — use the same path as a
best-effort").

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-019 | After MCP process crash, restarting the IDE reconnects. MCP lifespan spawns new gateway+worker. Orphaned processes from previous run may conflict (port in use). | Automatic cleanup of orphaned processes, or PID file detection. | MED — check for existing gateway on auto-start port before spawning. Actually, `_spawn_gateway` does check `/health` first (server.py:226) — if orphaned gateway is still running, it reuses it. This is acceptable. |
| UX-020 | Threads that were RUNNING during crash remain RUNNING in DB. No automatic cleanup. User sees "stuck" threads in `list_threads`. | Stale RUNNING threads auto-transition to FAILED on gateway restart, or at least are flagged. | MED — gateway startup could scan for RUNNING threads with no active worker heartbeat and mark them FAILED. |

**Note**: UX-019 is partially mitigated — `_spawn_gateway` health-checks first, so reuse of orphaned gateway works. But orphaned WORKER processes (if gateway died but worker didn't) could cause port conflicts on worker port 8001.

---

## Step 7: Observability and Status

### Logging architecture (utils/logging.py, 134 lines)

`setup_logging()` configures the root logger:
- **Interactive terminal** (TTY + no color disabled + not CI + is_dev):
  → `RichHandler` with rich tracebacks, timestamps, paths
- **All other cases** (non-TTY, production, CI):
  → `StreamHandler(sys.stdout)` with `JSONFormatter` (structured JSON lines)

**Where logs go in each mode**:

| Mode | Gateway logs | Worker logs | MCP server logs |
|------|-------------|-------------|-----------------|
| `vaultspec service start` (foreground) | stdout (visible in terminal) | stdout (if started separately) | N/A |
| MCP auto-start (IDE) | DEVNULL (server.py:250) | DEVNULL (gateway spawns worker same way) | MCP stderr → IDE's process manager (not visible to user) |
| Docker compose | stdout (docker logs) | stdout (docker logs) | N/A |

**Key problem**: In the most common user path (IDE → MCP → auto-start), ALL logs
from gateway and worker are discarded. The user has zero diagnostic data.

### CLI MCP commands (cli/_mcp.py, 75 lines)

| Command | What it does |
|---------|-------------|
| `vaultspec mcp status` | Prints launch instructions (not actual status). |
| `vaultspec mcp tools` | Lists 11 available MCP tools with descriptions. |
| `vaultspec mcp discovery` | Prints JSON with transport config (stdio + HTTP). |

**Note**: `vaultspec mcp status` is misleading — it prints static help text, not
runtime status of an MCP server. There is no command to check if the MCP server
is actually running.

### Friction points

| # | What happens | What user expected | Fix needed |
|---|-------------|-------------------|------------|
| UX-021 | `vaultspec service status` (CLI) checks `/internal/health` which is auth-gated in production. Shows "stopped" even when running. | Working status command in all environments. | MED — use public `/health` endpoint instead (_service.py:133 uses `/internal/health`). |
| UX-022 | No `vaultspec logs` command. Logs go to stderr (suppressed to DEVNULL in auto-spawn mode). User cannot access gateway or worker logs. | `vaultspec logs gateway` and `vaultspec logs worker` commands, or log file paths. | HIGH — critical observability gap. When things go wrong, the user has no diagnostic data. |
| UX-023 | `get_team_status` MCP tool returns agent metadata. But when no thread is running, it returns minimal data (empty agents list, 0 active threads). No indication of system health. | Team status includes system health: gateway up, worker up, DB accessible, configured providers. | LOW — team status is about agent state, not system health. A separate `system_status` tool could address this. |

---

## Summary: Friction Point Severity Distribution

| Severity | Count | Key Issues |
|----------|-------|------------|
| HIGH | 5 | UX-004 (no IDE docs), UX-008 (cold start), UX-010 (silent API key failure), UX-015 (stuck threads on crash), UX-022 (no log access) |
| MED | 10 | UX-002 (no post-install hint), UX-003 (no .env guidance), UX-009 (startup failure invisible), UX-011 (orphan processes), UX-013 (large status output), UX-016 (MCP health check), UX-017 (provider listing), UX-018 (port conflict), UX-020 (stale threads), UX-021 (CLI status auth) |
| LOW | 6 | UX-001 (install time), UX-005 (pip vs uv), UX-006 (help text), UX-007 (naming), UX-012 (polling guidance), UX-014 (preset descriptions) |
| OK | 2 | DB auto-migration (Step 5c), gateway reuse on restart (UX-019 partial) |

**Total**: 23 friction points (5 HIGH, 10 MED, 6 LOW, 2 OK)

## Top 5 Recommendations (ordered by user impact)

1. **Write IDE setup documentation** (UX-004) — without this, users literally cannot start. Create `docs/IDE_SETUP.md` with configurations for Claude Desktop, Cursor, and Windsurf.

2. **Implement lazy worker spawn** (UX-008) — Phase 1 tasks #25/#26 are in progress. This reduces cold start from 10-15s to 2-3s for read-only tools.

3. **Validate API keys at thread creation** (UX-010) — before dispatching to worker, check that at least one LLM provider has a configured API key. Return actionable error listing which env vars to set.

4. **Add log file output for auto-spawned processes** (UX-022) — write gateway/worker logs to `~/.vaultspec/logs/` or `$WORKSPACE/.vaultspec/logs/`. Without this, debugging is impossible.

5. **Detect and clean up stale RUNNING threads** (UX-015/UX-020) — on gateway startup, scan for RUNNING threads. If no worker heartbeat within 10s of startup, transition stale threads to FAILED with error "Worker process terminated unexpectedly."
