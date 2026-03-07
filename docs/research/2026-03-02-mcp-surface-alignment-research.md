# MCP Surface Alignment Research

**Date:** 2026-03-02
**Author:** codebase-researcher
**Scope:** Gap analysis between current MCP tool surface and the operations required by
coding CLI/IDE consumers, LangGraph protocol, and A2A protocol.

---

## 1. Current MCP Server — Complete Inventory

**File:** `src/vaultspec_a2a/protocols/mcp/server.py` (278 lines)
**Framework:** `mcp.server.fastmcp.FastMCP`
**Server name:** `vaultspec-orchestrator`

### 1.1 Registered Tools (3 total)

#### `start_thread(initial_message, team_preset=None) → str`

- **REST call:** `POST /api/threads`
- **Payload fields sent:** `title`, `initial_message`, `team_preset`, `autonomous=True` (hardcoded)
- **Returns:** Plain-text string with `thread_id`, preset name, monitor URL, status poll URL
- **Constraints:** `initial_message` capped at 32,000 chars (MCP-01 fix). Preset validated against `_KNOWN_PRESETS` (auto-discovered from TOML at import time via glob).
- **Gaps vs. CreateThreadRequest schema:**
  - `metadata` (workspace_root, feature_tag, source_branch, callee, context_refs, nickname) — not exposed
  - `autonomous` — hardcoded `True`, cannot be overridden by caller
  - `title` — only populated as `initial_message[:80]`, not a caller-supplied field

#### `get_thread_status(thread_id) → str`

- **REST call:** `GET /api/threads/{thread_id}/state`
- **Returns:** Plain-text summary: status, message count, live WS URL
- **Gaps:**
  - Returns only `status` + `msg_count` — no plan, no active agents, no pending permissions
  - No `GET /api/threads` (list) exposure — caller cannot discover existing threads
  - No `GET /api/threads/{id}/metadata` exposure
  - No artifact list, no tool call summary

#### `send_message(thread_id, message) → str`

- **REST call:** `POST /api/threads/{thread_id}/messages`
- **Payload:** `{"content": message}` — no `agent_id`
- **Returns:** Plain-text confirmation
- **Gaps:**
  - `agent_id` not exposed — cannot target a specific agent
  - No size validation (unlike `start_thread`) — `message` is uncapped in the MCP layer (the REST layer caps at 64KB)

### 1.2 Utility Functions

- `_ws_url_from_api_base(api_base_url)` — derives WebSocket URL from REST base. Used only in `get_thread_status` output. Strips credentials from netloc. Not a registered tool.
- `_KNOWN_PRESETS` — frozenset discovered at import time via glob of `_PRESET_TEAMS_DIR`. Falls back to hardcoded `_HARDCODED_PRESETS` with `logger.error` if TOML files not found.

### 1.3 Shared httpx Client

**Finding from prior MCP audit (MCP-05, completed):** The three tools each create `async with httpx.AsyncClient()` inline rather than sharing a module-level client. Connection pooling is not used. This is tracked as resolved but worth noting as context — if a shared client is now present, the gap is closed.

---

## 2. REST Endpoint Inventory (full gateway)

The following REST endpoints exist in `src/vaultspec_a2a/api/endpoints.py`. Only 3 are currently MCP-wrapped.

| Endpoint                    | Method | MCP-Exposed?                | Purpose                                                  |
| --------------------------- | ------ | --------------------------- | -------------------------------------------------------- |
| `/threads`                  | POST   | YES (start_thread)          | Create thread + dispatch to worker                       |
| `/threads`                  | GET    | NO                          | List threads (paginated, with metadata summary)          |
| `/threads/{id}/state`       | GET    | PARTIAL (get_thread_status) | Full state snapshot for reconnection                     |
| `/threads/{id}/metadata`    | GET    | NO                          | Full ThreadMetadata (ADR-014)                            |
| `/threads/{id}/messages`    | POST   | YES (send_message)          | Send follow-up message                                   |
| `/team/status`              | GET    | NO                          | Team agent status + active threads + pending permissions |
| `/teams`                    | GET    | NO                          | List available team presets                              |
| `/permissions/{id}/respond` | POST   | NO                          | Submit permission response (guaranteed delivery)         |

