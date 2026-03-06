# Frontend Readiness Audit Against Fixed Backend

**Date**: 2026-03-06
**Auditor**: codebase-auditor agent
**Scope**: Frontend event handlers, components, mappers, and query cache — readiness for backend fixes BE-13, BE-18, BE-19, BE-26, BE-27, BE-28, BE-29, BE-03, BE-04, BE-09, BE-10, BE-12, BE-30
**Files audited**: `stream-slice.ts`, `ws-bridge.ts`, `query-keys.ts`, `types.ts`, `wire-types.ts`, `mappers.ts`, `permission-slice.ts`, `message-stream.tsx`, `plan-update-card.tsx`, `artifact-card.tsx`, `thought-block.tsx`, `tool-call-card.tsx`, `error-alert.tsx`

---

## 1. stream-slice.ts Event Handler Coverage

### [OK] FE-01 -- `message_chunk` handler correctly uses `finish_reason`

- **Location**: `stream-slice.ts:49,72`
- **Description**: The handler sets `entry.streaming = !event.finish_reason`. Now that the backend emits `finish_reason` via BE-27 fix (`on_chat_model_end` handler), this will correctly transition messages from streaming to complete.
- **Status**: Ready -- no frontend change needed.

### [OK] FE-02 -- `thought_chunk` handler works with BE-26 fix

- **Location**: `stream-slice.ts:82-121`
- **Description**: The handler accumulates `thought_chunk` events by `message_id`, creating `ThoughtEvent` entries in the stream. The backend now emits `ThoughtChunkEvent` from both `on_custom_event` and from reasoning content blocks in `on_chat_model_stream` (BE-26 fix). The wire type has `message_id` and `content` fields which match.
- **Status**: Ready -- no frontend change needed.

### [OK] FE-03 -- `plan_update` handler matches BE-28 fix output

- **Location**: `stream-slice.ts:232-256`
- **Description**: The handler reads `event.entries` (array of `PlanEntry`), maps each entry to `{ id, title: e.content, status: e.status, priority: e.priority }`. The backend `PlanUpdateEvent` has `entries: list[PlanEntry]` where `PlanEntry` has `content`, `status`, `priority` fields. The wire-types.ts confirms this shape.
- **Note**: The handler maps `e.content` to `title` in the frontend `PlanEntry` type. This is correct -- the backend field is `content` (the plan step text) and the frontend uses `title` for display. The mapping at line 247 (`title: e.content`) handles this translation.
- **Status**: Ready -- no frontend change needed.

### [HIGH] FE-04 -- `artifact_update` handler reads `event.last_chunk` but backend field was `complete`

- **Location**: `stream-slice.ts:195-229`, wire-types.ts:926-931, backend events.py:202-203
- **Description**: The backend `ArtifactUpdateEvent` has fields `append: bool = False` and `last_chunk: bool = False`. The wire-types.ts confirms `append` and `last_chunk` fields. The stream-slice handler uses:
  - `event.append` (line 205) -- correct, matches wire type
  - `event.last_chunk` (line 209) -- correct, matches wire type

  However, the frontend `ArtifactEvent` type (types.ts:119-128) uses `complete: boolean`, not `last_chunk`. The handler maps `last_chunk` to `complete` at lines 209 and 222 (`complete: event.last_chunk`). This mapping is correct.

  **But**: the `ArtifactCard` component (artifact-card.tsx:19) checks `event.old_content` to distinguish "modified" vs "created". The backend `ArtifactUpdateEvent` does NOT have an `old_content` field -- it only has `content`, `append`, `last_chunk`. So `event.old_content` is always `undefined`, and all artifacts display as "created" even when they are modifications.
- **Impact**: All artifact cards show "created" label, never "modified". Minor cosmetic issue.
- **Fix**: Either remove the `old_content` check in `ArtifactCard` (always show "created" or just the filename), or have the backend include diff context in artifact events.

### [OK] FE-05 -- `tool_call_start` / `tool_call_update` handlers consume enriched data from BE-30

- **Location**: `stream-slice.ts:124-192`
- **Description**: The `tool_call_start` handler reads `event.locations`, `event.content` (array with text/diff blocks), `event.kind`, `event.status`. The `tool_call_update` handler reads `event.status`, `event.title`, `event.kind`, `event.content`. These fields match the `ToolCallStartEvent` and `ToolCallUpdateEvent` wire types. The BE-30 fix enriches these events with input/output content and kind classification.
- **Status**: Ready -- the handlers already consume the enriched fields. The content array structure (`content_type: 'text'` / `content_type: 'diff'`) is correctly parsed.

### [OK] FE-06 -- `error` handler is complete

