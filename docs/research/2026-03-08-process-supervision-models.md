# Process Supervision Models for Developer Tools on Desktop

**Date:** 2026-03-08
**Author:** Orchestrator (prod-readiness-audit team)
**Status:** DRAFT — Pending team review and ADR proposal

## 1. Problem Statement

The VaultSpec A2A system requires **three cooperating processes** for a single
MCP tool invocation to work:

```
IDE ──stdio──▶ MCP Server ──HTTP──▶ Gateway :8000 ──HTTP──▶ Worker :8001
                                        ▲                        │
                                        └────── events ──────────┘
```

A user who types `start_thread("fix the login bug")` in Cursor must wait for:
1. MCP server lifespan to auto-start the gateway subprocess
2. Gateway lifespan to auto-start the worker subprocess
3. Worker health check to pass (~0.5s polling * N attempts)
4. The actual HTTP round-trip to create the thread

**Cold start budget (worst case):** 60s gateway + 30s worker = 90s before the
first tool invocation succeeds. This is unacceptable.

**Current state after our fixes (CRIT-01/02/03):** The chain works, but it's
still 3 subprocesses spawned lazily with polling health checks.

## 2. Industry Analysis

### 2.1 The Ollama Model — Gold Standard for Developer Tool UX

**Architecture:** Single Go binary, client-server over localhost HTTP.
- `ollama serve` starts the HTTP server + GPU scheduler in one process.
- `ollama run llama3` is just an HTTP client that talks to the running server.
- First run: install binary, `ollama pull`, `ollama serve` — working in < 2min.
- **Key insight:** One process owns everything. No service coordination.

**Relevance to us:** Ollama proves that developers expect a single command/binary
to "just work." They don't want to think about service topology.

### 2.2 Cursor / Copilot / Windsurf — Cloud-First Architecture

**Architecture:** Cloud backend, thin local client.
- All LLM execution and context processing happens on vendor cloud infrastructure.
- The IDE extension is a pure client — no local servers to manage.
- MCP servers are spawned as subprocesses by the IDE host, not by the tool.
- **Key insight:** When you can't be cloud-first, you must emulate the simplicity
  of cloud-first locally.

**Relevance to us:** Our tool is local-first (SQLite, local LLM providers via
ACP). We can't punt complexity to the cloud. We must own the UX of local
service management.

### 2.3 Continue.dev — Open Source, Model-Agnostic

**Architecture:** VS Code extension + optional local inference via Ollama.
- Extension communicates directly to LLM providers (cloud or local).
- No intermediate gateway or worker process.
- Configuration is a single `config.json` file.
- **Key insight:** Minimize moving parts. If you can do it in-process, do it.

### 2.4 Sourcegraph Cody — Enterprise, Self-Hosted Option

**Architecture:** Sourcegraph server (multi-container) + VS Code extension.
- Self-hosted: Docker Compose with multiple services (frontend, gitserver,
  searcher, repo-updater, etc.)
- But the **VS Code extension itself** is just an API client — all complexity
  is server-side, managed by Docker.
- **Key insight:** Docker is acceptable for self-hosted enterprise deployments.
  It is NOT acceptable for individual developer desktop use.

### 2.5 MCP Ecosystem Patterns (2025-2026 specification)

From the MCP specification and best practices:
- **stdio transport** is the recommended default for IDE integration. The IDE
  spawns the MCP server as a subprocess — one process, no configuration.
- **Streamable HTTP** is for networked/production deployments.
- **Best practice:** "Single-service-per-server" — each MCP server should be a
  focused domain (Git server, weather server, etc.).
- **Production pattern:** Dockerize, add health endpoints, use API gateway.
- **Key insight:** The MCP spec assumes MCP servers are lightweight. Our MCP
  server is heavyweight because it needs a full backend stack behind it.

## 3. Architecture Options Analysis

### Option A: Status Quo — 3-Process Chain with Auto-Spawn (Current)

```
MCP (stdio) → spawns Gateway (subprocess) → spawns Worker (subprocess)
```

**Pros:**
- Already implemented (CRIT-01/02/03)
- Clean process isolation per ADR-031
- Worker can be scaled independently (future)

**Cons:**
- 90s worst-case cold start
- 3 processes to manage, kill, debug
- Cascading subprocess spawning is fragile (Windows process tree issues)
- User sees nothing during the 30-90s startup wait
- If any process crashes, the whole chain is broken

**Verdict:** Acceptable for v1 but not production-grade UX.

### Option B: 2-Process — Gateway Embeds MCP (Recommended for Desktop)

```
IDE ──stdio──▶ MCP+Gateway (single process :8000) ──HTTP──▶ Worker :8001
```

