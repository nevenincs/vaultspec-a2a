# IDE MCP Server Setup

Copy-pasteable MCP configurations for connecting your IDE to the Vaultspec A2A
orchestrator. The MCP server exposes LangGraph agent workflows as standard MCP
tools (start_thread, send_message, get_thread_status, etc.).

---

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. (Optional) Pre-start the gateway+worker — MCP auto-starts them if omitted
just dev service start gateway

# 3. Add the MCP config below to your IDE, then restart it
```text

That's it. The MCP server auto-starts the gateway subprocess on first
connection (controlled by `VAULTSPEC_MCP_AUTO_START_GATEWAY=true`), and
the gateway auto-spawns the worker on first dispatch.

---

## IDE Configurations

All configurations below use `uv run` to invoke the MCP server module. This
ensures the correct Python interpreter and virtual environment are used
regardless of your system PATH.

Replace `C:\path\to\vaultspec-a2a` with your actual project root.

### Cursor

File: `<project-root>/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a",
      "env": {}
    }
  }
}
```text

### Claude Desktop

File: `%APPDATA%\Claude\claude_desktop_config.json` (Windows)
File: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a"
    }
  }
}
```text

### Claude Code

File: `<project-root>/.claude/settings.json` or `~/.claude/settings.json`

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a"
    }
  }
}
```text

### VS Code (Copilot MCP)

File: `<project-root>/.vscode/mcp.json`

```json
{
  "servers": {
    "vaultspec": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a",
      "env": {}
    }
  }
}
```text

**Alternative:** Add to your workspace or user `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "vaultspec": {
        "type": "stdio",
        "command": "uv",
        "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
        "cwd": "C:\\path\\to\\vaultspec-a2a",
        "env": {}
      }
    }
  }
}
```text

### Windsurf

File: `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "vaultspec": {
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a",
      "env": {}
    }
  }
}
```text

### VS Code Continue

File: `~/.continue/config.json` (add to `"mcpServers"` array)

```json
{
  "mcpServers": [
    {
      "name": "vaultspec",
      "command": "uv",
      "args": ["run", "python", "-m", "vaultspec_a2a.protocols.mcp"],
      "cwd": "C:\\path\\to\\vaultspec-a2a",
      "env": {}
    }
  ]
}
```text

### Alternative: Direct venv invocation

If `uv` is not on PATH or you prefer explicit Python invocation:

```json
{
  "command": "C:\\path\\to\\vaultspec-a2a\\.venv\\Scripts\\python.exe",
  "args": ["-m", "vaultspec_a2a.protocols.mcp"]
}
```text

Or via the console script:

```json
{
  "command": "C:\\path\\to\\vaultspec-a2a\\.venv\\Scripts\\vaultspec-mcp.exe",
  "args": []
}
```text

---

## Environment Variables

All variables use the `VAULTSPEC_` prefix and can be set in your shell, a
`.env` file in the project root, or the IDE MCP config's `env` block.

### Required for LLM Calls

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (none) | Anthropic API key for Claude providers. |
| `CLAUDE_CODE_OAUTH_TOKEN` | (none) | OAuth token for Claude Code (takes precedence over API key per ADR-002). |

### MCP Server

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULTSPEC_GATEWAY_URL` | `http://localhost:8000` | Gateway API base URL. |
| `VAULTSPEC_MCP_AUTO_START_GATEWAY` | `true` | Auto-start gateway + worker as subprocesses on MCP server start. |
| `VAULTSPEC_MCP_HOST` | `0.0.0.0` | Bind host for `streamable-http` transport (not used in stdio mode). |
| `VAULTSPEC_MCP_PORT` | `8200` | Bind port for `streamable-http` transport (not used in stdio mode). |

### Gateway & Worker

| Variable | Default | Description |
|----------|---------|-------------|
| `VAULTSPEC_PORT` | `8000` | Gateway HTTP port. |
| `VAULTSPEC_WORKER_PORT` | `8001` | Worker HTTP port. |
| `VAULTSPEC_WORKER_URL` | `http://127.0.0.1:8001` | Worker base URL for dispatch calls. |
| `VAULTSPEC_AUTO_SPAWN_WORKER` | `true` | Gateway auto-spawns worker subprocess on first dispatch. |
| `VAULTSPEC_DATABASE_URL` | `sqlite+aiosqlite:///vaultspec.db` | SQLite database connection URL. |
| `VAULTSPEC_WORKSPACE_ROOT` | `./workspaces` | Project root for agent file operations. |
| `VAULTSPEC_INTERNAL_TOKEN` | (none) | Bearer token for gateway-worker IPC auth. None = dev mode (no auth). |
| `VAULTSPEC_MAX_CONCURRENT_THREADS` | `5` | Max concurrent graph executions per worker. |
| `VAULTSPEC_ENVIRONMENT` | `development` | `development` or `production`. |