- **Location**: `stream-slice.ts:281-300`
- **Description**: Reads `event.message`, `event.code`, `event.agent_id`. Matches `ErrorEvent` wire type.
- **Status**: Ready.

### [OK] FE-07 -- `agent_status` handler is complete

- **Location**: `stream-slice.ts:259-278`
- **Description**: Reads `event.agent_id`, `event.node_name`, `event.state`. Matches `AgentStatusEvent` wire type.
- **Status**: Ready.

---

## 2. ws-bridge.ts Event Dispatch

### [OK] FE-08 -- All stream event types are dispatched to `handleWireEvent`

- **Location**: `ws-bridge.ts:44-53`
- **Description**: The bridge dispatches `message_chunk`, `thought_chunk`, `tool_call_start`, `tool_call_update`, `artifact_update`, `plan_update`, `error` to `handleWireEvent`. All 7 stream event types that the backend can now emit are covered.
- **Status**: Ready.

### [OK] FE-09 -- `agent_status` triple dispatch is correct

- **Location**: `ws-bridge.ts:56-79`
- **Description**: Dispatches to: (1) stream slice via `handleWireEvent`, (2) TanStack Query team status cache, (3) TanStack Query thread list cache. Updates agent state in both caches optimistically.
- **Status**: Ready.

### [OK] FE-10 -- `team_status` updates TQ cache with full agent list

- **Location**: `ws-bridge.ts:82-88`
- **Description**: Full replacement of team status TQ cache via `setQueryData`. Uses `mapAgentSummary` which now maps `role`, `display_name`, `description` (enriched by BE-12 fix).
- **Status**: Ready.

### [OK] FE-11 -- `permission_request` pushes to permission slice

- **Location**: `ws-bridge.ts:91-93`
- **Description**: Calls `pushPermission(event)` which maps via `mapPermissionRequest`. Now that BE-13 is fixed, the wire event will have correct `option_id`/`name` field names.
- **Status**: Ready.

### [MED] FE-12 -- No `team_status` invalidation after `plan_update` or `artifact_update`

- **Location**: `ws-bridge.ts:44-53`
- **Description**: When `plan_update` or `artifact_update` events arrive, only the stream slice is updated. The TanStack Query thread state cache (`queryKeys.threads.state(threadId)`) is NOT invalidated. If the user has the thread state snapshot cached, it will be stale -- the plan/artifact data won't appear until the next manual refetch.
- **Impact**: Low in practice -- the stream view shows plan/artifact events immediately. The snapshot is only used on reconnection/initial load.
- **Fix**: Add `queryClient.invalidateQueries({ queryKey: queryKeys.threads.state(threadId) })` after plan_update and artifact_update events. This triggers a background refetch of the snapshot.

### [LOW] FE-13 -- No sequence gap detection or replay request

- **Location**: `ws-bridge.ts:101-104`
- **Description**: The bridge tracks `lastSequence` per thread via `wsClient.updateLastSequence()`. But there is no logic to detect gaps (e.g., received sequence 5 after sequence 3, missing 4) or request replay. This relates to backend BE-36 (no missed-event replay mechanism).
- **Impact**: On packet loss or brief disconnects, events may be silently missed. The sequence tracking infrastructure is in place but unused.
- **Fix**: Deferred until backend implements replay mechanism (BE-36).

---

## 3. Component Rendering Readiness

### [OK] FE-14 -- `PlanUpdateCard` renders correctly with backend data shape

- **Location**: `plan-update-card.tsx:1-37`
- **Description**: Receives `PlanUpdateEvent` with `entries: PlanEntry[]`. Counts completed entries. Renders "Plan updated" with progress indicator. The `PlanEntry` type has `id`, `title`, `status`, `priority`. The stream-slice handler correctly maps backend `content` to frontend `title`.
- **Status**: Ready.

### [MED] FE-15 -- `ArtifactCard` inspect handler shows raw JSON, not artifact content

- **Location**: `message-stream.tsx:220-236` (handleInspect)
- **Description**: When clicking an artifact card, `handleInspect` creates a `ContextDocument` with `content: JSON.stringify(e, null, 2)`. This shows the raw event JSON in the inspector panel, not the actual file content. For artifacts, the `content` field contains the file content but it's wrapped in JSON.
- **Impact**: Artifact inspection shows raw JSON instead of rendered file content. Usable but poor UX.
- **Fix**: Add artifact-specific handling in `handleInspect` that uses `event.content` directly and sets `type: 'file'` with proper filename.

### [OK] FE-16 -- `ThoughtBlock` renders correctly

- **Location**: `thought-block.tsx:1-33`
- **Description**: Collapsible block showing thought content. Receives `ThoughtEvent` with `content: string`. Renders in italic monospace. The backend now emits thought chunks from both extended thinking and custom events.
- **Status**: Ready.