**How it works:**
- The MCP tool functions call the gateway's internal Python APIs directly
  instead of making HTTP calls to `localhost:8000`.
- FastMCP runs in stdio mode as the IDE-facing transport.
- Gateway's FastAPI routes still exist for the web UI and external clients.
- Worker remains a separate process (ADR-031 rationale still valid — LLM
  execution isolation).
- MCP lifespan starts the FastAPI app in-process (no subprocess for gateway).
- Gateway lifespan auto-spawns the worker as before.

**Pros:**
- Eliminates one subprocess spawn (gateway)
- MCP tool calls are in-process function calls — near-zero latency
- Cold start: only worker startup (~5-10s)
- One fewer process to crash, debug, manage
- MCP `_require_gateway()` check becomes unnecessary — gateway IS the process
- Web UI still works (FastAPI serves on :8000 via uvicorn in a thread/task)

**Cons:**
- MCP server and gateway share an event loop — long REST handlers could
  theoretically block MCP responses (but MCP is async, so unlikely)
- More complex module coupling (MCP imports gateway internals)
- Breaks the "MCP is a separate concern" boundary
- Cannot horizontally scale MCP independently of gateway (not a real need)

**Implementation sketch:**
```python
@asynccontextmanager
async def _mcp_lifespan(server: FastMCP[None]) -> AsyncIterator[None]:
    # Start gateway in-process (not as subprocess)
    app = create_app()
    # Start uvicorn in background for web UI
    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    uvi_server = uvicorn.Server(config)
    serve_task = asyncio.create_task(uvi_server.serve())
    # Gateway lifespan auto-spawns worker
    try:
        yield
    finally:
        uvi_server.should_exit = True
        await serve_task
```

MCP tool functions would use in-process calls:
```python
@mcp.tool()
async def start_thread(...):
    # Instead of: httpx.post("http://localhost:8000/api/threads")
    # Direct: call the endpoint logic in-process
    from ..api.endpoints import create_thread_endpoint
    result = await create_thread_endpoint(body, services)
    return format_result(result)
```

**Verdict:** Best option for desktop developer UX. Eliminates the most painful
subprocess (gateway) while preserving worker isolation.

### Option C: Single Process — Everything In-Process

```
IDE ──stdio──▶ MCP+Gateway+Worker (single process)
```

**How it works:**
- MCP, gateway, and worker all run in one Python process.
- Graph execution uses `asyncio.create_task()` in a dedicated task group.
- No HTTP IPC — all communication is in-process function calls.

**Pros:**
- Zero cold start for service coordination
- Simplest possible architecture
- One process to manage

**Cons:**
- **ADR-031 explicitly rejected this.** Long LLM calls saturated the event loop,
  causing 10-30s latency spikes on REST calls.
- SQLite write contention without WAL read/write process separation.
- Cannot scale worker independently.
- A crash in graph execution kills the entire stack including the MCP server.

**Verdict:** Rejected per ADR-031. The original rationale is still valid.

### Option D: Daemon Mode — Background Service + Thin MCP Client

```
IDE ──stdio──▶ MCP client (thin) ──HTTP──▶ Daemon (Gateway+Worker) :8000
```

**How it works:**
- A persistent background daemon runs Gateway+Worker (or just Gateway with
  auto-spawn worker).
- The MCP server is a thin stdio wrapper that just forwards calls to the daemon
  via HTTP.
- Daemon started via: `vaultspec daemon start` (or auto-started on first MCP
  tool call via the thin client).
- Platform-specific: Windows Service / macOS launchd / Linux systemd user unit.

**Pros:**
- Daemon survives IDE restarts — no cold start after first run
- MCP server is truly lightweight (just an HTTP client + stdio bridge)
- Matches Ollama model (`ollama serve` = daemon)
- Clean separation of concerns

**Cons:**
- Platform-specific daemon management (Windows Service API, launchd plist, systemd)
- Users must install/manage a background service
- More complex first-run experience
- Debugging: "is the daemon running?" becomes a new failure mode

**Verdict:** Good for v2/production but adds platform complexity. Better as
an optional deployment mode alongside Option B.

## 4. Startup Latency Analysis

| Scenario | Current (3-process) | Option B (2-process) | Option D (daemon) |
|----------|--------------------|--------------------|------------------|
| Cold start (first ever) | 60-90s | 10-15s | 2-5s (daemon already running) |
| Warm start (daemon up) | N/A | N/A | <1s |
| IDE restart | 60-90s | 10-15s | <1s |
| Worker crash recovery | 30s (re-spawn) | 30s (re-spawn) | 30s (re-spawn) |
| Gateway crash recovery | Manual restart | N/A (in-process) | Auto-restart (daemon manager) |

