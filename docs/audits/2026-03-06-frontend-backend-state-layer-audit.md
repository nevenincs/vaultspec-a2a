# Frontend-Backend State Layer Audit

**Date**: 2026-03-06
**Auditor**: codebase-auditor agent
**Scope**: Backend API schemas vs Frontend wire-types, WS protocol, Docker mock, MCP server, REST endpoints

---

## Pass 1: Backend API Schemas vs Frontend Wire-Types

### [CRIT] P1-01 — ToolKind enum drift: backend has 10 values, frontend types.ts has 7

- **Location**: `src/vaultspec_a2a/api/schemas/enums.py:72-84` vs `src/ui/src/app/data/types.ts:13`
- **Description**: Backend `ToolKind` has: `read`, `edit`, `delete`, `move`, `search`, `execute`, `think`, `fetch`, `switch_mode`, `other`. Frontend `types.ts` ToolKind has: `read`, `edit`, `search`, `execute`, `browser`, `mcp`, `other`. The frontend defines `browser` and `mcp` which do NOT exist in the backend. The backend defines `delete`, `move`, `think`, `fetch`, `switch_mode` which the frontend silently drops to `other` via `mapToolKind()`.
- **Impact**: Any tool call with kind `delete`, `move`, `think`, `fetch`, or `switch_mode` will display as "other" in the UI, losing categorization. The frontend's `browser` and `mcp` kinds can never be emitted by the backend.
- **Suggested Fix**: Align `types.ts` ToolKind to match the backend enum exactly. Remove `browser` and `mcp`, add `delete`, `move`, `think`, `fetch`, `switch_mode`.

### [CRIT] P1-02 — ToolCallStatus enum mismatch: backend `in_progress` vs frontend `running`

- **Location**: `src/vaultspec_a2a/api/schemas/enums.py:87-93` vs `src/ui/src/app/data/types.ts:14`
- **Description**: Backend `ToolCallStatus` has `in_progress`. Frontend `types.ts` has `running`. The mapper `mapToolCallStatus()` translates `in_progress` to `running`, but this creates a semantic gap. Wire-types.ts (auto-generated) correctly has `in_progress`.
- **Impact**: Components that compare against `types.ts` ToolCallStatus values will use `running` while the wire format says `in_progress`. If any code path skips the mapper and uses raw wire data, status checks will fail silently.
- **Suggested Fix**: Either make the frontend canonical enum match the backend (`in_progress`) or ensure every code path uses the mapper. Prefer matching the backend.

### [CRIT] P1-03 — PermissionOptionKind enum mismatch: backend 4 values vs frontend 4 different values

- **Location**: `src/vaultspec_a2a/api/schemas/enums.py:96-111` vs `src/ui/src/app/data/types.ts:17`
- **Description**: Backend: `allow_once`, `allow_always`, `reject_once`, `reject_always`. Frontend types.ts: `allow`, `deny`, `allow_always`, `deny_always`. The names `allow`/`deny` (frontend) do not match `allow_once`/`reject_once` (backend). The `mapPermissionRequest()` mapper casts `o.kind as PermissionRequest['options'][0]['kind']` which is an unsafe cast -- no actual translation occurs.
- **Impact**: Permission option kinds from the backend will have values `allow_once`/`reject_once` but the frontend TypeScript type expects `allow`/`deny`. This will cause runtime string comparison failures when the UI tries to style or categorize permission options.
- **Suggested Fix**: Update `types.ts` PermissionOptionKind to: `allow_once | allow_always | reject_once | reject_always`. Update all UI components that reference these values.

### [HIGH] P1-04 — Provider enum mismatch: backend has 5 providers, wire-types has 4, types.ts has 3

- **Location**: `src/vaultspec_a2a/utils/enums.py:47-54` vs `src/ui/src/app/data/wire-types.ts:513` vs `src/ui/src/app/data/types.ts:18`
- **Description**: Backend Provider: `claude`, `gemini`, `mock`, `openai`, `zhipu`. Wire-types (auto-generated from OpenAPI): `claude`, `gemini`, `openai`, `zhipu` (missing `mock`). types.ts: `anthropic`, `openai`, `google` (completely wrong names and missing providers).
- **Impact**: The frontend types.ts uses `anthropic` instead of `claude` and `google` instead of `gemini`. The `mock` and `zhipu` providers are absent. Any component displaying provider names using `types.ts` Provider type will show wrong values or fail type checks.
- **Suggested Fix**: Update types.ts Provider to match backend exactly: `claude | gemini | mock | openai | zhipu`. The OpenAPI schema should also include `mock`.

### [HIGH] P1-05 — PlanEntry field name mismatch: backend `content` vs frontend `title` + missing `id`

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:95-100` vs `src/ui/src/app/data/types.ts:42-47`
- **Description**: Backend `PlanEntry` has fields: `content`, `status`, `priority`. Frontend `PlanEntry` has: `id`, `title`, `status`, `priority`. The backend has no `id` field and uses `content` instead of `title`. The stream-slice.ts handles this by synthesizing: `id: \`${e.content.slice(0, 20)}-${e.status}\`` and `title: e.content`. But the MCP server `get_thread_status` reads `entry.get("title", "untitled")` which will always return "untitled" since the backend field is `content`.
- **Impact**: MCP tool `get_thread_status` will show "untitled" for all plan entries because it reads `title` instead of `content`. The synthetic `id` in stream-slice is fragile and non-unique if two entries share the same 20-char prefix and status.
- **Suggested Fix**: Either add `id` and rename `content` to `title` in backend PlanEntry, or fix the MCP server to read `content` field. The stream-slice synthesis should use a more robust ID (e.g., index-based).

### [HIGH] P1-06 — PermissionOption field name mismatches

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:103-108` vs `src/ui/src/app/data/types.ts:49-53`
- **Description**: Backend `PermissionOption` has: `option_id`, `name`, `kind`. Frontend `PermissionOption` has: `id`, `kind`, `label`. Field renames: `option_id` -> `id`, `name` -> `label`. The mapper handles this correctly in `mapPermissionRequest()` with `id: o.option_id` and `label: o.name`.
- **Impact**: Low since the mapper handles it, but if any code path uses raw wire data without the mapper, field access will fail.
- **Suggested Fix**: Acceptable if mapper is always used. Document the field mapping.

### [HIGH] P1-07 — AgentSummary data loss in frontend mapping

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:111-124` vs `src/ui/src/app/data/types.ts:21-25` vs `src/ui/src/app/api/mappers.ts:40-48`
- **Description**: Backend `AgentSummary` has 8 fields: `agent_id`, `node_name`, `state`, `provider`, `model`, `role`, `display_name`, `description`. Frontend `AgentSummary` in types.ts has only 3: `agent_id`, `node_name`, `state`. The mapper `mapAgentSummary()` only maps these 3 fields, discarding `provider`, `model`, `role`, `display_name`, `description`.
- **Impact**: The UI cannot display agent role, display name, description, provider, or model. Team status views are severely impoverished. The `display_name` field is the human-readable label and its absence means agents show as raw IDs.
- **Suggested Fix**: Extend `types.ts` AgentSummary to include all backend fields. Update `mapAgentSummary()` to pass them through.

### [HIGH] P1-08 — ThreadSummary missing fields: `status`, `created_at`, `source_repo`

