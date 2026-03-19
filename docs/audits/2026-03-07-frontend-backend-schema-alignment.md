# Frontend ↔ Backend Schema Alignment Audit

**Date**: 2026-03-07
**Scope**: TypeScript wire-types.ts + types.ts vs. Pydantic schemas (events, REST, snapshots, enums)
**Status**: Backend CORRECT (5/7 CRIT fixed); Frontend BOTTLENECK: wire-types.ts is stale (not regenerated since backend fixes)
**Root Cause**: wire-types.ts is auto-generated from OpenAPI schema — needs regeneration to sync with backend changes from previous sprint

---

## Verification Status (2026-03-07)

### Backend Status: ✅ CORRECT

✓ **PermissionRequestEvent.tool_kind** — PRESENT (events.py:192); used in aggregator.py:913, emitted at ~line 917
✓ **ConnectedEvent** — PRESENT (events.py:235) with client_id, server_version, active_threads
✓ **PermissionOption fields** — CORRECT (option_id, name — events.py:106-107)
✓ **_classify_tool_kind()** — IMPLEMENTED (aggregator.py:271)
✓ **finish_reason emission** — IMPLEMENTED (aggregator.py:1264-1278)

### Frontend Status: ❌ STALE (wire-types.ts not regenerated)

❌ **wire-types.ts** lacks:

- PermissionRequestEvent.tool_kind field
- ConnectedEvent schema entirely
- Provider.mock enum value
- ArtifactUpdateEvent.append + last_chunk fields

**Root Cause**: wire-types.ts is auto-generated from OpenAPI schema. Generation hasn't been re-run since backend fixes committed in previous sprint.

---

## A. ENUM ALIGNMENT TABLE

| Enum | Backend (Pydantic) | Frontend (wire-types.ts) | Frontend (types.ts) | Mismatch? | Severity |
|------|-------------------|------------------------|------------------|-----------|----------|
| **ToolCallStatus** | `pending`, `in_progress`, `completed`, `failed` | `pending`, `in_progress`, `completed`, `failed` | `pending`, `running`, `completed`, `failed` | ⚠️ FE type uses `running` | **HIGH** |
| **ToolKind** | read, edit, delete, move, search, execute, think, fetch, switch_mode, other | read, edit, delete, move, search, execute, think, fetch, switch_mode, other | read, edit, delete, move, search, execute, think, fetch, switch_mode, other | ✓ Match | OK |
| **PermissionOptionKind** | allow_once, allow_always, reject_once, reject_always | allow_once, allow_always, reject_once, reject_always | allow_once, allow_always, reject_once, reject_always | ✓ Match | OK |
| **AgentLifecycleState** | submitted, idle, working, input_required, auth_required, completed, failed, cancelled | submitted, idle, working, input_required, auth_required, completed, failed, cancelled | submitted, idle, working, input_required, auth_required, completed, failed, cancelled | ✓ Match | OK |
| **PlanEntryStatus** | pending, in_progress, completed | pending, in_progress, completed | pending, in_progress, completed | ✓ Match | OK |
| **PlanEntryPriority** | high, medium, low | high, medium, low | high, medium, low | ✓ Match | OK |
| **Provider** | claude, gemini, mock, openai, zhipu | claude, gemini, openai, zhipu | claude, gemini, mock, openai, zhipu | ⚠️ wire-types missing `mock` | **HIGH** |
| **Model** | low, mid, high, max | low, mid, high, max | low, mid, high, max | ✓ Match | OK |
| **ServerEventType** | agent_status, message_chunk, thought_chunk, tool_call_start, tool_call_update, permission_request, artifact_update, plan_update, team_status, error, connected, heartbeat | (discriminated union) | (enum on switch) | ✓ Match | OK |

---

## B. EVENT SCHEMA ALIGNMENT

### 1. PermissionRequestEvent

| Field | Backend | Wire-Types (auto-gen) | Types.ts | Status |
|-------|---------|----------------------|----------|--------|
| type | Literal["permission_request"] | "permission_request" | N/A (handled in mappers) | ✓ |
| thread_id | str | string | N/A | ✓ |
| request_id | str | request_id | id (mapped) | ✓ |
| description | str | description | message (mapped) | ✓ |
| options | list[PermissionOption] | PermissionOption[] | PermissionOption[] (mapped) | ✓ |
| tool_call | str \| None | tool_call \| null | tool_name (mapped from tool_call) | ✓ |
| **tool_kind** | **ToolKind \| None** | **MISSING ❌** | tool_kind (expected from wire) | **CRIT** |
| agent_id | str (from EventEnvelope) | agent_id \| null | agent_id (mapped) | ✓ |
| timestamp | datetime | string | (not in PermissionRequest) | ⚠️ |
| sequence | int | number | (not stored) | ⚠️ |

**Finding**: Backend emits `tool_kind` on PermissionRequestEvent (events.py:192), but wire-types.ts has no such field. Mapper defaults it to `'other'` (mappers.ts:75). **Impact**: Frontend cannot distinguish tool permission types.**

### 2. ToolCallStartEvent

| Field | Backend | Wire-Types | Types.ts StreamEvent | Status |
|-------|---------|-----------|------------------|--------|
| type | Literal["tool_call_start"] | "tool_call_start" | "tool_call" | ✓ (discriminator mapped) |
| tool_call_id | str | tool_call_id | tool_call_id | ✓ |
| title | str | title | tool_name (mapped from title) | ✓ |
| kind | ToolKind | ToolKind | ToolKind | ✓ |
| status | ToolCallStatus | ToolCallStatus | ToolCallStatus (via mapToolCallStatus) | ⚠️ (enum mismatch) |
| locations | list[ToolCallLocation] | ToolCallLocation[] | location? (single, not array) | ⚠️ |
| content | list[ToolCallContent] | content? (array) | input?, output?, diff? (not content array) | **HIGH** |

**Finding**: Backend sends `locations: list[ToolCallLocation]` + `content: list[ToolCallContent]`, but frontend StreamEvent expects `location?: ToolCallLocation` (single) + `input/output/diff` (flat fields). **Data loss: content blocks not stored in timeline.**

### 3. ToolCallUpdateEvent

| Field | Backend | Wire-Types | Status |
|-------|---------|-----------|--------|
| All fields optional | Y | Y | ✓ |
| kind | ToolKind \| None | ToolKind \| null | ✓ |
| status | ToolCallStatus \| None | ToolCallStatus \| null | ⚠️ Enum mismatch: `in_progress` → `running` |
| locations | list \| None | ToolCallLocation[] \| null | ✓ |
| content | list \| None | content[] \| null | ✓ (but FE drops it) |

### 4. PlanUpdateEvent

| Field | Backend | Wire-Types | Types.ts | Status |
|-------|---------|-----------|----------|--------|
| type | Literal["plan_update"] | "plan_update" | "plan_update" | ✓ |
| entries | list[PlanEntry] | PlanEntry[] | PlanEntry[] (mapped) | ⚠️ |

**PlanEntry mismatch**:

- **Backend**: `{ content: str, status: PlanEntryStatus, priority: PlanEntryPriority }`
- **Wire-types**: `{ content, status, priority }`
- **Types.ts**: `{ id, title, status, priority }`

**Issue**: Frontend's PlanEntry expects `id` and `title`, but backend sends only `content`. Mapper doesn't populate `id`/`title` (see use-thread-state.ts — no plan handling).

### 5. ArtifactUpdateEvent

| Field | Backend | Wire-Types | Types.ts | Status |
|-------|---------|-----------|----------|--------|
| type | Literal["artifact_update"] | "artifact_update" | "artifact" | ✓ |
| artifact_id | str | artifact_id | artifact_id | ✓ |
| filename | str | filename | filename | ✓ |
| content | str | content | content | ✓ |
| append | bool | (missing) | (not used) | ⚠️ MISSING |
| last_chunk | bool | (missing) | (not used) | ⚠️ MISSING |

**Finding**: Backend sends `append` and `last_chunk` to signal streaming progress, but wire-types.ts omits both fields. **Data loss: Frontend cannot detect complete artifacts.**

### 6. TeamStatusEvent

| Field | Backend | Wire-Types | Usage (ws-bridge) | Status |
|-------|---------|-----------|------------------|--------|
| agents | list[AgentSummary] | AgentSummary[] | Stored flat in TQ cache | ✓ |
| active_thread_ids | list[str] (default=[]) | active_thread_ids? | (not used) | ⚠️ |

**Finding**: ws-bridge.ts:84-86 caches only `agents` array, discarding `active_thread_ids`. Backend sends it but frontend ignores.

### 7. ConnectedEvent

| Field | Backend | Wire-Types | Status |
|-------|---------|-----------|--------|
| type | Literal["connected"] | "connected" | ✓ |
| client_id | str | (missing) | **CRIT** |
| server_version | str | (missing) | **CRIT** |
| active_threads | list[str] | (missing) | **CRIT** |
| metadata | dict \| None | metadata (generated) | ⚠️ |

**CRITICAL**: wire-types.ts has NO ConnectedEvent schema! Auto-generation likely skipped it. Breaks reconnection flow.

---

## C. REST RESPONSE ALIGNMENT

### 1. TeamStatusResponse

| Field | Backend (rest.py) | Wire-Types | Frontend Usage | Status |
|-------|------------------|-----------|----------------|--------|
| agents | list[AgentStatusEntry] | AgentStatusEntry[] | Mapped to AgentSummary[] via mapAgentSummary | ✓ |
| active_threads | list[str] | active_threads | **NOT STORED** in TQ query cache | **MED** |
| pending_permissions | list[PendingPermission] | PendingPermission[] | **NOT QUERIED** (Zustand only) | **MED** |

**Finding**: useTeamStatusQuery() discards 2 of 3 response fields (active_threads, pending_permissions). Likely dead code fields in backend.

### 2. ThreadListResponse → ThreadSummary cache

| Field | Backend | Wire-Types | FE types.ts | Mapper | Status |
|-------|---------|-----------|------------|--------|--------|
| thread_id | str | string | string | ✓ | ✓ |
| title | str \| None | string \| null | string | Maps null → "Untitled" | ✓ |
| status | str | string | string | ✓ | ✓ |
| agent_state | AgentLifecycleState \| None | AgentLifecycleState \| null | AgentLifecycleState | Maps null → "submitted" | ✓ |
| team_preset | str \| None | string \| null | string \| undefined | ✓ | ✓ |
| created_at | datetime | string | string \| undefined | ❌ DROPPED | **HIGH** |
| updated_at | datetime | string | string | ✓ | ✓ |
| nickname | str \| None | string \| null | string \| undefined | ✓ | ✓ |
| feature_tag | str \| None | string \| null | string \| undefined | ✓ | ✓ |
| source_branch | str \| None | string \| null | string \| undefined | ✓ | ✓ |
| callee | str \| None | string \| null | string \| undefined | ✓ | ✓ |

**Critical**: Mapper (mappers.ts:27-40) does NOT map `created_at`. Thread list queries silently drop creation timestamp. **Impact: UI cannot sort by creation date.**

### 3. TeamPresetsResponse → TeamPreset

| Field | Backend | Wire-Types | FE types.ts | Mapper | Issue |
|-------|---------|-----------|------------|--------|-------|
| id | str | id | id | ✓ | ✓ |
| display_name | str | display_name | **name** (renamed!) | ✓ map display_name → name | ✓ |
| description | str | description | description | ✓ | ✓ |
| topology | str | string | TeamTopology | ✓ cast | ✓ |
| worker_count | int | number | worker_count | ✓ | ✓ |

---

## D. TANSTACK CACHE SHAPE ISSUES

### 1. Team Status Query

**useTeamStatusQuery()** (use-team.ts:6-14):

```typescript
queryFn: async () => {
  const res = await restClient.getTeamStatus();
  return res.agents.map(mapAgentSummary);  // Returns AgentSummary[]
}
```yaml

- **Expected cache shape**: `AgentSummary[]`
- **ws-bridge.ts:84-86**: Writes directly: `setQueryData<AgentSummary[]>(..., event.agents.map(mapAgentSummary))`
- **Status**: ✓ Aligned

### 2. Threads List Query

**useThreadsQuery()** (use-threads.ts:12-20):

```typescript
queryFn: async () => {
  const res = await restClient.listThreads();
  return res.threads.map(mapThreadSummary);  // Returns ThreadSummary[]
}
```typescript

- **Expected cache shape**: `ThreadSummary[]`
- **ws-bridge.ts:72-78**: Updates on agent_status: patches thread's `agent_state`
- **Status**: ✓ Aligned (but created_at missing)

### 3. Thread State Query

**useThreadStateQuery()** (use-thread-state.ts:24-95):

- Returns `{ events: StreamEvent[], lastSequence: number }`
- **Status**: ✓ Own shape, not synced with ws-bridge

---

## E. DATA LOSS INVENTORY

### Rank by User Impact

