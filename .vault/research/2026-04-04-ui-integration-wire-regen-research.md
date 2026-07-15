---
tags:
  - '#research'
  - '#ui-integration-wire-regen'
date: 2026-04-04
modified: '2026-07-15'
related:
  - "[[2026-02-26-frontend-backend-contract-adr]]"
  - "[[2026-02-28-react-tailwind-figma-migration-adr]]"
  - "[[2026-02-26-event-aggregation-server-side-replay-adr]]"
  - "[[2026-03-31-integration-testing-smoke-tests-api-verification-plan]]"
---

# `ui-integration-wire-regen` research: frontend contract alignment

Research for issue #28 / PR #29: regenerate wire types and validate the React 19
frontend against the restructured Layer 1/2/3 backend from PR #22.

## Findings

### 1. Frontend current state

The frontend is a complete React 19 + Vite 7 + Tailwind v4 application shell
with ~50 components, 5 Zustand slices, TanStack Query hooks, and full
WebSocket + REST client infrastructure. It is **completely non-functional**
because two critical type definition files are missing:

- `src/ui/src/app/data/wire-types.ts` — never generated on this branch
- `src/ui/src/app/data/types.ts` — frontend presentation types, absent

**TypeScript check yields 80+ errors**, all cascading from these two missing
modules (TS2307 missing module, TS7006 implicit any, TS2366 missing returns).

**What exists and is correctly wired (pending types):**

| Layer | Files | Status |
|-------|-------|--------|
| REST client | `rest-client.ts` (135 LOC) | 9 endpoints, imports wire types |
| WS client | `websocket-client.ts` (279 LOC) | Full lifecycle, reconnection, sequence tracking |
| Mappers | `mappers.ts` (105 LOC) | 6 wire-to-frontend translation functions |
| Store | `app-store.ts` + 5 slices (600+ LOC) | Stream, connection, permission, tab, UI slices |
| Bridge | `ws-bridge.ts` (126 LOC) | Routes WS events to store + QueryClient |
| Queries | `use-threads.ts`, `use-thread-state.ts`, `query-keys.ts` | List, create, state hydration hooks |

**REST client endpoints:**
POST /api/threads, GET /api/threads, GET /api/threads/{id}/state,
GET /api/threads/{id}/metadata, POST /api/threads/{id}/messages,
POST /api/threads/{id}/cancel, GET /api/team/status, GET /api/teams,
POST /api/permissions/{id}/respond

**handleWireEvent() processes 8 event types:**
`message_chunk`, `thought_chunk`, `tool_call_start`, `tool_call_update`,
`artifact_update`, `plan_update`, `agent_status`, `error`

Permission and team events are routed separately through `ws-bridge.ts`.

### 2. Backend contract surface (PR #22 state)

#### REST endpoints (11 total)

| Method | Path | Request | Response |
|--------|------|---------|----------|
| POST | /api/threads | CreateThreadRequest | CreateThreadResponse |
| GET | /api/threads | query: offset, limit, status | ThreadListResponse |
| GET | /api/threads/{id}/state | -- | ThreadStateSnapshot |
| GET | /api/threads/{id}/metadata | -- | ThreadMetadata |
| POST | /api/threads/{id}/messages | SendMessageRequest | SendMessageResponse |
| POST | /api/threads/{id}/cancel | -- | CancelThreadResponse |
| DELETE | /api/threads/{id} | -- | 204 |
| POST | /api/threads/{id}/archive | -- | {thread_id, status} |
| GET | /api/team/status | -- | TeamStatusResponse |
| GET | /api/teams | -- | TeamPresetsResponse |
| POST | /api/permissions/{id}/respond | PermissionResponseRequest | PermissionResponseResult |
| GET | /api/health | -- | dict |
| GET | /api/threads/{id}/stream | -- | SSE text/event-stream |

#### WebSocket protocol (/ws)

**12 ServerEventType values:** agent_status, message_chunk, thought_chunk,
tool_call_start, tool_call_update, permission_request, artifact_update,
plan_update, team_status, error, connected, heartbeat

**6 ClientCommandType values:** subscribe, unsubscribe, send_message,
permission_response (rejected over WS), agent_control, ping

#### Key schema changes from PR #22

**New fields on ThreadSummary:** `repair_status`, `execution_readiness`,
`approval_status`, `approval_request_id`

**New fields on ThreadStateSnapshot:** `repair_status`, `execution_readiness`,
`approval_status`, `approval_request_id`, `degraded_reasons[]`,
`snapshot_complete`, `replay_status`, `pause_cause`, `execution_tasks[]`,
`checkpoint_*` metadata fields

**New fields on PermissionResponseResult:** `approval_status`, `action_id`,
`idempotency_key`

**New fields on SendMessageResponse:** `action_status`, `action_id`,
`idempotency_key`

