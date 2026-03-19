# FastMCP Lifespan and Transport Research — 2026-03-08

## Context

VaultSpec A2A's MCP server uses FastMCP (from the `mcp` package) with a custom
lifespan that auto-starts the gateway subprocess. This document researches
FastMCP's lifespan pattern, transport internals, and caveats for embedding in
existing applications.

**Related documents:**

- `2026-03-08-library-validation-fastmcp.md` — API validation against installed source
- `2026-03-08-subprocess-coordination-patterns.md` — Process lifecycle patterns

**Source:** Validated against installed source at
`.venv/Lib/site-packages/mcp/server/fastmcp/server.py`

---

## 1. FastMCP Lifespan Pattern

### 1.1 Type Signature

```python
lifespan: Callable[
    [FastMCP[LifespanResultT]],
    AbstractAsyncContextManager[LifespanResultT]
] | None = None
```

The lifespan is a callable that:

- Receives the `FastMCP` instance as its sole argument
- Returns an async context manager
- The context manager yields a value of type `LifespanResultT`
- The yielded value becomes `Context.lifespan_context` in tool handlers

### 1.2 How FastMCP Wraps the Lifespan

The `lifespan_wrapper()` function (server.py line 132-143) adapts the FastMCP
lifespan to the lower-level `MCPServer` lifespan:

```python
def lifespan_wrapper(
    app: FastMCP[LifespanResultT],
) -> Callable[[MCPServer], AbstractAsyncContextManager[object]]:
    @asynccontextmanager
    async def wrapper(server: MCPServer) -> AsyncIterator[object]:
        async with app._lifespan_manager(app) as context:
            yield context
    return wrapper
```

**Key insight:** FastMCP stores the user's lifespan in `_lifespan_manager`.
If no lifespan is provided, `_lifespan_manager` defaults to a no-op context
manager that yields `None`.

### 1.3 Our Usage

```python
@asynccontextmanager
async def _mcp_lifespan(
    server: FastMCP[None],
) -> AsyncIterator[None]:
    """MCP server lifespan — auto-start gateway, health-check, cleanup."""
    # Startup: spawn gateway subprocess, wait for health
    gateway_proc = await _spawn_gateway()
    await _wait_for_health(gateway_url)
    _gateway_connected = True

    try:
        yield  # Server runs here
    finally:
        # Cleanup: kill gateway process tree
        await _shutdown_gateway_process(gateway_proc)
        _gateway_connected = False

mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions="...",
    lifespan=_mcp_lifespan,
)
```

**Validation:** Signature matches. `FastMCP[None]` matches `FastMCP[LifespanResultT]`
with `LifespanResultT=None`. Yielding `None` is correct since we don't use
`lifespan_context` in tool handlers.

### 1.4 Accessing Lifespan Context in Tools

If we wanted to pass the gateway process handle to tools:

```python
@asynccontextmanager
async def _mcp_lifespan(server: FastMCP[dict]) -> AsyncIterator[dict]:
    gateway_proc = await _spawn_gateway()
    yield {"gateway_proc": gateway_proc, "gateway_url": gateway_url}
    # cleanup...

@mcp.tool()
async def my_tool(ctx: Context) -> str:
    gateway_url = ctx.lifespan_context["gateway_url"]
    # ...
```

**Current decision:** We use module-level `_gateway_connected` flag instead.
Simpler and sufficient for boolean connected/disconnected state.

### 1.5 Known Issue: Per-Request Lifespan

GitHub issue #1115 reports that in some HTTP transport configurations, the
lifespan runs per-request rather than once at server start. This does NOT
affect stdio mode (our transport). The lifespan runs exactly once.

---

## 2. Transport Internals

### 2.1 `run_stdio_async()`

Source: `server.py` line 383-395

```python
async def run_stdio_async(self) -> None:
    async with stdio_server(
        self._transport_options.get("stdin", None),
        self._transport_options.get("stdout", None),
    ) as (read_stream, write_stream):
        await self._mcp_server.run(
            read_stream,
            write_stream,
            self._mcp_server.create_initialization_options(),
        )
```

**Internals:**

1. `stdio_server()` is an async context manager from `mcp.server.stdio`
2. It wraps `sys.stdin` and `sys.stdout` in `anyio.abc.ByteStream` adapters
3. `read_stream` reads JSON-RPC messages from stdin (line-delimited)
4. `write_stream` writes JSON-RPC responses to stdout
5. `MCPServer.run()` enters the main message processing loop

**Our entry point** (`protocols/mcp/__main__.py`):

```python
mcp.run(transport="stdio")
```

This calls `anyio.run(self.run_stdio_async)`, which creates a new event loop
and runs the stdio transport until stdin closes (IDE disconnects).

### 2.2 `run_streamable_http_async()`

Source: `server.py` line 397-430

```python
async def run_streamable_http_async(self) -> None:
    config = uvicorn.Config(
        self.streamable_http_app(),
        host=self._host,
        port=self._port,
        log_level=self._log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()
```

**Critical caveat:** This method **unconditionally starts its own uvicorn
instance**. You cannot embed a streamable-http FastMCP server inside an
existing FastAPI/Starlette application by calling this method — it creates
a separate HTTP server on its own port.

### 2.3 `streamable_http_app()` — Embeddable Starlette App

Source: `server.py` line 432-480

```python
def streamable_http_app(self) -> Starlette:
    """Create a Starlette app for streamable HTTP transport."""
    session_manager = StreamableHTTPSessionManager(
        app=self._mcp_server,
        # ...
    )

    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send,
    ) -> None:
        await session_manager.handle_request(scope, receive, send)

    app = Starlette(
        routes=[Mount(self._streamable_http_path, app=handle_streamable_http)],
        lifespan=...,
    )
    return app
```