Additionally, the WebSocket endpoint at `/ws` is not MCP-exposed (by design — WS is for real-time streaming, not tool calls).

---

## 3. LangGraph Protocol Operations — What Needs MCP Exposure

Based on ADR-012, ADR-013, and the full endpoint review:

### 3.1 Thread Lifecycle (core workflow)

| Operation                                 | REST Endpoint               | MCP Status | Notes                                               |
| ----------------------------------------- | --------------------------- | ---------- | --------------------------------------------------- |
| Create thread with workspace context      | POST /threads               | PARTIAL    | `metadata` (workspace_root, feature_tag) not passed |
| Create thread with specific preset        | POST /threads               | YES        | `team_preset` is passed                             |
| Create thread supervised (non-autonomous) | POST /threads               | NO         | `autonomous` hardcoded `True`                       |
| List existing threads                     | GET /threads                | NO         | Needed to resume work across IDE sessions           |
| Get thread status + plan                  | GET /threads/{id}/state     | PARTIAL    | Only status+msg_count returned                      |
| Get thread metadata                       | GET /threads/{id}/metadata  | NO         | Workspace provenance for context                    |
| Send follow-up message                    | POST /threads/{id}/messages | YES        | agent_id not exposed                                |

### 3.2 Permission/Interrupt Handling

| Operation                     | REST Endpoint                  | MCP Status | Notes                                               |
| ----------------------------- | ------------------------------ | ---------- | --------------------------------------------------- |
| Respond to permission request | POST /permissions/{id}/respond | NO         | Critical: non-autonomous threads block without this |
| Get pending permissions       | GET /team/status               | NO         | Caller needs to know what's pending                 |

### 3.3 Team/Preset Discovery

| Operation                   | REST Endpoint       | MCP Status | Notes                                                                                                    |
| --------------------------- | ------------------- | ---------- | -------------------------------------------------------------------------------------------------------- |
| List available team presets | GET /teams          | NO         | MCP server hardcodes preset discovery from TOML glob but does not expose the full TeamPresetSummary data |
| Describe a specific preset  | GET /teams (filter) | NO         | No per-preset detail endpoint exists yet                                                                 |

### 3.4 Agent Control

| Operation               | REST Endpoint                 | MCP Status | Notes                       |
| ----------------------- | ----------------------------- | ---------- | --------------------------- |
| Cancel a running thread | WS AGENT_CONTROL.TERMINATE    | NO         | No REST equivalent; only WS |
| Pause/resume agent      | WS AGENT_CONTROL.PAUSE/RESUME | NO         | No REST equivalent; only WS |

---

## 4. A2A Protocol Surface — Mandatory Operations

From `knowledge/repositories/A2A/docs/`:

The A2A protocol mandates these core operations for a compliant agent server:

| A2A Concept                                        | Vaultspec Equivalent                        | Gap                                                |
| -------------------------------------------------- | ------------------------------------------- | -------------------------------------------------- |
| `AgentCard` at `/.well-known/agent.json`           | None                                        | Missing — A2A discovery endpoint not implemented   |
| `SendMessage` (start new task or continue)         | POST /threads + POST /threads/{id}/messages | Partial — no contextId grouping                    |
| `GetTask` (poll task status)                       | GET /threads/{id}/state                     | Partial — mapped loosely, no formal Task object    |
| `CancelTask`                                       | No REST endpoint                            | Missing — only WS AGENT_CONTROL.TERMINATE          |
| `TaskResubscribe` (SSE stream)                     | WebSocket /ws                               | Present but different protocol (WS not SSE)        |
| `input-required` state → client must provide input | POST /permissions/{id}/respond              | Present but not MCP-wrapped                        |
| `contextId` grouping of related tasks              | No explicit contextId field                 | Missing — thread_id serves this purpose implicitly |
| Artifacts as formal outputs                        | ArtifactUpdateEvent + ArtifactSnapshot      | Present in wire schema, no MCP tool to retrieve    |