### [OK] FE-17 -- `ErrorAlert` renders correctly

- **Location**: `error-alert.tsx` (component exists)
- **Description**: Error events from `stream-slice.ts` are rendered by `ErrorAlert` in `message-stream.tsx:590`. Error events include `message`, `code`, `agent_id`.
- **Status**: Ready.

### [OK] FE-18 -- `message-stream.tsx` routes all event types to components

- **Location**: `message-stream.tsx:134-168` (AgentCapsule event switch)
- **Description**: The switch handles: `agent_message` -> `AgentBubble`, `thought` -> `ThoughtBlock`, `tool_call` -> `ToolCallCard`, `artifact` -> `ArtifactCard`, `plan_update` -> `PlanUpdateCard`, `agent_status` -> null (suppressed). All grouped by agent in capsules.
- **Status**: Ready -- all event types route to components.

### [MED] FE-19 -- `PermissionCard` passes `onInspect` but no inspector integration for plan approval

- **Location**: `message-stream.tsx:600-608`
- **Description**: Permission cards render inline in the stream. The `PermissionCard` component receives `onRespond` callback. Plan approval permissions (from BE-19 fix) send `option_id: "approve"` or `"reject"`. The `onRespondPermission` callback dispatches via REST `POST /api/permissions/{id}/respond` which the endpoint now correctly wraps in a dict for the supervisor. This flow is end-to-end correct.

  However, plan approval permissions have a `description` that mentions plan documents but there's no way to view the plan documents before approving. The inspector panel is not connected.
- **Impact**: Users approve/reject plans without being able to inspect the plan content. Functional but blind.
- **Fix**: Enhance `PermissionCard` to show plan details when `tool_call === "plan_approval"`, or link to the inspector panel with plan context.

---

## 4. Wire Type Staleness

### [CRIT] FE-20 -- `wire-types.ts` is stale: missing `tool_kind` on `PermissionRequestEvent`

- **Location**: `wire-types.ts:1076-1117`, backend `events.py:192`
- **Description**: The backend `PermissionRequestEvent` now has `tool_kind: ToolKind | None = None` (added as part of BE-04 fix). But `wire-types.ts` was generated before this field was added -- it only has `tool_call: string | null` (line 1116) and no `tool_kind` field.

  The mapper at `mappers.ts:75` hardcodes `tool_kind: 'other'` because the wire type doesn't expose `tool_kind`. Even after the BE-04 backend fix adds `tool_kind` to the event, the frontend won't use it until wire-types.ts is regenerated.
- **Impact**: Permission request cards continue to show the generic "other" icon even after the backend fix. The `tool_kind` data is sent over the wire but TypeScript types don't expose it, so the mapper ignores it.
- **Fix**: Regenerate `wire-types.ts` from the OpenAPI schema (`npx openapi-typescript`). Then update `mapPermissionRequest` to use `wire.tool_kind ?? 'other'` instead of hardcoded `'other'`.

### [HIGH] FE-21 -- `wire-types.ts` Provider enum missing `mock`

- **Location**: `wire-types.ts:513`
- **Description**: Wire type has `Provider: "claude" | "gemini" | "openai" | "zhipu"`. The backend `Provider` enum includes `MOCK = "mock"` (added during ADR-028 sprint). The frontend `types.ts:18` has `'mock'` in the Provider union. But the wire type is stale and doesn't include it.
- **Impact**: Mock provider agents may cause TypeScript type mismatches in strict type checking. Functionally works because the string passes through untyped.
- **Fix**: Regenerate `wire-types.ts`.

### [MED] FE-22 -- `wire-types.ts` may be missing enriched `_AgentSnapshot` fields from BE-10

- **Location**: Wire type `_AgentSnapshot` vs backend snapshot schema
- **Description**: BE-10 added `role`, `display_name`, `description` fields to `_AgentSnapshot`. If wire-types.ts was generated before BE-10, the snapshot hydration queries may not expose these fields to the frontend.
- **Impact**: Thread state snapshot agents may lack role/display_name/description even after the backend enriches them. Falls back to agent_id display.
- **Fix**: Regenerate `wire-types.ts`.

---

## 5. TanStack Query Cache Coherence

### [OK] FE-23 -- Thread list cache updated on `agent_status` events

- **Location**: `ws-bridge.ts:72-78`
- **Description**: `agent_status` events update the thread's `agent_state` in the thread list cache via `setQueryData`. This enables real-time status indicators in the sidebar.
- **Status**: Ready.

### [MED] FE-24 -- Thread list cache NOT updated on `thread_terminal` status changes