**Key insight:** This returns a raw Starlette app that CAN be mounted into an
existing application:

```python
# Hypothetical embedding in our gateway:
from starlette.routing import Mount

mcp_app = mcp.streamable_http_app()
gateway_app.mount("/mcp", mcp_app)
```

This would allow exposing MCP over HTTP alongside the REST API on the same
port. However, we currently run MCP over stdio (for IDE integration), so this
is not needed.

### 2.4 SSE Transport (Legacy)

Source: `server.py` line 350-380

The SSE transport is the older HTTP transport being superseded by
streamable-http. It uses Server-Sent Events for server-to-client messages
and POST requests for client-to-server messages.

**Not relevant to our implementation.** We use stdio only.

### 2.5 Transport Selection

```python
def run(self, transport: str = "stdio") -> None:
    match transport:
        case "stdio":
            anyio.run(self.run_stdio_async)
        case "sse":
            anyio.run(self.run_sse_async)
        case "streamable-http":
            anyio.run(self.run_streamable_http_async)
```

All three transports call `anyio.run()`, which creates a new event loop. This
means `mcp.run()` is a blocking call that owns the event loop. You cannot call
it from within an existing async application.

---

## 3. Caveats for Embedding in Existing Applications

### 3.1 `mcp.run()` Owns the Event Loop

`mcp.run()` calls `anyio.run()` which creates a new event loop. If you're
already inside an async application (e.g., FastAPI), you cannot call
`mcp.run()` — it will fail because an event loop is already running.

**Workaround for HTTP:** Use `mcp.streamable_http_app()` to get a Starlette
app and mount it.

**Workaround for stdio:** Run `mcp.run(transport="stdio")` in a separate
thread or process.

### 3.2 Streamable HTTP Starts Its Own Uvicorn

`run_streamable_http_async()` unconditionally creates a `uvicorn.Server` and
calls `server.serve()`. There is no way to use this method within an existing
uvicorn process. You must use `streamable_http_app()` instead.

### 3.3 Lifespan Runs Inside the Transport

The lifespan is nested inside the transport context. The startup/shutdown
sequence is:

```
mcp.run() → anyio.run()
  → run_stdio_async() / run_streamable_http_async()
    → MCPServer.run()
      → lifespan_wrapper()
        → _mcp_lifespan() [our code]
          → yield  ← server processes messages here
        → cleanup
```

This means:

- Lifespan startup runs AFTER the transport is connected
- Lifespan cleanup runs BEFORE the transport disconnects
- For stdio: lifespan runs once per stdin connection (IDE session)
- For HTTP: lifespan should run once per server lifetime (but see issue #1115)

### 3.4 DNS Rebinding Protection (HTTP only)

The installed version auto-enables DNS rebinding protection when `host` is
`localhost` or `127.0.0.1`. Not relevant for stdio mode.

---

## 4. Tool Registration

### 4.1 `@mcp.tool()` Decorator

```python
@mcp.tool()
async def start_thread(
    initial_message: Annotated[str, Field(description="...")],
    team_preset: Annotated[str | None, Field(description="...")] = None,
) -> str:
    """Docstring becomes the tool description."""
    return "result"
```

FastMCP extracts:

- Tool name from function name
- Description from docstring
- Parameters from function signature (Pydantic model generated)
- `Annotated[..., Field(description="...")]` for parameter descriptions
- Return type: `str` auto-converted to `TextContent`

### 4.2 Error Handling

```python
from mcp.server.fastmcp.exceptions import ToolError

@mcp.tool()
async def my_tool() -> str:
    if not healthy:
        raise ToolError("Gateway is not running. Start with: uv run vaultspec service start")
    return "result"
```

`ToolError` is caught by FastMCP and returned as an MCP error response (not
an unhandled exception). This is the correct way to report tool-level errors
to the IDE.

### 4.3 Context Injection (Optional)

```python
from mcp.server.fastmcp import Context

@mcp.tool()
async def my_tool(ctx: Context) -> str:
    ctx.log("info", "Processing request...")
    await ctx.report_progress(50, 100)
    gateway = ctx.lifespan_context  # Access lifespan yield value
    return "result"
```

We don't currently use `Context` injection. Our tools use module-level state
(`_gateway_connected`, `_mcp_settings`). Adding `Context` would enable MCP
progress notifications (potential PHASE-1d enhancement).

---

## 5. Recommendations

| Priority | Recommendation | Rationale |
|----------|---------------|-----------|
| — | Keep stdio transport | Standard for IDE integration, no embedding issues |
| — | Keep module-level gateway state | Simpler than lifespan_context for boolean state |
| LOW | Add `Context` to write tools | Enables MCP progress notifications |
| LOW | Consider `streamable_http_app()` mount | Future: expose MCP over HTTP alongside REST API |
| — | Never use `run_streamable_http_async()` in existing apps | Starts its own uvicorn, conflicts with existing server |

---

## 6. Sources

- FastMCP source: `.venv/Lib/site-packages/mcp/server/fastmcp/server.py`
- MCP stdio transport: `.venv/Lib/site-packages/mcp/server/stdio.py`
- Streamable HTTP: `.venv/Lib/site-packages/mcp/server/streamable_http.py`
- GitHub issue #1115: Per-request lifespan in HTTP mode
- Our implementation: `src/vaultspec_a2a/protocols/mcp/server.py`
