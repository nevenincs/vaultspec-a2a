# Industry Patterns for Multi-Service Developer Tool UX

**Date:** 2026-03-08
**Author:** docs-researcher (prod-readiness-audit team)
**Status:** Research Complete

## Executive Summary

This document surveys how production developer tools with complex service stacks
(IDE plugin -> API gateway -> background worker) deliver seamless UX. The key
finding is that **every successful tool hides multi-process complexity from the
user** through one of three patterns: in-process embedding, stdio subprocess
spawning, or background daemon with auto-start. Our architecture (MCP server ->
Gateway -> Worker) maps closest to the **Claude Desktop / Copilot model**: a
thin protocol surface (MCP/LSP) that spawns backend services as child processes
via stdio or HTTP, with zero user configuration.

---

## 1. Single-Binary vs Multi-Process Architectures

### Pattern A: In-Process Embedding (Continue.dev, Cody in VS Code)

Continue.dev runs its Core engine **in-process** with the VS Code extension,
sharing the Node.js runtime via `InProcessMessenger`. No child process, no
port, no startup delay. The GUI (React webview) communicates with Core through
the extension host's message-passing API.

For JetBrains, Continue switches to **out-of-process** via TCP sockets or
stdin/stdout because the JetBrains plugin runs in JVM, not Node.js.

Sourcegraph Cody similarly runs its agent in-process in VS Code but requires
a full Sourcegraph server stack (PostgreSQL, Redis, LSIF indexers) for
enterprise features -- delegated to a separately deployed backend.

**Applicability to us:** Limited. Our worker runs LangGraph + LLM calls that
saturate the event loop (ADR-031 rationale). In-process embedding was rejected
for exactly this reason.

### Pattern B: Language Server Protocol Subprocess (Copilot, Cursor)

GitHub Copilot ships a **Language Server** (`@github/copilot-language-server`)
as an npm package with platform-specific binaries in `native/` directory. The
IDE extension spawns it as a child process communicating via **JSON-RPC 2.0
over stdin/stdout**. No ports, no HTTP, no service discovery.

Key characteristics:

- IDE manages the child process lifecycle (spawn on activate, kill on deactivate)
- Communication is stdin/stdout (no port conflicts, no firewall issues)
- Platform binaries avoid Node.js dependency for end users
- The language server is stateless per-session; crash = restart

Cursor is a **VS Code fork** with a monolithic TypeScript + Rust backend. The
Rust performance layer is bridged via Node.js native bindings (not a separate
process). Heavy computation (embeddings, indexing) happens in the cloud, not
locally.

**Applicability to us:** The MCP protocol already supports stdio transport.
Our MCP server could spawn the gateway as a child process over stdio, but
the gateway needs to listen on HTTP for the frontend UI. This pattern works
for the MCP<->Gateway link but not Gateway<->Worker (which needs HTTP for
the dispatch protocol).

### Pattern C: Background Daemon (Ollama, Docker Desktop)

Ollama follows Docker's architecture: a **persistent daemon** (`ollama serve`)
runs in the background, with a CLI client and API. Platform integration:

| Platform | Mechanism | Auto-start | Restart on crash |
|----------|-----------|------------|------------------|
| macOS    | launchd plist | `RunAtLoad: true` | `KeepAlive: true` |
| Linux    | systemd unit | `systemctl enable` | `Restart=always` |
| Windows  | Background service or tray app | Startup folder / Task Scheduler | Service recovery options |

Docker Desktop uses a similar model: a system tray application that manages
the Docker daemon, VM, and supporting services.

**Applicability to us:** This is the right model for standalone/production
deployment where the gateway+worker should always be running. However, for
the MCP/IDE use case, the user shouldn't need to pre-install a daemon --
the MCP server should auto-start everything.

---

## 2. Process Supervision Patterns

### Claude Desktop (MCP Reference Implementation)

Claude Desktop is the canonical MCP host. Its process supervision:

1. **Config-driven spawn**: `claude_desktop_config.json` declares MCP servers
   with their command + args. Claude Desktop spawns each as a child process
   on app launch.
2. **Stdio transport**: Each MCP server communicates via stdin/stdout
   (JSON-RPC 2.0). No ports needed.
3. **Bundled runtime**: Desktop Extensions (`.mcpb` files) bundle all
   dependencies including a Node.js runtime. Zero-config for end users.
4. **Lifecycle = app lifecycle**: MCP servers start when Claude Desktop
   launches, stop when it closes. No independent daemon.

### VS Code Extension Host

VS Code's process model:

```text
Main Process (Electron)
  |-- Renderer Process (UI)
  |-- Extension Host (Node.js child process)
  |     |-- Extensions run here
  |     |-- Can spawn arbitrary child processes
  |-- Terminal processes (forked from main)
```text

Key supervision features:

- Extension Host crash = only extensions die, main process survives
- Extension Host is automatically restarted
- Extensions can spawn child processes freely
- Communication: bidirectional RPC between renderer and Extension Host

### JetBrains Gateway

Gateway acts as a **supervisor** that:

1. Launches a remote IDE backend on the target machine
2. Launches the local thin client
3. Sets up an encrypted TLS 1.3 tunnel between them
4. Monitors backend health via `remote-dev-worker` binary (`pid-alive` check)

### Summary Table

| Tool | Supervision Model | Crash Recovery | User Visibility |
|------|-------------------|----------------|-----------------|
| Claude Desktop | Parent spawns stdio children | Restart on next app launch | None (invisible) |
| Copilot | IDE spawns LSP child | IDE restarts language server | "Copilot is loading..." |
| Continue.dev | In-process (VS Code) / TCP (JB) | Extension Host restart | Error banner |
| Ollama | systemd/launchd daemon | `KeepAlive`/`Restart=always` | CLI error if daemon down |
| VS Code Server | Main process forks Extension Host | Auto-restart Extension Host | Notification |
| JetBrains Gateway | Supervisor + tunnel | `pid-alive` health check | Connection lost dialog |
| Docker Desktop | Tray app manages daemon | Service restart | Tray icon status |

---

## 3. Zero-Config Startup Patterns

### Pattern 1: Spawn-on-Activate (Copilot, Claude Desktop MCP)

The IDE extension activates on relevant file type or user action, spawns the
backend as a child process, waits for ready signal, then serves requests.

**Startup sequence:**

1. User opens IDE / activates extension
2. Extension spawns backend child process
3. Backend sends "ready" message (LSP: `initialized`, MCP: tool listing)
4. Extension begins accepting user requests

**Latency:** 500ms-2s (mostly Node.js/Python startup time)

### Pattern 2: Always-Running Daemon (Ollama, Docker Desktop)

Service runs as a system daemon. CLI/IDE connects to it. If daemon is down,
show actionable error.

**Startup sequence:**

1. System boots -> daemon starts (launchd/systemd)
2. User runs CLI command or IDE extension activates
3. CLI/Extension connects to daemon's HTTP API
4. If connection refused: "Ollama is not running. Run `ollama serve`"

**Latency:** Near-zero (daemon already running). But requires pre-installation.

### Pattern 3: Lazy Spawn with Health Gate (Our Architecture)

This is what we've just implemented:

1. MCP server starts (IDE activates it via stdio or streamable-http)
2. MCP lifespan spawns gateway as child process
3. Gateway lifespan spawns worker as child process
4. MCP health-checks gateway, gateway health-checks worker
5. MCP tools begin accepting requests

**Latency:** 3-5s (Python startup + uvicorn + DB init + health check loops).
This is the main UX risk -- see Section 6.

---

## 4. Health + Recovery UX Patterns

### Best-in-Class Examples

**GitHub Copilot:**

