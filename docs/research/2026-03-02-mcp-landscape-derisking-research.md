---
name: 'MCP Landscape Derisking'
date: 2026-03-02
type: research
summary: 'Deep-dive on MCP transport, validation, errors, resources, lifespan, and sampling to derisk upcoming coding tasks.'
maturity: 80
feature: mcp-landscape
---

## Research: MCP Landscape Deep-Dive for Coding Task Derisking

**Date**: 2026-03-02
**Status**: Complete
**Requested by**: team-lead

---

## 1. MCP Transport Layer: stdio vs SSE vs Streamable HTTP

### 1.1 Transport Options

FastMCP supports three transport mechanisms:

| Transport         | Invocation                             | Use Case                                                      |
| ----------------- | -------------------------------------- | ------------------------------------------------------------- |
| `stdio` (default) | `mcp.run()`                            | Subprocess integration (IDE launches server as child process) |
| `sse`             | `mcp.run(transport="sse")`             | Legacy streaming; superseded by streamable-http               |
| `streamable-http` | `mcp.run(transport="streamable-http")` | Production HTTP deployment (recommended)                      |

### 1.2 FastMCP Default

**`stdio` is the default.** When an IDE (Claude Code, Cursor, Windsurf) launches
an MCP server, it spawns the server as a subprocess and communicates over
stdin/stdout using JSON-RPC 2.0 messages. This is the standard integration path
for local development tools.

```python
# Default — stdio transport, launched as subprocess by IDE
if __name__ == "__main__":
    mcp.run()  # stdio

# Production — HTTP transport, deployed as network service
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```text

### 1.3 Subprocess Deployment Gotchas

When the MCP server runs as a **subprocess** (stdio):

- **No concurrent requests**: stdio is serial. The IDE sends one request at a
  time and waits for the response. Tool calls cannot overlap.
- **Process lifecycle**: The IDE owns the process. Server crash = total failure.
  No automatic restart unless the IDE implements it.
- **No shared state across clients**: Each IDE instance gets its own server
  process. No cross-client coordination.
- **Logging must avoid stdout**: Any `print()` or stdout logging corrupts the
  JSON-RPC stream. Use stderr or structured logging to a file.
- **Startup cost**: Every tool call goes through the same long-lived process,
  but the process must initialize on first launch (imports, DB connections, etc.).
  The lifespan pattern (Section 5) handles this.

### 1.4 Network Service Deployment Gotchas

When deployed as a **streamable-http** service:

- **Stateless vs stateful**: `stateless_http=True` disables session persistence.
  Each request is independent. Recommended for scalability.
- **JSON vs SSE responses**: `json_response=True` returns plain JSON instead of
  SSE streams. Simpler for tools that return single results.
- **CORS and auth**: Must be handled at the HTTP layer. FastMCP does not provide
  built-in authentication.
- **Port conflicts**: Default port must be configured; no auto-discovery.

```python
# Recommended production config
mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)
```text

### 1.5 Recommendation for Vaultspec

**Use stdio for IDE integration** (current approach is correct). The MCP server
acts as a thin proxy to the REST API, so it needs no persistent state of its own.
If we later need a shared MCP endpoint for multiple clients, switch to
`streamable-http` with `stateless_http=True`.

---

## 2. MCP Tool Input Validation

### 2.1 FastMCP Auto-Validation

FastMCP **automatically validates** parameter types from Python function
signatures. The SDK:

1. Inspects the function signature and type annotations
2. Generates a JSON Schema (`inputSchema`) from the annotations
3. Validates incoming `tools/call` arguments against that schema
4. Rejects invalid calls with a JSON-RPC `-32602` (Invalid Params) error

```python
@mcp.tool()
async def start_thread(initial_message: str, count: int = 5) -> str:
    ...
# Generates: {"type":"object","properties":{"initial_message":{"type":"string"},
#              "count":{"type":"integer","default":5}},"required":["initial_message"]}
```text

### 2.2 How Type Errors Surface

When a client sends invalid arguments:

- **Missing required param**: JSON-RPC error `-32602` with message indicating
  the missing field. This is a **protocol error** — the LLM sees it and may
  retry.
- **Wrong type**: JSON-RPC error `-32602`. E.g., sending `"abc"` for an `int`
  parameter.
- **Extra unknown params**: Silently ignored by default (JSON Schema does not
  enforce `additionalProperties: false` unless explicitly set).

### 2.3 Enhanced Validation with Pydantic

For richer validation, use Pydantic models as parameter types:

```python
from pydantic import BaseModel, Field

class ThreadRequest(BaseModel):
    initial_message: str = Field(min_length=1, max_length=32000)
    team_preset: str | None = None

@mcp.tool()
async def start_thread(request: ThreadRequest) -> str:
    ...
```text

This gives us Pydantic validation (min/max length, regex, etc.) with automatic
JSON Schema generation.

### 2.4 Recommendation for Vaultspec

Current approach (raw function params with manual validation) works but misses
the opportunity for schema-level constraints. Consider migrating to Pydantic
input models for tools that have complex validation (e.g., `start_thread`
message size cap could be a `Field(max_length=32000)` instead of manual check).

---

## 3. MCP Error Codes and Structured Errors

### 3.1 Two Error Categories

The MCP spec defines two distinct error surfaces:

**Protocol Errors** — JSON-RPC error responses (the call itself failed):

| Code                 | Name               | When                                    |
| -------------------- | ------------------ | --------------------------------------- |
| `-32700`             | Parse Error        | Malformed JSON                          |
| `-32600`             | Invalid Request    | Missing required JSON-RPC fields        |
| `-32601`             | Method Not Found   | Unknown tool name                       |
| `-32602`             | Invalid Params     | Parameter validation failure            |
| `-32603`             | Internal Error     | Server implementation bug               |
| `-32002`             | Resource Not Found | MCP-specific: requested resource absent |
| `-32000` to `-32099` | Server Error       | Implementation-specific errors          |

**Tool Execution Errors** — successful JSON-RPC response with `isError: true`:

```json
{
  "result": {
    "content": [{ "type": "text", "text": "Thread 'abc' not found." }],
    "isError": true
  }
}
```text

### 3.2 When to Use Which

The spec is explicit:

> **Tool Execution Errors** contain actionable feedback that language models
> can use to self-correct and retry with adjusted parameters.
> **Protocol Errors** indicate issues with the request structure itself that
> models are less likely to be able to fix.

| Failure Mode           | Error Type                       | Rationale                       |
| ---------------------- | -------------------------------- | ------------------------------- |
| Unknown tool name      | Protocol (`-32601`)              | Handled by SDK automatically    |
| Wrong param type       | Protocol (`-32602`)              | Handled by SDK automatically    |
| Thread not found       | Tool execution (`isError: true`) | LLM can retry with different ID |
| API server unreachable | Tool execution (`isError: true`) | LLM can inform user             |
| Rate limited           | Tool execution (`isError: true`) | LLM can wait and retry          |
| Internal server error  | Protocol (`-32603`)              | Unrecoverable                   |

### 3.3 How FastMCP Surfaces Tool Execution Errors

In FastMCP, returning a string from a tool function produces a successful
result. To signal an error, the tool should raise an exception or return
an error-formatted string. FastMCP catches exceptions and converts them to
`isError: true` responses automatically.

```python
# Option 1: Raise an exception (FastMCP wraps it as isError: true)
@mcp.tool()
async def get_thread(thread_id: str) -> str:
    raise ValueError(f"Thread {thread_id!r} not found")

# Option 2: Return error string (but isError is NOT set — LLM sees success)
@mcp.tool()
async def get_thread(thread_id: str) -> str:
    return f"Error: Thread {thread_id!r} not found"
```yaml

**Critical finding**: Our current tools return error strings (e.g.,
`return f"Error: ..."`) which do NOT set `isError: true`. The LLM sees
these as successful results. This may cause the LLM to treat errors as
valid data. We should raise exceptions for error conditions so FastMCP
sets `isError: true` properly.

### 3.4 Recommendation for Vaultspec

