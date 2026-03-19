# Library Validation: FastMCP — 2026-03-08

## Installed Version

Package: `mcp` (includes FastMCP in `mcp.server.fastmcp`)
Source: `.venv/Lib/site-packages/mcp/server/fastmcp/server.py`

---

## 1. FastMCP Constructor

### Library API (from installed source)

```python
class FastMCP(Generic[LifespanResultT]):
    def __init__(
        self,
        name: str | None = None,
        instructions: str | None = None,
        website_url: str | None = None,
        icons: list[Icon] | None = None,
        auth_server_provider: OAuthAuthorizationServerProvider | None = None,
        token_verifier: TokenVerifier | None = None,
        event_store: EventStore | None = None,
        retry_interval: int | None = None,
        *,
        tools: list[Tool] | None = None,
        debug: bool = False,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
        host: str = "127.0.0.1",
        port: int = 8000,
        mount_path: str = "/",
        sse_path: str = "/sse",
        message_path: str = "/messages/",
        streamable_http_path: str = "/mcp",
        json_response: bool = False,
        stateless_http: bool = False,
        warn_on_duplicate_resources: bool = True,
        warn_on_duplicate_tools: bool = True,
        warn_on_duplicate_prompts: bool = True,
        dependencies: Collection[str] = (),
        lifespan: Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None = None,
        auth: AuthSettings | None = None,
        transport_security: TransportSecuritySettings | None = None,
    ):
```

### Our Usage (`protocols/mcp/server.py:423-469`)

```python
mcp = FastMCP(
    name="vaultspec-orchestrator",
    instructions="...",
    lifespan=_mcp_lifespan,
)
```

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| `name` parameter | CORRECT | String, passed as `"vaultspec-orchestrator"` |
| `instructions` parameter | CORRECT | String, matches API |
| `lifespan` parameter | CORRECT | Takes `Callable[[FastMCP], AbstractAsyncContextManager]`, our `_mcp_lifespan` matches |
| No deprecated params used | CORRECT | No use of removed/deprecated parameters |
| `host`/`port` not set | OK | We run stdio mode, not HTTP; defaults don't matter for stdio |

**Verdict**: CORRECT. No divergence.

---

## 2. Lifespan Context Manager Pattern

### Library API

The `lifespan` parameter expects:

```python
Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]]
```

The `lifespan_wrapper()` function (line 132-143) wraps it for the low-level
MCPServer. The lifespan receives the `FastMCP` instance and must yield
a context value (or `None`).

The yielded value is stored as `lifespan_context` and accessible via
`Context.lifespan_context` in tool handlers.

### Our Usage (`protocols/mcp/server.py:370-421`)

```python
@asynccontextmanager
async def _mcp_lifespan(
    server: FastMCP[None],
) -> AsyncIterator[None]:
    # ... startup logic (gateway auto-start, health check) ...
    try:
        yield
    finally:
        # ... cleanup (shutdown gateway process) ...
```

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Signature matches | CORRECT | `server: FastMCP[None]` matches `FastMCP[LifespanResultT]` with `LifespanResultT=None` |
| Yields `None` | CORRECT | We don't use `lifespan_context` in tools, so yielding `None` is correct |
| Cleanup in `finally` | CORRECT | Gateway process shutdown on exit |
| `@asynccontextmanager` | CORRECT | Required for `AbstractAsyncContextManager` |

**Observation**: We could store the gateway process handle in `lifespan_context`
to make it accessible to tool handlers (e.g., for status reporting), but the
current approach using module-level `_gateway_connected` flag is simpler and
works for our use case.

**Known issue**: GitHub issue #1115 reports that lifespan runs per-request
in some configurations. Our stdio mode is not affected (lifespan runs once
at server start).

**Verdict**: CORRECT. No divergence.

---

## 3. Tool Registration

### Library API

Tools are registered via `@mcp.tool()` decorator on async functions.
Parameters are extracted from the function signature using Pydantic.
The `Context` parameter (if present) is injected automatically.

```python
@mcp.tool()
async def my_tool(arg1: str, arg2: int = 0) -> str:
    """Tool description from docstring."""
    return "result"
```

### Our Usage (`protocols/mcp/server.py:544+`)

```python
@mcp.tool()
async def start_thread(
    initial_message: Annotated[str, Field(description="...")],
    team_preset: Annotated[str | None, Field(description="...")] = None,
    autonomous: Annotated[bool, Field(description="...")] = True,
    workspace_root: Annotated[str | None, Field(description="...")] = None,
) -> str:
    """Start a new multi-agent coding workflow..."""
```

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| `@mcp.tool()` decorator | CORRECT | Matches library API |
| `Annotated[..., Field()]` | CORRECT | Pydantic Field annotations for rich descriptions |
| Return type `str` | CORRECT | FastMCP auto-converts to `TextContent` |
| `ToolError` for errors | CORRECT | `from mcp.server.fastmcp.exceptions import ToolError` |
| No `Context` parameter used | OK | We use module-level state instead; would work either way |
| Async function | CORRECT | All tools are `async def` |

**Best practice note**: The library supports injecting `Context` as a
parameter for access to `ctx.log()`, `ctx.report_progress()`, and
`ctx.lifespan_context`. We don't use this. Adding `ctx: Context` to write
tools would enable MCP progress notifications (PHASE-1d).

**Verdict**: CORRECT. No divergence.

---

## 4. Transport Configuration

### Library API

Three transport modes:

- `"stdio"`: `anyio.run(self.run_stdio_async)` -- used for IDE integration
- `"sse"`: SSE over HTTP (legacy, being deprecated in favor of streamable-http)
- `"streamable-http"`: Modern HTTP transport

### Our Usage (`protocols/mcp/__main__.py`)

We run in stdio mode via `mcp.run(transport="stdio")`.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Stdio mode | CORRECT | Standard for IDE integration |
| No SSE configuration | OK | We don't use SSE mode |
| `streamable_http_path` default `/mcp` | OK | Not relevant for stdio mode |

**DNS rebinding protection**: The installed version auto-enables DNS rebinding
protection when `host` is localhost. Not relevant for stdio mode.

**Verdict**: CORRECT. No divergence.

---

## 5. Summary

| Area | Status | Action Needed |
|------|--------|---------------|
| Constructor usage | CORRECT | None |
| Lifespan pattern | CORRECT | None |
| Tool registration | CORRECT | Consider adding `Context` parameter for PHASE-1d |
| Transport config | CORRECT | None |
| Deprecated API usage | NONE FOUND | None |
| Missing best practices | `Context` injection | LOW priority enhancement |

**Overall**: Our FastMCP usage is fully aligned with the installed library API.
No deprecated patterns, no divergences, no missed best practices (beyond the
optional `Context` injection for tool-level logging).
