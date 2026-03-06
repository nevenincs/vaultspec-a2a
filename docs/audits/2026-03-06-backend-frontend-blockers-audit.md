# Backend Issues Blocking Frontend Functionality

**Date**: 2026-03-06
**Auditor**: codebase-auditor agent
**Scope**: Backend code paths that block or degrade the frontend experience
**Source**: Extracted from `2026-03-06-frontend-backend-state-layer-audit.md` (Passes 1-9) + new deep audit of aggregator, endpoints, executor, internal relay, and schemas.

---

## 1. Event Emission Gaps

### [HIGH] BE-01 -- `plan_update` wire event defined but never emitted

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:205-209` (model), `src/vaultspec_a2a/core/aggregator.py:943-1087` (process_langgraph_event)
- **Origin**: P8-04
- **Description**: `PlanUpdateEvent` is defined with `entries: list[PlanEntry]`. The frontend `stream-slice.ts` handles `plan_update` events (lines 232-256). But `process_langgraph_event()` has no handler that produces `PlanUpdateEvent`. No code in the codebase constructs or emits this event type.
- **Impact**: Plan entries never stream to the browser. The `PlanUpdateCard` never renders with real data.
- **Fix effort**: Medium -- requires either (a) supervisor/worker nodes emitting plan changes via custom LangGraph events and a new `on_custom_event` sub-handler, or (b) state inspection after each node boundary to diff `current_plan`.

### [HIGH] BE-02 -- `artifact_update` wire event defined but never emitted

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:194-203` (model)
- **Origin**: P8-04
- **Description**: `ArtifactUpdateEvent` is defined with `artifact_id`, `filename`, `content`, `complete`. The frontend handles it in `stream-slice.ts` (lines 195-229). No aggregator code constructs or emits this event.
- **Impact**: Artifact streaming is entirely dead. File artifacts are only visible via snapshot hydration.
- **Fix effort**: Medium -- same pattern as BE-01.

### [MED] BE-03 -- `emit_team_status()` has full enrichment but no caller

- **Location**: `src/vaultspec_a2a/core/aggregator.py:908-937`
- **Origin**: P8-07
- **Description**: `emit_team_status()` accepts agent dicts, enriches with `_node_metadata` (role, display_name, description) per ADR-012 section 6, and broadcasts a `TeamStatusEvent`. No code path calls it. The frontend WS bridge has a handler for `team_status` that never fires.
- **Impact**: No team-wide status broadcasts over WS. Frontend relies solely on REST polling for team status.
- **Fix effort**: Low -- call after `emit_agent_status()` when a node transitions, building team status from `_agent_states` table.