**New fields on CancelThreadResponse:** `action_status`, `action_id`,
`idempotency_key`

**ToolCallContent discriminated union:** `ToolCallContentText`,
`ToolCallContentDiff`, `ToolCallContentTerminal` (content field on
ToolCallStartEvent/ToolCallUpdateEvent is now a list of these)

**New model:** `ExecutionTaskSnapshot` (task queue entries in state snapshot)

#### Permission service expansion

- Approval state consumption: thread.approval_status (PENDING/APPROVED/REJECTED)
- Supersession detection: newer permission requests invalidate older ones
- Idempotency: SHA256 deduplication of permission responses
- Repair readiness: on dispatch failure, thread transitions to INPUT_REQUIRED
- Plan approval flow: resume_value = {"approved": bool} for plan decisions

### 3. Frontend-backend delta analysis

**Endpoints the frontend calls that exist:** All 9 REST client endpoints match
backend routes. Two backend endpoints not yet called: DELETE /api/threads/{id},
POST /api/threads/{id}/archive (these are out of scope for #28).

**Wire type shape changes the frontend must absorb:**

- ThreadSummary: 4 new fields (repair_status, execution_readiness,
  approval_status, approval_request_id)
- ThreadStateSnapshot: 10+ new fields (checkpoint metadata, degradation,
  execution tasks, repair/approval state)
- SendMessageResponse: 3 new fields (action_status, action_id, idempotency_key)
- CancelThreadResponse: 3 new fields
- PermissionResponseResult: 3 new fields
- ToolCallStartEvent/ToolCallUpdateEvent: content is now a discriminated union
  list, not a flat string
- New type: ExecutionTaskSnapshot

**Mapper updates needed:**

- `mapThreadSummary()`: pass through new fields (repair_status, etc.)
- `mapPermissionRequest()`: no structural change, options mapping still works
- New: handle ToolCallContent union in tool_call event processing
- New: map ExecutionTaskSnapshot if exposing task queue in UI

**Store updates needed:**

- `handleWireEvent()` for tool_call_start/tool_call_update: adapt to
  ToolCallContent list format (currently expects flat string fields)
- Stream event types in `types.ts`: add new fields to ToolCallEvent interface
- ThreadSummary in `types.ts`: add approval/repair state fields

### 4. SSE vs WebSocket strategy

Both SSE (`/api/threads/{id}/stream`) and WebSocket (`/ws`) feed from the same
`EventAggregator`. They emit identical event types with identical payloads.

| Aspect | WebSocket | SSE |
|--------|-----------|-----|
| Direction | Bidirectional | Server-to-client only |
| Multiplexing | Single connection, subscription model | Per-thread connection |
| Commands | subscribe, send_message, agent_control, ping | None (read-only) |
| Reconnection | Custom backoff (1-30s) | Browser-native (EventSource) |
| Client LOC | 279 lines (production-ready) | ~100-150 lines estimated |
| Server LOC | 720 lines | 136 lines |

**Assessment:** The WebSocket client is production-ready with full reconnection,
sequence tracking, and heartbeat management. The SSE endpoint is a complementary
transport for restricted environments (corporate firewalls blocking WS).

**Recommendation:** Keep WebSocket as primary transport. Wire SSE as an optional
fallback in Phase 3 of #28. The dual-transport approach requires:
- A thin `SSEClient` class (~150 LOC) using browser `EventSource` API
- Shared event handler interface (both clients emit same event shape)
- No changes to store or bridge — just a transport-level addition

### 5. Execution roadmap

**Phase 1: Wire type regeneration**
- Start gateway to serve `/openapi.json`
- Run `npx openapi-typescript http://localhost:8000/openapi.json -o src/app/data/wire-types.ts`
- Create `types.ts` with frontend presentation types (inferred from store/mapper usage)
- Run `npm run check`, fix all TS errors

**Phase 2: Contract alignment**
- Update `mappers.ts` for new fields (approval, repair, execution state)
- Update `handleWireEvent()` for ToolCallContent union format
- Update `types.ts` StreamEvent interfaces for new fields
- Verify all REST endpoint shapes match

**Phase 3: SSE integration**
- Create `SSEClient` class with EventSource API
- Wire into `ws-bridge.ts` as alternative transport
- Keep WS as default, SSE as fallback

**Phase 4: Smoke test**
- Full-stack validation: gateway + worker + UI
- Thread creation, streaming, permission flows

### 6. Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| OpenAPI spec incomplete (missing schemas) | High | Verify all Pydantic models registered on FastAPI app |
| ToolCallContent union breaks existing tool_call rendering | Medium | Adapt stream-slice to handle content list |
| New ThreadSummary fields break list rendering | Low | New fields are optional, additive |
| SSE client complexity creep | Low | Keep minimal; EventSource handles reconnection |
| Backend not running (can't regenerate types) | High | Must start gateway first; document startup procedure |
