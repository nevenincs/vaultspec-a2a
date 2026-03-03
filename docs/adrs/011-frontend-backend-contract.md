---
adr_id: 011
title: Frontend-Backend Wire Contract
date: 2026-02-26
status: Proposed
related:
  - docs/adrs/003-protocol-bridging-translation.md
  - docs/adrs/004-event-aggregation-server-side-replay.md
  - docs/adrs/005-frontend-rendering-stack.md
  - docs/adrs/006-protocol-ecosystem-bridge.md
  - docs/adrs/007-workspace-file-management.md
  - docs/adrs/008-telemetry-observability.md
  - docs/adrs/009-approved-module-hierarchy.md
---

# ADR-011: Frontend-Backend Wire Contract

**Date:** 2026-02-26
**Status:** Proposed

## 1. Context and Problem Statement

The backend (LangGraph orchestrator) and frontend (React control surface)
have no formal wire contract. ADR-004, ADR-005, and ADR-009 describe the
architectural intent---multiplexed WebSocket, REST state replay, structured
events---but no concrete Pydantic models or endpoint signatures exist.
`lib/api/schemas.py` was an empty placeholder with stub classes.

Without a machine-readable contract:

- Frontend work cannot begin (no types to generate).
- Backend aggregator output shapes are undefined.
- Integration testing has no schema to validate against.
- TypeScript type generation via `openapi-typescript` is blocked.

## 2. Decision

We define a complete wire contract as a Pydantic subpackage at
`lib/api/schemas/` with the following protocol surfaces.

### 2.1 WebSocket Message Envelope

#### Server-to-Client Events

Every server-to-client WebSocket message is a JSON object with a top-level
`type` field acting as a discriminator. There are two categories:

**Thread-scoped events** (extend `EventEnvelope`):

| Field       | Type              | Description                  |
| ----------- | ----------------- | ---------------------------- |
| `type`      | `ServerEventType` | Discriminator                |
| `thread_id` | `str`             | Target thread                |
| `agent_id`  | `str \            | null`                        |
| `timestamp` | `datetime`        | Server timestamp             |
| `sequence`  | `int`             | Monotonic per-thread counter |

Concrete types: `AgentStatusEvent`, `MessageChunkEvent`, `ThoughtChunkEvent`,
`ToolCallStartEvent`, `ToolCallUpdateEvent`, `PermissionRequestEvent`,
`ArtifactUpdateEvent`, `PlanUpdateEvent`, `TeamStatusEvent`, `ErrorEvent`.

**Connection-scoped events** (standalone `BaseModel`, no envelope):

- `ConnectedEvent` --- sent once on WebSocket open with `client_id`,
  `server_version`, and `active_threads`.
- `HeartbeatEvent` --- periodic keepalive with `timestamp` and
  `server_uptime_seconds`.

All 12 event types form the `ServerEvent` discriminated union.

#### Client-to-Server Commands

Every client-to-server WebSocket message extends `ClientCommand`:

| Field        | Type                | Description   |
| ------------ | ------------------- | ------------- |
| `type`       | `ClientCommandType` | Discriminator |
| `request_id` | `str \              | null`         |

Concrete types: `SubscribeCommand`, `UnsubscribeCommand`,
`SendMessageCommand`, `AgentControlCommand`, `PermissionResponseCommand`,
`PingCommand`.

All 6 command types form the `ClientMessage` discriminated union.

### 2.2 REST Endpoint Signatures

REST endpoints complement WebSocket for operations requiring guaranteed
delivery and idempotent semantics.

| Method | Path                        | Request                     | Response                   | Purpose             |
| ------ | --------------------------- | --------------------------- | -------------------------- | ------------------- |
| `POST` | `/threads`                  | `CreateThreadRequest`       | `CreateThreadResponse`     | Create thread       |
| `GET`  | `/threads`                  | query params                | `ThreadListResponse`       | List threads        |
| `GET`  | `/threads/{id}/state`       | ---                         | `ThreadStateSnapshot`      | State replay        |
| `POST` | `/threads/{id}/messages`    | `SendMessageRequest`        | `202 Accepted`             | Send message        |
| `GET`  | `/team/status`              | ---                         | `TeamStatusResponse`       | Team overview       |
| `POST` | `/permissions/{id}/respond` | `PermissionResponseRequest` | `PermissionResponseResult` | Permission response |

