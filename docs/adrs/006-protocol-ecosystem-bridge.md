---
adr_id: 006
title: Protocol Ecosystem & Bridge Strategy (LangGraph vs MCP)
date: 2026-02-26
status: Proposed
related:
  - docs/distilled/2026-25-02-protocols-distilled.md
  - docs/research/2026-26-02-langgraph-gap-audit-research.md
---

# ADR-006: Protocol Ecosystem & Bridge Strategy (LangGraph vs MCP)

**Date:** 2026-02-26  
**Status:** Proposed

## 1. Context & Problem Statement

The ecosystem presents several competing protocols for agent workflows: A2A
(Agent-to-Agent), ACP (Agent Client Protocol), and MCP (Model Context
Protocol). Previously, we attempted to bridge all three by using A2A for
inter-agent routing, ACP for UI state extraction via wrapper processes, and
MCP for tool execution. This proven to be architecturally fragile,
particularly on Windows, due to process management and opaque CLI outputs.

We must decide on a simplified, robust protocol architecture that provides
stateful multi-agent orchestration while remaining compatible with standard
tooling ecosystems.

## 2. The Decision

We completely abandon the A2A and ACP protocol integrations in favor of a
native LangGraph architecture, with MCP serving strictly as the boundary
protocol:

1. **Core Internal Engine:** **LangGraph** replaces A2A as the authoritative
   mechanism for how agents discover, interact, and delegate tasks to one
   another. The overarching orchestration, state machine logic, and message
   routing occur entirely via native Python graph edges and
   `Command(goto="node")` returns, totally bypassing network-level SSE
   protocol translations for internal routing.
2. **Tool Execution Boundary:** **MCP** (Model Context Protocol) is retained
   exclusively for standardized tool execution at the system boundaries.
   - **Consuming Tools:** Individual LangGraph nodes (Agents) can consume
     tools exposed by remote or local MCP Servers.
   - **Exposing the Orchestrator:** The Orchestrator itself runs an MCP
     Server to allow external IDEs (Cursor, Windsurf) to trigger specific
     LangGraph workflows as if they were simple tools.
3. **Hybrid ACP-LangGraph Bridging (`AcpChatModel`):** Rather than abandoning
   the CLIs entirely (which violates the flat-rate consumer OAuth constraints
   established in ADR-002), we build `AcpChatModel` (`lib/providers/acp_chat_model.py`)
   — a custom `BaseChatModel` that spawns provider CLIs as managed stdio
   subprocesses and translates their JSON-RPC streams into native LangChain
   `AIMessageChunk`s and `ToolCallChunk`s. This preserves the LangChain
   telemetry loop (`astream_events`) for the UI while retaining the cost
   benefits of consumer CLIs.
   - **Claude:** Invoked as `node.exe <resolved dist/index.js path>` —
     never via the `.CMD` shim or `cmd.exe /c`. `CLAUDE_CODE_OAUTH_TOKEN`
     injected via subprocess `env`.
   - **Gemini:** Invoked as `gemini --experimental-acp` via
     `create_subprocess_shell`. Gemini deploys as a `.CMD` npm shim
     (not a native `.exe`), but the shell resolves it natively. Zero
     credential injection — Gemini CLI uses `~/.gemini/oauth_creds.json`.
   - **Zero PTY:** Both CLIs are spawned with `stdin=PIPE, stdout=PIPE,
stderr=PIPE` and no terminal allocation. `cmd.exe` is never in the
     process chain.
4. **Native Human-in-the-Loop:** Instead of relying on ACP's Permission
   Broker to halt processes for user input, we rely on LangGraph's native
   `interrupt` exceptions. When a tool requires approval, the node raises an
   `interrupt`, the graph suspends safely to SQLite, and resumes only when
   the frontend submits the approval via the REST API.

## 3. Rationale

- **Architectural Simplicity:** Eliminating A2A and ACP removes thousands of
  lines of fragile translation code. LangGraph natively solves the state
  management and multi-agent routing problems that A2A and ACP attempted to
  address at the networking layer.
- **Visibility and Telemetry:** Using native LangChain LLM wrappers directly
  in the unified Uvicorn process allows the Event Aggregator to stream
  high-fidelity `astream_events` (tool starts, token generation) to the UI
  without the opacity of a third-party CLI wrapper.
- **Native Interrupt Security:** Suspending a LangGraph state machine to
  disk via `interrupt` is infinitely more robust than leaving an OS
  subprocess blocked on an open `stdin` pipe waiting for user approval
  (which often caused timeouts).

## 4. Rejected Alternatives

- **A2A (Agent-to-Agent Protocol):** Rejected. While Google's A2A SDK is
  powerful, bringing it alongside LangGraph is highly redundant. LangGraph's
  multi-agent supervisor/worker patterns handle delegation more natively
  within the Python ecosystem.
- **ACP as an independent orchestration layer:** Rejected. ACP's role as a
  first-class protocol is eliminated. The CLIs _are_ still executed as
  subprocesses, but only as private implementation details of `AcpChatModel`
  — they are not visible to the orchestration graph as separate actors. ACP
  JSON-RPC is consumed internally within the wrapper and surfaced to
  LangGraph exclusively as LangChain message objects.