| Severity | Field | Source | Why Lost | Impact |
|----------|-------|--------|---------|--------|
| **CRIT** | `tool_kind` | PermissionRequestEvent | Wire-types missing, mapper defaults to 'other' | Users can't see permission reason (read vs edit vs delete) |
| **CRIT** | `ConnectedEvent` fields (client_id, server_version, active_threads) | Backend / wire-types | Wire-types schema MISSING entirely | Reconnection flow broken; can't validate session continuity |
| **HIGH** | `ToolCallStatus` enum: `in_progress` → `running` | Mappers | mapToolCallStatus converts; types.ts uses `running` | Enum mismatch causes type errors; ambiguous state names |
| **HIGH** | `created_at` timestamp | ThreadListResponse | Mapper (mappers.ts:27) never maps it | UI can't sort threads by creation date; lost audit trail |
| **HIGH** | `ToolCallContent` array (text/diff/terminal blocks) | ToolCallStartEvent + ToolCallUpdateEvent | Frontend StreamEvent stores only `input/output/diff`, not content array | Diff content lost; terminal outputs not captured |
| **HIGH** | `PlanEntry.id` and `title` | PlanUpdateEvent | Backend sends only `content`, no id; mapper doesn't populate | UI generates UUIDs instead of stable IDs; plan entries unmappable |
| **HIGH** | `Provider` enum: `mock` | wire-types.ts:513 | Auto-gen dropped mock provider | Can't test with mock provider via UI |
| **MED** | `ToolCallLocation` array → single | ToolCallStartEvent | Frontend StreamEvent stores single `location`, not array | Multi-location tool calls lose context |
| **MED** | `ArtifactUpdateEvent.append` + `last_chunk` | Backend events | Wire-types omits both | Frontend can't detect streaming completion; may merge incomplete artifacts |
| **MED** | `TeamStatusResponse.active_threads` + `pending_permissions` | REST response | useTeamStatusQuery only extracts `agents` | Stale team state; pending permissions not sync'd |
| **LOW** | `Agent.display_name` + `description` + `role` | AgentSummary | Mapped but ts.ts uses optional defaults | Incomplete team status display (fields empty) |
| **LOW** | `timestamp` in StreamEvent | Tool/Artifact events | use-thread-state.ts sets to empty string | Timeline events unordered; audit trail lost |

---

## F. CRITICAL FINDINGS SUMMARY

### 🔴 BLOCKING ISSUES

1. **PermissionRequestEvent lacks `tool_kind`** (wire-types line ~1079)
   - Backend emits it (events.py:192)
   - Wire-types MISSING field
   - Mapper defaults to `'other'` → lose permission context
   - **Fix**: Add `tool_kind?: components["schemas"]["ToolKind"] | null;` to PermissionRequestEvent in wire-types

2. **ConnectedEvent completely missing from wire-types**
   - Backend has it (events.py, line 235-242)
   - Wire-types has NO schema for it
   - **Impact**: Reconnection validation broken
   - **Fix**: Regenerate wire-types from OpenAPI schema OR manually add ConnectedEvent schema

3. **Provider enum missing `mock`** in wire-types
   - Backend has `mock` (utils/enums.py:52)
   - Wire-types:513 omits it
   - **Fix**: Re-run openapi-typescript generation with latest backend schema

4. **ThreadListResponse.created_at dropped by mapper**
   - Mapper (mappers.ts:27-40) never maps `created_at`
   - **Fix**: Add line: `created_at: wire.created_at,` to mapThreadSummary

5. **ToolCallStatus enum value mismatch** in types.ts
   - Backend: `in_progress`
   - Frontend types.ts: `running` (should be `in_progress`)
   - Wire-types correct: `in_progress`
   - **Fix**: Change types.ts:14 from `running` to `in_progress`

6. **ToolCallContent array lost** in StreamEvent
   - Backend sends `list[ToolCallContent]` (text/diff/terminal)
   - Frontend StreamEvent has no `content` field
   - **Fix**: Add `content?: ToolCallContent[]` to ToolCallEvent in types.ts

7. **PlanEntry missing `id` + `title` fields**
   - Backend sends `content` (string)
   - Frontend expects `id` + `title`
   - **Fix**: Either (a) add id/title to backend PlanEntry, or (b) update frontend to use `content` as title

### 🟡 HIGH PRIORITY

- ArtifactUpdateEvent missing `append` + `last_chunk` fields in wire-types
- TeamStatusResponse fields (active_threads, pending_permissions) unused in frontend
- Agent metadata fields (display_name, description, role) commonly empty

---

## G. RECOMMENDED FIXES (PRIORITY ORDER)

### Priority 1 (Today)

1. Add `tool_kind?: ToolKind | null;` to PermissionRequestEvent in wire-types.ts (around line 1117)
2. Update mappers.ts to use tool_kind from event (line 75)
3. Change types.ts ToolCallStatus from `'running'` to `'in_progress'` (line 14)
4. Add `created_at: wire.created_at,` to mapThreadSummary (mappers.ts:27)

### Priority 2 (This sprint)

5. Regenerate wire-types.ts from OpenAPI schema to capture:
   - ConnectedEvent (missing entirely)
   - Provider.mock (missing from enum)
   - ArtifactUpdateEvent.append + last_chunk
   - Any other stale fields

6. Add `content?: ToolCallContent[]` to ToolCallEvent in types.ts
7. Fix PlanEntry shape (add id + title to backend, or update frontend to use content)

### Priority 3 (Design decision)

8. Decide on TeamStatusResponse unused fields (active_threads, pending_permissions) — keep or deprecate?
9. Populate Agent metadata fields (display_name, description, role) from compiled graph metadata

---

---

## PASS 2: WS Event Emission Paths (14:45 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-201 | OK | EventEmission | All 10 emit_* methods called | aggregator.py: emit_agent_status, emit_message_chunk, emit_thought_chunk, emit_tool_call_start/update, emit_permission_request, emit_artifact_update, emit_plan_update, emit_error, emit_team_status all invoked |

**Status**: Backend emits all defined events. No dead-code emitters found.

---

## PASS 3: Snapshot Enrichment (14:48 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-301 | CRIT | SnapshotPopulation | `tool_calls` field NEVER populated | endpoints.py:_enrich_snapshot_from_state() populates messages, artifacts, plan, agents, pending_permissions; ToolCallSnapshot imported but never used; snapshot returned with tool_calls=[] (default) |
| SA-302 | HIGH | SnapshotFields | Agent metadata (role, display_name, description) sourced from aggregator.get_node_summaries() — may be empty | endpoints.py:535-537; depends on graph compilation populating metadata |
| SA-303 | HIGH | MessageTimestamp | Message timestamps fallback to datetime.now(UTC) if not in response_metadata | endpoints.py:466-467; affects snapshot consistency on replay |

**Impact**: Frontend queries tool_calls in snapshot (use-thread-state.ts line 56), receives empty list. WS events have tool calls but snapshot doesn't match.

---

## PASS 4: Component ↔ Type Alignment (14:50 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-401 | HIGH | ComponentUnsafeAccess | ArtifactCard references `event.old_content` without optional chaining | artifact-card.tsx:19 uses `event.old_content ? 'modified' : 'created'`; types.ts:127 defines old_content as optional; will fail if undefined |
| SA-402 | HIGH | MissingDataHandling | app-shell.tsx:70 defaults `agents = []` but TeamStatusQuery returns AgentSummary[] directly | safe fallback, but shows pattern of incomplete optional handling |
| SA-403 | HIGH | UnusedData | useTeamStatusQuery() response has active_threads + pending_permissions, but only agents[] is extracted (use-team.ts:11) | TeamStatusResponse schema includes 3 fields, only 1 used |
| SA-404 | MED | ComponentDataLoss | Stream events may lack agent_id (set to empty string in hydration) | use-thread-state.ts:48-49 falls back to empty string; components display "Unknown Agent" |

---

## APPENDIX: FIELD COVERAGE MATRIX

**Legend**: ✓ = mapped, ❌ = missing, ⚠️ = dropped/mismatch, ? = unused

| Event Type | wire-types Coverage | Mapper Coverage | FE StreamEvent Coverage | TQ Cache Sync |
|------------|-------------------|-----------------|------------------------|---------------|
| message_chunk | 100% | N/A | 90% (no finish_reason) | ✓ (Zustand) |
| thought_chunk | 100% | N/A | 100% | ✓ (Zustand) |
| tool_call_start | 85% (missing tool_kind) | 75% (content dropped) | 60% (locations→single, no content) | ⚠️ (Zustand) |
| tool_call_update | 85% | 75% | 60% | ⚠️ (Zustand) |
| permission_request | 85% (missing tool_kind) | 70% (no tool_kind map) | 70% | ✓ (Zustand) |
| artifact_update | 80% (missing append, last_chunk) | N/A | 100% | ✓ (Zustand) |
| plan_update | 100% | N/A | 50% (missing id/title) | ✓ (Zustand) |
| team_status | 100% | 100% | N/A | ✓ (TQ) |
| agent_status | 100% | 100% | 100% | ✓ (TQ + Zustand) |
| connected | 0% (MISSING) | N/A | N/A | ❌ BROKEN |
| error | ? (not reviewed) | N/A | 100% | ✓ (Zustand) |

---

---

## PASS 5: REST Error Handling (14:55 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-501 | HIGH | ErrorHandling | Frontend queries don't distinguish error types | rest-client.ts:23-31 throws RestClientError(status, statusText, body); all queries' onError just logs without status checking |
| SA-502 | HIGH | ErrorHandling | No UI feedback for REST errors (404, 409, 422) | useCreateThread (use-threads.ts:74), useThreadsQuery, useTeamStatusQuery all log errors but don't show toast/alert |
| SA-503 | MED | ErrorHandling | 404 (thread not found), 409 (archived), 422 (invalid metadata) responses are silent | endpoints.py raises HTTPException with detail, but frontend doesn't parse or display detail field |

**Status**: Errors silently logged to console. Users see nothing when operations fail.

---

## PASS 6: Zustand Store ↔ WS Bridge Data Flow (15:02 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-601 | OK | DataFlow | ArtifactUpdateEvent.append + last_chunk ARE used | stream-slice.ts:213,217,230 correctly references fields; wire-types HAS them (append boolean, last_chunk boolean) — earlier finding SA-302 was CORRECTED |
| SA-602 | HIGH | DataFlow | tool_call_id used as chunk index key but tool calls not in snapshots | stream-slice.ts:143 indexes tool_call_id; but endpoints.py:_enrich_snapshot never populates tool_calls — snapshot mismatch |
| SA-603 | MED | DataFlow | Agent names resolved from _agentDisplayNames map (thread-global) | stream-slice.ts:41-42; name sourced from team_status event; undefined agents show as empty string |
| SA-604 | MED | DataFlow | Plan entries use unstable ID (timestamp-based) | stream-slice.ts:247 `id: plan-${event.timestamp}` — multiple events same timestamp collide |

**Status**: Most data flows correctly. Main mismatch: tool_calls not populated in snapshots (SA-301 unchanged).

---

## PASS 7: Node Metadata Population (15:08 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-701 | CRIT | MetadataPopulation | `register_graph()` is NEVER called on EventAggregator | app.py:256 initializes EventAggregator() but never calls register_graph(). Result:_node_metadata always empty. |
| SA-702 | CRIT | MetadataPopulation | Agent metadata (role, display_name, description) always returns empty strings | aggregator.py:403-406 caches metadata, but if register_graph() never runs, defaults to "". Snapshots return empty agent summaries. |
| SA-703 | HIGH | MetadataPopulation | Workers (langchain/thread runners) don't populate aggregator metadata | ADR-012 §6 assumes register_graph() on aggregator; nothing in worker flow calls it |

**Impact**: All AgentSummary instances have empty role/display_name/description. Team status shows agents with no metadata. Snapshot agents likewise empty.

---

## PASS 8: Database Schema ↔ REST Response (15:15 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-801 | OK | Schema | ThreadModel has all fields needed by ThreadSummary | models.py: id, title, created_at, updated_at, status, nickname, team_preset present; metadata stored as JSON string in thread_metadata |
| SA-802 | OK | Schema | ThreadMetadata JSON parsing graceful fallback | endpoints.py:369-380 tries to parse metadata, falls back to None on error |
| SA-803 | MED | Schema | ArtifactModel missing content field | models.py has id/thread_id/type/path/hash/created_at/agent_id; content is stored in LangGraph checkpoint (not DB) |

**Status**: Database schema adequate. Content stored in checkpointer (by design). REST responses map correctly.

---

## PASS 9: WebSocket Error Handling (15:18 UTC)

| ID | Severity | Category | Finding | Evidence |
|----|----------|----------|---------|----------|
| SA-901 | LOW | ErrorHandling | WS onerror silently ignored | websocket-client.ts:97 `this.ws.onerror = () => {}` — error event swallowed, only onclose fires |
| SA-902 | LOW | ErrorHandling | Malformed JSON silently dropped | websocket-client.ts:172-173 catches parse error and returns without logging |
| SA-903 | LOW | ErrorHandling | No instrumentation on message failures | WebSocket send (line 158) doesn't check success or log errors |

**Status**: WS client robust but silent. Errors not propagated to UI.

---

## PASS 10: Event Emission Trace (15:25 UTC)

### Event Emission Table

| Event Type | Emitted? | From | Triggers | Evidence |
|------------|----------|------|----------|----------|
| **AgentStatusEvent** | ✅ | aggregator.py | emit_agent_status() × 3 call sites | aggregator.py:1386,1393,1435 |
| **MessageChunkEvent** | ✅ | aggregator.py | on_chat_model_stream callback | aggregator.py:1273 |
| **ThoughtChunkEvent** | ✅ | aggregator.py | on_chain_stream callback | aggregator.py:1227,1256,1375 |
| **ToolCallStartEvent** | ✅ | aggregator.py | _emit_tool_call_start (on_tool_start) | aggregator.py:1287 |
| **ToolCallUpdateEvent** | ✅ | aggregator.py | on_tool_stream + on_tool_end | aggregator.py:1315,1361 |
| **PermissionRequestEvent** | ✅ | aggregator.py | emit_permission_request (on_interrupt) | aggregator.py:1545,1593 |
| **ArtifactUpdateEvent** | ✅ | aggregator.py | on_tool_end (file-tool detection) | aggregator.py:1342,1420 |
| **PlanUpdateEvent** | ✅ | aggregator.py | on_chain_end (supervisor update) | aggregator.py:1414 |
| **ErrorEvent** | ✅ | aggregator.py | on_chain_error | aggregator.py:1699 |
| **TeamStatusEvent** | ✅ | aggregator.py | emit_team_status + _emit_team_status_from_agent_states | aggregator.py:1141,1143 |
| **ConnectedEvent** | ✅ | websocket.py | connect() on WS accept | websocket.py:156 |
| **HeartbeatEvent** | ✅ | websocket.py | _heartbeat_loop every 30s | websocket.py:500 |