- **Location**: `ws-bridge.ts:43-99` (no handler for thread completion)
- **Description**: When a thread completes or fails, the backend emits `thread_terminal` as an internal event (not a wire event). The frontend learns about status changes only via REST polling (`useThreadsQuery` refetch). There is no WS event that signals thread completion to invalidate the thread list cache.

  The `agent_status` event with `state: "completed"` does arrive and updates `agent_state` in the cache. But the thread's `status` field (COMPLETED/FAILED/CANCELLED in the DB) is separate from `agent_state` and is not updated.
- **Impact**: Thread list shows correct agent activity state but the thread-level status (e.g., "completed" badge) is stale until the next REST refetch. The `useThreadsQuery` likely has a refetchInterval but this introduces latency.
- **Fix**: Either (a) emit a wire `thread_status_changed` event when the DB status updates, or (b) invalidate `queryKeys.threads.list()` when `agent_status` state is `"completed"` or `"failed"`.

### [LOW] FE-25 -- No query invalidation on permission resolution

- **Location**: `ws-bridge.ts`, `permission-slice.ts`
- **Description**: When a user responds to a permission request (REST mutation), the permission is removed from the Zustand queue via `removePermission`. But the thread state TQ cache is not invalidated. If the snapshot was cached with pending permissions, it remains stale.
- **Impact**: Negligible -- the permission queue is Zustand-managed, not TQ-cached. The snapshot's `pending_permissions` field is only used on initial load.
- **Fix**: None needed for now.

---

## 6. Mapper and Type Alignment Issues

### [MED] FE-26 -- `mapPermissionRequest` uses `agent_id` as `agent_name` fallback

- **Location**: `mappers.ts:73`
- **Description**: `agent_name: wire.agent_id ?? ''` -- the mapper uses the raw agent_id as the display name. The wire `PermissionRequestEvent` does not have an `agent_name` or `node_name` field. The frontend `PermissionRequest` type expects `agent_name: string`.
- **Impact**: Permission request cards display the technical agent_id (e.g., `"mock-coder-success"`) instead of a human-readable name (e.g., `"Coder"`). Functional but ugly.
- **Fix**: Either add `node_name` to the backend `PermissionRequestEvent` model (aligning with `AgentStatusEvent` which has it), or have the frontend resolve the display name from the team status TQ cache using `agent_id`.

### [OK] FE-27 -- `mapAgentSummary` correctly maps enriched fields

- **Location**: `mappers.ts:43-56`
- **Description**: Maps `role`, `display_name`, `description` with fallbacks to empty string. Now that BE-12 syncs node metadata to the API aggregator, these fields will be populated in `team_status` events and REST responses.
- **Status**: Ready.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 1     | wire-types.ts stale: missing `tool_kind` on PermissionRequestEvent (FE-20) |
| HIGH     | 2     | ArtifactCard always shows "created" (FE-04), wire-types missing `mock` provider (FE-21) |
| MED      | 6     | No TQ invalidation on plan/artifact events (FE-12), artifact inspect shows JSON (FE-15), plan approval blind approve (FE-19), stale _AgentSnapshot wire type (FE-22), thread status cache stale (FE-24), permission agent_name is agent_id (FE-26) |
| LOW      | 2     | No sequence gap detection (FE-13), no permission resolution TQ invalidation (FE-25) |
| OK       | 13    | All event handlers ready, components render correctly, ws-bridge dispatch complete |

**Total: 24 findings** (1 CRIT, 2 HIGH, 6 MED, 2 LOW, 13 OK)

---

## Priority Fix Order

### Tier 1: Immediate (blocks correctness)
1. **FE-20** (CRIT) -- Regenerate `wire-types.ts` from OpenAPI schema. Update `mapPermissionRequest` to use `wire.tool_kind`.

### Tier 2: High UX impact
2. **FE-21** (HIGH) -- Included in wire-types regeneration (FE-20).
3. **FE-22** (MED) -- Included in wire-types regeneration (FE-20).
4. **FE-04** (HIGH) -- Fix ArtifactCard "created"/"modified" logic (remove `old_content` check or derive from context).
5. **FE-24** (MED) -- Add thread status invalidation on terminal `agent_status` events.

### Tier 3: Polish
6. **FE-12** (MED) -- Invalidate thread state TQ cache on plan/artifact events.
7. **FE-26** (MED) -- Resolve agent display name from team status cache for permissions.
8. **FE-15** (MED) -- Artifact inspect shows file content instead of raw JSON.
9. **FE-19** (MED) -- Plan approval context display.

### Tier 4: Deferred
10. **FE-13** (LOW) -- Sequence gap detection (needs backend BE-36).