- Status bar icon: spinning (loading), checkmark (ready), warning (error)
- Notification: "GitHub Copilot could not connect to server"
- Auto-retry with exponential backoff
- Graceful fallback: completions silently disabled, chat shows error

**VS Code Extension Host:**

- If Extension Host crashes: notification "Extension Host terminated unexpectedly"
- One-click "Restart Extension Host" action
- Extensions that fail to activate are silently skipped with error in Output panel

**JetBrains Gateway:**

- Connection lost: modal dialog with retry button and timeout countdown
- Backend health: periodic `pid-alive` check, reconnect on failure
- Status bar shows connection quality

### GitHub Primer Design System (Degraded Experiences)

GitHub's internal design system codifies degradation patterns:

1. **Global banner** for system-wide issues (warning variant, above nav)
2. **Inline replacement** for unavailable content (warning icon + short message)
3. **Blankslate component** for large unavailable areas (icon + explanation + action)
4. **Inactive buttons** (not disabled) for critical unavailable actions -- allows
   focus and explanation on click
5. **Hide counters/badges** rather than showing stale data
6. **Never suppress global navigation** -- remove individual unavailable items

### Recommended Pattern for Our Stack

```text
MCP Tool Call Flow:
  1. Tool invoked by IDE
  2. MCP tries to reach gateway
  3a. Success -> forward request, return result
  3b. ConnectError -> ToolError("Gateway is not running.
      Start with: uv run vaultspec-a2a serve")
  3c. Timeout -> ToolError("Gateway is not responding.
      It may be starting up. Retry in a few seconds.")
  3d. HTTP 503 -> ToolError("Worker is unavailable.
      The system is starting up or recovering.")
```yaml

Key principle: **Every error message must be actionable** -- tell the user
exactly what to do, not just what went wrong.

---

## 5. MCP Server Implementations Compared

| Implementation | Backend Dependencies | Auto-Start | Transport |
|---------------|---------------------|------------|-----------|
| Claude Desktop MCP | None (stdio children) | Yes (app launch) | stdio |
| Zed MCP | None (stdio children) | Yes (editor launch) | stdio |
| Our MCP server | Gateway + Worker | Yes (lifespan spawn) | streamable-http |
| Docker MCP Toolkit | Docker daemon | No (pre-installed) | stdio |

**Key insight:** Most MCP servers are **self-contained** -- they don't need
external services. They either do everything in-process or spawn stdio
children. Our architecture is unusual in requiring an HTTP gateway and worker.