### Findings

| ID | Severity | Finding | Evidence |
|----|----------|---------|----------|
| SA-1001 | OK | All 12 event types EMITTED | No dead schemas; all routes covered |
| SA-1002 | HIGH | ConnectedEvent + HeartbeatEvent in websocket.py, not aggregator | websocket.py:156 (connect), websocket.py:500 (_heartbeat_loop every 30s) |
| SA-1003 | HIGH | Heartbeat metadata missing worker threads on startup | websocket.py:148-155 falls back to aggregator if no worker_active_threads |
| SA-1004 | OK | All event emissions have telemetry instrumentation | _ws_heartbeats_counter.add(1) + event logging |

**Status**: Event emission complete and healthy. No dead schemas. ConnectedEvent/HeartbeatEvent correctly separated to WS layer (not aggregator).

---

---

## PASS 11: Snapshot Enrichment Detailed Inventory (15:32 UTC)

### ThreadStateSnapshot Field Population

| Field | Schema Default | Populated By | Status | Evidence |
|-------|---------------|----|--------|----------|
| **thread_id** | required | endpoints.py:599 | ✅ | from ThreadModel |
| **status** | required | endpoints.py:600 | ✅ | from ThreadModel |
| **messages** | [] | _enrich_snapshot_from_state:437-486 | ✅ | from LangChain messages in checkpoint |
| **tool_calls** | [] | NEVER | ❌ EMPTY | aggregator not queried, checkpoint channel unknown |
| **pending_permissions** | [] | _enrich_snapshot_from_state:542-560 | ✅ | from aggregator.get_pending_permissions() |
| **artifacts** | [] | _enrich_snapshot_from_state:507-519 | ✅ | from checkpoint['artifacts'] |
| **plan** | [] | _enrich_snapshot_from_state:492-506 | ✅ | from checkpoint['current_plan'] |
| **agents** | [] | _enrich_snapshot_from_state:521-539 | ✅ | from aggregator.get_node_summaries() + aggregator.get_agent_states() |
| **last_sequence** | required | endpoints.py:596 | ✅ | from aggregator.get_sequence() |
| **checkpoint_id** | None | _enrich_snapshot_from_state:488-490 | ⚠️ Optional | from checkpoint config if present |

### Critical Gap

**SA-1101 (CRIT)**: `tool_calls` array ALWAYS empty in snapshots

- Schema expects `list[ToolCallSnapshot]` (snapshots.py:100)
- _enrich_snapshot_from_state() does NOT populate it (no code reads from checkpoint or aggregator)
- Frontend queries snapshot expecting tool_calls (use-thread-state.ts:56-70)
- **Impact**: Tool call history lost on reconnect; WS events have tool calls but snapshot doesn't match

### Implementation Guidance

To fix SA-1101, add to _enrich_snapshot_from_state() (after line 519, before line 521):

```python
# Extract tool calls from aggregator
tool_call_snapshots: list[ToolCallSnapshot] = []
# Query aggregator for accumulated tool calls (design TBD:
# store in aggregator._tool_calls dict keyed by thread_id?)
# OR fetch from checkpoint if LangGraph stores them
```yaml

**Status**: 8/9 fields correctly populated. tool_calls is architectural gap requiring aggregator enhancement.

---

## PASS 12: WS Bridge ↔ Zustand ↔ TanStack Alignment (15:38 UTC)

### Event Handler → Zustand + TQ Cache Mapping

| WS Event | Zustand Action | TQ Cache Updated | Race Condition Risk? | Evidence |
|----------|---------------|-----------------|--------------------|----------|
| message_chunk | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| thought_chunk | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| tool_call_start | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| tool_call_update | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| artifact_update | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| plan_update | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| error | handleWireEvent | NONE (stream only) | ❌ Low | ws-bridge.ts:52 |
| **agent_status** | handleWireEvent + updateAgentDisplayNames | team.status (agents[]) + threads.list() | ⚠️ MEDIUM | ws-bridge.ts:58-78 |
| **team_status** | updateAgentDisplayNames | team.status (FULL REPLACE) | ⚠️ MEDIUM | ws-bridge.ts:84-89 |
| **permission_request** | pushPermission | NONE (Zustand only) | ❌ Low | ws-bridge.ts:94 |
| connected | setConnectionState | NONE | ❌ Low | ws-bridge.ts:34 |
| heartbeat | setLastHeartbeat | NONE | ❌ Low | ws-bridge.ts:39 |

### Race Condition Analysis

| ID | Severity | Scenario | Risk | Evidence |
|----|----------|----------|------|----------|
| SA-1201 | HIGH | agent_status → team.status cache + threads.list cache | Partial update if agent not in array | ws-bridge.ts:62-68: `findIndex` returns -1, array unchanged; threads.list only updates thread with matching ID |
| SA-1202 | HIGH | team_status FULL REPLACE vs in-flight REST query | Cache overwrite race if REST query completes after WS | ws-bridge.ts:84-86 does `setQueryData` directly; useTeamStatusQuery runs in parallel |
| SA-1203 | MEDIUM | REST snapshot query + WS tool_call events | Frontend loads empty tool_calls from snapshot, then WS emits tool_call_start but tool_calls array not in cache | No TQ cache for tool_calls; snapshot mismatch |

### Missing Cache Updates

| Event | Missing Cache | Impact | Evidence |
|-------|---------------|--------|----------|
| team_status | active_thread_ids | Thread list not sync'd from WS | ws-bridge.ts:82-90 only updates agents, not active_thread_ids |
| permission_request | permissions query | No TQ cache for pending permissions | ws-bridge.ts:94 pushes to Zustand only |
| artifact_update | artifacts (if tracked) | No TQ cache for artifacts | ws-bridge.ts:52 Zustand only |

**Status**: WS bridge architecture sound but incomplete. Agent status dual-dispatch safe. Major gap: tool_calls never cached; snapshot mismatch with WS events.

---

## SUMMARY: 13+ Critical Issues Found (Passes 3-12)

1. **tool_calls snapshot population MISSING** — backend never populates ToolCallSnapshot array (SA-301)
2. **ArtifactCard unsafe access** — references optional field without guard (SA-401)
3. **TeamStatusQuery unused data** — fetches 3 fields, uses 1 (SA-403)
4. **Agent ID loss in hydration** — stream events default to empty string (SA-404)
5. **REST errors silent** — no UI feedback for 404/409/422 errors (SA-502)
6. **Error detail fields unparsed** — backend sends helpful messages, frontend ignores (SA-503)
7. **Message timestamps inconsistent** — fallback to now() on missing metadata (SA-303)

---

## PASS 13: ERROR HANDLING & VALIDATION ALIGNMENT

**Objective**: Verify error propagation, validation schema alignment, and error recovery semantics between REST client and frontend mutations.

### 13.1 Backend Error Response Schema

**Backend Exception Handlers** (endpoints.py):

- 422 (Unprocessable Entity): `workspace_root` validation (line 175), nickname validation error
- 409 (Conflict): Duplicate nickname (line 254), archived thread message (line 688), invalid status transition (line 1035)
- 404 (Not Found): Thread/metadata missing (lines 417, 594, 685, 879, 955, 1010, 1027)
- 202 (Accepted): SendMessage returns 202 on success (line 741)

**FastAPI Default Error Format** (as per Pydantic):

```json
{
  "detail": "Thread not found"  // simple string
}
```text

### 13.2 Frontend Error Handling Gaps

| Component | Handles | Details Parsed | Severity | Evidence |
|-----------|---------|-----------------|----------|----------|
| **RestClient.get()** | res.ok check | ❌ NO — only calls `res.text()` | MEDIUM | rest-client.ts:113-114 |
| **RestClient.post()** | res.ok check | ❌ NO — only calls `res.text()` | MEDIUM | rest-client.ts:126-127 |
| **useSendMessage.onError** | Catches error | ❌ NO — logs only, no UI feedback | MEDIUM | use-send-message.ts:43-45 |
| **useCancelThread.onError** | Catches + rolls back | ⚠️ PARTIAL — no error detail extraction | MEDIUM | use-cancel-thread.ts:26-32 |
| **useCreateThread.onError** | Catches error | ❌ NO — logs only, no UI feedback | MEDIUM | use-threads.ts:74-76 |
| **useRespondToPermission.onError** | Catches error | ❌ NO — logs only, no UI feedback | MEDIUM | use-permissions.ts:21-23 |

### 13.3 RestClientError Class Initialization

**Defined** (rest-client.ts:23-32):

```typescript
class RestClientError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body?: unknown,
  ) { ... }
}
```text

**Instantiated** (rest-client.ts:114, 127):

```typescript
throw new RestClientError(res.status, res.statusText, body);  // body = res.text()
```yaml

**Problem**: `body` is the raw text (usually JSON string), not parsed object. No attempt to extract `detail` field.

### 13.4 Validation Schema Misalignment

**Backend nickname validation** (schemas/rest.py:53-59):

```python
@field_validator("nickname")
def _validate_nickname_slug(cls, v: str | None) -> str | None:
  if v is not None and not re.match(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$", v):
    raise ValueError("nickname must be a lowercase slug (3-64 chars, [a-z0-9-], no leading/trailing hyphens)")
  return v
```yaml

**Frontend validation**: ❌ NONE. Component accepts any string for nickname.

- Evidence: use-threads.ts:46 passes `nickname: ''` directly to metadata without validation
- Error Case: User enters uppercase or special chars → 422 response → no UI feedback

**Impact**: Validation errors from backend never reach user UI; requests silently fail.

### 13.5 HTTP Status Semantics

| Status | Backend Meaning | Frontend Handling | Issue |
|--------|-----------------|-------------------|-------|
| **202 Accepted** | Message queued, worker will process | N/A (treated as success) | ✓ Correct |
| **404** | Thread/metadata not found | Log only | ❌ Should show toast |
| **409** | Conflict (archived thread, duplicate nickname, invalid transition) | Log only | ❌ Should show dialog |
| **422** | Validation error (workspace_root, nickname) | Log only | ❌ Should highlight field |

**Finding SA-1301 (MEDIUM)**: No UI component displays HTTP error details. All errors logged to console; users see silent failures.

### 13.6 Error Recovery Semantics

**useCancelThread** (use-cancel-thread.ts:12-32):

```typescript
onMutate: async (threadId) => {
  // Optimistic: set agent_state to 'cancelled' immediately
  queryClient.setQueryData(..., prev =>
    prev.map(t => t.thread_id === threadId
      ? { ...t, agent_state: 'cancelled' as const }
      : t)
  );
  return { previous };  // save for rollback
},

onError: (err, threadId, context) => {
  if (context?.previous) {
    queryClient.setQueryData(..., context.previous);  // restore
  }
  log.error(...);
}
```yaml

**Semantics**: ✓ Optimistic update + rollback on failure (correct pattern)

**useSendMessage** (use-send-message.ts:21-45):

```typescript
onMutate: ({ threadId, content }) => {
  // Optimistic: push user message to stream
  appStore.setState((state) => {
    if (!state.streamEvents[threadId]) {
      state.streamEvents[threadId] = [];
    }
    state.streamEvents[threadId].push(event);
  });
},

onError: (err, { threadId }) => {
  // No rollback! Orphaned message left in stream
  log.error(...);
}
```yaml

**Finding SA-1302 (HIGH)**: Optimistic message append has no rollback. If REST fails, user sees ghost message in stream forever.

### 13.7 Pydantic Validation Error Detail Serialization

**Backend Behavior** (Pydantic default):

- When `@field_validator` raises `ValueError`, FastAPI catches and returns HTTP 422 with:

  ```json
  {
    "detail": [
      {
        "loc": ["body", "nickname"],
        "msg": "nickname must be a lowercase slug ...",
        "type": "value_error"
      }
    ]
  }
  ```yaml

**Frontend Capture**: RestClient receives this but never parses it.

- Evidence: rest-client.ts:127 stores `errBody` as raw text, never accessed by callers
- `useSendMessage.onError(err)` receives Error object with `.body` field, but `.body` is string, not parsed

**Finding SA-1303 (MEDIUM)**: Validation error details (msg, loc) are serialized by backend but lost in transit to frontend.

### 13.8 Thread State Transition Error Cases

**Backend** (endpoints.py:1035-1036):

```python
raise HTTPException(
  status_code=409,
  detail=f"Cannot archive thread in {thread.status!r} state",
)
```yaml

**Frontend** (use-threads.ts): No mutation defined for archive operation.

**Finding SA-1304 (LOW)**: Archive endpoint exists but frontend has no mutation hook to call it.

### 13.9 Missing Error Handler for Binary Operations

| Operation | Mutation | Error Handler | Recovery | Status |
|-----------|----------|----------------|----------|--------|
| Create thread | useCreateThread | onError logs | None | ❌ No rollback |
| Cancel thread | useCancelThread | onError + rollback | TQ restore | ✓ OK |
| Send message | useSendMessage | onError logs | None | ❌ No rollback |
| Respond permission | useRespondToPermission | onError logs | None | ❌ No rollback (optimistic removes) |

