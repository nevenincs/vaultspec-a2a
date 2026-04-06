---
tags:
  - '#plan'
  - '#ui-integration-wire-regen'
date: 2026-04-04
related:
  - "[[2026-04-04-ui-integration-wire-regen-research]]"
  - "[[2026-02-26-frontend-backend-contract-adr]]"
  - "[[2026-02-28-react-tailwind-figma-migration-adr]]"
  - "[[2026-02-26-event-aggregation-server-side-replay-adr]]"
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `ui-integration-wire-regen` plan

Regenerate wire types and fix every frontend drift point against the
restructured Layer 1/2/3 backend (PR #22). This plan covers issue #28 / PR #29.

The frontend shell is complete (~50 components, 5 Zustand slices, WS+REST
clients, TanStack Query hooks) but entirely non-functional due to two missing
type definition files. Beyond the compilation blocker, two rounds of multi-agent
drift auditing identified 30+ specific regressions across REST endpoints,
WebSocket events, mappers, store hydration, and component rendering.

## Proposed Changes

Wire type regeneration from live OpenAPI spec, creation of the frontend
presentation type module, and systematic repair of every identified drift
between the frontend and the current backend contract. No new features, no
design system changes, no backend modifications. Pure contract alignment.

The work is organized in 4 phases, each with atomic verifiable steps:

- Phase 1: Foundation — install tooling, generate wire types, create types.ts
- Phase 2: API client + mapper alignment — fix every REST/WS/mapper drift
- Phase 3: Store + hydration alignment — fix reconnection data loss
- Phase 4: SSE integration + smoke test

## Tasks

### Phase 1: Type Foundation

This phase unblocks compilation. Every subsequent phase depends on it.

- Phase 1: Type Foundation
  1. Install `openapi-typescript` as devDependency in `src/ui/`
  1. Start the gateway backend (`uv run vaultspec-core gateway` or equivalent)
  1. Generate `src/ui/src/app/data/wire-types.ts` from
     `http://localhost:8000/openapi.json` via
     `npx openapi-typescript http://localhost:8000/openapi.json -o src/app/data/wire-types.ts`
  1. Verify the generated file contains all expected schemas:
     `CreateThreadRequest`, `CreateThreadResponse`, `ThreadListResponse`,
     `ThreadStateSnapshot`, `ThreadMetadata`, `SendMessageRequest`,
     `SendMessageResponse`, `TeamStatusResponse`, `TeamPresetsResponse`,
     `PermissionResponseRequest`, `PermissionResponseResult`,
     `CancelThreadResponse`, `ServerEvent` union (12 types),
     `ClientMessage` union (6 types), all component types
     (`ToolCallContent`, `ToolCallLocation`, `PermissionOption`,
     `AgentSummary`, `PlanEntry`, `ExecutionTaskSnapshot`, etc.)
  1. Create `src/ui/src/app/data/types.ts` with all frontend presentation
     types. This file must define:
     - `ConnectionState`: `'connected' | 'reconnecting' | 'disconnected'`
     - `AgentLifecycleState`: full 8-value union — `'submitted' | 'idle' |
       'working' | 'input_required' | 'auth_required' | 'completed' |
       'failed' | 'cancelled'`
     - `ToolKind`: 10-value union — `'read' | 'edit' | 'delete' | 'move' |
       'search' | 'execute' | 'think' | 'fetch' | 'switch_mode' | 'other'`
     - `ToolCallStatus`: `'pending' | 'in_progress' | 'completed' | 'failed'`
     - `ThreadSummary`: all fields from backend `ThreadSummary` schema
       **including** `repair_status`, `execution_readiness`,
       `approval_status`, `approval_request_id` (all `string | null`)
     - `AgentSummary`: 8 fields matching backend `AgentStatusEntry`
     - `TeamPreset`: 5 fields (with `name` renamed from `display_name`)
     - `PermissionRequest`: with `id` (from `request_id`), `thread_id`,
       `agent_id`, `agent_name`, `tool_name`, `tool_kind`, `message`,
       `options[]` with `id`/`kind`/`label`
     - `EditorTab`: `{ threadId: string; isPinned: boolean }`
     - `ThemeMode`: `'light' | 'dark' | 'system'`
     - `InspectorTarget`: discriminated union with `type` field
     - `ContextDocument`: shape extracted from inspector component usage
     - `StreamEvent` discriminated union (8 variants):
       `UserMessageEvent`, `AgentMessageEvent`, `ThoughtEvent`,
       `ToolCallEvent`, `ArtifactEvent`, `PlanUpdateEvent`,
       `AgentStatusEvent`, `ErrorStreamEvent`
     - `ToolCallEvent` must carry `terminal_id?: string` field for terminal
       content and `diff_path?: string` for the diff file path
     - `ErrorStreamEvent` must carry `recoverable?: boolean` field
  1. Run `npm run check` — expect significant reduction in errors; remaining
     errors guide Phase 2 work

### Phase 2: API Client + Mapper Alignment

Fix every field-level drift identified by the audit across REST client,
WebSocket client, mappers, and bridge.

- Phase 2a: REST Client Fixes
  1. `rest-client.ts` — verify all 9 endpoint function signatures align with
     regenerated wire types. Specific checks:
     - `createThread()`: request body matches `CreateThreadRequest`
     - `listThreads()`: response typed as `ThreadListResponse`
     - `getThreadState()`: response typed as `ThreadStateSnapshot`
     - `sendMessage()`: response typed as `SendMessageResponse`
     - `cancelThread()`: response typed as `CancelThreadResponse`
     - `respondToPermission()`: response typed as `PermissionResponseResult`
     - `getTeamStatus()`: response typed as `TeamStatusResponse`
     - `listTeamPresets()`: response typed as `TeamPresetsResponse`
     - `getThreadMetadata()`: response typed as `ThreadMetadata`
  1. Verify the `components['schemas']` namespace path is correct in the
     generated wire-types (openapi-typescript v7 may use a different
     structure than assumed by the existing import syntax)

- Phase 2b: Mapper Fixes
  1. `mappers.ts` — `mapThreadSummary()`: pass through the 4 new fields
     (`repair_status`, `execution_readiness`, `approval_status`,
     `approval_request_id`) from wire to frontend type
  1. `mappers.ts` — `mapPermissionRequest()`: fix `agent_name` to resolve
     via display name lookup from `_agentDisplayNames` in the store instead
     of using raw `agent_id`. If lookup unavailable, fall back to `agent_id`.
  1. `mappers.ts` — verify `mapAgentSummary()` handles both `AgentSummary`
     (events.py) and `AgentStatusEntry` (rest.py) — both are structurally
     identical, confirm with generated types
  1. `mappers.ts` — verify `mapTeamPreset()` field rename
     (`display_name` → `name`) still works with generated types
  1. `mappers.ts` — verify `mapToolCallStatus()` and `mapToolKind()`
     pass-through casts are type-safe with generated enums

- Phase 2c: WebSocket Client Fixes
  1. `websocket-client.ts` — update all type imports to reference generated
     wire types. Verify `ServerEvent`, `ClientMessage`, `ConnectedEvent`,
     `HeartbeatEvent`, and all command types resolve correctly.
  1. `websocket-client.ts` — verify the `ConnectionState` type includes
     4 values internally (`'connecting' | 'connected' | 'reconnecting' |
     'disconnected'`) and maps correctly to the 3-value frontend
     `ConnectionState`

- Phase 2d: WS Bridge + Store Slice Fixes
  1. `ws-bridge.ts` — `agent_status` handler (line ~76-88): fix the
     `status` conflation bug. Currently sets `thread.status = event.state`
     for terminal agent states, but `ThreadSummary.status` is an
     independent field from `agent_state`. Must set `agent_state` only,
     not overwrite `status`.
  1. `ws-bridge.ts` — propagate `repair_status`, `execution_readiness`,
     `approval_status` from `agent_status` events if the backend includes
     them (verify with wire types; if not on event, these only refresh via
     REST — acceptable).
  1. `stream-slice.ts` — `handleWireEvent` case `'tool_call_start'`:
     - Extract `terminal` content type and store as
       `entry.terminal_id` on the `ToolCallEvent`
     - Extract `diff.path` and store as `entry.diff_path`
     - Consider consuming `locations[1..n]` (secondary locations)
       or document the single-location limitation
  1. `stream-slice.ts` — `handleWireEvent` case `'tool_call_update'`:
     - Extract `terminal` content type updates
     - Extract `diff.path` updates
     - Consume `event.locations` updates (currently ignored)
  1. `stream-slice.ts` — `handleWireEvent` case `'error'`:
     - Pass through `event.recoverable` to `ErrorStreamEvent`
  1. `stream-slice.ts` — fix all implicit `any` parameter types (TS7006
     errors). Add explicit types to callback parameters in `.find()`,
     `.filter()`, `.map()` calls.
  1. `permission-slice.ts` — fix implicit `any` parameter type on the
     `.filter()` callback (line 35)
  1. `tab-slice.ts` — fix all implicit `any` parameter types on
     `.find()`, `.filter()`, `.findIndex()` callbacks

### Phase 3: State Hydration + Reconnection Alignment

Fix the critical data loss on reconnect/refresh. The thread state snapshot
contains 30+ fields; the frontend currently consumes only 4 (`messages`,
`tool_calls`, `artifacts`, `last_sequence`).

- Phase 3a: Snapshot Hydration
  1. `use-thread-state.ts` — hydrate `pending_permissions` from snapshot:
     - The snapshot carries `_PermissionSnapshot[]` which differs from
       `PermissionRequestEvent` (missing `thread_id`, `agent_id`,
       `tool_kind`). Create a mapping function that accepts the snapshot
       permission + thread_id context and produces a `PermissionRequest`
       frontend type. Push to `permissionSlice.setPermissionQueue()`.
  1. `use-thread-state.ts` — hydrate `plan` entries from snapshot:
     - Map `PlanEntry[]` to `PlanUpdateEvent` StreamEvent and include
       in the hydrated events array.
  1. `use-thread-state.ts` — hydrate `agents` from snapshot:
     - Call `updateAgentDisplayNames()` with the agents array to
       populate the `_agentDisplayNames` cache. This ensures subsequent
       streaming events resolve display names correctly.
  1. `use-thread-state.ts` — hydrate `ToolCallSnapshot.content`:
     - The backend provides `content: list[ToolCallContent]` on each
       tool call snapshot. Map text content to `input`/`output`, diff
       content to `diff` + `diff_path`, terminal content to
       `terminal_id`. Currently these fields are empty on hydrated
       tool call events.
  1. `use-thread-state.ts` — consume `snapshot.status` and
     `snapshot.agents` to update TanStack Query caches (thread list
     status, team status) during hydration.
  1. `use-thread-state.ts` — build agent_id → display_name lookup from
     `snapshot.agents` and use it to set `agent_name` on hydrated message
     and tool call events (currently defaults to `agent_id`).

- Phase 3b: Optimistic Update Fixes
  1. `use-threads.ts` — `useCreateThread` optimistic insert (line ~55-62):
     add missing `status` field (default `'submitted'`), `created_at`
     field (default `new Date().toISOString()`), and the 4 new fields
     (`repair_status: null`, `execution_readiness: null`,
     `approval_status: null`, `approval_request_id: null`).
  1. `use-threads.ts` — verify optimistic thread summary survives
     cache reconciliation when the real REST response arrives.

- Phase 3c: ConnectedEvent Bootstrap
  1. `websocket-client.ts` — on receiving `ConnectedEvent`, expose
     `active_threads` and `server_version` to the bridge via
     the connected callback.
  1. `ws-bridge.ts` — when receiving `active_threads` from
     `ConnectedEvent`, use the list to determine which threads may
     need state refresh (threads in active_threads that the UI has
     open tabs for but no local events). This is a progressive
     enhancement — not blocking.

### Phase 4: SSE Integration + Verification

Wire the new SSE endpoint as a complementary transport. The existing
WebSocket client (279 LOC, production-ready) remains the primary transport.

- Phase 4a: SSE Client
  1. Create `src/ui/src/app/api/sse-client.ts` — thin wrapper around
     browser `EventSource` API. Must handle:
     - Connect to `GET /api/threads/{thread_id}/stream`
     - Parse SSE events (named events via `event:` header)
     - Handle `thread_terminal` ad-hoc event (not in `ServerEventType`
       enum — hardcoded in backend)
     - Handle `heartbeat` events
     - Expose same callback interface as `WebSocketClient`:
       `setEventCallback(threadId, event)`,
       `setConnectionCallback(state)`
     - Disconnect + cleanup
     - Note: browser `EventSource` handles reconnection automatically;
       no custom backoff needed
  1. `ws-bridge.ts` — add ability to route SSE events through the same
     event handling pipeline. Since SSE events use identical payload shapes
     to WS events, the bridge should accept events from either transport.
  1. Expose transport selection (WS vs SSE) as a configuration option,
     not a user-facing toggle. Default to WS.

- Phase 4b: Component Drift Fixes
  1. `state-indicators.tsx` — verify all 3 `agentState*` functions cover
     the full 8-value `AgentLifecycleState` union. The audit found they
     do, but confirm after types.ts is created that `noFallthroughCasesInSwitch`
     doesn't fire. Add exhaustive default cases if needed.
  1. `message-stream.tsx` — replace the 6 `as any` casts with proper
     discriminated union narrowing. After `types.ts` exists, each
     `StreamEvent` variant has typed fields; narrow via `event.type`
     checks instead of casting.
  1. `sidebar.tsx` — the 4 new `ThreadSummary` fields
     (`repair_status`, `execution_readiness`, `approval_status`,
     `approval_request_id`) are now available. No new visual indicators
     are required for #28 (that's feature work), but verify the sidebar
     doesn't break when these fields are present.
  1. `input-bar.tsx` — verify `auth_required` agent state doesn't cause
     unexpected behavior in the input bar (currently treated as generic
     non-working state — acceptable for #28).

- Phase 4c: Verification
  1. Run `npm run check` — zero TypeScript errors
  1. Run `npm run build` — clean production build
  1. Full-stack smoke test (if gateway + worker available):
     - Create thread via UI
     - Observe streaming messages in message-stream
     - Trigger and respond to a permission request
     - Cancel a running thread
     - Refresh page and verify state hydration (permissions, plan,
       tool call content, agent display names)
     - Verify SSE client connects to
       `GET /api/threads/{id}/stream` (network tab)

## Drift Registry

Complete catalog of every identified drift point, mapped to the phase/step
that fixes it. Every item must be resolved — no skips.

### BLOCKING (prevents compilation)

| # | Drift | Fix |
|---|-------|-----|
| B1 | `wire-types.ts` does not exist | Phase 1.3 |
| B2 | `types.ts` does not exist | Phase 1.5 |
| B3 | 31 TS2307 "Cannot find module" errors | Phase 1.3 + 1.5 |
| B4 | 21 TS7006 "implicit any" errors | Phase 2d.6 + 2d.7 + 2d.8 |
| B5 | 3 TS2366 "missing return" in state-indicators | Phase 4b.1 |

### HIGH (data loss or incorrect behavior)

| # | Drift | File | Fix |
|---|-------|------|-----|
| H1 | `pending_permissions` not hydrated on reconnect | `use-thread-state.ts` | Phase 3a.1 |
| H2 | `plan` entries not hydrated on reconnect | `use-thread-state.ts` | Phase 3a.2 |
| H3 | `agents` not hydrated on reconnect — display names lost | `use-thread-state.ts` | Phase 3a.3 + 3a.6 |
| H4 | `ToolCallSnapshot.content` dropped on hydration — tool call content invisible after reconnect | `use-thread-state.ts` | Phase 3a.4 |
| H5 | `mapThreadSummary()` drops `repair_status`, `execution_readiness`, `approval_status`, `approval_request_id` | `mappers.ts` | Phase 2b.1 |
| H6 | Optimistic `ThreadSummary` missing required `status`, `created_at` fields | `use-threads.ts` | Phase 3b.1 |
| H7 | `ws-bridge.ts` conflates `agent_state` with `thread.status` on terminal states | `ws-bridge.ts` | Phase 2d.1 |

### MEDIUM (degraded UX or silent data loss)

| # | Drift | File | Fix |
|---|-------|------|-----|
| M1 | `ToolCallContentTerminal` silently dropped — Bash tool output invisible | `stream-slice.ts` | Phase 2d.3 + 2d.4 |
| M2 | `ToolCallContentDiff.path` dropped — diff has no file attribution | `stream-slice.ts` | Phase 2d.3 + 2d.4 |
| M3 | `tool_call_update` ignores `locations` updates | `stream-slice.ts` | Phase 2d.4 |
| M4 | `ErrorEvent.recoverable` unconsumed — no error triage | `stream-slice.ts` | Phase 2d.5 |
| M5 | `TeamStatusEvent.active_thread_ids` unconsumed | `ws-bridge.ts` | Out of scope (feature work) |
| M6 | `ConnectedEvent.active_threads`/`server_version` unconsumed | `websocket-client.ts` | Phase 3c.1 |
| M7 | `mapPermissionRequest` sets `agent_name` = `agent_id` | `mappers.ts` | Phase 2b.2 |
| M8 | 6 `as any` casts in `message-stream.tsx` mask field access errors | `message-stream.tsx` | Phase 4b.2 |
| M9 | 3 incompatible permission shapes (Event vs Snapshot vs REST) need separate mapper | `use-thread-state.ts` | Phase 3a.1 |
| M10 | `snapshot.status` not consumed — thread may show incorrect status after reconnect | `use-thread-state.ts` | Phase 3a.5 |

### LOW (minor gaps, acceptable for #28)

| # | Drift | File | Fix |
|---|-------|------|-----|
| L1 | `PermissionResponseRequest.kind` never sent (ALLOW_ALWAYS vs ALLOW_ONCE lost) | `use-permissions.ts` | Out of scope (feature) |
| L2 | No `Idempotency-Key` header on any POST | `rest-client.ts` | Out of scope (feature) |
| L3 | `autonomous`/`nickname` top-level fields never sent from UI | `rest-client.ts` | Out of scope (feature) |
| L4 | `AgentStatusEvent.detail` unconsumed | `stream-slice.ts` | Out of scope (info field) |
| L5 | `HeartbeatEvent.server_uptime_seconds` unconsumed | `websocket-client.ts` | Out of scope (monitoring) |
| L6 | `plan_update` events have `agent_id: null` from adapter | `event_adapter.py` | Backend issue, not UI scope |
| L7 | `AgentControlCommand.option_id` never sent | `websocket-client.ts` | Out of scope (feature) |
| L8 | `snapshot_complete`/`degraded_reasons` not consumed | `use-thread-state.ts` | Out of scope (UX) |
| L9 | `input-bar.tsx` no specific UX for `auth_required` | `input-bar.tsx` | Out of scope (feature) |
| L10 | `locations[1..n]` on tool_call_start dropped (only first used) | `stream-slice.ts` | Out of scope (multi-location) |

## Parallelization

- Phase 1 is sequential (each step depends on the previous).
- Phase 2a, 2b, 2c, 2d can be parallelized as sub-agents once Phase 1
  is complete — they modify different files with no cross-dependencies
  except that 2d depends on 2b for mapper types.
- Phase 3a, 3b, 3c are largely independent and can be parallelized.
- Phase 4a and 4b can be parallelized.
- Phase 4c (verification) must run after all other phases complete.

Recommended: execute Phase 1 first, then fan out into parallel tracks
for Phases 2+3, then converge on Phase 4.

## Verification

Mission success criteria:

- `npm run check` exits 0 (zero TypeScript errors)
- `npm run build` produces a clean production bundle
- Every item in the Drift Registry marked "Phase X" has a corresponding
  code change — no items left unaddressed
- All items marked "Out of scope" are documented and justified
- State hydration test: after generating `wire-types.ts` and `types.ts`,
  the generated types must be structurally compatible with every import
  site (rest-client, websocket-client, mappers, store slices, queries,
  components)
- Reconnection test (if full stack available): refresh page during active
  thread, verify permissions re-appear, plan entries re-appear, tool call
  content is visible, agent display names resolve correctly
- SSE test: verify `EventSource` connects to
  `GET /api/threads/{id}/stream` and receives typed events

Honest assessment: without a running backend, Phases 1.2-1.3 (type
generation) and Phase 4c (smoke test) cannot be verified. The plan depends
on the gateway being startable. If the gateway cannot start (e.g., missing
database, worker dependency), the fallback is to manually construct
`wire-types.ts` from the OpenAPI schema models — but this is fragile and
should be avoided.