### 2.3 Reconnection Protocol

1. Client detects disconnect (WebSocket `close` or heartbeat timeout).
2. Client reconnects and receives `ConnectedEvent`.
3. Client fetches `GET /threads/{id}/state` for each subscribed thread.
4. Client records `last_sequence` from each `ThreadStateSnapshot`.
5. Client sends `SubscribeCommand` for all thread IDs.
6. Client discards any incoming events with `sequence <= last_sequence`.
7. Normal streaming resumes from `sequence > last_sequence`.

### 2.4 TypeScript Type Generation Strategy

1. Backend registers all schema models on FastAPI endpoints.
2. FastAPI exports `/openapi.json` with discriminated unions rendered as
   `oneOf` with `propertyName` discriminators.
3. `openapi-typescript` consumes the OpenAPI spec and generates
   `src/ui/src/app/data/wire-types.ts`. _(Amended by ADR-018: path
   changed from `src/lib/api/` to `src/app/data/`.)_
4. The generated types are committed to the repository (not generated at
   build time) to enable frontend work without a running backend.
5. CI validates that generated types match the current OpenAPI spec.
6. _(ADR-018 addition)_ Frontend-only presentation types live in
   `src/ui/src/app/data/types.ts`. Mapper functions in
   `src/ui/src/app/api/mappers.ts` translate wire types to frontend
   types (e.g., `WireThreadSummary` → `ThreadSummary`, `in_progress` →
   `running`). TanStack Query hooks consume wire types from REST
   responses and map to frontend types at the query boundary.

### 2.5 Fixture and Mock Strategy for Contract-First Development

Frontend development proceeds before the backend is fully wired:

1. **Schema fixtures**: Each Pydantic model provides `.model_json_schema()`
   for JSON Schema validation in frontend tests.
2. **Factory functions**: A `lib/api/schemas/tests/` module contains
   builder functions that produce valid model instances for each event type.
3. **Recorded sessions**: Integration tests record real WebSocket sessions
   to JSON files in `src/ui/tests/fixtures/` for Playwright replay.
4. _(Superseded by ADR-018)_ The React frontend uses a live backend
   integration layer (`websocket-client.ts`, `rest-client.ts`) with
   TanStack Query for REST caching and Zustand stores for real-time
   state. Mock data stubs exist in `mock-data.ts` for offline
   development but are not the primary development path.

## 3. Rationale

### Top-level `type` discriminator

Every WebSocket message carries a `type` field enabling O(1) `switch`
dispatch on both Python (`match event.type`) and TypeScript
(`switch (msg.type)`) sides. No nested field inspection or trial
deserialization is needed.

### Separate `ToolCallStart` and `ToolCallUpdate`

Mirrors the ACP protocol's `tool_call` / `tool_call_update` split from
Toad. `ToolCallStartEvent` carries all required fields for initial render;
`ToolCallUpdateEvent` carries all-optional fields for incremental merge.
This avoids forcing the frontend to handle "is this the first time I've
seen this tool call?" logic.

### `AgentLifecycleState` vs `AgentState`

The wire protocol uses the 6 ADR-003 MCP-mapped states (`idle`, `working`,
`input_required`, `completed`, `failed`, `cancelled`). The internal
`lib.utils.enums.AgentState` (`init`, `ready`, `running`, `error`, `done`)
tracks process lifecycle. The aggregator maps between them. This separation
prevents internal state machine details from leaking into the frontend
contract.

### REST fallback for permission responses

LangGraph's `Command(resume=...)` is a one-shot operation requiring
guaranteed delivery. WebSocket messages can be lost during reconnection.
The REST `POST /permissions/{id}/respond` endpoint provides idempotent,
retryable delivery with proper HTTP status codes.