**Finding SA-1305 (HIGH)**: 3 of 4 mutations lack error recovery. usePermissions removes from Zustand optimistically but has no way to restore on failure.

### 13.10 Wire Type Error Response Schemas

**Auto-generated from OpenAPI** (wire-types.ts):

- No explicit `HttpErrorResponse` or `ValidationErrorResponse` type defined
- Callers cannot distinguish 404 from 422 at TypeScript level without string matching

**Finding SA-1306 (LOW)**: No discriminated union type for error responses. Frontend relies on `.status` field to branch.

### 13.11 Network Timeout & Abort Handling

**RestClient** (rest-client.ts:110-116):

```typescript
private async get<T>(path: string): Promise<T> {
  const res = await fetch(`${this.baseUrl}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => undefined);
    throw new RestClientError(res.status, res.statusText, body);
  }
  return res.json() as Promise<T>;
}
```text

**Issues**:

- No timeout specified (uses browser default, ~300s on Firefox)
- No AbortController support for manual cancellation
- Network error (no response) falls through uncaught; not wrapped in RestClientError

**Finding SA-1307 (MEDIUM)**: Unhandled network errors and unbounded timeouts can leave requests hanging.

### 13.12 Logger Error Detail Handling

**Logger** (utils/logger.ts:117-120):

```typescript
case 'error':
  console.error(tag, message, data ?? '');
  break;
```text

**Usage** (use-send-message.ts:44):

```typescript
log.error('api.send', `Failed to send message to ${threadId}`, err);
```yaml

**Problem**: `err` (RestClientError) has `.body` field with JSON string, never parsed. Console shows:

```text
[api.send] Failed to send message to thread-abc
RestClientError: REST 422 Unprocessable Entity
```text

No detail about which field failed validation.

**Finding SA-1308 (MEDIUM)**: Error logging captures RestClientError but doesn't extract/parse `.body.detail`.

---

## FINDINGS SUMMARY: Error Handling (Pass 13)

| ID | Severity | Finding | Evidence | Fix Priority |
|----|-----------|---------|-----------|----|
| SA-1301 | MEDIUM | No UI feedback for HTTP errors (404/409/422) | All mutations log only | HIGH |
| SA-1302 | HIGH | useSendMessage optimistic append lacks rollback | use-send-message.ts:21-36 | CRIT |
| SA-1303 | MEDIUM | Validation error details lost in RestClientError.body | rest-client.ts:127 + use-send-message.ts:44 | HIGH |
| SA-1304 | LOW | Archive operation has no frontend mutation | endpoints.py:1030 vs use-threads.ts | LOW |
| SA-1305 | HIGH | 3/4 mutations lack error recovery (no rollback) | use-threads.ts, use-send-message.ts, use-permissions.ts | CRIT |
| SA-1306 | LOW | No discriminated error response type in wire-types | wire-types.ts auto-gen limitation | LOW |
| SA-1307 | MEDIUM | Network timeouts unbounded; no AbortController | rest-client.ts:110-116 | MED |
| SA-1308 | MEDIUM | RestClientError.body never parsed for detail | utils/logger.ts:120 + rest-client.ts | HIGH |

**Root Cause**: Mutations focus on happy path; error branches are either missing or silent (log only). RestClientError has `.body` field but it's the raw text response, not parsed JSON. Callers don't extract the `detail` field for display.

**Recommendation**:

1. Parse RestClientError.body as JSON in RestClient constructor
2. Add `detail` field extraction to RestClientError
3. Wire error handlers to UI toast/dialog component
4. Add rollback callbacks to all 4 mutations
5. Implement AbortController + 30s timeout in RestClient

---

## PASS 14: OBSERVABILITY & LOGGING ALIGNMENT

**Objective**: Verify consistent logging/observability between backend and frontend; check for structured logging, debuggability, and telemetry gaps.

### 14.1 Backend Logging Coverage

**Aggregator** (aggregator.py):

- Line 408: DEBUG ingest start
- Line 521: INFO cancellation requested
- Line 1493: EXCEPTION on ingest error
- Line 1711: WARNING step timeout
- No structured logging for event emission (emit_* methods not logged)

**Evidence**:

```python
logger.info("Cancellation requested for thread %s", thread_id)  # Line 521
logger.exception("Ingest failed: %s", error, exc_info=True)  # Line 1725
```text

**Endpoints** (endpoints.py):

- Line 258: INFO thread created
- Line 321: WARNING status filter case mismatch
- Line 690: INFO message accepted
- No structured logging for REST errors (HTTPException raised but not logged)

**Finding SA-1401 (MEDIUM)**: Backend exceptions raised but not logged. Caller sees HTTP 404/409 but no server-side log entry visible in CloudWatch/structlog.

### 14.2 Frontend Logging Coverage

**Logger utility** (utils/logger.ts:1-221):

- ✓ Centralized logging with 4 levels (debug/info/warn/error)
- ✓ Structured source tags (e.g., 'api.send', 'thread.create')
- ✓ Ring buffer (500 entries, in-memory)
- ✓ Subscriber notification system (surface to UI)
- ✓ Auto-dismiss timers (info: 4s, warn: 6s, error: sticky)

**Usage across codebase**:

- use-threads.ts:72: `log.info('thread.create', ...)`
- use-send-message.ts:40: `log.info('thread.send', ...)`
- use-cancel-thread.ts:35: `log.info('thread.cancel', ...)`
- ws-bridge.ts: ❌ NO logging (silent dispatch)

**Finding SA-1402 (MEDIUM)**: WS bridge handles 12 event types with zero logging. No visibility into event dispatch, cache updates, or rate limiting.

### 14.3 Logging Asymmetry

| Layer | Logging | Debuggability | Evidence |
|-------|---------|----------------|----------|
| **Backend aggregator** | INFO/WARNING/EXCEPTION only | ⚠️ MEDIUM (no event emission logs) | aggregator.py:521, 1493 |
| **Backend endpoints** | INFO/WARNING only | ⚠️ MEDIUM (no error logs) | endpoints.py:258, 690 |
| **Frontend REST client** | ❌ NONE | ❌ POOR (no fetch logging) | rest-client.ts:110-130 |
| **Frontend mutations** | onError only | ⚠️ MEDIUM (errors logged, success silent) | use-threads.ts:74 |
| **Frontend WS bridge** | ❌ NONE | ❌ POOR (12 event handlers unlogged) | ws-bridge.ts:1-100 |

**Finding SA-1403 (HIGH)**: Zero logging in critical paths (WS dispatch, REST fetch). Missing observability for debugging WS event loss, network failures, or cache inconsistencies.

### 14.4 Logging Levels & Semantics

**Backend** (Python logging):

```python
logger.debug(...)    # Lowest — hidden in production
logger.info(...)     # Operations (thread created, message accepted)
logger.warning(...) # Degraded (timeout, parse error, missing config)
logger.exception(...) # Errors + traceback
```text

**Frontend** (custom logger.ts):

```typescript
log.debug(...)  // Lowest — console only
log.info(...)   // Operations + optional UI pill
log.warn(...)   // Warnings + UI pill (medium auto-dismiss)
log.error(...) // Errors + sticky UI pill
```yaml

**Semantics**: ✓ Aligned (debug < info < warn < error)

### 14.5 Missing Observability Points

| Point | Backend | Frontend | Gap | Severity |
|-------|---------|----------|-----|----------|
| REST POST /threads | ✓ Logged (line 258) | ✓ Logged (line 72) | None | OK |
| REST GET /threads/{id}/state | ❌ Not logged | ❌ Not logged | No visibility | MED |
| REST POST /permissions/{id}/respond | ❌ Not logged | ✓ Logged as permission.respond | ASYMMETRIC | MED |
| WS connect | ✓ Logged (ConnectionManager) | ❌ Not logged | One-way | MED |
| WS event (12 types) | ✓ Emitted (aggregator) | ❌ Not logged | Silent dispatch | HIGH |
| Tool call execution | ✓ Logged at aggregator | ❌ Not logged in frontend stream | ASYMMETRIC | HIGH |
| Permission response | ✓ Logged (endpoints.py) | ✓ Logged in mutation | OK | OK |

**Finding SA-1404 (HIGH)**: WS event dispatch has zero observability. When client receives `tool_call_start`, no log entry records it. Debugging event loss requires reading DevTools Network tab manually.

### 14.6 Structured Logging Gaps

**Backend** (Python):

```python
logger.info("Thread %s created with preset %s", thread_id, preset_id)  # positional args
```text

**Frontend** (TypeScript):

```typescript
log.info('thread.create', `Thread ${res.thread_id} created`);  // string interpolation
```yaml

**Problem**: No structured key-value pairs (JSON fields). Can't filter/aggregate logs by thread_id.

**Finding SA-1405 (MEDIUM)**: Backend uses positional args; frontend uses string templates. Neither supports JSON object logging for log aggregation tools (ELK, Datadog, etc.).

### 14.7 Ring Buffer & History Access

**Frontend Logger** (utils/logger.ts:198-200):

```typescript
history(): readonly LogEntry[] {
  return _history;  // Last 500 entries, in-memory only
}
```yaml

**Availability**: ✓ Accessible via `window.__vaultspec_log.history()` in browser console

**Limitations**:

- ❌ Entries lost on page reload
- ❌ No export/download function
- ❌ No filtering beyond log level
- ❌ No persistence to localStorage/IndexedDB

**Finding SA-1406 (LOW)**: Ring buffer useful for debugging current session but data lost on reload. No integration with backend logging for correlation.

### 14.8 Error Stack Traces

**Backend** (aggregator.py:1493):

```python
logger.exception("Ingest failed: %s", error, exc_info=True)  # Includes traceback
```text

**Frontend** (use-send-message.ts:44):

```typescript
log.error('api.send', `Failed to send message to ${threadId}`, err);  // err = RestClientError
```yaml

**Problem**: `err` is RestClientError object with no stack trace. Frontend logger logs string representation only (see line 119).

**Finding SA-1407 (MEDIUM)**: Frontend error logging doesn't preserve stack traces from fetch/network errors.

### 14.9 Performance Metrics Logging

**Backend**: ❌ No latency logging for ingest, aggregation, or API endpoints
**Frontend**: ❌ No latency logging for REST calls or WS event processing

**Missing**:

- REST response time (useful for API perf tracking)
- WS event delivery latency (server emit → client receive)
- Aggregator ingest time (useful for identifying slow graphs)

**Finding SA-1408 (MEDIUM)**: No performance metrics logged. Can't diagnose slow API calls or WS lag without DevTools Network tab.

### 14.10 Correlation IDs

**Backend**: ❌ No correlation IDs in logs
**Frontend**: ❌ No correlation IDs in logs

**Impact**: When debugging a failed thread creation:

1. Backend logs: "Thread XYZ created"
2. Frontend logs: "Thread created: XYZ"
3. No way to tie together logs from different processes

**Finding SA-1409 (MEDIUM)**: No request ID or correlation ID propagation between frontend and backend logs.

### 14.11 Redaction & Secrets

**Backend logging** (aggregator.py):

```python
logger.info("Ingest: %s", graph_state)  # Logs full state dict — may contain secrets!
```text

**Frontend logging** (all mutations):

```typescript
log.error('api.send', '...', err);  // err.body may contain validation error detail with user input
```yaml

**Finding SA-1410 (HIGH)**: No redaction of sensitive data in logs. Graph state may contain credentials; validation errors may expose user input. Ring buffer visible via `window.__vaultspec_log`.

---

## FINDINGS SUMMARY: Observability (Pass 14)

| ID | Severity | Finding | Evidence | Fix Priority |
|----|-----------|---------|-----------|----|
| SA-1401 | MEDIUM | Backend exceptions raised but not logged | endpoints.py HTTPException handlers | HIGH |
| SA-1402 | MEDIUM | WS bridge has zero logging | ws-bridge.ts:1-100 silent | HIGH |
| SA-1403 | HIGH | Missing observability in critical paths | REST client + WS dispatch | CRIT |
| SA-1404 | HIGH | WS event dispatch unlogged | No log.info/warn in handleWireEvent | CRIT |
| SA-1405 | MEDIUM | Structured logging missing (no JSON fields) | String templates + positional args | HIGH |
| SA-1406 | LOW | Ring buffer not persistent | 500-entry in-memory only | LOW |
| SA-1407 | MEDIUM | Error stack traces lost in frontend | RestClientError logged as string | MED |
| SA-1408 | MEDIUM | No performance metrics | No latency logging anywhere | MED |
| SA-1409 | MEDIUM | No correlation IDs | Frontend/backend logs not tied together | MED |
| SA-1410 | HIGH | No secret redaction | Graph state + validation errors logged raw | CRIT |

**Root Cause**: Logging implemented for happy path (success cases) but missing for failure/debug paths. WS bridge is a critical data path with zero observability. No correlation mechanism between frontend and backend logs.

**Recommendation**:

1. Add log.debug/info calls to ws-bridge.ts event handlers (12 events)
2. Add logging to RestClient.get/post methods (performance + errors)
3. Log HTTPException handlers in endpoints.py
4. Extract `.detail` from FastAPI validation errors and log
5. Implement correlation ID propagation (X-Request-ID header)
6. Add message redaction filter for graph state logging
7. Consider localStorage persistence for ring buffer with rotation

---

## PASS 15: TYPE SAFETY & SERIALIZATION BOUNDARIES

**Objective**: Verify discriminated unions, type assertions, serialization correctness, and enum exhaustiveness across the wire.

### 15.1 Discriminated Union Safety

**Backend Events** (events.py):

```python
type: Literal[ServerEventType.AGENT_STATUS] = ServerEventType.AGENT_STATUS
type: Literal[ServerEventType.MESSAGE_CHUNK] = ServerEventType.MESSAGE_CHUNK
# ... 12 total event types with Literal discriminators
```text

**Frontend Handler** (ws-bridge.ts):

```typescript
const handleWireEvent = (data: unknown) => {
  const event = data as WireServerEvent;  // Type assertion without guard
  switch (event.type) {
    case 'agent_status':
      updateAgentDisplayNames(event as AgentStatusEvent);
      break;
    case 'message_chunk':
      // ...
  }
};
```yaml

**Problem**: `data as WireServerEvent` is unchecked. No runtime validation. Malformed JSON from server could slip through.

**Example**:

```json
{ "type": "unknown_event_type", "content": "..." }
```text

Would pass type assertion, then fall through to default case (missing).

**Finding SA-1501 (HIGH)**: No discriminated union validation at deserialization boundary. Relies on TypeScript compile-time type narrowing only.

### 15.2 Type Assertion Patterns

**Mappers** (mappers.ts):

- Line 62: `topology: wire.topology as TeamPreset['topology']` — unchecked cast
- Line 99: `return wire as ToolCallStatus` — unchecked cast
- Line 103: `wire as ToolKind` — guarded only by Set membership check

**Problem**: Lines 62 and 99 assume wire shape is correct. No validation.

**Finding SA-1502 (MEDIUM)**: Type assertions used instead of runtime validation. If wire-types.ts out of sync, assertions hide the mismatch.

### 15.3 Enum Validation on Ingestion

**Backend** (schemas/enums.py):

```python
class ToolKind(str, Enum):
  READ = "read"
  EDIT = "edit"
  # ... 8 more