**A2A operations not mandated by the protocol but highly relevant for coding agents:**

- Listing tasks/threads by contextId (workspace session correlation)
- Streaming artifact content incrementally
- Attaching file Parts to messages (binary/URL part types)

---

## 5. Gap Analysis

### 5A — Missing MCP Tools (high priority first)

| #   | Tool Name                 | REST Endpoint Wrapped          | Priority | Rationale                                                                                                                                                                                                   |
| --- | ------------------------- | ------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `list_threads`            | GET /threads                   | HIGH     | Cursor/IDE needs to discover existing threads to resume work; without this, every session starts blind                                                                                                      |
| 2   | `respond_to_permission`   | POST /permissions/{id}/respond | HIGH     | Non-autonomous threads (supervised mode) will block indefinitely without this; MCP consumers cannot unblock them                                                                                            |
| 3   | `list_team_presets`       | GET /teams                     | MEDIUM   | Currently MCP server discovers presets via internal glob but returns them only as a validation set in `start_thread` docstring — callers have no way to enumerate presets with descriptions + topology info |
| 4   | `cancel_thread`           | None (WS only)                 | MEDIUM   | Need a REST endpoint first: `POST /threads/{id}/cancel` — then wrap it. Without this, MCP consumers cannot terminate runaway agents                                                                         |
| 5   | `get_pending_permissions` | GET /team/status (partial)     | MEDIUM   | team/status returns pending_permissions=[] always (TODO in endpoints.py:658) — needs worker wiring first, then MCP exposure                                                                                 |

### 5B — Missing REST Endpoints (that MCP tools would wrap)

| #   | Endpoint                    | Method | Priority | Notes                                                                                                                                       |
| --- | --------------------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `/threads/{id}/cancel`      | POST   | MEDIUM   | No REST cancel path exists; only WS AGENT_CONTROL.TERMINATE. Required before `cancel_thread` MCP tool.                                      |
| 2   | `/threads/{id}/permissions` | GET    | MEDIUM   | Pending permission requests scoped to a specific thread; currently only available via team/status (all-threads aggregate, and always empty) |
| 3   | `/.well-known/agent.json`   | GET    | LOW      | A2A AgentCard for external discovery. ADR-012 §4 explicitly rejected this for internal use, but external A2A interop requires it.           |

### 5C — Existing Tools Requiring Enrichment

| #   | Tool                | Missing Parameter             | Priority | Notes                                                                                                                                                                                                           |
| --- | ------------------- | ----------------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `start_thread`      | `workspace_root: str \| None` | HIGH     | Most critical missing parameter — coding agents need to bind the thread to a workspace for config discovery, context injection, and ACP sandbox scoping. Maps to `CreateThreadRequest.metadata.workspace_root`. |
| 2   | `start_thread`      | `autonomous: bool = True`     | HIGH     | Currently hardcoded `True`. Supervised mode (`autonomous=False`) is needed for coding workflows where the user must approve writes.                                                                             |
| 3   | `start_thread`      | `feature_tag: str \| None`    | MEDIUM   | Enables `.vault/` context auto-discovery (ADR-014). Coding agents in CI/CD pipelines pass feature branch names here.                                                                                            |
| 4   | `get_thread_status` | Return plan entries           | MEDIUM   | Current output omits `current_plan` from state snapshot. For coding workflows, the plan is the primary progress indicator.                                                                                      |
| 5   | `get_thread_status` | Return pending permissions    | MEDIUM   | Consumer must know if the thread is blocked on a permission request. Currently not surfaced.                                                                                                                    |
| 6   | `get_thread_status` | Return active agent name      | LOW      | Which agent is currently running. Available in state snapshot as `agents[]`.                                                                                                                                    |
| 7   | `send_message`      | `agent_id: str \| None`       | LOW      | Allows targeting a specific agent node. Default fallback to supervisor is acceptable but constrains directed interventions.                                                                                     |
| 8   | `send_message`      | Input size validation         | LOW      | No size cap at MCP layer (only at REST layer). Consistent with start_thread's explicit cap.                                                                                                                     |