1. **Raise exceptions for tool errors** instead of returning error strings.
   FastMCP will set `isError: true` and the LLM gets proper error signaling.
2. **Use descriptive error messages** — the LLM reads them to decide what to do.
3. **No custom error codes needed** — protocol errors are handled by the SDK;
   tool errors use `isError: true` with text content.

---

## 4. MCP Resources vs Tools

### 4.1 Core Distinction

| Aspect              | Resources                               | Tools                           |
| ------------------- | --------------------------------------- | ------------------------------- |
| **Control**         | Application-driven (user/host decides)  | Model-driven (LLM decides)      |
| **Analogy**         | GET requests (read data)                | POST requests (perform actions) |
| **Side effects**    | None (read-only)                        | May have side effects           |
| **Discovery**       | `resources/list` + URI templates        | `tools/list`                    |
| **Invocation**      | `resources/read` by URI                 | `tools/call` by name            |
| **Context loading** | Loaded into context before conversation | Called during conversation      |

### 4.2 When to Use Resources

Use resources when:

- Data should be loaded **before** the LLM starts reasoning (context priming)
- The **user or application** should control what data is available
- Data is **read-only** with no side effects
- Data has a natural **URI** (files, configs, database records)

Examples for vaultspec:

- `vaultspec://presets/teams/{team_id}` — team preset TOML content
- `vaultspec://presets/agents/{agent_id}` — agent definition content
- `vaultspec://threads/{thread_id}/plan` — current plan for a thread

### 4.3 When to Use Tools

Use tools when:

- The **LLM** should decide when to invoke the operation
- The operation has **side effects** (create, cancel, send message)
- The operation requires **parameters** that the LLM constructs
- Results are needed **during** reasoning, not before

Examples for vaultspec: all current tools (start_thread, send_message, etc.)

### 4.4 Discoverability Differences

- **Resources**: Clients call `resources/list` to get URIs. The list can be
  static or dynamic. Supports URI templates (`vaultspec://threads/{id}`) for
  parameterized access. Resources can also be **subscribed to** for change
  notifications.
- **Tools**: Clients call `tools/list` to get tool definitions. The LLM sees
  tool descriptions in its system prompt and self-selects.

Key difference: resources are **opt-in by the user/app** (the user picks which
resources to load), while tools are **opt-in by the LLM** (the LLM picks which
tools to call).

### 4.5 Recommendation for Vaultspec

**Phase 1 (current)**: Tools only. Our MCP server is a proxy to REST endpoints
where the LLM drives all interactions. This is correct.

**Phase 2 (future)**: Add resources for read-only context:

- Team preset definitions as resources (IDE can show them in sidebar)
- Agent definitions as resources
- Thread state snapshots as resources (for context priming)

Resources would complement tools, not replace them. The IDE loads resources
for context; the LLM calls tools for actions.

---

## 5. FastMCP Lifespan Management

### 5.1 The Pattern

FastMCP provides a **lifespan** async context manager for managing long-lived
resources (database connections, HTTP clients, etc.):

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

@dataclass
class AppContext:
    http_client: httpx.AsyncClient

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    async with httpx.AsyncClient() as client:
        yield AppContext(http_client=client)

mcp = FastMCP("vaultspec-orchestrator", lifespan=app_lifespan)

@mcp.tool()
async def start_thread(
    initial_message: str,
    ctx: Context[ServerSession, AppContext],
) -> str:
    client = ctx.request_context.lifespan_context.http_client
    resp = await client.post(...)
    ...