```yaml

Pydantic validates at deserialization: if unknown value received, raises ValidationError.

**Frontend** (mappers.ts:102-104):

```typescript
export function mapToolKind(wire: WireToolKind): ToolKind {
  return FRONTEND_TOOL_KINDS.has(wire) ? (wire as ToolKind) : 'other';
}
```yaml

**Semantics**: ✓ Guarded with Set check; unknown values default to 'other'

**But Problem**: `FRONTEND_TOOL_KINDS` is a hardcoded Set. If backend adds new ToolKind, frontend silently defaults to 'other' instead of erroring.

**Finding SA-1503 (MEDIUM)**: Enum validation uses hardcoded Set instead of mapping from wire-types. Out-of-sync leads to silent fallback.

### 15.4 Timestamp Serialization

**Backend** (schemas/snapshots.py):

```python
created_at: datetime  # Pydantic auto-serializes to ISO-8601 string
updated_at: datetime
```text

**Frontend** (types.ts):

```typescript
created_at?: string;  // ISO-8601 string
updated_at?: string;
```text

**Deserialization** (use-thread-state.ts):

```typescript
const snapshot = await restClient.getThreadState(threadId);
// snapshot.created_at is string, never parsed to Date object
```yaml

**Problem**: Timestamp stays as string forever. Comparisons like `new Date(snapshot.created_at) < Date.now()` work but require manual parsing every time.

**Finding SA-1504 (MEDIUM)**: Timestamps not auto-parsed to Date objects on ingestion. Callers must remember to wrap in `new Date()`.

### 15.5 Array Serialization & Nullability

**Backend** (schemas/events.py):

```python
options: list[_PermissionOptionSnapshot]  # Never null, always array
message_history: list[MessageSnapshot] = []  # Default empty array
tool_calls: list[ToolCallSnapshot] = []  # Default empty array
```text

**Frontend** (wire-types.ts):

```typescript
options: PermissionOptionSnapshot[];  // Not optional
message_history?: MessageSnapshot[];  // Optional
tool_calls?: ToolCallSnapshot[];  // Optional (should match backend)
```yaml

**Problem**: `tool_calls` is optional in wire-types but always present in backend (default `[]`). Inconsistency.

**Finding SA-1505 (MEDIUM)**: Optional array fields don't match backend defaults. Frontend code must guard with `?.map()` even though backend guarantees value.

### 15.6 Nested Object Serialization

**ThreadMetadata** (core/metadata.py):

```python
class ThreadMetadata(BaseModel):
  workspace_root: str
  feature_tag: str
  source_branch: str
  nickname: str
  source_repo: str
  callee: str
```text

**Wire Format** (wire-types.ts):

```typescript
metadata?: ThreadMetadata;  // Optional
```text

**Frontend Ingestion** (use-threads.ts:41-50):

```typescript
metadata: repo ? {
  workspace_root: repo,
  feature_tag: featureTag ?? '',
  source_branch: branch ?? '',
  nickname: '',
  source_repo: '',
  callee: '',
} : undefined
```yaml

**Problem**: Frontend manually constructs metadata object. If backend adds/removes field, frontend breaks silently.

**Finding SA-1506 (MEDIUM)**: Nested object construction manual, not code-generated. Schema drift causes runtime errors.

### 15.7 Pydantic Validation vs TypeScript Narrowing

**Backend** (schemas/rest.py:37-59):

```python
class CreateThreadRequest(BaseModel):
  initial_message: str = Field(max_length=65536)
  team_preset: str | None = Field(default=None, max_length=64)
  nickname: str | None = Field(default=None, max_length=64)

  @field_validator("nickname")
  def _validate_nickname_slug(cls, v):
    if v is not None and not re.match(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$", v):
      raise ValueError("nickname must be lowercase slug")
```text

**Frontend** (use-threads.ts):

```typescript
// No validation — passes anything to createThread()
const newThread = { nickname: 'ANY_CASING_OK', ... };
```yaml

**Problem**: Backend validation not mirrored on frontend. User input validation only happens on server (slow feedback loop).

**Finding SA-1507 (MEDIUM)**: Client-side input validation missing. Form validation (length, regex, required) not enforced before REST call.

### 15.8 Union Type Exhaustiveness

**Backend Events** (events.py:10-250):
12 event types defined with Literal discriminators:

- AGENT_STATUS, MESSAGE_CHUNK, THOUGHT_CHUNK, TOOL_CALL_START, TOOL_CALL_UPDATE
- PERMISSION_REQUEST, ARTIFACT_UPDATE, PLAN_UPDATE, TEAM_STATUS
- ERROR, CONNECTED, HEARTBEAT

**Frontend Switch** (ws-bridge.ts:15-100):

```typescript
switch (event.type) {
  case 'agent_status': ...
  case 'message_chunk': ...
  // ... all 12 cases present
  // no default case — dead code error if new event added
}
```yaml

**Semantics**: ✓ All 12 cases covered; no default

**But Problem**: TypeScript doesn't force exhaustiveness check. If backend adds new event type and wire-types.ts regenerates, frontend switch won't warn about missing case.

**Finding SA-1508 (MEDIUM)**: Union exhaustiveness not enforced by TypeScript. Missing event handler is a silent bug.

### 15.9 JSON Serialization Edge Cases

**Backend** (Pydantic auto-serialization):

- Enum fields serialized as string value (not name)
- datetime fields serialized to ISO-8601 string
- None values included in JSON (not omitted)

**Frontend** (JSON.stringify for REST):

```typescript
JSON.stringify({
  team_preset: preset?.id,
  metadata: repo ? { ... } : undefined,
})
```yaml

**Problem**: `undefined` values serialized as omitted fields (correct). But if backend receives `{ "metadata": null }` vs `{}`, behavior may differ.

**Finding SA-1509 (LOW)**: JSON serialization semantics differ for null vs undefined. Pydantic treats both as "value not provided" but JSON differs.

### 15.10 Type-Safe Message Construction

**Backend** (aggregator.py):

```python
event = ToolCallStartEvent(
  type=ServerEventType.TOOL_CALL_START,
  thread_id=thread_id,
  ...
)
```text

**Pydantic validates** all fields match schema at construction time.

**Frontend** (mappers.ts):

```typescript
export function mapPermissionRequest(wire: PermissionRequestEvent): PermissionRequest {
  return {
    id: wire.request_id,
    agent_id: wire.agent_id ?? '',  // Default if missing
    // ... 6 fields
  };
}
```yaml

**Problem**: Mapper doesn't validate that all fields are present. If wire is missing a field, mapper silently defaults to empty string.

**Finding SA-1510 (MEDIUM)**: Frontend mappers use null-coalescing without validation. Missing fields silently default; no error raised.

---

## FINDINGS SUMMARY: Type Safety (Pass 15)

| ID | Severity | Finding | Evidence | Fix Priority |
|----|-----------|---------|-----------|----|
| SA-1501 | HIGH | No discriminated union validation at wire boundary | ws-bridge.ts:15 no guard | CRIT |
| SA-1502 | MEDIUM | Type assertions without guards | mappers.ts:62, 99 | HIGH |
| SA-1503 | MEDIUM | Enum validation via hardcoded Set | mappers.ts:85-96 | HIGH |
| SA-1504 | MEDIUM | Timestamps not auto-parsed to Date | use-thread-state.ts uses string | MED |
| SA-1505 | MEDIUM | Optional array fields don't match backend defaults | wire-types.ts: `tool_calls?` vs schema: `tool_calls: []` | MED |
| SA-1506 | MEDIUM | Nested object construction manual | use-threads.ts:41-50 | MED |
| SA-1507 | MEDIUM | No client-side input validation | createThread() accepts any nickname | HIGH |
| SA-1508 | MEDIUM | Union exhaustiveness not enforced | ws-bridge.ts switch has no default | MED |
| SA-1509 | LOW | JSON serialization semantics differ (null vs undefined) | fetch JSON.stringify behavior | LOW |
| SA-1510 | MEDIUM | Mappers silently default missing fields | mappers.ts:72 `?? ''` | HIGH |

**Root Cause**: Type safety relies on TypeScript compile-time checking + Pydantic backend validation. No runtime guards at deserialization boundaries. Enum validation hardcoded. Mappers use defaults instead of validation.

**Recommendation**:

1. Add runtime discriminated union validation (e.g., `zod` schema)
2. Replace hardcoded enum Sets with runtime check from wire-types
3. Add nullable/required field validation in mappers
4. Implement client-side form validation for CreateThreadRequest
5. Auto-parse timestamp strings to Date objects on ingestion
6. Use TypeScript `as const` + assertion functions for type-safe casts
7. Add exhaustiveness check helper for event union

---

## PASS 16: CONCURRENCY & RACE CONDITIONS AT WIRE BOUNDARY

**Objective**: Analyze concurrent WS events, TanStack Query cache mutations, and Zustand state updates for race conditions and ordering guarantees.

### 16.1 Event Processing Concurrency Model

**WS Bridge** (ws-bridge.ts:42-107):

```typescript
wsClient.setEventCallback((threadId, event) => {
  switch (event.type) {
    case 'agent_status': {
      appStore.getState().handleWireEvent(threadId, event);  // (1) Zustand update
      queryClient.setQueryData(...team.status(), ...);       // (2) TQ update
      queryClient.setQueryData(...threads.list(), ...);      // (3) TQ update
      break;
    }
    // ... 11 more event types
  }
});
```text

**Concurrency Model**:

- WS events arrive sequentially (WebSocket is FIFO)
- Each `setEventCallback` call is synchronous
- Zustand store update (1) completes before TQ cache update (2)
- **No locks** between (1), (2), (3)

**Ordering Guarantee**: ✓ WS FIFO guarantees sequential event delivery

**Problem**: Even though WS events are FIFO, React renders and REST queries may interleave.

### 16.2 TanStack Query Cache Update Race Conditions

**agent_status Event Handler** (ws-bridge.ts:56-80):

```typescript
case 'agent_status': {
  // Update TQ cache: team.status() agents array
  queryClient.setQueryData<AgentSummary[]>(
    queryKeys.team.status(),
    (prev = []) => {
      const idx = prev.findIndex((a) => a.agent_id === event.agent_id);
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = { ...updated[idx], state: event.state };  // Shallow copy
        return updated;
      }
      return prev;  // if not found, no-op
    },
  );
}
```yaml

**Race Condition 1: Parallel useTeamStatusQuery**

Timeline:

```text
t=0  WS agent_status arrives for agent-123 (state=working)
t=1  handler calls setQueryData (updater fn begins)
t=2  Meanwhile: useTeamStatusQuery refetch completes from server
t=3  WS handler updater sees stale agents array, updates agent-123
t=4  Refetch result overwrites WS update — agent-123 back to old state
```yaml

**Impact**: WS state update lost. Agent shows old state in UI.

**Evidence**: No coordination between WS setQueryData and REST query refetch. TanStack Query doesn't guarantee setter > getter ordering.

**Finding SA-1601 (HIGH)**: WS agent_status update can be overwritten by concurrent REST refetch.

### 16.3 Thread List Cache Update Race Condition

**agent_status Handler** (ws-bridge.ts:71-78):

```typescript
queryClient.setQueryData<ThreadSummary[]>(
  queryKeys.threads.list(),
  (prev = []) =>
    prev.map((t) =>
      t.thread_id === threadId ? { ...t, agent_state: event.state } : t,
    ),
);
```yaml

**Race Condition 2: Concurrent thread list invalidation**

Timeline:

```text
t=0  WS agent_status arrives for thread-abc
t=1  handler calls setQueryData on threads.list cache
t=2  Meanwhile: component calls useCancelThread() mutation
t=3  useCancelThread.onSettled() calls invalidateQueries(threads.list)
t=4  Invalidate clears cache, starts new fetch
t=5  WS setQueryData updater runs (too late, cache cleared)
t=6  REST fetch completes, overwrites WS update
```yaml

**Impact**: WS update lost. Thread state not synced to server state.

**Evidence**: ws-bridge.ts:84-86 setQueryData happens synchronously, but invalidateQueries is async. No ordering guarantee.

**Finding SA-1602 (HIGH)**: WS thread state update can be lost if REST mutation invalidates cache concurrently.

### 16.4 Team Status Full Replacement Race

**team_status Event Handler** (ws-bridge.ts:82-90):

```typescript
case 'team_status': {
  queryClient.setQueryData<AgentSummary[]>(
    queryKeys.team.status(),
    event.agents.map(mapAgentSummary),  // Full replacement
  );
  appStore.getState().updateAgentDisplayNames(event.agents);
}
```yaml

**Race Condition 3: team_status replacement vs individual agent_status**

Timeline:

```text
t=0  WS agent_status for agent-1 (state=working)
t=1  handler updates team.status cache (agent-1 only)
t=2  Meanwhile: server sends team_status event with full agent list (agent-1 is idle)
t=3  team_status handler runs, full replacement, agent-1 reverts to idle
```yaml

**Impact**: Agent state oscillates between WS updates and server snapshot. No consistency.

**Evidence**: Two separate WS event handlers updating same TQ cache with different semantics (incremental vs full).

**Finding SA-1603 (HIGH)**: team_status full replacement can overwrite prior agent_status incremental updates in-flight.

### 16.5 Zustand Store Race Conditions

**handleWireEvent** (stream-slice.ts):

```typescript
const handleWireEvent = (threadId: string, event: ServerEvent) => {
  setState((state) => {
    if (!state.streamEvents[threadId]) {
      state.streamEvents[threadId] = [];
    }
    // Push various event types...
  });
};
```yaml

**State Mutation Pattern**: Zustand with Immer plugin allows direct mutation.

**Race Condition 4: Concurrent event appends**

Timeline:

```text
t=0  WS message_chunk arrives for thread-abc
t=1  handler calls setState, Immer draft created
t=2  Meanwhile: WS tool_call_start arrives (in microtask queue)
t=3  setState from (1) commits, subscribers notified
t=4  setState from (2) starts with stale draft from t=1
t=5  tool_call_start lost (overwritten by message_chunk commit)
```yaml

**Problem**: No lock. WS callback is synchronous but JavaScript microtasks can interleave.

**Mitigation**: Zustand batches all setState calls in same event loop tick, so (4) won't actually lose (2). But order is not guaranteed.

**Evidence**: initWsBridge calls setState synchronously (line 52), but no batch wrapper.

**Finding SA-1604 (MEDIUM)**: WS event ordering not guaranteed in Zustand. Rapid events may batch in wrong order.

### 16.6 Sequence Number Tracking

**Sequence update** (ws-bridge.ts:103-106):

```typescript
if ('sequence' in event && typeof event.sequence === 'number') {
  wsClient.updateLastSequence(threadId, event.sequence);
}
```yaml

**Used For**: Reconnection hydration (request only events after lastSequence).

**Problem**: Sequence updated AFTER all state updates. If reconnect fires after (1) but before (2), client refetch may see partially-applied events.

**Finding SA-1605 (MEDIUM)**: Sequence number tracking lags event processing. Reconnect hydration may re-receive already-applied events.

### 16.7 Optimistic Update Rollback Timing

**useCancelThread** (use-cancel-thread.ts:12-32):

```typescript
onMutate: async (threadId) => {
  await queryClient.cancelQueries({ queryKey: queryKeys.threads.list() });
  const previous = queryClient.getQueryData<ThreadSummary[]>(queryKeys.threads.list());
  queryClient.setQueryData(...);  // Optimistic: set cancelled
  return { previous };
},