## 5. Implementation Constraints & Pitfalls

- **MCP Tool Mapping:** Exposing a complex LangGraph workflow (which might
  take 10 minutes and human interaction) as a synchronous MCP tool to a
  client like Cursor requires careful timeout management. The MCP server must
  immediately return a "Task Started, track progress at [URL]" response
  rather than holding the MCP connection open indefinitely.
- **Callback Flood:** Directly capturing LangChain events can flood the
  frontend. We must strictly filter `astream_events` to only broadcast
  relevant updates (e.g., `on_chat_model_stream`, `on_tool_start`) and drop
  internal graph routing noise.

### 5.1 `AcpChatModel` Subprocess Patterns (Empirically Verified)

The following patterns were validated end-to-end on Windows 11. All future
implementors **must** follow them exactly:

1. **`asyncio.create_subprocess_shell(command_str, ...)`** — NOT
   `create_subprocess_exec`. The command is a **single string** (e.g.,
   `"claude-agent-acp"`). The OS shell resolves `.CMD` wrappers natively.
   `create_subprocess_exec` with a list requires manual `.CMD` / `.EXE`
   resolution and is fragile.

2. **Stream buffer limit:** Always set `limit=10 * 1024 * 1024` (10MB).
   Without this, large ACP JSON payloads (e.g., `session/new` with many
   available commands) cause asyncio `StreamReader` backpressure that
   silently truncates or blocks reads.

3. **Stdin write format:** `process.stdin.write(b"%s\n" %
json.dumps(req).encode("utf-8"))` — exactly as in Toad's `agent.py`. The
   `\n` is the JSON-RPC line delimiter required by the ACP spec.

4. **Stdout reading pattern:** Use the walrus operator: `while line :=
await process.stdout.readline()`. The loop exits naturally on EOF when
   the process terminates.

5. **Bidirectional dispatch:** Stdout messages are either:
   - **(A) Responses** to client-sent requests: contain `"result"` or
     `"error"` → dispatch to `asyncio.Future` waiters keyed by `id`.
   - **(B) Server-to-client notifications**: contain `"method"` (e.g.,
     `"session/update"`) → dispatch to notification handler. These carry
     `agent_message_chunk` streaming content.

6. **ACP session lifecycle:**
   - `initialize` → await response (stores `agentCapabilities`,
     `authMethods`). **Critical:** the `loadSession` capability must be
     checked before attempting `session/load`.
   - `session/new` → await response (stores `sessionId`, extracts `modes`
     including `currentModeId` and `availableModes`).
   - `session/prompt` → await response → `{"stopReason": "end_turn"}`
     signals generation complete.
   - Streaming content arrives as `session/update` **notifications** (no
     `id` field), not as the response to `session/prompt`.
   - `session/cancel` → send as a **proper RPC** (not a notification),
     with a 3-second timeout wait. This matches Toad's `agent.py` line
     795 — `await response.wait()`, not fire-and-forget.

7. **Tool call tracking:** Agent `session/update` notifications with
   `"sessionUpdate": "tool_call"` must be stored in a dict keyed by
   `toolCallId`. Subsequent `tool_call_update` messages are **merged**
   into the original entry (non-None values overwrite). The agent may
   send a `tool_call_update` without a prior `tool_call` — handle by
   creating a synthetic entry (Toad line 277).

8. **`end_turn` detection:** The `session/prompt` **response** (not a
   notification) contains `{"result": {"stopReason": "end_turn"}}`. This is
   the signal that generation is complete. Other valid stop reasons:
   `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`.

9. **Windows pipe cleanup (`_ProactorBasePipeTransport.__del__` fix):** After
   terminating the subprocess, call `process._transport.close()` directly.
   Using `process.wait()` alone leaves pipe transports open until GC,
   triggering a spurious `ValueError: I/O operation on closed pipe` from
   Python's `proactor_events.py`. Using `process.communicate()` deadlocks
   when active reader tasks already hold the streams. The direct
   `_transport.close()` call is the correct fix.

## 6. Negative Consequences

- **Vendor Lock-in (LangChain):** By deeply integrating LangGraph and
  LangChain models, we are heavily coupled to their ecosystem. Implementing a
  custom LLM requires writing a full `BaseChatModel` adapter.
- **ACP Translation Overhead:** Parsing nested JSON-RPC `stdio` pipes and
  reconstructing LangChain's Pydantic objects (`AIMessageChunk`,
  `ToolCallChunk`) introduces parsing overhead and complex asynchronous
  stream handling that native REST SDks typically handle for us.

## 7. References

- [LangGraph Gap Audit Research](../research/2026-02-26-langgraph-gap-audit-research.md)
- [Protocols Domain - Distilled](../research/2026-02-25-protocols-distilled-research.md)
- **Reference Implementation:**
  `knowledge/repositories/toad/src/toad/acp/agent.py` — Toad's
  `_run_agent()` method is the primary reference for all ACP subprocess
  patterns above.
- **Protocol Types:**
  `knowledge/repositories/toad/src/toad/acp/protocol.py` — authoritative
  Python `TypedDict` definitions for all ACP message schemas.