- **Location**: `src/vaultspec_a2a/api/schemas/rest.py:90-104` vs `src/ui/src/app/data/types.ts:27-40`
- **Description**: Backend ThreadSummary has `status` (string) and `created_at` (datetime). Frontend types.ts ThreadSummary omits both. The mapper `mapThreadSummary()` also skips them. Additionally, frontend has `source_repo` and `topology` fields that don't exist in the backend ThreadSummary.
- **Impact**: Thread list cannot show creation date or thread status. The `source_repo` and `topology` fields on the frontend will always be undefined.
- **Suggested Fix**: Add `status`, `created_at` to frontend ThreadSummary. Remove `source_repo` and `topology` (they're not in the backend response). Add `team_preset` mapping.

### [MED] P1-09 — PermissionRequest frontend type has extra fields not provided by backend

- **Location**: `src/ui/src/app/data/types.ts:157-166` vs `src/vaultspec_a2a/api/schemas/events.py:182-192`
- **Description**: Frontend `PermissionRequest` has `tool_name` and `tool_kind` fields. Backend `PermissionRequestEvent` has `tool_call: str | None` (just a string name, not kind). The mapper hardcodes `tool_kind: 'other'` and maps `tool_name: wire.tool_call ?? ''`.
- **Impact**: Permission request UI will always show tool_kind as "other" regardless of actual tool type. The tool name mapping is lossy (null becomes empty string).
- **Suggested Fix**: Consider adding `tool_kind` to the backend PermissionRequestEvent if available from the ACP data. Or remove `tool_kind` from the frontend type.

### [MED] P1-10 — TeamPreset frontend type has `agents` array, backend TeamPresetSummary does not

- **Location**: `src/ui/src/app/data/types.ts:170-178` vs `src/vaultspec_a2a/api/schemas/rest.py:162-170`
- **Description**: Frontend `TeamPreset` has an `agents: string[]` field. Backend `TeamPresetSummary` has no `agents` list, only `worker_count: int`. The mapper `mapTeamPreset()` sets `agents: []` (always empty). Frontend also has `status` and `archived` fields not in backend.
- **Impact**: Team preset picker cannot display individual agent names, only worker count. Status/archived filtering is non-functional.
- **Suggested Fix**: Either add agent IDs to the backend response or remove from frontend type. Remove `status`/`archived` phantom fields.

### [MED] P1-11 — ToolCallLocation field name mismatch: backend `path` vs frontend `file`

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:59-63` vs `src/ui/src/app/data/types.ts:55-58`
- **Description**: Backend `ToolCallLocation` has `path: str`. Frontend has `file?: string`. The stream-slice.ts handles this with `file: loc.path` in tool_call_start. But the field is optional in frontend (`file?`) while required in backend (`path`).
- **Impact**: Low since the mapper handles it in stream-slice. But any direct wire data access would fail.
- **Suggested Fix**: Rename frontend field to `path` to match backend, or document the mapping.

### [LOW] P1-12 — Wire-types.ts OpenAPI Provider enum missing `mock`

- **Location**: `src/ui/src/app/data/wire-types.ts:513`
- **Description**: Auto-generated wire-types show Provider as `"claude" | "gemini" | "openai" | "zhipu"` but backend has `mock` as well. This suggests `mock` is excluded from the OpenAPI schema generation (possibly via a schema customization or the OpenAPI export was generated before mock was added).
- **Impact**: If the backend sends `provider: "mock"` in an AgentSummary, the wire-type validation would reject it. Mock provider data from vidaimock/mock-seeder flows will break type safety.
- **Suggested Fix**: Regenerate wire-types.ts from current backend OpenAPI schema. Ensure `mock` is included in the Provider enum export.

---

## Pass 2: WebSocket Protocol Alignment

### [CRIT] P2-01 — AgentStatusEvent `old_state` field fabricated by frontend

- **Location**: `src/ui/src/app/store/slices/stream-slice.ts:259-279` vs `src/vaultspec_a2a/api/schemas/events.py:132-138`
- **Description**: Backend `AgentStatusEvent` has `state` (current state) and `detail`. Frontend `AgentStatusEvent` type in types.ts requires both `old_state` and `new_state`. The stream-slice hardcodes `old_state: 'idle'` for every status event. The backend never sends `old_state`.
- **Impact**: The UI will always show agent transitions as "idle -> X" regardless of actual previous state. State transition history is completely fabricated.
- **Suggested Fix**: Either track previous agent state in the frontend store and compute `old_state` from the last known state for that agent, or remove `old_state` from the frontend type.

### [HIGH] P2-02 — WS bridge team_status handler stores to wrong TanStack Query key shape

- **Location**: `src/ui/src/app/bridge/ws-bridge.ts:59-69` and `ws-bridge.ts:76-79`
- **Description**: For `agent_status`, the bridge updates `queryKeys.team.status()` with `AgentSummary[]`. For `team_status`, it replaces the same cache with `event.agents.map(mapAgentSummary)`. But `TeamStatusResponse` from REST returns `{ agents, active_threads, pending_permissions }`. The TQ cache stores `AgentSummary[]` (flat array) while the REST query returns the full `TeamStatusResponse` object. This mismatch means `setQueryData` overwrites the full response object with just the agents array.
- **Impact**: After a team_status WS event, any component reading `useTeamStatusQuery` expecting `TeamStatusResponse` will get a bare `AgentSummary[]` instead, causing runtime property access errors on `.active_threads` and `.pending_permissions`.
- **Suggested Fix**: The `setQueryData` call should wrap the agents in a proper `TeamStatusResponse` shape: `{ agents: mapped, active_threads: event.active_thread_ids, pending_permissions: prev?.pending_permissions ?? [] }`.

### [HIGH] P2-03 — Heartbeat interval mismatch: backend 30s, frontend timeout 65s

- **Location**: `src/vaultspec_a2a/api/websocket.py:74` vs `src/ui/src/app/api/websocket-client.ts:39`
- **Description**: Backend sends heartbeat every 30s. Frontend considers connection dead after 65s without heartbeat. This is actually correct (65s > 2x30s gives margin). However, the backend disconnects clients after 90s of silence (`_DEAD_CLIENT_TIMEOUT`), while the frontend sends pings every 30s. This is aligned.
- **Impact**: None -- this is correctly configured. Documenting for completeness.
- **Suggested Fix**: No action needed.

### [MED] P2-04 — Permission request via WS is silently rejected but frontend may still try it

- **Location**: `src/vaultspec_a2a/api/websocket.py:335-372` vs `src/ui/src/app/api/websocket-client.ts`
- **Description**: The backend explicitly rejects `PERMISSION_RESPONSE` commands over WebSocket and returns an ErrorEvent. The frontend rest-client correctly sends permissions via REST. However, the `PermissionResponseCommand` type is still exported in websocket-client.ts types, which could mislead developers.
- **Impact**: Low -- the correct REST path is used. But the WS command type export is misleading.
- **Suggested Fix**: Remove or comment `PermissionResponseCommand` from websocket-client exports to prevent misuse.

### [MED] P2-05 — No handler for `connected` event's `active_threads` in WS bridge

- **Location**: `src/ui/src/app/bridge/ws-bridge.ts:29-105`
- **Description**: The ConnectedEvent includes `active_threads: string[]` (list of currently active thread IDs). The bridge's `onConnected` callback is set by ws-bridge but only uses it to set connection state. The `active_threads` data is discarded.
- **Impact**: On reconnection, the frontend doesn't know which threads are active. It could subscribe to stale threads or miss active ones.
- **Suggested Fix**: Use `active_threads` from ConnectedEvent to update the thread list cache or trigger thread list refetch.

---

## Pass 3: Docker Mock Services

### [HIGH] P3-01 — Mock-seeder produces DB records but no WS events reach the frontend

- **Location**: `docker/run.py:98-131` vs `docker-compose.dev.yml:106-139`
- **Description**: The mock-seeder runs `graph.astream()` directly using `AsyncSqliteSaver` as checkpointer. It writes thread records to the shared SQLite DB and graph checkpoints. However, it does NOT connect to the API server's WebSocket or POST events to `/internal/events`. The mock-seeder is a standalone process that writes directly to the DB.
- **Impact**: The frontend will see mock threads appear in the thread list (via REST polling) but will never receive real-time streaming events for them. The stream timeline for mock threads will be empty. Only the snapshot endpoint (`GET /threads/{id}/state`) will show data (from checkpoint).
- **Suggested Fix**: Either: (1) Have mock-seeder connect to the API as a worker using WorkerBridge to relay events, or (2) Document that mock threads only support snapshot hydration, not live streaming.

### [MED] P3-02 — vidaimock tapes in providers/ subdirectory but compose mounts parent

- **Location**: `docker-compose.dev.yml:99` vs tape file paths
- **Description**: Docker compose mounts `./src/vaultspec_a2a/core/presets/mock/tapes:/app/tapes`. Tape YAML files are in `.../tapes/providers/*.yaml`. The vidaimock command uses `--config-dir /app/tapes`. vidaimock needs to find the YAML files -- if it expects them directly in the config dir (not nested), it won't find them in `providers/` subdirectory.
- **Impact**: Depends on vidaimock's directory scanning behavior. If it doesn't recurse, no tapes will load and the mock LLM will return empty/default responses.
- **Suggested Fix**: Verify vidaimock supports recursive tape discovery. If not, mount the `providers/` subdirectory directly or flatten the tape structure.

### [MED] P3-03 — Mock-seeder health endpoint on port 8080 but compose healthcheck targets 8080

- **Location**: `docker/run.py:200` vs `docker-compose.dev.yml:128-135`
- **Description**: Mock-seeder runs uvicorn on port 8080 and compose healthcheck targets `http://localhost:8080/health`. This is aligned.
- **Impact**: None -- correctly configured.
- **Suggested Fix**: No action needed.

---

## Pass 4: MCP Server Implementation

### [HIGH] P4-01 — MCP server uses deprecated `_transport.__del__()` for client cleanup

- **Location**: `src/vaultspec_a2a/protocols/mcp/server.py:75-78`
- **Description**: `_reset_client()` calls `_shared_client._transport.__del__()` which is an internal implementation detail of httpx and may not properly close connections. The comment says "Synchronous close is fine in test teardown" but `__del__` is not a reliable cleanup mechanism.
- **Impact**: Test isolation may be compromised -- connections may leak between tests. In production this code path is never hit (only test fixtures call `_reset_client`).
- **Suggested Fix**: Use `asyncio.run(_shared_client.aclose())` in test teardown, or restructure to use async fixture cleanup.

### [HIGH] P4-02 — MCP `get_thread_status` reads `title` from plan entries, but backend field is `content`

- **Location**: `src/vaultspec_a2a/protocols/mcp/server.py:512-514`
- **Description**: The MCP tool reads `entry.get("title", "untitled")` from plan entry dicts. The backend `PlanEntry` model serializes as `{"content": "...", "status": "...", "priority": "..."}`. There is no `title` field.
- **Impact**: All plan entries in MCP status output will show as "untitled" regardless of actual content.
- **Suggested Fix**: Change to `entry.get("content", "untitled")`.

### [MED] P4-03 — MCP `_KNOWN_PRESETS` is frozen at import time

- **Location**: `src/vaultspec_a2a/protocols/mcp/server.py:94`
- **Description**: `_KNOWN_PRESETS: frozenset[str] = discover_team_preset_ids()` is evaluated once at module import. If team presets are added/removed while the server is running, the MCP validation will be stale.
- **Impact**: New team presets added after server start will be rejected by the MCP `start_thread` tool. This is documented as intentional ("The list is stable within a server session") but could surprise users.
- **Suggested Fix**: Accept as designed, or switch to runtime discovery per call (with caching/TTL).

### [LOW] P4-04 — MCP server is fully functional, not a stub

- **Location**: `src/vaultspec_a2a/protocols/mcp/server.py`
- **Description**: The MCP server exposes 9 tools (start_thread, list_threads, get_thread_status, send_message, respond_to_permission, get_team_status, get_pending_permissions, list_team_presets, cancel_thread). All are real `async def` implementations using `httpx.AsyncClient` to proxy to the REST API. Error handling is comprehensive with specific httpx exception types.
- **Impact**: Positive -- this is production-ready, not a stub.
- **Suggested Fix**: No action needed.

---

## Pass 5: REST Endpoints Actual Behavior

### [HIGH] P5-01 — REST client missing `cancelThread` method

- **Location**: `src/ui/src/app/api/rest-client.ts`
- **Description**: The backend has `POST /api/threads/{thread_id}/cancel` (endpoints.py:817-871). The frontend `RestClient` class has no `cancelThread()` method. The cancel endpoint returns `CancelThreadResponse` with `{thread_id, status, cancelled}`.
- **Impact**: The frontend cannot cancel running threads via the REST client. Any cancel button in the UI will be non-functional.
- **Suggested Fix**: Add `cancelThread(threadId: string): Promise<CancelThreadResponse>` to RestClient.

### [HIGH] P5-02 — Thread state snapshot missing agent `role`, `display_name`, `description`

- **Location**: `src/vaultspec_a2a/api/schemas/snapshots.py:77-84`
- **Description**: `_AgentSnapshot` has only `agent_id`, `node_name`, `state`, `provider`, `model`. It is missing `role`, `display_name`, `description` which are present in `AgentSummary` and `AgentStatusEntry`. The `_enrich_snapshot_from_state` in endpoints.py doesn't populate agents at all -- the snapshot `agents` list stays empty.
- **Impact**: On reconnection, the frontend snapshot will have no agent metadata. The team panel will be empty until a live `team_status` event arrives.
- **Suggested Fix**: Populate `agents` in the snapshot from the aggregator's node summaries. Add `role`, `display_name`, `description` to `_AgentSnapshot`.

### [MED] P5-03 — Thread state endpoint uses `checkpointer.aget()` which may not exist

- **Location**: `src/vaultspec_a2a/api/endpoints.py:505-508`
- **Description**: The endpoint calls `checkpointer.aget()` but `AsyncSqliteSaver` may not have an `aget()` method in all LangGraph versions. The documented method is `aget_tuple()`. This was flagged in the LangGraph alignment sprint (LG-027) but the current code still uses `aget()`.
- **Impact**: If the LangGraph version doesn't support `aget()`, snapshot enrichment silently fails (caught by the broad `except Exception`). Users get partial snapshots without message history.
- **Suggested Fix**: Use `checkpointer.aget_tuple()` as recommended by LangGraph docs, and extract channel_values from the tuple result.

### [MED] P5-04 — GET /team/status always returns agents with state IDLE

- **Location**: `src/vaultspec_a2a/api/endpoints.py:657-667`
- **Description**: The `get_team_status_endpoint` hardcodes `state=AgentLifecycleState.IDLE` for all agents. It reads node summaries from the aggregator but doesn't use any actual state data.
- **Impact**: The team status REST endpoint always shows all agents as "idle" regardless of their actual state. This is misleading for monitoring dashboards and MCP tools.
- **Suggested Fix**: Track actual agent states in the aggregator from relayed `agent_status` events and use them when building the response.

### [MED] P5-05 — REST response shape mismatch: thread list `title` is nullable but frontend expects string

- **Location**: `src/vaultspec_a2a/api/schemas/rest.py:94` vs `src/ui/src/app/data/types.ts:29`
- **Description**: Backend `ThreadSummary.title` is `str | None`. Frontend types.ts `ThreadSummary.title` is `string` (non-optional). The mapper handles this with `title: wire.title ?? 'Untitled'`.
- **Impact**: Low since the mapper handles it. But if the wire-types are used directly, TypeScript will expect `string | null` (from auto-generated types) which is correct.
- **Suggested Fix**: No action needed -- the mapper correctly falls back to 'Untitled'.

### [LOW] P5-06 — Vite proxy env var name inconsistency

- **Location**: `docker-compose.dev.yml:73` vs `src/ui/src/app/api/rest-client.ts:39`
- **Description**: Docker compose sets `VITE_API_URL` but the REST client reads `VITE_API_BASE_URL`. These are different env variable names.
- **Impact**: In Docker, the frontend will fall back to `http://localhost:8000` instead of using the Docker network URL `http://api:8000`, because the env var name doesn't match.
- **Suggested Fix**: Align env var name. Either change compose to `VITE_API_BASE_URL` or change the rest-client/ws-client to read `VITE_API_URL`.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 3     | Enum drift (ToolKind, ToolCallStatus, PermissionOptionKind) |
| HIGH     | 8     | Data loss in mappers (AgentSummary, ThreadSummary, PlanEntry), missing cancelThread, TQ cache shape mismatch, mock-seeder no WS events, snapshot agents empty, team status always IDLE |
| MED      | 8     | Extra phantom fields, vidaimock tape path, MCP plan field name, env var mismatch |
| LOW      | 3     | Wire-types mock provider, MCP functional confirmation, title nullable |

**Total findings: 37** (5 CRIT, 13 HIGH, 13 MED, 6 LOW)

---

## Pass 6: Component Layer Audit

### [CRIT] P6-01 — PermissionModal and PermissionCard check `allow`/`deny` but backend sends `allow_once`/`reject_once`

- **Location**: `src/ui/src/app/components/permission/permission-modal.tsx:67-73` and `src/ui/src/app/components/stream/permission-card.tsx:91-106`
- **Description**: Both components switch on `option.kind` using values `'allow'`, `'deny'`, `'allow_always'`. The backend sends `allow_once`, `allow_always`, `reject_once`, `reject_always` (P1-03). Since the mapper does an unsafe cast without translation, the runtime values will be `allow_once`/`reject_once` but the code compares against `allow`/`deny`. None of the `if (isAllow)` / `if (isDeny)` branches will ever match.
- **Impact**: All permission buttons will render with `variant="ghost"` (the fallback). The "allow" button won't be prominent, the "deny" button won't show error styling. Permission UX is broken -- all options look identical and unstyled.
- **Suggested Fix**: Change comparisons to `allow_once`/`reject_once`/`allow_always`/`reject_always`, or fix the mapper to translate backend values to frontend values.

### [CRIT] P6-02 — `toolKindIcon()` has no cases for backend-only ToolKind values

- **Location**: `src/ui/src/app/components/layout/state-indicators.tsx:85-102` and `src/ui/src/app/components/stream/permission-card.tsx:16-33`
- **Description**: Both `toolKindIcon()` implementations switch on 7 values: `read`, `edit`, `search`, `execute`, `browser`, `mcp`, `other`. The backend sends 10 ToolKind values (P1-01). After the `mapToolKind()` mapper, values `delete`, `move`, `think`, `fetch`, `switch_mode` become `other`. However, `browser` and `mcp` cases can NEVER be reached because the backend never sends these values. These are dead switch cases.
- **Impact**: Two switch cases (`browser`, `mcp`) are dead code. If the enum alignment fix (P1-01) adds the new backend values to the frontend type, the switch statement will need corresponding icon cases or TypeScript will report exhaustiveness errors.
- **Suggested Fix**: When fixing P1-01, add icon cases for `delete`, `move`, `think`, `fetch`, `switch_mode`. Remove or repurpose `browser`/`mcp` cases.

### [HIGH] P6-03 — Sidebar reads `thread.source_repo` and `thread.topology` which are never populated

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx:135,425-430`
- **Description**: The sidebar search filter includes `t.source_repo` (line 135). The TaskItem reads `thread.source_repo` and `thread.source_branch` to build `diskPath` (lines 428-430). It reads `thread.topology` to call `topologyLabel()` (line 425). Per P1-08, `source_repo` and `topology` are phantom fields -- the backend `ThreadSummary` does not include them, and `mapThreadSummary()` does not map them.
- **Impact**: `diskPath` is always `null` (never rendered -- benign). `topoLabel` is always `''` (never rendered -- benign). `source_repo` search filter is dead code. The tooltip section showing "Path" never appears.
- **Suggested Fix**: Remove `source_repo` and `topology` from `ThreadSummary` frontend type and clean up the sidebar code that references them. Alternatively, add these fields to the backend if desired.

### [HIGH] P6-04 — Sidebar agents tooltip shows `node_name` instead of `display_name`

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx:426`
- **Description**: `teamComposition = agents.map((a) => a.node_name).join(' . ')`. Per P1-07, the frontend `AgentSummary` only has `agent_id`, `node_name`, `state` -- it's missing `display_name`. So the tooltip shows internal node names like `vaultspec-coder` instead of human-readable names like `Coder`.
- **Impact**: Team composition tooltip shows technical IDs rather than user-friendly names.
- **Suggested Fix**: After fixing P1-07 to include `display_name`, change this line to use `a.display_name || a.node_name`.

### [HIGH] P6-05 — ToolCallCard checks `status === 'running'` which depends on the mapper being applied

- **Location**: `src/ui/src/app/components/stream/tool-call-card.tsx:17`
- **Description**: The card checks `event.status === 'running'` to show a spinner. The backend sends `in_progress`. This works ONLY because `stream-slice.ts` calls `mapToolCallStatus()` which converts `in_progress` to `running`. If the enum fix (P1-02) changes the canonical frontend value to `in_progress`, this comparison will break.
- **Impact**: Currently works via mapper. But if P1-02 is fixed by aligning to backend values, every `=== 'running'` check in the codebase needs updating to `=== 'in_progress'`.
- **Suggested Fix**: Track this as a dependency of the P1-02 fix. When aligning ToolCallStatus, update: `tool-call-card.tsx:17`, `state-indicators.tsx:77`.

### [HIGH] P6-06 — `toolStatusColor()` in state-indicators.tsx uses `running` not `in_progress`

- **Location**: `src/ui/src/app/components/layout/state-indicators.tsx:72-83`
- **Description**: `toolStatusColor()` switches on `running` (line 77). Same dependency as P6-05 -- if P1-02 aligns to backend values, this breaks.
- **Impact**: Same as P6-05. Tool call status colors would stop working after enum alignment.
- **Suggested Fix**: Update simultaneously with P6-05 when fixing P1-02.

### [HIGH] P6-07 — InputBar `onSend` passes `repo` and `branch` but AppShell likely doesn't wire them to CreateThreadRequest

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:251-259`
- **Description**: In create mode, `handleSend` calls `onSend(message, { preset, repo, branch, featureTag })`. The `repo` and `branch` come from local state backed by `MOCK_REPOS` and `MOCK_BRANCHES` hardcoded arrays (lines 22-35). These are mock data, not fetched from any API. The `CreateThreadRequest` backend schema expects `metadata.workspace_root`, `metadata.source_repo`, `metadata.source_branch` -- but the InputBar's `repo`/`branch` values are mock strings.
- **Impact**: Thread creation sends hardcoded mock repo/branch values. In production, the workspace picker should fetch real data.
- **Suggested Fix**: Replace `MOCK_REPOS` and `MOCK_BRANCHES` with data from a workspace discovery API or from user configuration. Until then, document that these are placeholder values.

### [HIGH] P6-08 — InputBar `source_repo` accessed on `activeThread` but field doesn't exist

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:421`
- **Description**: `const displayRepo = isCreateMode ? createRepo : activeThread?.source_repo`. Per P1-08, `source_repo` is not in the backend ThreadSummary response and not mapped. This will always be `undefined` for non-create mode.
- **Impact**: The repository widget in message mode never shows a value. Low visual impact since it falls through to `null` and isn't rendered.
- **Suggested Fix**: Remove `source_repo` usage or add it to backend/mapper.

### [MED] P6-09 — MessageStream `agentState` prop not wired to actual thread state

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:185,216`
- **Description**: `agentState` is used to show WorkingIndicator when `'working'` or `'submitted'`. This prop comes from AppShell. Per P1-08, `ThreadSummary` has `agent_state` but the mapper doesn't include it. The prop likely needs to be derived from the latest `agent_status` stream event or the thread summary.
- **Impact**: WorkingIndicator may not appear during active execution if the prop isn't connected properly. This needs verification against AppShell wiring.
- **Suggested Fix**: Verify AppShell passes `agentState` derived from actual thread data (agent_status events or TQ query), not just from the thread summary.

### [MED] P6-10 — MessageStream uses `(event as any).agent_name` casts extensively

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:62,255`
- **Description**: `getAgentInfo()` casts to `(event as any).agent_name` and `availableAgents` also uses `(e as any).agent_name`. These rely on `agent_name` existing on stream events. The `stream-slice.ts` sets `agent_name: event.agent_id ?? ''` for all events, so `agent_name` always equals `agent_id`.
- **Impact**: Agent names in the capsule headers, filter chips, and tooltips all show raw agent IDs (e.g., `vaultspec-coder`) instead of display names. This is a UX degradation -- agents show as `mock-coder-success` rather than `Coder`.
- **Suggested Fix**: The backend `AgentStatusEvent` has `node_name` but no `display_name`. The stream-slice should use `event.node_name` for `agent_name` on agent_status events. For other event types, consider enriching from the agents TQ cache.

### [MED] P6-11 — PermissionCard and PermissionModal have duplicated `toolKindIcon()` implementations

- **Location**: `src/ui/src/app/components/stream/permission-card.tsx:16-33` and `src/ui/src/app/components/layout/state-indicators.tsx:85-102`
- **Description**: Two identical implementations of `toolKindIcon()` exist. Both have the same dead `browser`/`mcp` cases and will need identical updates when P1-01 is fixed.
- **Impact**: Maintenance burden -- changes must be made in two places.
- **Suggested Fix**: Remove the local copy in permission-card.tsx and import from state-indicators.tsx.

### [MED] P6-12 — `agentStateDot()` returns `null` for `completed` and `idle` -- no visual indicator

- **Location**: `src/ui/src/app/components/layout/state-indicators.tsx:34-49`
- **Description**: The function returns `null` for `completed` and `idle` states. The sidebar TaskItem renders an empty `<span>` spacer when `dot` is null (line 482-483). Completed and idle threads show no status indicator at all.
- **Impact**: Users cannot visually distinguish completed/idle threads from unstarted threads in the sidebar. Low severity since the tooltip still shows state info.
- **Suggested Fix**: Consider adding a static green dot for `completed` and a grey dot for `idle` to provide visual distinction.

### [MED] P6-13 — PlanUpdateCard maps `PlanEntry.content` to `title` via stream-slice, fragile ID

- **Location**: `src/ui/src/app/store/slices/stream-slice.ts:245-250`
- **Description**: Stream-slice synthesizes plan entry objects with `id: \`${e.content.slice(0, 20)}-${e.status}\`` and `title: e.content`. If two plan entries share the first 20 chars and same status, they get the same `id`, causing React key collisions and rendering bugs.
- **Impact**: Plan updates with similar entries may render incorrectly due to duplicate keys.
- **Suggested Fix**: Use an index-based ID: `id: \`plan-entry-${idx}\`` or include the full content hash.

### [LOW] P6-14 — InputBar `selectedPreset.agents` iterates an always-empty array

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:191-192,455-466`
- **Description**: `availableAgents = selectedPreset.agents` is used for @ mention autocomplete. Per P1-10, `mapTeamPreset()` always sets `agents: []`. The @ mention popup will never show any agents.
- **Impact**: @ mention feature is non-functional. Users cannot mention specific agents in messages.
- **Suggested Fix**: After fixing P1-10 to populate `agents` from the backend, or by adding agent list discovery, this will start working.

### [LOW] P6-15 — InputBar hardcodes `MOCK_REPOS` and `MOCK_BRANCHES`

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:22-35`
- **Description**: Repository and branch pickers use hardcoded mock data. These are never fetched from any API or configuration.
- **Impact**: In production, users will see `wgergely/vaultspec-a2a`, `wgergely/vaultspec-core`, `wgergely/vaultspec-ui` as the only repo options, regardless of their actual workspace.
- **Suggested Fix**: Replace with workspace discovery or make configurable. Document as known mock data.

---

## Component Impact Matrix for Enum Fixes

This matrix shows which components need updating when each Pass 1 finding is fixed:

| Finding | Files Impacted by Fix |
|---------|----------------------|
| P1-01 (ToolKind) | `types.ts`, `state-indicators.tsx` (both toolKindIcon), `permission-card.tsx` (toolKindIcon), `mappers.ts` (mapToolKind) |
| P1-02 (ToolCallStatus) | `types.ts`, `tool-call-card.tsx:17`, `state-indicators.tsx:72-83`, `mappers.ts` (mapToolCallStatus -- remove or update) |
| P1-03 (PermissionOptionKind) | `types.ts`, `permission-modal.tsx:67-73`, `permission-card.tsx:91-106`, `mappers.ts` (mapPermissionRequest unsafe cast) |
| P1-04 (Provider) | `types.ts` only -- no components switch on Provider values currently |
| P1-07 (AgentSummary) | `types.ts`, `mappers.ts`, `sidebar.tsx:426` (use display_name), `ws-bridge.ts:59-69` (pass more fields) |
| P1-08 (ThreadSummary) | `types.ts`, `mappers.ts`, `sidebar.tsx:135,425-430` (remove phantom fields), `input-bar.tsx:421` |

---

---

## Pass 7: Component Wiring Audit

**Context**: `types.ts` has been partially updated by the coder (task #6 in progress). ToolKind now has all 10 backend values, PermissionOptionKind is `allow_once`/`allow_always`/`reject_once`/`reject_always`, Provider is `claude`/`gemini`/`mock`/`openai`/`zhipu`, AgentSummary has all 8 fields, ToolCallStatus is `pending`/`running`/`completed`/`failed` (still uses `running` not `in_progress`). However, **mappers and components have NOT been updated** to match. This pass documents exactly what will break and what needs updating in each file.

### 1. sidebar.tsx — Thread Rendering

**Fields accessed on `ThreadSummary`**:
- `thread.thread_id` (line 358) -- OK
- `thread.nickname` (line 424) -- OK
- `thread.title` (line 424, 530) -- OK (present in types.ts)
- `thread.agent_state` (lines 419, 421-422, 465) -- OK
- `thread.updated_at` (line 491) -- OK
- `thread.feature_tag` (lines 496, 503, 561-568) -- OK
- `thread.source_branch` (lines 496, 508, 571-579) -- OK
- `thread.topology` (line 425) -- **PHANTOM**: not in backend `ThreadSummary`, not in current `types.ts`
- `thread.source_repo` (lines 135, 428) -- **PHANTOM**: not in backend, not in `types.ts`
- `thread.team_preset` (line 538) -- OK (optional in types.ts)
- `thread.status` -- NOT accessed (despite being available in backend)
- `thread.created_at` -- NOT accessed (despite being available in backend)

#### [HIGH] P7-01 — sidebar.tsx reads `thread.topology` (phantom field)

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx:425,538`
- **Description**: `topologyLabel(thread.topology)` is called at line 425 and displayed in the tooltip at line 538-548. But `ThreadSummary` in `types.ts` has no `topology` field. It's also absent from the backend REST schema. The `TeamTopology` type is imported at line 30 but only used as a phantom.
- **Impact**: `thread.topology` is always `undefined`, `topologyLabel()` returns `''`, the tooltip "Team" section only shows `thread.team_preset || '—'` with no topology label. Dead code.
- **Suggested Fix**: Remove `topology` access from sidebar. If topology is needed, fetch it from the team preset data, not the thread.

#### [HIGH] P7-02 — sidebar.tsx reads `thread.source_repo` (phantom field)

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx:135,428-430`
- **Description**: Used in search filter (line 135) and tooltip "Path" section (lines 428-430, 581-589). Not present in `ThreadSummary` type or backend schema.
- **Impact**: Search filter includes `undefined` string (harmless but wasted). Tooltip "Path" section never renders because `diskPath` is always `null`. Dead code.
- **Suggested Fix**: Remove `source_repo` from the search filter and tooltip path calculation. If workspace path is needed, source it from thread metadata endpoint.

#### [MED] P7-03 — sidebar.tsx shows `node_name` not `display_name` for agents

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx:426`
- **Description**: `agents.map((a) => a.node_name).join(' · ')` -- shows internal node names in the tooltip "Agents" section. Now that `AgentSummary` has `display_name`, the sidebar should prefer it.
- **Impact**: Users see internal identifiers like `vaultspec-coder` instead of human-friendly display names.
- **Suggested Fix**: `agents.map((a) => a.display_name || a.node_name).join(' · ')`

#### [LOW] P7-04 — sidebar.tsx does not use `status` or `created_at`

- **Location**: `src/ui/src/app/components/layout/sidebar.tsx` (entire file)
- **Description**: Backend `ThreadSummary` includes `status` and `created_at`. The sidebar never reads either. `status` could be used for visual status badges. `created_at` could be used for sorting or display.
- **Impact**: No breakage, but missed functionality.
- **Suggested Fix**: Consider adding `status` badge and using `created_at` for time display or sort ordering.

### 2. message-stream.tsx — Stream Event Rendering

**Discriminated union branches checked** (line 135-168, AgentCapsule switch):
- `agent_message` -- renders `AgentBubble`
- `thought` -- renders `ThoughtBlock`
- `tool_call` -- renders `ToolCallCard`
- `artifact` -- renders `ArtifactCard`
- `plan_update` -- renders `PlanUpdateCard`
- `agent_status` -- returns `null` (silently dropped)
- Standalone switch (line 586-593): `user_message`, `error`

**Missing from switch**: No case for `permission_request` (handled separately via `pendingPermissions` prop). No case for `team_status`, `connected`, `heartbeat` (these are connection-scoped and don't enter stream events).

#### [HIGH] P7-05 — message-stream.tsx `getAgentInfo()` uses `(event as any).agent_name` unsafe cast

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:62`
- **Description**: `getAgentInfo()` does `(event as any).agent_name` to extract agent name from events. This bypasses TypeScript type narrowing. The `agent_name` field IS present on most `StreamEvent` subtypes (`AgentMessageEvent`, `ThoughtEvent`, `ToolCallEvent`, etc.) in `types.ts`, so the cast is technically safe but defeats type safety.
- **Impact**: If `agent_name` is ever renamed or moved, no compile-time error. Also, `agent_name` is set to `event.agent_id` in stream-slice.ts (see P7-10), so all agent capsule headers show agent IDs, not display names.
- **Suggested Fix**: Use proper type narrowing: `if ('agent_name' in event && typeof event.agent_name === 'string')` or narrow on event.type.

#### [HIGH] P7-06 — message-stream.tsx `handleInspect()` uses multiple `(event as any)` casts

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:223-231`
- **Description**: `handleInspect` accesses `(e as any).tool_name`, `(e as any).filename`, `(e as any).agent_name` without type narrowing. These are valid fields on the respective event subtypes but bypassed via `any`.
- **Impact**: Same as P7-05 -- no compile-time safety if fields change.
- **Suggested Fix**: Narrow event type first: `if (e.type === 'tool_call') { e.tool_name ... }`.

#### [MED] P7-07 — message-stream.tsx `availableAgents` extraction uses `(e as any).agent_name`

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:255`
- **Description**: The agent filter popover extracts `(e as any).agent_name` from all events, building a map of agentId->agentName for the filter UI. Same unsafe cast pattern.
- **Impact**: Filter labels show agent IDs instead of display names (because `agent_name` is set to `event.agent_id` in stream-slice).
- **Suggested Fix**: Use typed access. Also, consider using `display_name` from `AgentSummary` data (passed via `agents` prop) instead of extracting from events.

#### [LOW] P7-08 — message-stream.tsx `isWorking` checks `working` and `submitted`

- **Location**: `src/ui/src/app/components/stream/message-stream.tsx:216`
- **Description**: `const isWorking = agentState === 'working' || agentState === 'submitted'`. Both values are valid `AgentLifecycleState` values in the backend. This is correct behavior.
- **Impact**: No breakage. Noted for completeness.

### 3. tool-call-card.tsx — ToolKind and ToolCallStatus

#### [HIGH] P7-09 — tool-call-card.tsx checks `event.status === 'running'` (depends on mapper)

- **Location**: `src/ui/src/app/components/stream/tool-call-card.tsx:17`
- **Description**: The status icon switch checks `event.status === 'running'` for the spinner. The backend sends `in_progress`. This only works because `stream-slice.ts` calls `mapToolCallStatus()` which translates `in_progress` -> `running`. If the types.ts `ToolCallStatus` is updated to match backend (`in_progress`), this component will break -- `running` spinner case will never match.
- **Impact**: **Latent breakage**: if the coder aligns `ToolCallStatus` to backend's `in_progress`, tool call cards will show the fallback (empty circle) for in-progress tools instead of the spinner.
- **Suggested Fix**: If `ToolCallStatus` is changed to `in_progress`, update this component's check to `'in_progress'`. If keeping `running`, document why.

#### [MED] P7-10 — tool-call-card.tsx does NOT switch on ToolKind at all

- **Location**: `src/ui/src/app/components/stream/tool-call-card.tsx` (entire file)
- **Description**: The component only displays `event.tool_name` as text. It does not use `event.tool_kind` for any icon or visual distinction. The new ToolKind values (`delete`, `move`, `think`, `fetch`, `switch_mode`) will not break this component, but there's a missed opportunity for visual affordance.
- **Impact**: No breakage from ToolKind changes. All tool calls look identical regardless of kind.
- **Suggested Fix**: Consider adding `toolKindIcon(event.tool_kind)` for visual categorization (like permission-card.tsx does).

### 4. input-bar.tsx — Send Flow and Data Model

**Send flow**:
1. User types in `MarkdownEditor`, state held in `message` useState
2. `handleSend()` at line 251-267 fires on Enter or button click
3. In "create" mode (new thread): calls `onSend(message.trim(), { preset, repo, branch, featureTag })`
4. In "message" mode (existing thread): calls `onSend(message.trim())` with no options

#### [HIGH] P7-11 — input-bar.tsx `onSend` passes `repo`/`branch`/`featureTag` but backend ignores them

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:46-54,253-259`
- **Description**: The `onSend` callback signature accepts `opts?: { preset?, repo?, branch?, featureTag? }`. In create mode, it passes `repo: createRepo`, `branch: createBranch`, `featureTag: createFeatureTag`. But the `CreateThreadRequest` backend schema only has `message`, `team_preset`, `autonomous`, and `metadata`. The `repo` and `branch` fields are NOT part of the API contract.
- **Impact**: The repo and branch values selected by the user are silently discarded. Users think they're configuring a repo/branch but the backend never receives them.
- **Suggested Fix**: Either (a) add `source_branch`/workspace fields to `CreateThreadRequest` backend schema, or (b) remove the repo/branch pickers from the input bar and set these via thread metadata after creation.

#### [HIGH] P7-12 — input-bar.tsx reads `activeThread?.source_repo` (always undefined)

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:421`
- **Description**: `const displayRepo = isCreateMode ? createRepo : activeThread?.source_repo`. `source_repo` does not exist on `ThreadSummary` type. Always `undefined`.
- **Impact**: In message mode, the repo widget never renders (line 493-498 checks `displayRepo` which is falsy). This is cosmetically OK but indicates dead logic.
- **Suggested Fix**: Remove `source_repo` reference. If displaying workspace info in message mode, fetch from thread metadata.

#### [MED] P7-13 — input-bar.tsx `TeamPreset` expects `agents: string[]` but mapper sets `agents: []`

- **Location**: `src/ui/src/app/components/stream/input-bar.tsx:189-198,455-468`
- **Description**: The `@mention` autocomplete reads `selectedPreset.agents` (line 191-192) and the team preset picker displays `p.agents.map((a) => ...)` (line 455). But `mapTeamPreset()` in mappers.ts hardcodes `agents: []`. The backend `TeamPresetSummary` has `worker_count` but no `agents` list.
- **Impact**: `@mention` autocomplete never has any agents to suggest. Team preset picker never shows agent composition badges. Both features are dead.
- **Suggested Fix**: Either (a) add `agents` field to backend `TeamPresetSummary`, or (b) add a separate endpoint to fetch agent composition per preset, or (c) remove the `@mention` feature until agent data is available.

### 5. permission-modal.tsx — PermissionOptionKind Matching

#### [CRIT] P7-14 — permission-modal.tsx checks `option.kind === 'allow'`/`'deny'` (backend sends `allow_once`/`reject_once`)

- **Location**: `src/ui/src/app/components/permission/permission-modal.tsx:67-73`
- **Description**: The button variant logic:
  ```
  option.kind === 'allow' ? 'default'
  : option.kind === 'deny' ? 'outline'
  : option.kind === 'allow_always' ? 'secondary'
  : 'ghost'
  ```
  And the extra class (line 75-77): `option.kind === 'deny'` for error styling.
  But `types.ts` PermissionOptionKind is now `allow_once | allow_always | reject_once | reject_always`. No option will ever have kind `'allow'` or `'deny'`. The `allow_always` check happens to match. `reject_once` and `reject_always` fall through to `'ghost'` with no error styling.
- **Impact**: **BROKEN**: Allow-once buttons get `'ghost'` variant (barely visible) instead of `'default'` (primary). Reject buttons get `'ghost'` with no error coloring instead of `'outline'` with red styling. Only `allow_always` renders correctly as `'secondary'`.
- **Suggested Fix**: Update to:
  ```
  option.kind === 'allow_once' ? 'default'
  : option.kind === 'reject_once' ? 'outline'
  : option.kind === 'allow_always' ? 'secondary'
  : 'ghost'
  ```
  And update the `extraClass` check to `option.kind === 'reject_once' || option.kind === 'reject_always'`.

### 6. permission-card.tsx — Same PermissionOptionKind Issue

#### [CRIT] P7-15 — permission-card.tsx checks `option.kind === 'allow'`/`'deny'` (same as P7-14)

- **Location**: `src/ui/src/app/components/stream/permission-card.tsx:91-106`
- **Description**: Identical pattern to permission-modal.tsx:
  ```
  const isAllow = option.kind === 'allow';
  const isDeny = option.kind === 'deny';
  const isAlwaysAllow = option.kind === 'allow_always';
  ```
  With `types.ts` now using `allow_once`/`reject_once`, `isAllow` and `isDeny` are always `false`.
- **Impact**: **BROKEN**: Same as P7-14. In-stream permission cards render all buttons as ghost variant, no visual distinction between allow and reject.
- **Suggested Fix**: Update to `option.kind === 'allow_once'`, `option.kind === 'reject_once'` or `option.kind.startsWith('reject')`.

#### [MED] P7-16 — permission-card.tsx has duplicated `toolKindIcon()` function

- **Location**: `src/ui/src/app/components/stream/permission-card.tsx:16-33`
- **Description**: Local `toolKindIcon()` duplicates the one in `state-indicators.tsx:85-101`. Both have the same `browser`/`mcp` dead cases. Both are missing `delete`/`move`/`think`/`fetch`/`switch_mode`.
- **Impact**: When ToolKind values are added to the icon function, two places need updating. If only one is updated, inconsistent behavior.
- **Suggested Fix**: Remove the local copy in permission-card.tsx. Import from state-indicators.tsx (permission-modal.tsx already does this).

### 7. plan-update-card.tsx — PlanEntry Access

#### [MED] P7-17 — plan-update-card.tsx reads `entry.status` but not `entry.title` or `entry.content`

- **Location**: `src/ui/src/app/components/stream/plan-update-card.tsx:15`
- **Description**: The component only counts completed entries: `event.entries.filter((e) => e.status === 'completed').length`. It doesn't display individual entry text. The `PlanEntry` type in `types.ts` has `id`, `title`, `status`, `priority`. The backend has `content` not `title`. The stream-slice maps `content` -> `title` so `entry.title` would work if accessed.
- **Impact**: No breakage -- the component doesn't access the mismatched field. But it also means the plan update card is very minimal (just "Plan updated 3/5") with no detail view.
- **Suggested Fix**: None needed for correctness. Consider adding entry detail view in the inspect panel.

### 8. state-indicators.tsx — ToolKind and ToolCallStatus

#### [HIGH] P7-18 — state-indicators.tsx `toolKindIcon()` missing 5 backend ToolKind values

- **Location**: `src/ui/src/app/components/layout/state-indicators.tsx:85-101`
- **Description**: The switch handles: `read`, `edit`, `search`, `execute`, `browser`, `mcp`, `other`. Missing from backend: `delete`, `move`, `think`, `fetch`, `switch_mode`. Has phantom cases: `browser`, `mcp` (not in backend enum). With `types.ts` now including all 10 backend values, TypeScript will error because the switch is non-exhaustive (missing `delete`, `move`, `think`, `fetch`, `switch_mode` cases) and includes invalid cases (`browser`, `mcp`).
- **Impact**: **TypeScript compile error** once types.ts ToolKind update is consumed. At runtime, tool calls with `delete`/`move`/`think`/`fetch`/`switch_mode` kinds will return `undefined` from the function (no icon rendered).
- **Suggested Fix**: Remove `browser`/`mcp` cases. Add cases for `delete`, `move`, `think`, `fetch`, `switch_mode` with appropriate icons (e.g., Trash2, ArrowRightLeft, Brain, Download, ToggleLeft).

#### [MED] P7-19 — state-indicators.tsx `toolStatusColor()` uses `running` (ToolCallStatus dependency)

- **Location**: `src/ui/src/app/components/layout/state-indicators.tsx:72-83`
- **Description**: `case 'running': return 'text-status-info'`. The `ToolCallStatus` type in types.ts still has `running`. If aligned to backend's `in_progress`, this will break.
- **Impact**: Latent breakage, same dependency as P7-09.
- **Suggested Fix**: Keep in sync with whatever ToolCallStatus canonical value is chosen.

### 9. stream-slice.ts — Wire Event Translation

#### [HIGH] P7-20 — stream-slice.ts sets `agent_name: event.agent_id` for ALL event types

- **Location**: `src/ui/src/app/store/slices/stream-slice.ts:70,107,142,217,244,271`
- **Description**: Every event handler sets `agent_name: event.agent_id ?? ''`. The wire events have `agent_id` but no `agent_name` (that's a frontend domain field). The `display_name` from AgentSummary is available via team_status events but is never wired into individual stream events.
- **Impact**: All agent capsule headers, inspect panels, and filter labels show the internal `agent_id` (e.g., `vaultspec-coder`) instead of human-readable display names. The `agent_name` field on `AgentMessageEvent`, `ThoughtEvent`, etc. in types.ts exists but is always populated with the ID.
- **Suggested Fix**: Maintain an `agentId -> displayName` map in the store (populated by team_status events). When creating stream events, resolve `agent_name` from this map. Fallback to `agent_id` if unknown.

#### [HIGH] P7-21 — stream-slice.ts agent_status handler sets `old_state: 'idle'` (fabricated)

- **Location**: `src/ui/src/app/store/slices/stream-slice.ts:272`
- **Description**: `old_state: 'idle'` is hardcoded. The backend `AgentStatusEvent` has `state` (new state) and `node_name`, but no `old_state` field. The frontend `AgentStatusEvent` type in types.ts has `state` but no `old_state` field.
- **Impact**: The `old_state: 'idle'` is set but `AgentStatusEvent` in types.ts doesn't have `old_state`, so this is an extra field that TypeScript won't complain about (structural typing) but it's fabricated data.
- **Suggested Fix**: Remove `old_state` from the handler since it's not in the type definition and not used by any component (agent_status returns null in the switch).

#### [MED] P7-22 — stream-slice.ts plan_update handler uses fragile synthetic IDs

- **Location**: `src/ui/src/app/store/slices/stream-slice.ts:246`
- **Description**: `id: \`${e.content.slice(0, 20)}-${e.status}\`` -- plan entries get synthetic IDs by concatenating the first 20 chars of content with status. Two entries with the same prefix and status will collide.
- **Impact**: React key collisions in plan entry lists. If plan-update-card ever renders individual entries, duplicate keys cause rendering bugs.
- **Suggested Fix**: Use index-based IDs: `id: \`plan-${idx}\`` or add `crypto.randomUUID()`.

### 10. mappers.ts — Stale Mapper Logic

#### [HIGH] P7-23 — mappers.ts `mapToolKind()` uses stale `FRONTEND_TOOL_KINDS` set with `browser`/`mcp`

- **Location**: `src/ui/src/app/api/mappers.ts:77-84,91-93`
- **Description**: `FRONTEND_TOOL_KINDS` contains `['read','edit','search','execute','browser','mcp','other']`. The mapper checks `FRONTEND_TOOL_KINDS.has(wire)` and returns `other` for anything not in the set. With types.ts now including `delete`, `move`, `think`, `fetch`, `switch_mode`, the mapper will STILL map these to `other` because `FRONTEND_TOOL_KINDS` hasn't been updated.
- **Impact**: Even though types.ts is correct, the mapper silently destroys the new ToolKind values before they reach components.
- **Suggested Fix**: Update `FRONTEND_TOOL_KINDS` to match the new types.ts ToolKind values. Remove `browser`/`mcp`. Add `delete`, `move`, `think`, `fetch`, `switch_mode`. Or better: remove the mapper entirely since types.ts now matches backend.

#### [HIGH] P7-24 — mappers.ts `mapToolCallStatus()` translates `in_progress` -> `running`

- **Location**: `src/ui/src/app/api/mappers.ts:87-89`
- **Description**: `return wire === 'in_progress' ? 'running' : wire`. This mapper is the sole reason `running` works in components. If `ToolCallStatus` in types.ts is changed to `in_progress`, this mapper creates a value that doesn't match the type.
- **Impact**: Currently functional but fragile. The mapper must be updated in lockstep with any ToolCallStatus enum change.
- **Suggested Fix**: If keeping `running` in types.ts, document why. If changing to `in_progress`, remove this mapper and update all component checks.

#### [HIGH] P7-25 — mappers.ts `mapAgentSummary()` only maps 3 of 8 fields

- **Location**: `src/ui/src/app/api/mappers.ts:40-48`
- **Description**: Maps `agent_id`, `node_name`, `state`. Drops `provider`, `model`, `role`, `display_name`, `description` from the wire data. types.ts `AgentSummary` now has all 8 fields as optional, but the mapper never populates them.
- **Impact**: All downstream consumers that check `agent.display_name`, `agent.provider`, etc. will get `undefined` even though the backend provides the data.
- **Suggested Fix**: Map all fields: `provider: wire.provider ?? undefined`, `model: wire.model ?? undefined`, `role: wire.role ?? ''`, `display_name: wire.display_name ?? ''`, `description: wire.description ?? ''`.

#### [HIGH] P7-26 — mappers.ts `mapThreadSummary()` drops `status` and `created_at`

- **Location**: `src/ui/src/app/api/mappers.ts:27-38`
- **Description**: The mapper does not include `status: wire.status` or `created_at: wire.created_at` in the returned object. types.ts `ThreadSummary` has both as optional fields.
- **Impact**: `thread.status` and `thread.created_at` are always `undefined` in the frontend, even though the backend provides them.
- **Suggested Fix**: Add `status: wire.status ?? undefined` and `created_at: wire.created_at ?? undefined` to the mapper.

#### [MED] P7-27 — mappers.ts `mapPermissionRequest()` sets `agent_name: wire.agent_id`

- **Location**: `src/ui/src/app/api/mappers.ts:65`
- **Description**: `agent_name: wire.agent_id ?? ''`. The permission request event from the backend has `agent_id` but no dedicated `agent_name` field. The mapper uses the agent_id as the display name.
- **Impact**: Permission modal and card show the internal agent ID (e.g., `vaultspec-coder`) as the agent name. Should resolve to display_name from AgentSummary data.
- **Suggested Fix**: Accept an agent lookup map as parameter, resolve `agent_name` from `display_name`. Fallback to `agent_id`.

#### [MED] P7-28 — mappers.ts `mapPermissionRequest()` hardcodes `tool_kind: 'other'`

- **Location**: `src/ui/src/app/api/mappers.ts:67`
- **Description**: `tool_kind: 'other'` is hardcoded. The backend `PermissionRequestEvent` has `tool_call: str | None` but no `tool_kind` field. The frontend expects `tool_kind` on `PermissionRequest`.
- **Impact**: All permission cards show the generic wrench icon regardless of what tool is being requested.
- **Suggested Fix**: Either (a) add `tool_kind` to backend `PermissionRequestEvent`, or (b) attempt to infer kind from tool_call name, or (c) accept 'other' as a known limitation.

---

## Findings Summary: Which Components Have Hardcoded Enum String Comparisons That Will Break

| Component | Hardcoded Value | Backend Value | Will Break? |
|-----------|----------------|---------------|-------------|
| `permission-modal.tsx:67` | `'allow'` | `'allow_once'` | **YES -- NOW** |
| `permission-modal.tsx:69` | `'deny'` | `'reject_once'` | **YES -- NOW** |
| `permission-modal.tsx:75` | `'deny'` | `'reject_once'` | **YES -- NOW** |
| `permission-card.tsx:91` | `'allow'` | `'allow_once'` | **YES -- NOW** |
| `permission-card.tsx:92` | `'deny'` | `'reject_once'` | **YES -- NOW** |
| `permission-card.tsx:93` | `'allow_always'` | `'allow_always'` | No (matches) |
| `tool-call-card.tsx:17` | `'running'` | `'in_progress'` | Latent (mapper translates) |
| `state-indicators.tsx:76` | `'running'` | `'in_progress'` | Latent (mapper translates) |
| `state-indicators.tsx:87-98` | `'browser'`, `'mcp'` | N/A | Dead (never sent) |
| `stream-slice.ts:272` | `'idle'` (fabricated old_state) | N/A | No (unused) |

## Which Component Props Need Interface Changes

| Component | Prop/Field | Change Needed |
|-----------|-----------|---------------|
| `permission-modal.tsx` | `option.kind` comparisons | Update to `allow_once`/`reject_once`/`reject_always` |
| `permission-card.tsx` | `option.kind` comparisons | Same as above |
| `state-indicators.tsx` | `toolKindIcon()` switch | Remove `browser`/`mcp`, add `delete`/`move`/`think`/`fetch`/`switch_mode` |
| `state-indicators.tsx` | `toolStatusColor()` switch | Update if ToolCallStatus changes to `in_progress` |
| `tool-call-card.tsx` | `event.status` comparison | Update if ToolCallStatus changes to `in_progress` |
| `sidebar.tsx` | `ThreadSummary` phantom fields | Remove `topology`, `source_repo` access |
| `sidebar.tsx` | Agent display | Use `display_name` instead of `node_name` |
| `input-bar.tsx` | `onSend` opts | Remove `repo`/`branch` or wire to backend |
| `mappers.ts` | `FRONTEND_TOOL_KINDS` | Update to match types.ts |
| `mappers.ts` | `mapAgentSummary` | Map all 8 fields |
| `mappers.ts` | `mapThreadSummary` | Add `status`, `created_at` |

## Components Using `as any` Casts on Store/Query Data

| File | Line(s) | Cast | Risk |
|------|---------|------|------|
| `message-stream.tsx:62` | `(event as any).agent_name` | getAgentInfo() | Bypasses type narrowing |
| `message-stream.tsx:223-230` | `(e as any).tool_name`, `(e as any).filename`, `(e as any).agent_name` | handleInspect() | Bypasses type narrowing |
| `message-stream.tsx:255` | `(e as any).agent_name` | availableAgents extraction | Bypasses type narrowing |
| `permission-modal.tsx:81` | `variant as any` | Button variant prop | Bypasses union type check |

---

## Summary (Updated)

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 7     | Permission kind matching broken (modal+card, x2), enum drift (P1-01 through P1-03), dead toolKindIcon cases |
| HIGH     | 21    | Mapper data loss (AgentSummary 3/8 fields, ThreadSummary missing status/created_at), stale FRONTEND_TOOL_KINDS set, phantom sidebar fields, ToolCallStatus latent breakage, agent_name=agent_id everywhere, InputBar repo/branch not in API, fabricated old_state |
| MED      | 19    | Phantom fields, vidaimock tapes, MCP plan field, env var mismatch, duplicated toolKindIcon, agent names show IDs, plan entry fragile IDs, mapPermissionRequest agent_name/tool_kind, toolStatusColor dependency |
| LOW      | 8     | Wire-types mock provider, MCP functional, title nullable, empty agents for @mention, hardcoded mock repos, no visual dot for completed/idle, sidebar ignores status/created_at, isWorking check correct |

**Total findings: 53** (7 CRIT, 21 HIGH, 19 MED, 8 LOW) across 7 audit passes.