onError: (err, threadId, context) => {
  if (context?.previous) {
    queryClient.setQueryData(..., context.previous);  // Rollback
  }
}
```yaml

**Race Condition 5: WS event + pessimistic rollback**

Timeline:

```text
t=0  User clicks cancel; onMutate optimistically sets agent_state=cancelled
t=1  WS agent_status arrives with state=working (thread still running)
t=2  WS handler updates same TQ cache
t=3  REST POST /cancel returns 500 error
t=4  onError rollback restores previous state
t=5  But previous state was captured at t=0, before WS update at t=1
```yaml

**Impact**: Rollback overwrites WS update. WS state lost.

**Evidence**: `previous` captured before mutation fires; if WS event arrives during mutation, rollback misses it.

**Finding SA-1606 (HIGH)**: Optimistic rollback doesn't account for concurrent WS updates. Rollback can erase WS state.

### 16.8 Permission Response Optimistic Remove

**useRespondToPermission** (use-permissions.ts:16-19):

```typescript
onMutate: ({ requestId }) => {
  appStore.getState().removePermission(requestId);  // Optimistic remove
},

onError: (err, { requestId }) => {
  // No rollback! Permission removed from Zustand forever
  log.error(...);
}
```yaml

**Race Condition 6: Permission response + concurrent WS event**

Timeline:

```text
t=0  User clicks "Accept"; onMutate removes from Zustand
t=1  Permission widget disappears from UI
t=2  Meanwhile: server sends permission_request event (stale, already responded)
t=3  WS handler calls pushPermission, adds back to Zustand
t=4  Widget reappears — user confused
```text

**OR if REST fails**:

```text
t=0  User clicks "Accept"; onMutate removes permission
t=1  REST returns 500 error
t=2  onError has no rollback
t=3  Permission lost from UI forever (even though it's still pending on server)
```yaml

**Impact**: Orphaned UI state or lost permission requests.

**Evidence**: use-permissions.ts has no onError rollback; no protection against concurrent WS events.

**Finding SA-1607 (HIGH)**: Permission response optimistic remove has no rollback + no protection against concurrent WS events.

### 16.9 No Deduplication of Concurrent Events

**Example**: Two clients send permission responses concurrently for same requestId.

**Backend**: ✓ Validates and rejects duplicates (idempotent)

**Frontend**: ❌ No deduplication. Two pushPermission calls in Zustand both succeed (but permission already removed by first).

**Finding SA-1608 (MEDIUM)**: Frontend doesn't deduplicate concurrent WS events (though server does).

### 16.10 Microtask Ordering Guarantees

**WS Event Loop** (initWsBridge):

```typescript
wsClient.setEventCallback((threadId, event) => {
  // Synchronous handler — runs in microtask queue
  appStore.getState().handleWireEvent(...);  // Zustand
  queryClient.setQueryData(...);             // TQ cache (async, batched)
});
```text

**JavaScript Event Loop**:

1. Macrotask: WS message received
2. WS handler runs (setEventCallback)
3. Zustand setState (sync)
4. TQ setQueryData (sync but batches internally)
5. Microtasks flush (React renders, TQ refetches)

**Guarantee**: Within single event, setState completes before React render. ✓

**But Problem**: If WS fires two events back-to-back in same message, setState batch may not separate them.

**Finding SA-1609 (LOW)**: WS events not explicitly batched. Rapid events may batch together, losing ordering.

---

## FINDINGS SUMMARY: Concurrency (Pass 16)

| ID | Severity | Scenario | Impact | Root Cause |
|----|-----------|---------|---------|----|
| SA-1601 | HIGH | WS agent_status overwritten by REST refetch | Agent state reverts to old | No coordination between setQueryData + refetch |
| SA-1602 | HIGH | WS thread state lost on concurrent invalidate | Thread state not synced | invalidateQueries clears WS update |
| SA-1603 | HIGH | team_status full replacement overwrites agent_status | Agent state oscillates | Two handlers, same cache, different semantics |
| SA-1604 | MEDIUM | Zustand setState batching loses event order | Events apply in wrong order | No explicit batching around setState |
| SA-1605 | MEDIUM | Sequence tracking lags event processing | Reconnect may re-receive events | updateLastSequence after all state updates |
| SA-1606 | HIGH | Optimistic rollback erases concurrent WS update | WS state lost on REST error | Rollback uses stale `previous` snapshot |
| SA-1607 | HIGH | Permission remove has no rollback + no WS guard | Permission lost forever | onError missing + no deduplication |
| SA-1608 | MEDIUM | Frontend doesn't deduplicate concurrent events | Stale events re-applied | No idempotency key tracking |
| SA-1609 | LOW | WS events not explicitly batched | Ordering may be lost | Events processed in same microtask |

**Root Cause**: Frontend uses multiple state systems (TanStack Query + Zustand) without coordination layer. WS events can race with REST mutations and refetches. No atomic transactions or locks. Optimistic updates lack rollback protection for WS events.

**Recommendation**:

1. Implement request deduplication (idempotency key) for mutations
2. Add WS handler guards: check TQ cache timestamp before overwriting with old data
3. Batch WS events explicitly with React batching or custom batching
4. Use TanStack Query mutation options to skip refetch if WS recently updated
5. Add `onSuccess` callback to mutations to reconcile WS state
6. Implement sequence number atomicity (update before applying state)
7. Add explicit rollback protection: capture `previous` after WS settle
8. Consider single source of truth (Zustand only, not TQ cache) or explicit reconciliation

---

## COMPREHENSIVE FINDINGS SUMMARY (Passes 3-16: 40+ Issues Identified)

### CRITICAL Findings (6 issues — block frontend readiness)

| ID | Area | Finding | Status |
|----|----|---------|--------|
| SA-301 | Snapshot | tool_calls array ALWAYS empty, never populated from graph | OPEN |
| SA-1302 | Error Recovery | useSendMessage optimistic append has no rollback | OPEN |
| SA-1501 | Type Safety | No discriminated union validation at WS boundary | OPEN |
| SA-1601 | Concurrency | WS agent_status can be overwritten by REST refetch | OPEN |
| SA-1602 | Concurrency | WS thread state lost on concurrent cache invalidate | OPEN |
| SA-1607 | Concurrency | Permission response optimistic remove lacks rollback + WS protection | OPEN |

### HIGH Findings (12 issues — significant feature/data loss risks)

| ID | Area | Finding | Status |
|----|----|---------|--------|
| SA-1301 | Error Handling | No UI feedback for HTTP errors (404/409/422) | OPEN |
| SA-1305 | Error Recovery | 3/4 mutations lack error recovery (no rollback) | OPEN |
| SA-1307 | Error Handling | Network timeouts unbounded; no AbortController | OPEN |
| SA-1308 | Error Handling | RestClientError.body never parsed for detail | OPEN |
| SA-1402 | Observability | WS bridge has zero logging (12 event handlers) | OPEN |
| SA-1403 | Observability | Missing observability in REST client + WS dispatch | OPEN |
| SA-1404 | Observability | WS event dispatch unlogged (no visibility) | OPEN |
| SA-1410 | Observability | No secret redaction — graph state logged raw | OPEN |
| SA-1502 | Type Safety | Type assertions without guards (mappers.ts) | OPEN |
| SA-1503 | Type Safety | Enum validation via hardcoded Set (not wire-types) | OPEN |
| SA-1507 | Type Safety | No client-side input validation | OPEN |
| SA-1603 | Concurrency | team_status full replacement overwrites agent_status | OPEN |

### MEDIUM Findings (15+ issues — degraded observability/robustness)

| ID | Area | Finding | Status |
|----|----|---------|--------|
| SA-1303 | Error Handling | Validation error details lost in RestClientError.body | OPEN |
| SA-1405 | Observability | No structured logging (JSON fields) | OPEN |
| SA-1407 | Observability | Error stack traces lost in frontend logging | OPEN |
| SA-1408 | Observability | No performance metrics (latency logging) | OPEN |
| SA-1409 | Observability | No correlation IDs between frontend/backend | OPEN |
| SA-1504 | Type Safety | Timestamps not auto-parsed to Date objects | OPEN |
| SA-1505 | Type Safety | Optional array fields don't match backend defaults | OPEN |
| SA-1506 | Type Safety | Nested object construction manual (not code-gen) | OPEN |
| SA-1510 | Type Safety | Mappers silently default missing fields | OPEN |
| SA-1604 | Concurrency | Zustand setState batching may lose event order | OPEN |
| SA-1605 | Concurrency | Sequence tracking lags event processing | OPEN |
| SA-1606 | Concurrency | Optimistic rollback erases concurrent WS update | OPEN |
| SA-1608 | Concurrency | Frontend doesn't deduplicate concurrent events | OPEN |
| + 15 findings from Passes 3-12 (see sections above) | Multiple | | |

### Issue Distribution by Category

```text
Error Handling     → 8 issues (SA-1301/1302/1303/1304/1305/1307/1308, plus SA-502/503)
Observability      → 10 issues (SA-1401/1402/1403/1404/1405/1406/1407/1408/1409/1410)
Type Safety        → 10 issues (SA-1501/1502/1503/1504/1505/1506/1507/1508/1509/1510)
Concurrency        → 10 issues (SA-1601/1602/1603/1604/1605/1606/1607/1608/1609, + SA-1201/1202/1203 from Pass 12)
Data Loss          → 5 issues (SA-301, SA-1302, SA-404, SA-1602, SA-1607)
Schema Alignment   → 7 issues (Passes 1-2)
Snapshot/Cache     → 6 issues (SA-301/303/401/403/404, SA-1205)
```text

### Top Blockers for Frontend Readiness

**CRIT (Cannot deploy)**:

1. tool_calls array always empty (SA-301) — clients load snapshot expecting tool list, get empty array
2. No optimistic rollback for messages (SA-1302) — users see ghost messages on send error
3. No WS boundary validation (SA-1501) — malformed WS data crashes without guard
4. WS/REST race conditions (SA-1601/1602) — state flips back/forth unpredictably

**HIGH (Must fix before launch)**:
5. No error UI feedback (SA-1301) — users see silent failures
6. No WS logging (SA-1402/1404) — impossible to debug WS issues
7. Type assertions unguarded (SA-1502) — runtime errors if wire-types stale

### Pass-by-Pass Summary

| Pass | Focus | Key Findings | Status |
|------|-------|--------------|--------|
| 3-9 | Event/snapshot/REST alignment | 7 CRIT, 7 HIGH | COMPLETE |
| 10-12 | Event emission, snapshot enrichment, WS bridge | 3 MEDIUM race conditions | COMPLETE |
| **13** | **Error handling & validation** | **8 issues (2 CRIT, 2 HIGH)** | **COMPLETE** |
| **14** | **Observability & logging** | **10 issues (4 HIGH)** | **COMPLETE** |
| **15** | **Type safety & serialization** | **10 issues (1 CRIT, 3 HIGH)** | **COMPLETE** |
| **16** | **Concurrency & races** | **10 issues (4 CRIT, 1 HIGH)** | **COMPLETE** |

---

## PASS 17: STATE RECOVERY & RECONNECTION (GAP DETECTION & HYDRATION)

**Objective**: Audit reconnection protocol, sequence-based gap detection, and state hydration after network disconnects.

### 17.1 Reconnection Protocol

**WebSocket Client** (websocket-client.ts:221-235):

```typescript
private handleClose(): void {
  this.ws = null;
  this.clearTimers();
  if (this.connectionState !== 'disconnected') {
    this.setConnectionState('reconnecting');
    this.scheduleReconnect();  // Exponential backoff
  }
}

private scheduleReconnect(): void {
  const delay = RECONNECT_DELAYS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
  this.reconnectAttempt++;
  this.reconnectTimer = setTimeout(() => this.connect(), delay);
}
```yaml

**Delays**: `[1000, 2000, 4000, 8000, 16000, 30000]` ms (exponential backoff, caps at 30s)

**On Reconnection** (websocket-client.ts:162-195):

```typescript
private handleOpen(): void {
  this.reconnectAttempt = 0;
  this.startPingInterval();
}

// Server sends ConnectedEvent
if (eventType === 'connected') {
  this.clientId = data.client_id as string;
  this.setConnectionState('connected');
  // Re-subscribe to all threads
  if (this.subscribedThreads.size > 0) {
    this.send({
      type: 'subscribe',
      thread_ids: [...this.subscribedThreads],
    } as SubscribeCommand);
  }
}
```yaml

**Semantics**: ✓ Reconnection re-subscribes to threads, maintains clientId

### 17.2 Sequence-Based Gap Detection

**Last Sequence Tracking** (websocket-client.ts:150-152):

```typescript
updateLastSequence(threadId: string, sequence: number): void {
  this.lastSequences.set(threadId, sequence);
}
```yaml

**Called From**: ws-bridge.ts:104-106

```typescript
if ('sequence' in event && typeof event.sequence === 'number') {
  wsClient.updateLastSequence(threadId, event.sequence);
}
```text

**Stale Event Filtering** (websocket-client.ts:210-214):

```typescript
if (threadId && typeof sequence === 'number') {
  const lastSeq = this.lastSequences.get(threadId) ?? 0;
  if (sequence <= lastSeq) return; // Skip stale events
  this.lastSequences.set(threadId, sequence);
}
```yaml

**Semantics**: ✓ Prevents re-applying events after reconnect

**Problem**: Only detects **stale events** (sequence ≤ lastSeq). Doesn't detect **gaps** (sequence > lastSeq + 1).

**Example**:

```text
t=0  Client connected, receives events seq=1, seq=2, seq=3
t=1  Network disconnects
t=2  Server continues emitting seq=4, seq=5 (events lost by client)
t=3  Client reconnects, receives seq=6
t=4  Client has lastSeq=3, but seq=6 arrives
t=5  Client accepts seq=6 (doesn't know seq=4,5 were missed!)
```yaml

**Finding SA-1701 (HIGH)**: Gap detection only filters stale events. Missing events (gap >1) are silently accepted. No recovery mechanism.

### 17.3 Gap Filling via Snapshot

**Snapshot Endpoint** (endpoints.py:602-686):

```python
@router.get("/threads/{thread_id}/state", response_model=ThreadStateSnapshot)
async def get_thread_state_endpoint(...):
  """Return a complete thread state snapshot for client reconnection.

  The ``last_sequence`` field enables gap detection...
  """
  last_seq = aggregator.get_sequence(thread_id)
  snapshot = ThreadStateSnapshot(
    thread_id=thread.id,
    status=thread.status,
    last_sequence=last_seq,  # Tells client the latest sequence
  )
  # Enrich from checkpoint...
```yaml

**Endpoint Returns**: ThreadStateSnapshot with `last_sequence` field

**Frontend Usage**: ❌ NOT USED

- Evidence: No code in frontend queries snapshot on reconnect
- `use-thread-state.ts` loads snapshot but only on manual click (not automatic on gap)

**Finding SA-1702 (HIGH)**: Backend provides `last_sequence` field to enable gap detection, but frontend doesn't use it. No auto-refetch on gap.

### 17.4 Missing Gap Fill Query

**What Frontend Should Do on Reconnect**:

```text
1. Connect to WS
2. Receive event seq=6
3. Check lastSeq=3
4. If seq > lastSeq + 1: gap detected (seq=4,5 missing)
5. Call GET /threads/{id}/state to refill snapshot
6. Discard any WS events <= snapshot.last_sequence
```text

**What Frontend Actually Does**:

```text
1. Connect to WS
2. Receive event seq=6
3. Update lastSeq=6
4. Apply event (data loss!)
```yaml

**Finding SA-1703 (CRIT)**: No gap fill logic. Missing events silently accepted. Clients will have stale state after reconnect.

### 17.5 Heartbeat Timeout

**Timeout Configuration** (websocket-client.ts:37-39):

```typescript
const HEARTBEAT_TIMEOUT = 65_000; // ~2x 30s interval + margin
```text

**Backend Heartbeat** (websocket.py):

```python
async def _heartbeat_loop(self):
  while True:
    await asyncio.sleep(30)
    # Send HeartbeatEvent
```text

**Client Timeout Handler** (websocket-client.ts:244-250):

```typescript
private resetHeartbeatTimer(): void {
  if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
  this.heartbeatTimer = setTimeout(() => {
    // No heartbeat in 65s — assume connection dead
    this.ws?.close();
  }, HEARTBEAT_TIMEOUT);
}
```yaml

**Semantics**: ✓ If no heartbeat in 65s, close WS and trigger reconnect

**Problem**: No logging when heartbeat timeout fires. Silent disconnection.

**Finding SA-1704 (MEDIUM)**: Heartbeat timeout closes WS but doesn't log. No visibility into network issues.

### 17.6 Re-subscription Logic

**On Reconnect** (websocket-client.ts:189-194):

```typescript
if (this.subscribedThreads.size > 0) {
  this.send({
    type: 'subscribe',
    thread_ids: [...this.subscribedThreads],
  } as SubscribeCommand);
}
```yaml

**Problem**: `subscribedThreads` is memory-only Set. If page reloads, subscriptions are lost.

**Example**:

```text
1. User opens app, subscribes to thread-abc
2. Network disconnects
3. Browser tab refreshes (accidental or explicit)
4. App reconnects but subscribedThreads is empty
5. No events received even though user expects to see them
```yaml

**Finding SA-1705 (MEDIUM)**: Subscriptions not persisted. Page reload after disconnect loses subscriptions.

### 17.7 Checkpoint Timeout

**Snapshot Query Timeout** (endpoints.py:637-640):

```python
checkpoint_tuple = await asyncio.wait_for(
  checkpointer.aget_tuple(config),
  timeout=10.0,  # 10 second timeout
)
```text

**On Timeout** (endpoints.py:673-678):

```python
except TimeoutError:
  logger.warning(
    "Timed out loading checkpoint for thread %s after 10s; "
    "returning partial snapshot",
    thread_id,
  )
```yaml

**Problem**: Client receives partial snapshot without knowing. No signal that state is incomplete.

**Example**:

```text
1. Client calls GET /state on reconnect
2. Backend times out loading checkpoint
3. Returns partial snapshot (status only, no messages/artifacts)
4. Client thinks state is current
5. User sees empty stream forever
```yaml

**Finding SA-1706 (MEDIUM)**: Checkpoint timeout returns partial snapshot without warning. Client can't distinguish complete from incomplete state.

### 17.8 Sequence Number Initialization

**On First Connect**: `lastSequences` is empty Map (line 47)

**First Event**: Sequence=1 arrives, lastSeq lookup returns 0 (undefined coalesces to 0)

**Check**: `1 > 0`, so event accepted ✓

**Problem**: If server starts numbering at 0, client would accept it. But if server batch-sends multiple events before client first connect, client would only see the last one.

**Finding SA-1707 (MEDIUM)**: Initial sequence state not specified. Assume 0 is correct, but not documented.

### 17.9 No Event Log Endpoint

**Backend**: No endpoint to query events by sequence range

- Evidence: Endpoints list (lines 208-1077) has no such endpoint
- Only `/threads/{id}/state` returns snapshot, not event log

**Frontend Need**: If gap detected, should query `GET /threads/{id}/events?from_seq=4&to_seq=6` but this doesn't exist

**Workaround**: Call `GET /state` to get full snapshot, effectively starting over

**Finding SA-1708 (MEDIUM)**: No targeted gap fill endpoint. Must refetch entire snapshot on gap (inefficient).

### 17.10 Sequence Number Monotonicity

**Question**: Are sequence numbers guaranteed monotonically increasing?

**Backend**: EventAggregator emits events but no sequence field in emit

- Evidence: aggregator.py emit_* methods don't set sequence
- Sequence set by ConnectionManager.broadcast() before sending

**Frontend**: Assumes monotonic, filters with `sequence <= lastSeq` (line 212)

**Risk**: If backend sends events out of order, client gap detection breaks

**Finding SA-1709 (LOW)**: No documentation of sequence number monotonicity. Assumption not validated.

---

## FINDINGS SUMMARY: Reconnection & State Recovery (Pass 17)

| ID | Severity | Finding | Evidence | Fix Priority |
|----|-----------|---------|-----------|----|
| SA-1701 | HIGH | Gap detection only filters stale, not missing events | websocket-client.ts:210-214 | CRIT |
| SA-1702 | HIGH | Backend provides last_sequence but frontend never uses it | endpoints.py:629 vs use-thread-state.ts | CRIT |
| SA-1703 | **CRIT** | **No gap fill logic — missing events silently accepted** | ws-bridge.ts no refetch on gap | **CRIT** |
| SA-1704 | MEDIUM | Heartbeat timeout closes WS silently, no logging | websocket-client.ts:248 | MED |
| SA-1705 | MEDIUM | Subscriptions not persisted — page reload loses them | websocket-client.ts:46 Set | MED |
| SA-1706 | MEDIUM | Checkpoint timeout returns partial snapshot without warning | endpoints.py:673-678 | MED |
| SA-1707 | MEDIUM | Initial sequence number state not documented | websocket-client.ts:47 | LOW |
| SA-1708 | MEDIUM | No targeted event log endpoint — must refetch full snapshot | endpoints.py endpoint list | MED |
| SA-1709 | LOW | Sequence monotonicity not documented or validated | assumption only | LOW |

**Root Cause**: Reconnection protocol detects stale events but not gaps. No automatic refetch on gap. Clients silently accept out-of-order state.

**Recommendation**:

1. Implement gap detection: `if (seq > lastSeq + 1) refetchSnapshot()`
2. Add backoff to snapshot refetch (exponential, cap at 30s)
3. Persist subscriptions to localStorage
4. Return `is_partial` flag in snapshot to signal incomplete state
5. Add `GET /threads/{id}/events?from=X&to=Y` endpoint for targeted gap fill
6. Document sequence number contract (monotonic, starting at 1)
7. Log heartbeat timeouts to observability system

---

---

## COMPREHENSIVE AUDIT SUMMARY (All Passes 3-18)

**Total Issues Found**: 65+
**Critical Issues**: 12 (security, data loss, crashes, network failures)
**High Issues**: 16 (feature degradation, missing functionality, broken boundaries)
**Medium Issues**: 25+ (robustness, observability, incomplete implementations)
**Low Issues**: 12+ (polish, documentation, minor gaps)

**Distribution by Severity**:

```text
CRIT (12):
  - SA-301 (tool_calls always empty)
  - SA-1302 (message optimistic append no rollback)
  - SA-1501 (no WS boundary validation)
  - SA-1601 (WS agent_status overwritten by REST)
  - SA-1602 (WS thread state lost on invalidate)
  - SA-1607 (permission remove no rollback)
  - SA-1703 (no gap fill on reconnect — data loss)
  - SA-1802 (public REST API has zero auth)
  - SA-1803 (no authorization scopes)
  - SA-1805 (public WS has zero auth)
  - SA-1806 (permission responses not authorized)
  - SA-1807 (no thread ownership enforcement)

HIGH (16):
  - SA-1301/1305 (error handling, no UI feedback, no recovery)
  - SA-1307/1308 (timeouts unbounded, error details lost)
  - SA-1402/1403/1404 (WS bridge + REST client + event dispatch unlogged)
  - SA-1410 (no secret redaction)
  - SA-1502/1503/1507 (type assertions unguarded, enum validation hardcoded, no input validation)
  - SA-1603 (team_status full replacement overwrites agent_status)
  - SA-1701/1702 (gap detection only filters stale, backend provides last_sequence unused)
  - SA-1810 (no CORS validation)

MED (25+):
  - SA-1303 (validation error details lost)
  - SA-1405/1407/1408/1409 (no structured logging, no perf metrics, no correlation IDs)
  - SA-1504/1505/1506/1510 (timestamps not parsed, optional arrays mismatch, manual object construction)
  - SA-1604/1605/1606/1608 (concurrency issues, sequence tracking lags, optimistic rollback erases WS)
  - SA-1704/1705/1706/1708 (heartbeat unlogged, subscriptions not persisted, checkpoint timeout unwarned)
  - SA-1804/1808/1809 (token refresh missing, token leaks in logs, XSS risk)
  + Findings from Passes 3-12

LOW (12+):
  - SA-1304 (archive endpoint has no mutation)
  - SA-1406 (ring buffer not persistent)
  - SA-1508/1509 (union exhaustiveness not enforced, JSON serialization semantics)
  - SA-1609 (WS events not explicitly batched)
  - SA-1707/1709 (sequence initialization not documented, monotonicity not validated)
  + Findings from earlier passes
```text

**TOP 10 BLOCKERS (Must fix before ANY deployment)**:

| Rank | ID | Severity | Issue | Impact |
|------|----|---------|---------|----|
| 1 | **SA-1802** | **CRIT** | **Public REST API has ZERO authentication** | **ANYONE can read/write any thread** |
| 2 | **SA-1805** | **CRIT** | **Public WS has ZERO authentication** | **ANYONE can subscribe to any thread** |
| 3 | **SA-1807** | **CRIT** | **No thread ownership checks** | **Users can access other users' threads** |
| 4 | **SA-1806** | **CRIT** | **Permission responses not authorized** | **Users can bypass permission guards** |
| 5 | **SA-1703** | **CRIT** | **No gap fill on WS reconnect** | **Data loss after network disconnect** |
| 6 | **SA-1601** | **CRIT** | **WS/REST race condition on agent_status** | **State flips back/forth unpredictably** |
| 7 | **SA-1602** | **CRIT** | **WS state lost on cache invalidation** | **Thread status not synced** |
| 8 | **SA-301** | **CRIT** | **tool_calls snapshot always empty** | **Tool history missing forever** |
| 9 | **SA-1501** | **CRIT** | **No WS event boundary validation** | **Can crash on malformed data** |
| 10 | **SA-1302** | **CRIT** | **Message optimistic append no rollback** | **Ghost messages on send error** |

**Security Risk Level**: 🚨 **CRITICAL** — System is NOT SAFE for multi-user or untrusted network deployment. Recommend for local/trusted use ONLY until auth implemented.

**Next Steps**:

1. **IMMEDIATE (Today)**:
   - Add authentication layer (endpoints.py: require Depends(authenticate_request))
   - Add thread ownership checks (all endpoints: filter by user)
   - Add WS auth (websocket.py: validate token before accept)
   - Implement gap fill (ws-bridge.ts: if seq > lastSeq+1, refetch snapshot)
   - Add optimistic message rollback (use-send-message.ts)

2. **URGENT (This Sprint)**:
   - Fix all 12 CRIT issues (security, data integrity, crashes)
   - Fix all 16 HIGH issues (feature completeness, robustness)
   - Add logging to WS bridge + REST client
   - Implement WS/REST race condition guards

3. **BACKLOG (Next Sprint)**:
   - Fix 25+ MEDIUM issues (observability, performance, optional features)
   - Implement token refresh, correlation IDs, structured logging
   - Add input validation, CORS configuration
   - Performance optimization (deduplication, batching)

**Estimated Fix Effort**:

- CRIT: 3-5 days (auth + data integrity)
- HIGH: 2-3 days (feature completeness)
- MED: 3-5 days (observability + robustness)
- LOW: 1-2 days (polish)
- **Total**: 1-2 weeks to production readiness

**Audit Date**: 2026-03-07
**Audit Scope**: Passes 3-18 (comprehensive frontend-backend schema alignment, security, observability, concurrency)
**Document Size**: 2,267 lines
**Total Findings**: 65+
**Auditor**: Frontend-Backend Alignment Continuous Audit Mode

---

## END OF AUDIT

This comprehensive audit identified critical security gaps, data integrity issues, and missing error handling. Highest priority: implement authentication and thread ownership checks immediately. Second priority: fix data loss and concurrency race conditions. Observability and robustness improvements can be deferred to next sprint after security baseline is established.

---

## PASS 18: AUTHORIZATION & PERMISSION BOUNDARY

**Objective**: Verify authentication, authorization, token handling, and scope enforcement at frontend-backend boundary.

### 18.1 Frontend Authentication

**REST Client** (rest-client.ts:110-130):

```typescript
private async get<T>(path: string): Promise<T> {
  const res = await fetch(`${this.baseUrl}${path}`);
  if (!res.ok) {
    const body = await res.text().catch(() => undefined);
    throw new RestClientError(res.status, res.statusText, body);
  }
  return res.json() as Promise<T>;
}
```yaml

**Problem**: No Authorization header sent. No token extraction or refresh.

**Finding SA-1801 (HIGH)**: Frontend doesn't send authorization headers. If backend auth implemented later, client requests will fail silently (401).

### 18.2 Backend Authentication

**Public API** (endpoints.py):

- All routes (POST /threads, GET /threads, etc.) have NO `Depends(authenticate_request)`
- No authentication enforced on any public endpoint

**Evidence**: endpoints.py router routes (lines 208-1077) use only `Depends(get_db)`, not auth

**Internal API** (internal.py:92-105):

```python
async def _verify_internal_token(
  authorization: str | None = Header(None),
) -> None:
  token = settings.internal_token
  if token is None:
    return  # Auth disabled in dev mode
  if authorization != f"Bearer {token}":
    raise HTTPException(status_code=401, detail="Invalid internal token")
```yaml

**Token Source**: `settings.internal_token` (env var or config)

**Semantics**: ✓ Internal endpoints (WS + HTTP POST) require Bearer token if configured

**But Problem**: Public API has NO authentication. Anyone can call `/threads`, `/permissions`, etc.

**Finding SA-1802 (CRIT)**: Public REST API has zero authentication. No user isolation. All users see all threads.

### 18.3 Authorization Scopes

**Question**: What scopes does each endpoint require?

**Backend**: No scope checking in any endpoint

- Evidence: No Depends() on scope validators
- `authenticate_request` is a no-op (line 41)

**Frontend**: No scope enforcement

- Evidence: No token claims parsing, no scope validation before calling API

**Example Scenario**:

```text
1. User A creates thread-abc
2. User B calls GET /threads
3. Backend returns all threads (no filter by user)
4. User B can see thread-abc
```yaml

**Finding SA-1803 (CRIT)**: No authorization scopes. No user isolation at API level.

### 18.4 Token Refresh & Expiration

**Frontend**: No token refresh logic

- Evidence: No token extraction, no exp checking, no refresh endpoint called

**Backend**: No token issuing

- Evidence: No POST /auth/token endpoint, no JWT signing

**Problem**: If future implementation adds JWT tokens, frontend has no way to refresh before expiry

**Finding SA-1804 (MEDIUM)**: No token refresh mechanism. Frontend will fail with 401 on token expiry with no recovery.

### 18.5 WebSocket Authorization

**Public WS** (websocket.py):

```python
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
  # No auth check
  await websocket.accept()
```yaml

**Problem**: Anyone can connect to `/ws` without authentication

**Internal WS** (internal.py:115-126):

```python
@internal_router.websocket("/ws")
async def worker_ws_endpoint(websocket: WebSocket):
  if _settings.internal_token is not None:
    token = websocket.headers.get("authorization", "").removeprefix("Bearer ")
    if token != _settings.internal_token:
      await websocket.close(code=1008, reason="Unauthorized")
      return

  await websocket.accept()
```yaml

**Semantics**: ✓ Internal WS validates token before accept

**But Problem**: Public WS has zero auth. No access control on subscription commands.

**Example**:

```text
1. Client A connects to WS
2. Sends SubscribeCommand for thread-123 (owned by User B)
3. WS accepts (no auth check)
4. Client A receives all events from thread-123
```yaml

**Finding SA-1805 (CRIT)**: Public WS has zero auth. Clients can subscribe to any thread.

### 18.6 Permission Request Isolation

**Permission Response Endpoint** (endpoints.py:965-1000):

```python
@router.post("/permissions/{request_id}/respond", response_model=PermissionResponseResult)
async def respond_to_permission_endpoint(
  request_id: str,
  body: PermissionResponseRequest,
  ...
) -> PermissionResponseResult:
  # No check that requester is the target user
  # Any client can respond to any request
```yaml

**Problem**: No verification that requester has authority to respond

**Example**:

```text
1. Backend sends PermissionRequestEvent to thread-123 (User A)
2. User B calls POST /permissions/req-456/respond
3. Endpoint doesn't verify User B has authority
4. User B can bypass User A's permission guard
```yaml

**Finding SA-1806 (CRIT)**: Permission responses not authorized. Any user can respond to any permission request.

### 18.7 Thread Ownership & Access Control

**GET /threads** (endpoints.py:346-380):

```python
@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(...):
  threads = await list_threads(db)
  return ThreadListResponse(threads=threads, total=len(threads))
```yaml

**Problem**: Returns ALL threads regardless of user

**GET /threads/{id}/state** (endpoints.py:602-686):

```python
async def get_thread_state_endpoint(thread_id: str, ...):
  thread = await get_thread(db, thread_id)
  if thread is None:
    raise HTTPException(status_code=404, detail="Thread not found")
  # No check: does authenticated user own this thread?
  return snapshot
```yaml

**Problem**: No ownership check. Any thread ID can be queried by any user

**Finding SA-1807 (CRIT)**: No thread ownership enforcement. Users can read/write any thread.

### 18.8 Internal Token Exposure

**Settings** (core/config.py):

```python
internal_token: str | None = Field(
  default=None,
  description="Bearer token for internal WS/HTTP endpoints"
)
```yaml

**Problem**: Token stored in settings. If settings logged or exposed in error, token leaks

**Evidence**: No redaction in logging (Pass 14 finding SA-1410)

**Example**:

```text
1. Internal WS handshake fails
2. Backend logs: "Unauthorized: Bearer abc123def456xyz"
3. Token visible in log aggregation system
```yaml

**Finding SA-1808 (MEDIUM)**: Internal token can leak in logs. No redaction of Authorization headers.

### 18.9 Frontend Token Storage

**If tokens are implemented**:

- Where would token be stored? (localStorage, sessionStorage, memory?)
- No xsrf protection (no CSRF token visible)
- No HttpOnly flag possible (fetch() can't set it)

**Problem**: No plan for secure token storage

**Finding SA-1809 (MEDIUM)**: No secure token storage mechanism. Frontend vulnerable to XSS token theft.

### 18.10 CORS & Origin Validation

**Backend** (app.py):

```python
# No CORS configuration visible
# No origin whitelist
```yaml

**Problem**: No CORS headers. Either all origins allowed or blocked completely

**Frontend**: Calls API at `VITE_API_BASE_URL` (could be different origin)

**Risk**: If CORS allows *, any website can call backend API and read/write user data

**Finding SA-1810 (HIGH)**: No CORS origin validation. Either overpermissive or broken cross-origin.

---

## FINDINGS SUMMARY: Authorization & Permission (Pass 18)

| ID | Severity | Finding | Evidence | Fix Priority |
|----|-----------|---------|-----------|----|
| SA-1801 | HIGH | Frontend doesn't send Authorization header | rest-client.ts:111-115 | HIGH |
| SA-1802 | **CRIT** | **Public REST API has zero authentication** | endpoints.py no Depends(auth) | **CRIT** |
| SA-1803 | **CRIT** | **No authorization scopes — no user isolation** | authenticate_request is no-op | **CRIT** |
| SA-1804 | MEDIUM | No token refresh mechanism | No refresh endpoint | MED |
| SA-1805 | **CRIT** | **Public WS has zero auth — clients can subscribe to any thread** | websocket.py no auth check | **CRIT** |
| SA-1806 | **CRIT** | **Permission responses not authorized** | endpoints.py:965-1000 no ownership check | **CRIT** |
| SA-1807 | **CRIT** | **No thread ownership enforcement — users can access any thread** | GET /threads/{id} no auth | **CRIT** |
| SA-1808 | MEDIUM | Internal token can leak in logs | No Authorization header redaction | MED |
| SA-1809 | MEDIUM | No secure token storage plan | Future vulnerability | MED |
| SA-1810 | HIGH | No CORS origin validation | No CORS config visible | HIGH |

**Root Cause**: API designed for local/trusted use only (no authentication). But if exposed to network, zero security. No user isolation, no scope enforcement, no token management.

**Critical Risk**: System is NOT SAFE for multi-user deployment or untrusted network access.

**Recommendation**:

1. **IMMEDIATE**: Add user authentication (e.g., OIDC, API key)
2. **IMMEDIATE**: Add thread ownership checks (only owner can access)
3. **IMMEDIATE**: Add scope validation (permission endpoint requires authority)
4. **IMMEDIATE**: Validate WS subscription (only allow threads user owns)
5. Add CORS origin whitelist
6. Add Authorization header extraction to rest-client.ts
7. Add token refresh + expiry handling
8. Add Authorization header redaction in logging
9. Document security model and threat boundaries
10. Consider mTLS for internal WS if deployed across network