**Industry benchmark:** Cursor/Copilot: <2s (cloud). Ollama first run: <120s
including model download. Ollama subsequent: <1s. Continue.dev: <3s (direct
LLM call).

**Our target:** <15s cold start, <2s warm start.

## 5. Recommended Architecture Evolution

### Phase 1 (Now — v1.0): Optimize 3-Process Chain
- Already done: CRIT-01/02/03, circuit breaker, health checks
- **Add:** Progress feedback during startup (MCP can send notifications)
- **Add:** Startup parallelization (gateway + worker concurrently)
- **Add:** Pre-warmed worker (start loading common models on boot)
- **Target:** <30s cold start

### Phase 2 (v1.1): Merge MCP + Gateway (Option B)
- MCP tool functions call gateway logic in-process
- Gateway still serves HTTP for web UI
- Worker remains separate subprocess
- **Target:** <15s cold start (only worker spawn)

### Phase 3 (v2.0): Daemon Mode (Option D)
- Background daemon with platform-specific auto-start
- Thin MCP client for IDE integration
- **Target:** <2s after first run

### Phase 4 (Future): Horizontal Scaling
- PostgreSQL replaces SQLite
- Multiple workers behind load balancer
- Gateway becomes a proper API gateway

## 6. Immediate Recommendations

### 6.1 Quick Wins (No Architecture Change)

1. **Parallel startup:** MCP should start gateway, then immediately return
   tools as available. Gateway should start worker in parallel with its own
   startup. Don't wait for the full chain before accepting tool calls.

2. **Lazy worker spawn:** Don't spawn worker on gateway start. Spawn it on
   first dispatch. This shaves 10-15s off startup for users who just want to
   list threads or check status.

3. **Startup progress notifications:** MCP servers can send `notifications/progress`
   during lifespan. Use this to tell the IDE "Starting gateway...",
   "Starting worker...", "Ready."

4. **Cached responses during startup:** `list_threads`, `get_thread_status`,
   `list_team_presets` don't need the worker. Let these work immediately
   by calling the gateway directly (which can read the DB without the worker).

5. **Socket activation pattern:** Instead of health-check polling, use
   `asyncio.Event` signaling within the process to know when subprocesses
   are ready. For cross-process: have the child write to a pipe or file
   when ready.

### 6.2 Configuration Simplification

Current env vars a user might need to set:
- `VAULTSPEC_MCP_API_BASE_URL`
- `VAULTSPEC_MCP_AUTO_START_GATEWAY`
- `VAULTSPEC_AUTO_SPAWN_WORKER`
- `VAULTSPEC_WORKER_URL`
- `VAULTSPEC_WORKER_PORT`
- `VAULTSPEC_INTERNAL_TOKEN`
- `VAULTSPEC_DATABASE_PATH`
- `VAULTSPEC_PORT`

**Recommendation:** Zero config for development. All defaults should work
out of the box with a fresh `uv sync`. The only env var a user should EVER
need to set is their LLM provider credentials (`ANTHROPIC_API_KEY` etc.).
Everything else should have sensible defaults and auto-discovery.

### 6.3 Error Message Quality

Every error a user might see should include:
1. What went wrong (one sentence)
2. Why it matters (one sentence)
3. How to fix it (one command)

Example (current): `"Gateway not connected."`
Example (better): `"Cannot reach the gateway at localhost:8000. Run 'vaultspec service start' or set VAULTSPEC_MCP_AUTO_START_GATEWAY=true in your environment."`

## 7. Sources

- [MCP Architecture - Model Context Protocol](https://modelcontextprotocol.io/specification/2025-06-18/architecture)
- [15 Best Practices for Building MCP Servers in Production - The New Stack](https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/)
- [MCP Architecture Patterns for Production-Grade Agents - DEV Community](https://dev.to/julesk/mcp-architecture-patterns-for-production-grade-agents-i4i)
- [Agent System Architectures of GitHub Copilot, Cursor, and Windsurf](https://cuckoo.network/blog/2025/06/03/coding-agent)
- [Ollama Architecture - DeepWiki](https://deepwiki.com/ollama/ollama/2-architecture)
- [Running Your Server - FastMCP](https://gofastmcp.com/deployment/running-server)
- [FastAPI + FastMCP Integration](https://gofastmcp.com/integrations/fastapi)
- [Why the MCP Server Is Now a Critical Microservice - The New Stack](https://thenewstack.io/why-the-mcp-server-is-now-a-critical-microservice/)
- ADR-031: Worker Process Architecture (internal)
- ADR-017: Containerization Strategy (internal)
- ADR-007: Tech Stack Deployment (internal)