### LLM Provider Keys (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (none) | Google Gemini API key. |
| `OPENAI_API_KEY` | (none) | OpenAI API key. |
| `GOOGLE_API_KEY` | (none) | Google API key. |

### LangSmith Tracing (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGSMITH_TRACING` | `false` | Enable LangSmith tracing. Also accepted as `LANGCHAIN_TRACING_V2`. |
| `LANGSMITH_API_KEY` | (none) | LangSmith API key (also `LANGCHAIN_API_KEY`). |
| `LANGSMITH_PROJECT` | (none) | LangSmith project name (also `LANGCHAIN_PROJECT`). |

---

## Available MCP Tools

Once connected, the following tools are available:

| Tool | Description | Requires Worker |
|------|-------------|-----------------|
| `start_thread` | Start a new agent team workflow (non-blocking) | Yes |
| `send_message` | Send a follow-up message into an existing thread | Yes |
| `cancel_thread` | Cancel a running thread | Yes |
| `respond_to_permission` | Respond to a pending permission request | Yes |
| `get_thread_status` | Query status of a specific thread | No |
| `list_threads` | List existing orchestration threads | No |
| `get_team_status` | Get agent lifecycle states and active threads | No |
| `get_pending_permissions` | List outstanding permission requests | No |
| `list_team_presets` | List available team presets with details | No |
| `delete_thread` | Permanently delete a thread and its data | No |
| `archive_thread` | Archive a completed/failed/cancelled thread | No |

Read-only tools (marked "No" above) work immediately without a running worker
or gateway. Write tools require the full service chain to be healthy.

---

## Streamable HTTP Mode

For network clients (not IDEs), run the MCP server as a standalone HTTP service:

```bash
uv run python -m vaultspec_a2a.protocols.mcp --transport streamable-http --host 127.0.0.1 --port 8200
```text

This starts an HTTP server at `http://127.0.0.1:8200` that accepts MCP
Streamable HTTP requests.

---

## Troubleshooting

### "Gateway not connected" / "Gateway is not running"

The MCP server cannot reach the gateway API.

1. If `VAULTSPEC_MCP_AUTO_START_GATEWAY=true` (default), the MCP server spawns
   the gateway automatically. Wait for the health check to pass (~5-15s on
   first start).
2. If running the gateway separately:

   ```bash
   just dev service start gateway
   ```text

3. Verify the gateway is healthy:

   ```bash
   curl http://localhost:8000/health
   ```text

### "Worker unavailable" / dispatch failures

The gateway cannot reach the worker.

1. Check if the worker is running:

   ```bash
   curl http://localhost:8001/health
   ```text

2. If using auto-spawn (default), the worker starts on first dispatch. The
   first request may take 5-10s while the worker initializes.
3. Check gateway logs for worker spawn errors.
4. Restart the service:

   ```bash
   just dev service start gateway
   ```text

### "Circuit breaker open" / HTTP 503

The gateway's circuit breaker opened after 3 consecutive worker dispatch
failures. This typically means the worker crashed.

1. **Wait 30 seconds** -- the circuit breaker auto-transitions to HALF_OPEN
   and allows a probe dispatch. If the worker is back, it recovers.
2. If the worker crashed, the watchdog will auto-restart it (up to 5 attempts
   with exponential backoff).
3. Check circuit breaker status:

   ```bash
   curl http://localhost:8000/health
   # Look for "circuit_breaker": {"status": "open"|"closed"|"half_open"}
   ```text

4. If stuck open, restart the gateway:

   ```bash
   just dev service start gateway
   ```text

### Port conflicts

Another process is using port 8000 or 8001.

1. Check what's using the port:

   ```powershell
   # Windows
   netstat -ano | findstr :8000
   taskkill /F /PID <pid>
   ```text

   ```bash
   # Linux/macOS
   lsof -i :8000 | grep LISTEN
   kill <pid>
   ```text

2. Change the ports via environment variables:

   ```bash
   VAULTSPEC_PORT=9000 VAULTSPEC_WORKER_PORT=9001 just dev service start gateway
   ```text

   Update `VAULTSPEC_GATEWAY_URL` accordingly:

   ```json
   {
     "env": {
       "VAULTSPEC_GATEWAY_URL": "http://localhost:9000"
     }
   }
   ```text

### Windows: orphaned processes after crash

If the MCP server or gateway crashed without clean shutdown, orphan processes
may hold ports.

```powershell
# Find Python processes from vaultspec
Get-Process -Name python | Where-Object {
    $_.MainModule.FileName -like "*vaultspec*"
} | Stop-Process -Force

# Or kill by port
netstat -ano | findstr ":8000 :8001"
taskkill /F /PID <pid>
```text

### LLM calls fail / "No API key"

Set the appropriate API key for your provider:

```bash
# In your shell or .env file
export ANTHROPIC_API_KEY=sk-ant-...

# Or in the IDE MCP config env block:
{
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```text

The thread will transition to `failed` status if the provider cannot
authenticate. This is expected behavior -- fix the API key and start a new
thread.