### Monotonic `sequence` counter per thread

Enables gap detection on reconnect without complex vector clocks. Each
thread maintains an independent counter. The frontend notes the
`last_sequence` from the state snapshot and discards any WebSocket events
at or below that value.

### `openapi-typescript` over manual TypeScript types

Manual type maintenance is error-prone and creates drift. Generating types
from the single-source-of-truth Pydantic models ensures the frontend
contract is always in sync with the backend.

## 4. Rejected Alternatives

### Raw Server-Sent Events (SSE)

SSE is unidirectional (server-to-client only). The protocol requires
bidirectional communication for commands like `subscribe`, `send_message`,
and `permission_response`. Using SSE would require a separate REST channel
for all client-to-server communication, doubling the API surface.

### Manual TypeScript type definitions

Writing TypeScript types by hand creates a maintenance burden and
inevitable drift. A single Pydantic source of truth with automated
generation eliminates this class of bugs entirely.

### Single polymorphic event type

A single `Event` model with optional fields for every possible payload
trades type safety for apparent simplicity. Discriminated unions give the
frontend compiler-checked exhaustive `switch` handling and accurate
IntelliSense.

### GraphQL

The primary data flow is streaming events, not request/response queries.
GraphQL subscriptions add complexity (subscription resolver, batching)
without benefit over a plain WebSocket with typed JSON messages.

## 5. Implementation Constraints

### Sequence Numbering

- Sequences are monotonically increasing integers, starting at 1.
- Sequences are scoped per thread (not global).
- Connection-scoped events (`ConnectedEvent`, `HeartbeatEvent`) do not
  carry sequence numbers.
- The aggregator increments the sequence atomically before broadcasting.

### Heartbeat Intervals

- Server sends `HeartbeatEvent` every 30 seconds.
- Client considers the connection dead after 90 seconds without any
  message (3 missed heartbeats).
- Client initiates reconnection with exponential backoff (1s, 2s, 4s,
  max 30s).

### Debouncing Rules

- `ToolCallUpdateEvent`: backend batches updates and emits at most one
  update per tool call per 100ms.
- `PlanUpdateEvent`: full plan replacement, debounced to at most one
  emission per 250ms.
- `TeamStatusEvent`: emitted on state transitions only, not on a timer.

### Schema Evolution

- New event types can be added without breaking existing clients (unknown
  `type` values are ignored by the frontend).
- Existing event types may gain new optional fields (additive changes).
- Removing fields or changing field types requires a major version bump
  in `server_version`.

## 6. Schema Module Structure

```text
lib/api/schemas/
    __init__.py       # Facade: re-exports all public types
    enums.py          # ServerEventType, ClientCommandType, etc.
    base.py           # EventEnvelope, ClientCommand
    events.py         # All 12 server event models + component models
    commands.py       # All 6 client command models
    rest.py           # REST request/response models
    snapshots.py      # State replay snapshot models
    tests/
        __init__.py
        test_schemas.py
```

## 7. References

- [ADR-003](003-protocol-bridging-translation.md): Protocol Bridging
  and Translation (MCP state mapping)
- [ADR-004](004-event-aggregation-server-side-replay.md): Event Aggregation
  and State Replay (WebSocket + checkpoint sourcing)
- [ADR-005](005-frontend-rendering-stack.md): Frontend Rendering Stack
  _(Superseded by ADR-018: React + shadcn/ui)_
- [ADR-006](006-protocol-ecosystem-bridge.md): Protocol Ecosystem Bridge
  (ACP, A2A)
- [ADR-009](009-approved-module-hierarchy.md): Approved Module Hierarchy
  (facade pattern, `__all__`)
- Toad `protocol.py`: ACP type definitions (ToolCall, ToolCallUpdate,
  PermissionOption, PlanEntry)
- `lib/providers/acp_chat_model.py`: Reference implementation for ACP
  session update handling