**Recommendation:** Consider offering a **lightweight mode** where the MCP
server embeds a minimal gateway (using FastMCP's ASGI mount: `mcp.http_app()`)
for simple use cases, falling back to the full gateway+worker architecture
only when the frontend UI or multi-worker scaling is needed.

---

## 6. Startup Latency Budget

### Industry Benchmarks

| Category | Target | Source |
|----------|--------|--------|
| Mobile app cold start | < 500ms | Android Developer Guidelines |
| IDE extension activation | < 2s | VS Code Extension Guidelines |
| Language server ready | < 3s | LSP best practices |
| CLI first response | < 1s | General UX research |
| Background daemon connect | < 100ms | Ollama, Docker |

### Our Current Latency Estimate

```yaml
MCP stdio startup:           ~200ms  (Python interpreter)
Gateway uvicorn startup:     ~1-2s   (DB init, migrations, checkpointer)
Worker uvicorn startup:      ~1-2s   (DB init, checkpointer, bridge)
Health check polling:         ~1-3s   (exponential backoff retries)
                              --------
Total worst case:             ~4-7s
```text

This exceeds the 3s language server target. Mitigation strategies:

1. **Eager tool listing**: Return MCP tool definitions immediately (they're
   static). Defer health checking to first actual tool invocation.
2. **Parallel startup**: Spawn gateway and worker simultaneously instead of
   sequentially (gateway spawns worker in its lifespan).
3. **Skip migrations on warm start**: Cache migration state, only run on
   first launch or version change.
4. **Lazy DB init in worker**: Worker's checkpointer can be initialized on
   first dispatch rather than at startup.
5. **Background warm-up**: Start health probing in background, let tool
   calls queue until ready (with a timeout).

---

## 7. Graceful Degradation Patterns

### Tier 1: Gateway Down (Fatal for MCP)

All MCP tools depend on the gateway. When it's down:

- **Current behavior**: `ToolError` with connection error message
- **Recommended**: Retry 3x with 1s backoff, then return actionable error:
  "Could not connect to VaultSpec gateway at localhost:8000. Start with:
  `uv run vaultspec-a2a serve`"
- **Auto-recovery**: If gateway was auto-spawned and crashed, attempt
  one restart before reporting failure

### Tier 2: Worker Down (Partial Degradation)

Read-only operations (list_threads, get_thread_status) work via gateway.
Write operations (start_thread, send_message) fail at dispatch.

- **Recommended**: Gateway returns HTTP 503 with `{"detail": "Worker
  unavailable"}`. MCP translates to: "The agent worker is starting up.
  You can query existing threads but cannot start new ones yet."
- **Auto-recovery**: Gateway's auto-spawn monitor restarts worker

### Tier 3: LLM Provider Down (Application-Level)

Graph execution fails but infrastructure is healthy.

- **Recommended**: Thread status shows "failed" with error detail.
  MCP `get_thread_status` surfaces the failure reason.
- **No auto-recovery**: User must retry or change LLM config

---

## 8. Concrete Recommendations for Our Stack

### Immediate (This Sprint)

1. **Actionable error messages in every MCP ToolError** -- always tell the
   user what command to run or what to check
2. **Health-check gate in MCP lifespan** -- fail fast with clear message if
   gateway doesn't come up in 10s
3. **Worker crash auto-restart** -- gateway monitor task restarts worker once
   before circuit-breaking (already partially implemented)

### Near-Term (Next Sprint)

4. **Eager tool listing** -- return MCP tools immediately, defer health check
   to first tool invocation to reduce perceived startup latency
5. **Parallel process startup** -- spawn gateway and worker concurrently
6. **Status endpoint for MCP** -- add `/status` to gateway that reports
   overall system health including worker state, so MCP can give users
   a single diagnostic command

### Future (v2)

7. **Lightweight embedded mode** -- mount MCP tools directly in gateway via
   `mcp.http_app()` for single-process deployment without separate MCP server
8. **System tray / background daemon** -- for Windows, a tray application
   that manages gateway+worker lifecycle (like Docker Desktop or Ollama)
9. **Desktop Extension packaging** -- bundle as `.mcpb` file for one-click
   install in Claude Desktop (includes Python runtime)

---

## Sources

- [Sourcegraph Cody Architecture](https://mgx.dev/insights/sourcegraph-cody-an-in-depth-analysis-of-its-functionality-architecture-use-cases-and-competitive-landscape/a1c220a9fb544c84bc6a6c531e8cf8cd)
- [Continue.dev Architecture (DeepWiki)](https://deepwiki.com/continuedev/continue)
- [Cursor Engineering Challenges](https://newsletter.pragmaticengineer.com/p/cursor)
- [GitHub Copilot Language Server](https://github.com/github/copilot-language-server-release)
- [Ollama Daemon Setup](https://github.com/ollama/ollama/issues/2955)
- [VS Code Extension Host Architecture](https://code.visualstudio.com/api/advanced-topics/extension-host)
- [JetBrains Gateway Deep Dive](https://blog.jetbrains.com/blog/2021/12/03/dive-into-jetbrains-gateway/)
- [Claude Desktop MCP Setup](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [Claude Desktop Extensions](https://www.anthropic.com/engineering/desktop-extensions)
- [GitHub Primer Degraded Experiences](https://primer.style/ui-patterns/degraded-experiences/)
- [Android Startup Latency Guidelines](https://developer.android.com/topic/performance/vitals/launch-time)