```text

### 5.2 How It Works

1. When the MCP server starts, `app_lifespan` runs up to the `yield`.
2. The yielded `AppContext` is stored and accessible to all tool functions via
   `ctx.request_context.lifespan_context`.
3. When the server shuts down, cleanup runs after the `yield` (e.g., closing
   the HTTP client).

### 5.3 Current Vaultspec State

Our MCP server currently creates a **shared `httpx.AsyncClient`** at module
level (from MCP-05 fix). The lifespan pattern is the official SDK way to do
this and provides:

- Proper async initialization (module-level `AsyncClient()` may miss event loop)
- Guaranteed cleanup on shutdown
- Type-safe context access in tools

### 5.4 Recommendation for Vaultspec

**Migrate to lifespan pattern.** Replace the module-level shared client with
a lifespan-managed `AppContext` containing:

- `httpx.AsyncClient` — shared HTTP client for REST API calls
- `api_base_url: str` — from settings, avoiding repeated access
- Any future shared state (caches, connection pools)

This is a small refactor with significant correctness benefits.

---

## 6. MCP Sampling / Server-to-Client LLM Requests

### 6.1 What Sampling Is

MCP sampling allows the **server** to request an LLM completion from the
**client**. The server sends a `SamplingMessage` and the client's LLM
generates a response.

```python
from mcp.types import SamplingMessage, TextContent

@mcp.tool()
async def summarize(text: str, ctx: Context[ServerSession, None]) -> str:
    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=f"Summarize: {text}"),
            )
        ],
        max_tokens=200,
    )
    return result.content.text
```text

### 6.2 Configuration Options

```python
result = await ctx.session.create_message(
    messages=[...],
    max_tokens=500,
    system_prompt="You are a helpful assistant",
    temperature=0.7,
    stop_sequences=["\n\n"],
    model_preferences=ModelPreferences(hints=[ModelHint(name="claude-3")])
)
```text

### 6.3 Client Support

Sampling requires the client to implement a **sampling callback**:

```python
async def sampling_callback(context, params) -> CreateMessageResult:
    # Client decides how to handle the LLM request
    return CreateMessageResult(model="...", role="assistant", content=...)
```yaml

**Critical caveat**: Not all MCP clients support sampling. Claude Code and
Cursor may not implement the sampling callback. If the client doesn't support
it, `create_message` will fail.

### 6.4 Use Cases for Vaultspec

| Use Case                                      | Feasibility  | Notes                                   |
| --------------------------------------------- | ------------ | --------------------------------------- |
| Summarize thread status                       | Low priority | Our tools already return formatted text |
| Generate thread title from message            | Interesting  | Could improve UX but adds latency       |
| Classify task complexity for preset selection | Interesting  | But adds a round-trip                   |

### 6.5 Recommendation for Vaultspec

**Do not use sampling in v1.** The client support is uncertain and our tools
are simple REST proxies that don't need LLM assistance. Revisit if we add
tools that need to reason about their input (e.g., auto-selecting team preset
based on task description).

---

## 7. Summary of Recommendations

| Topic            | Recommendation                                                       | Priority |
| ---------------- | -------------------------------------------------------------------- | -------- |
| Transport        | Keep stdio (current); document streamable-http for future deployment | LOW      |
| Input validation | Consider Pydantic input models for complex tools                     | MEDIUM   |
| Error handling   | **Raise exceptions instead of returning error strings**              | HIGH     |
| Resources        | Add in Phase 2 for read-only context (presets, agents, plans)        | LOW      |
| Lifespan         | **Migrate to official lifespan pattern** for shared httpx client     | MEDIUM   |
| Sampling         | Do not use in v1; revisit later                                      | LOW      |

---

## 8. Sources

- [MCP Python SDK README](https://github.com/modelcontextprotocol/python-sdk) — FastMCP transport, lifespan, sampling examples
- [MCP Specification: Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) — tool schema, error handling, structured output
- [MCP Error Codes](https://www.mcpevals.io/blog/mcp-error-codes) — JSON-RPC error code reference
- [MCP Resources vs Tools](https://medium.com/@laurentkubaski/mcp-resources-explained-and-how-they-differ-from-mcp-tools-096f9d15f767) — comparison guide
- [MCP Resources Spec](https://modelcontextprotocol.io/specification/2025-06-18/server/resources) — resource discovery and URI templates
- [MCP Best Practices](https://modelcontextprotocol.info/docs/best-practices/) — architecture and implementation guide
- [Error Handling in MCP Tools](https://apxml.com/courses/getting-started-model-context-protocol/chapter-3-implementing-tools-and-logic/error-handling-reporting) — tool error patterns