### [MED] BE-04 -- `PermissionRequestEvent` has no `tool_kind` field

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:182-191`
- **Origin**: P1-09
- **Description**: Backend `PermissionRequestEvent` has `tool_call: str | None` (a string tool name). The frontend `PermissionRequest` type expects `tool_kind: ToolKind`. The mapper hardcodes `tool_kind: 'other'`. ACP interrupt data includes the tool name and could include the kind.
- **Impact**: All permission request cards display the generic wrench icon regardless of tool category.
- **Fix effort**: Low -- derive `tool_kind` from the ACP tool classification in `_emit_interrupt_events()` and add the field to the event model.

---

## 2. Aggregator.ingest() and process_langgraph_event() Coverage

### [INFO] BE-05 -- process_langgraph_event() handles 7 of 10 LangGraph event types

- **Location**: `src/vaultspec_a2a/core/aggregator.py:943-1087`
- **Description**: Handled: `on_chat_model_stream`, `on_tool_start`, `on_tool_end`, `on_tool_error`, `on_custom_event`, `on_chain_start`, `on_chain_end`, `on_chain_error`. The remaining LangGraph v2 events (`on_llm_start`, `on_llm_end`, `on_retriever_start/end`) are filtered out by design (research section 1.2). This is correct -- they are noisy sub-runnable events.
- **Impact**: None -- acceptable filtering.

### [LOW] BE-06 -- `on_custom_event` maps to ThoughtChunkEvent only

- **Location**: `src/vaultspec_a2a/core/aggregator.py:1032-1043`
- **Description**: All custom events are assumed to be thought/reasoning chunks. If plan updates or artifact updates are emitted via custom events (the likely future path for BE-01/BE-02), a discriminator field will be needed.
- **Impact**: Future consideration. Currently no graph nodes emit custom events beyond thoughts.
- **Fix effort**: Low when needed -- check for `data.get("type")` in the custom event handler and branch.

---

## 3. Worker Executor Broadcast Hooks

### [INFO] BE-07 -- Worker executor relay chain is correctly wired

- **Location**: `src/vaultspec_a2a/worker/executor.py:88-96`
- **Description**: `Executor.__init__()` creates an `EventAggregator` and wires a `_relay_event` broadcast hook that calls `bridge.send_event(thread_id, event.model_dump())` for every emitted event. This correctly relays all worker events to the API server via HTTP POST `/internal/events`.
- **Impact**: None -- this is functioning correctly.

### [MED] BE-08 -- Worker aggregator's `register_graph()` populates node metadata; API aggregator's does not

- **Location**: `src/vaultspec_a2a/worker/executor.py:182` (worker), `src/vaultspec_a2a/api/app.py` (API)
- **Origin**: P8-03
- **Description**: The worker calls `aggregator.register_graph(graph)` which populates `_node_metadata` with role, display_name, description from graph node specs. The API server's aggregator never calls `register_graph()` because it has no compiled graphs.
- **Impact**: `aggregator.get_node_summaries()` on the API aggregator returns empty. `get_team_status_endpoint` at `endpoints.py:658` calls this and gets no agent metadata. The endpoint falls back to constructing agents from `_agent_states` keys only.
- **Fix effort**: Medium -- either sync node metadata via the internal events channel (add a `graph_registered` event type), or have the API server load team config to derive agent metadata without needing a compiled graph.

---

## 4. Snapshot Enrichment Gaps

### [HIGH] BE-09 -- `_enrich_snapshot_from_state()` only populates `messages` and `checkpoint_id`

- **Location**: `src/vaultspec_a2a/api/endpoints.py:397-467`
- **Origin**: P5-02
- **Description**: `ThreadStateSnapshot` has fields for `agents`, `pending_permissions`, `plan`, `artifacts`, `tool_calls` (all `list[...]`). The enrichment function only populates `messages` and `checkpoint_id` via `model_copy(update={...})`. All other fields remain empty default lists.
- **Impact**: On reconnection, the frontend gets messages but no agent state, no tool calls, no plan, no artifacts, no permissions. The stream view is impoverished until live events start flowing.
- **Fix effort**: Medium-High. Requires:
  - `agents`: Read from API aggregator's `_agent_states` (now available via `sync_worker_event`)
  - `pending_permissions`: Read from API aggregator's `_pending_permissions`
  - `plan`: Extract from checkpoint `channel_values["current_plan"]`
  - `artifacts`: Extract from checkpoint `channel_values["artifacts"]`
  - `tool_calls`: Not available from checkpoint (transient stream data)

### [HIGH] BE-10 -- `_AgentSnapshot` missing `role`, `display_name`, `description` fields

- **Location**: `src/vaultspec_a2a/api/schemas/snapshots.py:77-84`
- **Origin**: P5-02
- **Description**: `_AgentSnapshot` has `agent_id`, `node_name`, `state`, `provider`, `model`. The wire `AgentSummary` has additional `role`, `display_name`, `description`. When snapshot `agents` is eventually populated (BE-09 fix), agents will lack human-readable metadata.
- **Impact**: Reconnection snapshot agents display as raw IDs without role or display name.
- **Fix effort**: Low -- add the 3 fields to `_AgentSnapshot`.

### [MED] BE-11 -- Thread state endpoint uses `checkpointer.aget()` (may not exist on all LangGraph versions)

- **Location**: `src/vaultspec_a2a/api/endpoints.py:505-508`
- **Origin**: P5-03
- **Description**: Calls `checkpointer.aget(config)` which returns a `Checkpoint` dict. The LangGraph-documented method is `aget_tuple()` which returns `CheckpointTuple`. If the LangGraph version's `AsyncSqliteSaver` lacks `aget()`, the broad `except Exception` silently catches the AttributeError and returns a partial snapshot.
- **Impact**: Silent degradation -- users get snapshots without messages if `aget()` isn't available.
- **Fix effort**: Low -- switch to `aget_tuple()` and extract `channel_values` from the tuple.

---

## 5. Team Status Endpoint

### [HIGH] BE-12 -- `get_team_status_endpoint` agent metadata empty on API aggregator

- **Location**: `src/vaultspec_a2a/api/endpoints.py:644-685`
- **Origin**: P8-03 (partially fixed by sync_worker_event for states, but not for metadata)
- **Description**: The endpoint calls `aggregator.get_node_summaries()` which returns metadata from `_node_metadata` (populated by `register_graph()`). Since the API aggregator never calls `register_graph()`, this returns `[]`. The endpoint then falls back to constructing agents from `get_agent_states()` keys, but these agents lack `role`, `display_name`, `description`.

  The agent_states tracking (via `sync_worker_event`) was added (P8-01 fix), so states are now accurate. But metadata (role, display_name, description) is still missing.

- **Impact**: `GET /team/status` returns agents with correct lifecycle states but empty `role`, `display_name`, `description`. Frontend team panel shows agent IDs without context.
- **Fix effort**: Medium -- worker should relay node metadata to API on graph compilation, or API should derive from team config.

---

## 6. Permission Flow

### [CRIT] BE-13 -- `sync_worker_event` permission_request handler uses wrong field names for PermissionOption

- **Location**: `src/vaultspec_a2a/core/aggregator.py:860-868`
- **Description**: Constructs `PermissionOption(id=opt.get("id", ""), label=opt.get("label", ""), kind=...)`. But `PermissionOption` model (events.py:103-108) has fields `option_id`, `name`, `kind`. Using `id` and `label` as kwargs will cause a **Pydantic validation error** at runtime because those are not valid field names.

  The worker-side `emit_permission_request()` (aggregator.py:779-788) correctly uses `option_id=...`, `name=...`. But the API-side `sync_worker_event()` reads from the serialized dict and uses the wrong keys.

  The serialized dict from the worker event has keys `option_id` and `name` (Pydantic serializes by field name). So `opt.get("id", "")` returns `""` and `opt.get("label", "")` returns `""`, resulting in `PermissionOption(id="", label="", kind=...)` which then crashes with Pydantic's unexpected keyword argument error.

- **Impact**: **CRITICAL** -- any relayed `permission_request` event will crash `sync_worker_event()` with a Pydantic ValidationError. The permission is NOT stored in the API aggregator's `_pending_permissions`. The `GET /team/status` endpoint's `pending_permissions` remains empty. The WS relay still works (events bypass the aggregator), so the frontend receives permission requests over WS, but REST queries for pending permissions fail.
- **Fix**: Change to:
  ```python
  PermissionOption(
      option_id=opt.get("option_id", ""),
      name=opt.get("name", ""),
      kind=_map_acp_option_kind(opt.get("option_id", "")),
  )
  ```

### [MED] BE-14 -- `resolve_permission()` clears from API aggregator that was never populated (pre-BE-13 fix)

- **Location**: `src/vaultspec_a2a/api/endpoints.py:771-812`, `src/vaultspec_a2a/core/aggregator.py:814-820`
- **Origin**: P8-05
- **Description**: `respond_to_permission_endpoint` calls `aggregator.resolve_permission(request_id)` which pops from `_pending_permissions`. Since BE-13 prevents permissions from being stored (Pydantic crash), `resolve_permission()` is a no-op (pop on empty dict). The permission response still works because the endpoint dispatches a resume to the worker independently.
- **Impact**: Low functional impact since the resume dispatch works. But the API aggregator's permission tracking is broken end-to-end.
- **Fix effort**: Fixing BE-13 fixes this automatically.

---

## 7. Internal Event Relay

### [INFO] BE-15 -- `sync_worker_event()` correctly handles `agent_status` and `permission_resolved`

- **Location**: `src/vaultspec_a2a/core/aggregator.py:839-886`, `src/vaultspec_a2a/api/internal.py:105,157`
- **Description**: Both WS and HTTP internal relay paths call `agg.sync_worker_event(thread_id, payload)`. The `agent_status` handler correctly parses `AgentLifecycleState` from the raw state string and updates `_agent_states`. The `permission_resolved` handler correctly pops from `_pending_permissions`. Sequence numbers are advanced via `_next_sequence()`.
- **Impact**: None -- correctly implemented (aside from BE-13 bug in `permission_request` handler).

### [MED] BE-16 -- No `plan_update` or `artifact_update` sync in `sync_worker_event()`

- **Location**: `src/vaultspec_a2a/core/aggregator.py:826-886`
- **Description**: `sync_worker_event()` only handles 3 event types: `agent_status`, `permission_request`, `permission_resolved`. If BE-01/BE-02 are fixed and the worker starts emitting `plan_update` and `artifact_update` events, the API aggregator will need corresponding handlers to track current plan and artifact state for REST queries.
- **Impact**: Future blocker -- no impact until BE-01/BE-02 are implemented.
- **Fix effort**: Low when needed -- add `elif event_type == "plan_update": ...` handler.

### [HIGH] BE-17 -- Mock-seeder writes to SQLite directly, bypasses event pipeline

- **Location**: `docker/run.py:98-131`
- **Origin**: P8-02
- **Description**: Mock-seeder uses `graph.astream()` (state snapshots, not events), writes checkpoints to shared SQLite, updates DB via CRUD. Does NOT create an `EventAggregator` or `WorkerBridge`. No events are POSTed to the API server.
- **Impact**: Mock threads are "silent" -- they appear in thread list via DB but produce no live streaming events. Frontend stream view is empty for mock threads.
- **Fix effort**: Medium -- requires switching to `astream_events()` and creating a `WorkerBridge` or direct HTTP client to POST events.

---

## 8. PlanEntry Field Name Mismatch

### [HIGH] BE-18 -- Backend PlanEntry uses `content`, MCP server reads `title`

- **Location**: `src/vaultspec_a2a/api/schemas/events.py:95-100` (model), `src/vaultspec_a2a/protocols/mcp/server.py:512-514` (consumer)
- **Origin**: P1-05, P4-02
- **Description**: Backend `PlanEntry` has fields `content`, `status`, `priority`. The MCP server's `get_thread_status` reads `entry.get("title", "untitled")`. Since there is no `title` field, all plan entries show as "untitled" in MCP output.
- **Impact**: MCP tool returns useless plan data.
- **Fix effort**: Trivial -- change `entry.get("title", "untitled")` to `entry.get("content", "untitled")`.

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 1     | sync_worker_event PermissionOption field name mismatch (runtime crash) |
| HIGH     | 7     | plan/artifact events never emitted, snapshot enrichment empty, team status metadata missing, mock-seeder bypass, MCP plan field wrong |
| MED      | 5     | emit_team_status uncalled, tool_kind missing on permissions, checkpointer.aget() fragile, node metadata not synced, future plan/artifact sync |
| INFO     | 3     | Correctly functioning: executor relay, event coverage, agent_status sync |
| LOW      | 1     | on_custom_event assumed to be thought chunks only |

**Total: 17 findings** (1 CRIT, 7 HIGH, 5 MED, 3 INFO, 1 LOW)

---

---

## 9. Worker and Supervisor Node Audit

### [CRIT] BE-19 -- Plan approval resume sends string `option_id`, supervisor expects dict with `approved` key

- **Location**: `src/vaultspec_a2a/api/endpoints.py:778-784` (dispatch), `src/vaultspec_a2a/worker/executor.py:336` (resume), `src/vaultspec_a2a/core/nodes/supervisor.py:255-263` (consumer)
- **Description**: The permission response endpoint dispatches `DispatchRequest(action="resume", option_id=body.option_id)`. The executor resumes with `Command(resume=req.option_id)` where `req.option_id` is a plain string (e.g. `"approve"` or `"reject"`).

  But the supervisor's `interrupt()` at line 255 returns the resume value, and line 263 does `resume_value.get("approved")`. Since `resume_value` is a **string**, not a dict, calling `.get()` on it raises `AttributeError: 'str' object has no attribute 'get'`.

  The test prep at `tests/preps/plan_approval.py:43` uses `Command(resume={"approved": True})` which is a dict -- confirming the supervisor expects a dict. But the real endpoint sends a bare string.

  **Worker permission flow is fine**: `_interrupt_permission_callback` at `worker.py:90` correctly handles string resume values.

- **Impact**: **Plan approval is completely broken** in the real permission response flow. Clicking "Approve Plan" in the frontend sends `option_id: "approve"` which arrives as a string, then `"approve".get("approved")` crashes. The graph raises an unhandled `AttributeError`, emitting an `INGEST_ERROR` event.
- **Fix**: Either:
  (a) Change the executor resume to wrap the option_id: `Command(resume={"approved": option_id == "approve", "option_id": option_id})`, or
  (b) Change the supervisor to handle both string and dict: `approved = resume_value.get("approved") if isinstance(resume_value, dict) else resume_value == "approve"`.
  Option (b) is more defensive.

### [HIGH] BE-20 -- Worker node does NOT emit events directly; relies entirely on LangGraph `astream_events`

- **Location**: `src/vaultspec_a2a/core/nodes/worker.py:140-216`
- **Description**: The worker node is a plain async function that calls `model.ainvoke(messages)` and returns `{"messages": [response]}`. It does NOT call any aggregator emit methods. All event emission comes from LangGraph's internal instrumentation:
  - `on_chat_model_stream` fires for each LLM token (from `BaseChatModel.ainvoke` internally)
  - `on_chain_start/end` fires for node boundary (LangGraph node entry/exit)
  - `on_tool_start/end` fires for LangGraph `ToolNode` execution

  This means: the worker node itself has no knowledge of or control over what events are emitted. It cannot emit custom events like plan updates or artifact updates.

- **Impact**: Plan and artifact events can only be produced via:
  1. Custom events emitted by the model itself (e.g. via StreamWriter in a custom runnable)
  2. State inspection by the aggregator after node completion
  3. A post-node hook that diffs state changes
  None of these exist today, which is why BE-01/BE-02 are open.
- **Fix effort**: Medium -- the cleanest approach is to add an `on_chain_end` handler in `process_langgraph_event()` that inspects the node output for `current_plan` changes and emits `PlanUpdateEvent` when the plan differs from the previous state.

### [MED] BE-21 -- Supervisor node uses `TAG_NOSTREAM` for routing model, suppressing token events

- **Location**: `src/vaultspec_a2a/core/nodes/supervisor.py:138`
- **Description**: `routing_model = model.with_config({"tags": [TAG_NOSTREAM]})` -- the supervisor's LLM call is tagged to suppress streaming events. This is intentional (the supervisor's routing response is a single word, not useful to stream). However, this means `on_chat_model_stream` events are NOT emitted for the supervisor node.
- **Impact**: Expected behavior -- the frontend doesn't need to see the supervisor's internal routing deliberation. But it means the supervisor never produces `MessageChunkEvent` events, only `AgentStatusEvent` (WORKING/IDLE) from `on_chain_start/end`.
- **Fix effort**: None needed.

### [MED] BE-22 -- `_interrupt_permission_callback` sets `interrupt()` value with ACP field names (`optionId`), but `_emit_interrupt_events` reads mixed field names

- **Location**: `src/vaultspec_a2a/core/nodes/worker.py:78-84` (interrupt payload), `src/vaultspec_a2a/core/aggregator.py:1196-1213` (consumer)
- **Description**: The worker's `_interrupt_permission_callback` passes ACP-format options to `interrupt()`:
  ```python
  {"type": "permission_request", "tool_name": ..., "options": options}
  ```
  where `options` is the raw ACP options list with `optionId` keys (camelCase).

  The aggregator's `_emit_interrupt_events` at line 1202-1209 reads these options and constructs the wire-protocol format:
  ```python
  "option_id": opt.get("optionId", opt.get("option_id", "allow_once"))
  "name": opt.get("label", opt.get("name", opt.get("optionId", "Allow")))
  ```
  This dual-key lookup (`optionId` OR `option_id`, `label` OR `name`) is a defensive pattern that handles both ACP format and wire format. Currently correct since the worker always passes ACP format.

- **Impact**: Working correctly today. The dual-key lookup is robust. Noting for documentation.
- **Fix effort**: None needed.

### [LOW] BE-23 -- `current_plan` state field exists but no node writes plan entries via LangGraph state updates

- **Location**: `src/vaultspec_a2a/core/state.py:113` (field), `src/vaultspec_a2a/core/nodes/supervisor.py` (no plan writes), `src/vaultspec_a2a/core/nodes/worker.py` (no plan writes)
- **Description**: `TeamState.current_plan` is `Annotated[list[dict[str, str]], _replace_plan]` with a full-replacement reducer. Neither the supervisor node nor any worker node returns `current_plan` in their state update dicts. The field is only populated if `graph_input` includes it (executor.py:228 sets `current_plan: []` on first ingest).
- **Impact**: `current_plan` is always `[]` in the checkpoint state. Even if BE-09 (snapshot enrichment) extracts it, there's nothing to extract. Plan data must come from the LLM's message content (parsed by the supervisor) or from custom events.
- **Fix effort**: Medium -- requires either the supervisor or a post-processing node to parse plan data from LLM messages and write to `current_plan`.

---

## 10. Race Conditions and Edge Cases

### [MED] BE-24 -- No lock on `sync_worker_event()` despite concurrent event relay

- **Location**: `src/vaultspec_a2a/core/aggregator.py:826-886`
- **Description**: `sync_worker_event()` is a synchronous method that mutates `_agent_states`, `_pending_permissions`, and calls `_next_sequence()`. It's called from async endpoint handlers (`receive_worker_event` and `worker_ws_endpoint`) which may handle concurrent requests. Since it's synchronous and Python has the GIL, individual attribute mutations are atomic. However, the `_pending_permissions[request_id] = PermissionRequestEvent(...)` construction is multi-step (build event, then assign), and a concurrent `permission_resolved` could try to pop a request_id that hasn't been stored yet.
- **Impact**: Low in practice -- FastAPI runs async handlers on a single event loop, so concurrent calls are interleaved at `await` points, not within synchronous code. The sync method body executes atomically between awaits.
- **Fix effort**: None needed unless the architecture changes to multi-worker or threaded.

### [LOW] BE-25 -- Worker aggregator subscriber queues are unused (no WS clients in worker process)

- **Location**: `src/vaultspec_a2a/worker/executor.py:85`, `src/vaultspec_a2a/core/aggregator.py:365-372`
- **Description**: The worker's `EventAggregator` maintains subscriber queues and subscription sets, but the worker process has no WebSocket clients. All events flow via the broadcast hook to the bridge. The subscriber infrastructure in the worker aggregator is dead weight.
- **Impact**: Negligible memory overhead. No functional impact.
- **Fix effort**: None needed -- the aggregator is a shared class used in both contexts.

---

---

## 11. LangGraph astream_events v2 Coverage Gaps

*Source: docs-researcher Task #16 analysis cross-referenced against aggregator code.*

### [HIGH] BE-26 -- Reasoning/thought tokens silently dropped from `on_chat_model_stream`

- **Location**: `src/vaultspec_a2a/core/aggregator.py:980-991`
- **Description**: The `on_chat_model_stream` handler extracts `chunk.content` only:
  ```python
  content = getattr(chunk, "content", "")
  if isinstance(content, str) and content:
      await self._buffer_message_chunk(...)
  ```
  Claude and other models emit reasoning/thinking tokens in two ways:
  1. `chunk.additional_kwargs.reasoning` (Anthropic extended thinking)
  2. `chunk.content` as a list of content blocks where `block["type"] == "thinking"` (structured content)

  Neither path is handled. When `content` is a list (structured content blocks), the `isinstance(content, str)` check fails silently and the entire chunk is dropped. When reasoning is in `additional_kwargs`, it's never read.

  The aggregator has `emit_thought_chunk()` (line 690-706) ready to emit `ThoughtChunkEvent`, but it's only called from the `on_custom_event` handler. The `on_chat_model_stream` handler never checks for reasoning content.

- **Impact**: All reasoning/thinking tokens from Claude extended thinking are silently dropped. The frontend `ThoughtBlock` component never receives data from the primary reasoning path. Mock tapes that produce reasoning tokens are invisible.
- **Fix**: In `on_chat_model_stream`, check for:
  1. `content` as list: iterate blocks, route `type=="thinking"` to `emit_thought_chunk()`, `type=="text"` to `_buffer_message_chunk()`
  2. `chunk.additional_kwargs.get("reasoning")`: route to `emit_thought_chunk()`

### [MED] BE-27 -- No `finish_reason` signal emitted; `on_chat_model_end` filtered out

- **Location**: `src/vaultspec_a2a/core/aggregator.py:130-146` (filter sets)
- **Description**: `on_chat_model_end` is not in `_PASSTHROUGH_EVENTS` or `_NODE_BOUNDARY_EVENTS`, so it's silently filtered. This event carries `response.response_metadata` which includes `finish_reason` (e.g. `"stop"`, `"end_turn"`, `"tool_use"`).

  The `MessageChunkEvent` schema has a `finish_reason: str | None` field (events.py), and `emit_message_chunk()` accepts it as a parameter (aggregator.py:676). But no code path ever populates it.

  The frontend stream-slice checks `finish_reason` to detect message completion (stream-slice.ts message_chunk handler). Without it, messages appear permanently "streaming" until the next event arrives.

- **Impact**: Frontend cannot detect when a message is complete. The streaming indicator stays active until the next agent_status (IDLE) event, which may be delayed.
- **Fix**: Add `on_chat_model_end` to `_PASSTHROUGH_EVENTS`. In the handler, extract `finish_reason` from `event_data["data"]["output"].response_metadata.get("finish_reason")` and emit a final `MessageChunkEvent` with `content=""` and `finish_reason` populated. Alternatively, emit `finish_reason` on the last `on_chat_model_stream` chunk when `chunk.response_metadata.get("finish_reason")` is present.

### [HIGH] BE-28 -- `PlanUpdateEvent` has no emission mechanism (reinforces BE-01/BE-20/BE-23)

- **Location**: `src/vaultspec_a2a/core/aggregator.py:943-1087` (process_langgraph_event), `src/vaultspec_a2a/core/nodes/supervisor.py:284` (supervisor return)
- **Origin**: G3, cross-refs BE-01, BE-20, BE-23
- **Description**: The supervisor node returns `{"next": route, "pipeline_phase": phase}` but never `current_plan`. The `on_chain_end` handler in `process_langgraph_event()` only emits `AgentStatusEvent(IDLE)` -- it does not inspect the node's output data for state changes.

  LangGraph `on_chain_end` events include `data.output` which contains the node's return dict. For the supervisor, this would contain `current_plan` if the supervisor wrote it. For workers, it would contain `artifacts` if the worker wrote them.

  **Missing mechanism**: There is no post-node state diff. The aggregator never compares pre/post node state to detect plan or artifact changes. Even if nodes wrote to `current_plan`, no event would be emitted.

- **Impact**: Combined with BE-01/BE-23, this means plan streaming is triple-blocked: (1) no node writes plan data, (2) no handler detects plan changes, (3) no event is emitted.
- **Fix**: The cleanest path is:
  1. Have the supervisor parse plan steps from the LLM routing response and return `current_plan: [...]`
  2. In the `on_chain_end` handler, when `node == "supervisor"`, inspect `data.output.get("current_plan")` and emit `PlanUpdateEvent` if non-empty

### [HIGH] BE-29 -- `ArtifactUpdateEvent` has no emission mechanism (reinforces BE-02/BE-20)

- **Location**: Same as BE-28
- **Origin**: G4, cross-refs BE-02, BE-20
- **Description**: Same structural gap as BE-28 but for artifacts. Worker nodes return `{"messages": [response]}` but never `artifacts`. Even if they did, the `on_chain_end` handler wouldn't inspect for artifact changes.
- **Impact**: Artifact streaming is completely dead. Files modified by ACP tools are invisible to the frontend until snapshot hydration.
- **Fix**: ACP tool calls that modify files should be detectable from `on_tool_end` events. The handler could inspect the tool output for file paths and emit `ArtifactUpdateEvent`. Alternatively, a post-node hook could diff `state["artifacts"]`.

### [LOW] BE-30 -- Tool call events lack input args, output content, and kind classification

- **Location**: `src/vaultspec_a2a/core/aggregator.py:993-1030`
- **Origin**: G5
- **Description**: `on_tool_start` emits `ToolCallStartEvent` with only `tool_call_id` and `title` (tool name). The `event_data["data"]["input"]` (tool arguments) is available but not included. `on_tool_end` emits `ToolCallUpdateEvent` with only `status=COMPLETED` -- the `event_data["data"]["output"]` (tool result) is not included.

  The `ToolCallStartEvent` schema has a `kind: ToolKind` field but it's always defaulted to `ToolKind.OTHER` because the aggregator doesn't classify tools by name.

- **Impact**: Frontend tool call cards show tool name and status but no arguments or results. All tools show the generic "other" icon. The inspect panel cannot display tool I/O details.
- **Fix effort**: Low-Medium. For kind: add a `_classify_tool_kind(tool_name: str) -> ToolKind` function that maps known ACP tool names to ToolKind enum values. For input/output: add optional fields to the event models and populate from event data.

### [INFO] BE-31 -- G6 (spurious ToolNode agent_status) does NOT apply to this codebase

- **Location**: `src/vaultspec_a2a/core/graph.py` (no ToolNode imports or usage)
- **Origin**: G6
- **Description**: The docs-researcher flagged spurious `agent_status` events from `{agent_id}_tools` ToolNode nodes. However, this codebase does NOT use LangGraph `ToolNode`. All tools execute inside the ACP subprocess (via `AcpChatModel`), not as separate LangGraph graph nodes. The `on_tool_start/end` events come from LangGraph's model instrumentation of the ACP process, not from ToolNode graph nodes.
- **Impact**: None -- not applicable.

---

## Summary (Updated)

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 2     | sync_worker_event PermissionOption field names (BE-13), plan approval resume type mismatch (BE-19) |
| HIGH     | 11    | plan/artifact events never emitted (triple-blocked), reasoning tokens dropped, snapshot enrichment empty, team status metadata missing, mock-seeder bypass, MCP plan field wrong, worker nodes don't emit events directly |
| MED      | 9     | emit_team_status uncalled, tool_kind missing on permissions, checkpointer.aget() fragile, node metadata not synced, no finish_reason signal, TAG_NOSTREAM supervisor, interrupt field name dual-lookup, sync_worker_event concurrency, future plan/artifact sync |
| INFO     | 4     | Correctly functioning: executor relay, event coverage, agent_status sync, G6 not applicable |
| LOW      | 4     | on_custom_event assumed thought chunks, current_plan always empty, worker subscriber queues unused, tool call data minimal |

**Total: 30 findings** (2 CRIT, 11 HIGH, 9 MED, 4 INFO, 4 LOW)

---

## Priority Fix Order

### Tier 1: Runtime crashes (immediate)
1. **BE-13** (CRIT) -- Fix PermissionOption field names in `sync_worker_event()`. One-line fix.
2. **BE-19** (CRIT) -- Fix plan approval resume type mismatch. Small fix in supervisor or executor.
3. **BE-18** (HIGH) -- Fix MCP server PlanEntry field name. Trivial one-line fix.

### Tier 2: Silent data loss (high UX impact)
4. **BE-26** (HIGH) -- Reasoning/thought token extraction from `on_chat_model_stream`. Medium effort -- handle list content blocks + `additional_kwargs.reasoning`.
5. **BE-27** (MED) -- Add `finish_reason` signal via `on_chat_model_end` handler. Low effort.
6. **BE-10** (HIGH) -- Add missing fields to `_AgentSnapshot`. Low effort.
7. **BE-09** (HIGH) -- Enrich snapshot with agents, plan, artifacts from checkpoint + aggregator state. Medium effort.

### Tier 3: Missing features (event pipeline completeness)
8. **BE-28/BE-01** (HIGH) -- Implement PlanUpdateEvent emission (supervisor writes plan + aggregator detects). Medium effort.
9. **BE-29/BE-02** (HIGH) -- Implement ArtifactUpdateEvent emission. Medium effort.
10. **BE-12** (HIGH) -- Sync node metadata to API aggregator for team status display names. Medium effort.
11. **BE-03** (MED) -- Wire `emit_team_status()` caller after agent state transitions.
12. **BE-30** (LOW) -- Enrich tool call events with input/output/kind. Low-Medium effort.

### Tier 4: Infrastructure
13. **BE-17** (HIGH) -- Convert mock-seeder to use event pipeline. Medium effort.

---

## 12. Error Handling Paths

### [MED] BE-32 -- Cancel race: `thread_terminal(completed)` overwrites DB `CANCELLED` status

- **Location**: `src/vaultspec_a2a/core/aggregator.py:1526-1536` (cancel break), `src/vaultspec_a2a/worker/executor.py:316-328` (ingest finally), `src/vaultspec_a2a/api/endpoints.py:962-965` (cancel endpoint DB update), `src/vaultspec_a2a/api/internal.py:44-73` (terminal status handler)
- **Description**: When a user cancels a thread:
  1. Cancel endpoint sets `ThreadStatus.CANCELLED` in DB (endpoints.py:964)
  2. Cancel dispatch reaches worker, sets cancel event
  3. Ingest loop sees cancel, emits `CANCELLED` agent_status, `break`s cleanly
  4. Since no exception was raised, `_outcome` remains `"completed"`
  5. `_emit_terminal_status()` sends `thread_terminal(status="completed")` to API
  6. Internal.py receives this and calls `update_thread_status(db, thread_id, "completed")`
  7. DB status is overwritten from `CANCELLED` back to `COMPLETED`

  The `ingest()` method does not propagate the cancel state back to the executor. There is no `"cancelled"` outcome string.

- **Impact**: After cancelling a thread, the DB briefly shows `CANCELLED` then reverts to `COMPLETED`. The frontend thread list flickers between states. The thread appears completed rather than cancelled.
- **Fix**: In `aggregator.ingest()`, after the cancel break, set `_outcome = "cancelled"`. In `executor._emit_terminal_status()`, add `"cancelled"` to the outcome filter (or keep it excluded since the DB is already set by the cancel endpoint). The simplest fix is to make `_emit_terminal_status` skip emission when the thread is already `CANCELLED` in DB, or have the aggregator return a `"cancelled"` outcome that the executor skips.

### [MED] BE-33 -- `emit_error()` error events lack `agent_id` context for frontend routing

- **Location**: `src/vaultspec_a2a/core/aggregator.py:1570-1606`
- **Description**: Error events emitted during ingest failures (`RECURSION_LIMIT_EXCEEDED`, `STEP_TIMEOUT`, `INGEST_ERROR`) include `agent_id` but always use the top-level `agent_id` parameter (typically `"vaultspec-supervisor"`). When the error occurs inside a specific worker node, the frontend displays the error attributed to the supervisor rather than the failing agent.
- **Impact**: Low -- error attribution is cosmetically wrong but the error message reaches the frontend. The `thread_id` routing is correct.
- **Fix effort**: Low -- the `on_chain_error` handler at lines 1298-1313 already attributes correctly to the node's agent. The `except BaseException` block could track the last active node from `on_chain_start` events and use that for error attribution.

### [LOW] BE-34 -- `INGEST_ERROR` message is generic; original exception message is not relayed

- **Location**: `src/vaultspec_a2a/core/aggregator.py:1600-1606`
- **Description**: When `ingest()` catches a non-recognized `BaseException`, it emits `ErrorEvent(code="INGEST_ERROR", message="Graph event stream failed unexpectedly")`. The actual exception message (e.g. `"AttributeError: 'str' object has no attribute 'get'"` from BE-19) is logged to server stderr via `logger.exception()` but NOT included in the `ErrorEvent` sent to the frontend.
- **Impact**: Frontend shows a generic error message. Users must check server logs to understand the failure cause.
- **Fix effort**: Low -- include `str(exc)[:500]` in the `message` field (truncated to prevent leaking internal stack traces). The `on_chain_error` handler already does this pattern at line 1300.

---

## 13. WebSocket Reconnection Edge Cases

### [HIGH] BE-35 -- `ConnectedEvent.active_threads` reflects subscribers, not running threads

- **Location**: `src/vaultspec_a2a/api/websocket.py:148`, `src/vaultspec_a2a/core/aggregator.py:401-410`
- **Description**: `ConnectedEvent` sends `active_threads=aggregator.get_active_thread_ids()`. But this method returns threads that have at least one WS *subscriber*, NOT threads that are actively running. When a client reconnects after a disconnect:
  1. Old client's subscriptions were cleaned up by `disconnect()` -> `remove_subscriber()`
  2. New client connects, no subscriptions exist yet
  3. `get_active_thread_ids()` returns `[]`
  4. Frontend receives empty `active_threads`, cannot auto-resubscribe to in-progress threads

  The frontend needs to know which threads are currently running to resubscribe. The correct data source would be `worker_active_threads` from the worker heartbeat (stored on `app.state.worker_active_threads` by internal.py:225).

- **Impact**: On reconnection, the frontend has no automatic way to discover which threads are in-progress. It must query `GET /threads` and filter by status, then manually resubscribe to each. The `ConnectedEvent` field is misleading.
- **Fix**: Change `active_threads` source to use worker heartbeat data (`app.state.worker_active_threads`) which tracks actually-running threads. Alternatively, add a `running_threads` field sourced from the worker heartbeat alongside the existing `active_threads`.

### [MED] BE-36 -- No `missed_events` replay on reconnection

- **Location**: `src/vaultspec_a2a/api/websocket.py:129-180` (connect), `src/vaultspec_a2a/api/endpoints.py:555-639` (thread state)
- **Description**: ADR-011 section 2.3 specifies that on reconnection, the client should receive a state snapshot to hydrate missed events. The current implementation sends `ConnectedEvent` with `active_threads` only. There is no automatic replay of events missed during the disconnect window.

  The client can manually call `GET /threads/{id}/state` to get a snapshot, but:
  1. The client must know which threads to query (see BE-35)
  2. There is no `last_sequence` tracking per-client to determine what was missed
  3. The snapshot may not include in-flight streaming data (only checkpoint state)

- **Impact**: After reconnection, the frontend stream view is stale until new events arrive. Messages sent during the disconnect window appear only after the next REST poll or new stream event.
- **Fix effort**: Medium-High. Options:
  (a) Add server-side event buffer per thread (ring buffer of last N events) and replay from client's `last_sequence` on resubscribe
  (b) Have the frontend snapshot-hydrate all subscribed threads on reconnect (simpler but requires BE-35 fix first)
  Option (b) is the pragmatic path -- the snapshot endpoint already exists (BE-09 enrichment was fixed).

---

## 14. Thread Lifecycle Edge Cases

### [MED] BE-37 -- No thread status transition validation (any status can be set from any state)

- **Location**: `src/vaultspec_a2a/database/crud.py:207-236` (update_thread_status)
- **Description**: `update_thread_status()` accepts any `ThreadStatus` value and writes it regardless of the current state. There are no guard rails preventing:
  - `COMPLETED` -> `RUNNING` (restarting a finished thread)
  - `CANCELLED` -> `COMPLETED` (the BE-32 race condition)
  - `FAILED` -> `SUBMITTED` (resurrecting a dead thread)

  The cancel endpoint has a manual guard (endpoints.py:936-945 checks terminal states) but the CRUD function itself is unprotected. Internal.py's `_handle_terminal_event` and the executor's terminal status emission both call `update_thread_status` without checking current state.

- **Impact**: Thread status can regress to earlier states due to race conditions (see BE-32). The frontend thread list shows incorrect status.
- **Fix**: Add a state machine validation in `update_thread_status()`:
  ```python
  _VALID_TRANSITIONS = {
      "submitted": {"created", "running", "cancelled"},
      "created": {"running", "cancelled"},
      "running": {"completed", "failed", "cancelled"},
      # Terminal states: no transitions allowed
  }
  ```
  Reject transitions from terminal states (`completed`, `failed`, `cancelled`) to any other state.

### [LOW] BE-38 -- Orphaned threads: no cleanup for threads stuck in `RUNNING` after worker crash

- **Location**: Worker process, no implementation
- **Description**: If the worker process crashes or is killed while threads are in `RUNNING` state, those threads remain `RUNNING` in the database indefinitely. There is no periodic reconciliation job that checks whether `RUNNING` threads still have an active ingest in the worker.

  The worker heartbeat (internal.py:216-230) reports `active_threads`, but no code compares this against DB `RUNNING` threads to detect orphans.

- **Impact**: After a worker crash-restart, previously-running threads show as perpetually "running" in the frontend. Users must manually cancel them.
- **Fix effort**: Medium -- add a startup reconciliation in the API server lifespan that queries `RUNNING` threads from DB, compares against worker heartbeat's `active_threads`, and marks orphans as `FAILED`.

---

## 15. Database CRUD Gaps

### [MED] BE-39 -- `list_threads` has no status filter parameter

- **Location**: `src/vaultspec_a2a/database/crud.py:178-204`, `src/vaultspec_a2a/api/endpoints.py:337-346`
- **Description**: `list_threads()` accepts only `offset` and `limit`. There is no `status` filter parameter. The list endpoint similarly has no query param for status filtering. The frontend thread list must fetch all threads and filter client-side.

  The MCP server's `list_threads` tool (mcp/server.py:259-274) also lacks status filtering.

- **Impact**: Frontend cannot efficiently show "running threads only" or "failed threads" views. All threads are fetched and filtered client-side, which scales poorly as thread count grows.
- **Fix effort**: Low -- add `status: ThreadStatus | None = None` parameter to `list_threads()` CRUD function and wire a `?status=running` query param in the endpoint.

### [LOW] BE-40 -- No `delete_thread` CRUD operation

- **Location**: `src/vaultspec_a2a/database/crud.py`
- **Description**: There is no function to delete a thread or its associated data (artifacts, permission logs, cost records). The only lifecycle operations are create, update status, and update metadata. Threads accumulate indefinitely.
- **Impact**: No thread cleanup mechanism. Database grows unbounded. Frontend has no "delete thread" capability.
- **Fix effort**: Low -- add `delete_thread()` with cascading deletes on related models. Wire a `DELETE /threads/{id}` endpoint with terminal-state-only guard.

### [LOW] BE-41 -- No thread title update endpoint

- **Location**: `src/vaultspec_a2a/api/endpoints.py`, `src/vaultspec_a2a/database/crud.py`
- **Description**: `ThreadModel` has a `title` field but there is no CRUD function or endpoint to update it after creation. The title can only be set at thread creation time. The frontend has no way to rename threads.
- **Impact**: Thread titles are immutable. Users cannot add descriptive names to threads after starting them.
- **Fix effort**: Trivial -- add `update_thread_title()` to CRUD and wire a `PATCH /threads/{id}` or `PUT /threads/{id}/title` endpoint.

---

## Summary (Final)

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRIT     | 2     | sync_worker_event PermissionOption field names (BE-13), plan approval resume type mismatch (BE-19) |
| HIGH     | 12    | plan/artifact events never emitted (triple-blocked), reasoning tokens dropped, snapshot enrichment empty, team status metadata missing, mock-seeder bypass, MCP plan field wrong, worker nodes don't emit events directly, ConnectedEvent active_threads wrong source |
| MED      | 13    | emit_team_status uncalled, tool_kind missing, checkpointer.aget() fragile, node metadata not synced, no finish_reason signal, TAG_NOSTREAM supervisor, interrupt field name dual-lookup, sync_worker_event concurrency, future plan/artifact sync, cancel race, error agent_id context, no missed event replay, no status filter, no status transition validation |
| INFO     | 4     | Correctly functioning: executor relay, event coverage, agent_status sync, G6 not applicable |
| LOW      | 7     | on_custom_event assumed thought chunks, current_plan always empty, worker subscriber queues unused, tool call data minimal, generic INGEST_ERROR message, orphaned running threads, no delete/title update |

**Total: 38 findings** (2 CRIT, 12 HIGH, 13 MED, 4 INFO, 7 LOW)