---

## 6. Priority Ranking Summary

### Immediate / HIGH (blocks real-world coding IDE use)

1. `start_thread` — add `workspace_root` parameter (maps entire workspace context system)
2. `start_thread` — expose `autonomous` as caller-controlled parameter
3. `respond_to_permission` — new tool (supervised workflows are dead without it)
4. `list_threads` — new tool (session continuity across IDE restarts)

### Post-hardening / MEDIUM

5. `list_team_presets` — new tool (enumeration with descriptions)
6. `cancel_thread` — new tool (requires new REST endpoint first)
7. `get_thread_status` — enrich with plan entries and pending permissions
8. `get_pending_permissions` — new tool (requires worker wiring of team/status first)
9. `start_thread` — add `feature_tag` parameter

### Low / Deferred

10. `send_message` — add `agent_id`
11. `send_message` — add input size cap
12. `get_thread_status` — add active agent name
13. `/.well-known/agent.json` — A2A AgentCard (external interop only)

---

## 7. Design Notes for Implementation

### workspace_root threading

`start_thread(workspace_root=...)` must map to `CreateThreadRequest.metadata.workspace_root`.
The full `ThreadMetadata` model (from `src/vaultspec_a2a/core/metadata.py`) is:

- `workspace_root: str` (required when metadata is provided)
- `feature_tag: str | None`
- `source_branch: str | None`
- `callee: str | None`
- `context_refs: list[ContextRef]` (auto-discovered if feature_tag provided)
- `nickname: str | None`

For a coding IDE tool, the minimal useful enrichment is:

```python
async def start_thread(
    initial_message: str,
    team_preset: str | None = None,
    workspace_root: str | None = None,
    autonomous: bool = True,
    feature_tag: str | None = None,
) -> str:
```

The MCP tool should construct `metadata` only when `workspace_root` is provided, keeping the interface clean.

### respond_to_permission

Must wrap `POST /permissions/{request_id}/respond`. The `request_id` is embedded as `"{thread_id}:{uuid}"` by the aggregator. The `option_id` is the selected option from the `PermissionRequestEvent.options[]` list. Minimal signature:

```python
async def respond_to_permission(request_id: str, option_id: str) -> str:
```

Returns confirmation or error. This tool is what allows a supervised thread to proceed after an agent requests approval for a destructive operation.

### A2A Protocol Alignment Note

Vaultspec's architecture (per ADR-012 §4) explicitly rejected A2A's `AgentCard`/`/.well-known/agent.json` for internal use — agents are compiled LangGraph nodes, not independently-deployed HTTP services. The MCP surface is the correct integration point for IDEs. Full A2A compliance would require:

1. A `/.well-known/agent.json` endpoint exposing `AgentCard` (skills, auth requirements, streaming mode)
2. JSON-RPC 2.0 message envelope wrapping (vs. current REST+JSON)
3. Formal `Task` objects with A2A lifecycle states vs. current `thread_id` + `status` string

None of these are required for Cursor/Windsurf/Claude Code integration, which uses MCP natively. A2A compliance is a future consideration if Vaultspec wants to be callable by other A2A-compliant agent orchestrators.

---

## 8. References

- `src/vaultspec_a2a/protocols/mcp/server.py` — current MCP server implementation
- `src/vaultspec_a2a/api/endpoints.py` — all REST endpoints (full read)
- `src/vaultspec_a2a/api/schemas/rest.py` — `CreateThreadRequest`, `SendMessageRequest` schemas
- `src/vaultspec_a2a/core/metadata.py` — `ThreadMetadata` model (ADR-014)
- `docs/adrs/012-agent-definition-schema.md` — agent TOML schema
- `docs/adrs/013-team-composition-topology.md` — team TOML schema, preset discovery
- `knowledge/repositories/A2A/docs/topics/key-concepts.md` — A2A core concepts
- `knowledge/repositories/A2A/docs/topics/life-of-a-task.md` — A2A task lifecycle
- `docs/audits/2026-03-02-mcp-surface-audit.md` — prior MCP security audit (MCP-01 through MCP-07)
