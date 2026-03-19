# Backend Edge Surface Audit

**Date:** 2026-03-03
**Status:** Active (Continuous Audit)

## 1. WebSocket Protocol (Real-Time Edge)

**Connection:** `ws://<host>/ws`

- **Lifecycle:** On connect, the server immediately sends a `connected` event. The server sends a `heartbeat` every 30 seconds. The client must respond with a `ping` command periodically to prevent the connection from being dropped (90s timeout).

### A. Client-to-Server Commands (`ClientMessage`)

All messages sent from the UI to the backend must be JSON objects with a top-level `type` discriminator.

| Command Type          | Payload Fields                                                                            | Description / Behavior                                                                                                                   |
| :-------------------- | :---------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------- |
| `subscribe`           | `thread_ids: string[]` (max 50)                                                           | Subscribes the WS connection to events for specific threads.                                                                             |
| `unsubscribe`         | `thread_ids: string[]` (max 50)                                                           | Removes subscription for specific threads.                                                                                               |
| `send_message`        | `thread_id: string`<br>`content: string` (max 64KB)<br>`agent_id: string \| null`         | Streams a user message into a thread directly via WS.                                                                                    |
| `agent_control`       | `thread_id: string`<br>`agent_id: string`<br>`action: "pause" \| "resume" \| "terminate"` | Interrupts or controls the LangGraph execution flow.                                                                                     |
| `ping`                | _(none)_                                                                                  | Keepalive ping. Server replies with a `heartbeat` event immediately.                                                                     |
| `permission_response` | `request_id: string`<br>`option_id: string`                                               | **REJECTED OVER WS.** Submitting permissions over WS returns a `PERMISSION_RESPONSE_WS_FORBIDDEN` error. You must use the REST endpoint. |

### B. Server-to-Client Events (`ServerEvent`)

All messages sent from the backend to the UI have a `type` discriminator. Thread-scoped events also carry a `sequence` integer. The frontend must track the `sequence` to drop stale messages during reconnection.

**Connection-Scoped Events:**

| Event Type | Payload Fields |
| :--- | :--- |
| `connected` | `client_id: string`<br>`server_version: string`<br>`active_threads: string[]` |
| `heartbeat` | `timestamp: string (ISO)`<br>`server_uptime_seconds: float` |

**Thread-Scoped Events (Streaming LangGraph Data):**
_(All include `thread_id: string` and `sequence: int`)_

| Event Type | Payload Fields | Description |
| :--- | :--- | :--- |
| `agent_status` | `agent_id: string \| null`<br>`node_name: string`<br>`state: "submitted" \| "idle" \| "working" \| "input_required" \| "auth_required" \| "completed" \| "failed" \| "cancelled"`<br>`detail: string \| null` | Top-level state transitions mapped from LangGraph nodes. |
| `message_chunk` | `message_id: string`<br>`content: string`<br>`finish_reason: string \| null` | Raw LLM output streaming. |
| `thought_chunk` | `message_id: string`<br>`content: string` | Internal reasoning/CoT streaming. |
| `tool_call_start` | `tool_call_id: string`<br>`title: string`<br>`kind: "read" \| "edit" \| "execute" \| "search" \| "think" \| ...`<br>`status: "pending" \| "in_progress" \| "completed" \| "failed"`<br>`locations: { path, line? }[]`<br>`content: ToolCallContent[]` | Initial emission of a LangChain tool call. `content` can be `text`, `diff`, or `terminal`. |
| `tool_call_update`| _(Partial fields from above)_ | Debounced (100ms) merge updates for streaming tool arguments/output. |
| `permission_request`| `request_id: string`<br>`description: string`<br>`options: { option_id, name, kind }[]`<br>`tool_call: string \| null` | Native LangGraph `interrupt`. UI must render options and POST response to REST API. Option kinds: `allow_once`, `allow_always`, `reject_once`, `reject_always`. |
| `artifact_update` | `artifact_id: string`<br>`filename: string`<br>`content: string`<br>`append: boolean`<br>`last_chunk: boolean` | File generation/modification streaming. |
| `plan_update` | `entries: { content, status, priority }[]` | Full array replacement of the agent's current plan (debounced 250ms). |
| `team_status` | `active_thread_ids: string[]`<br>`agents: { agent_id, node_name, state, role, display_name... }[]` | Team topology updates. |
| `error` | `code: string`<br>`message: string`<br>`recoverable: boolean` | Exceptions caught during Graph execution. |

---

## 2. REST API Protocol (State & Idempotency Edge)

The backend enforces REST for guaranteed delivery (like permissions) and state recovery (Snapshots).

| Method   | Endpoint                    | Payload / Request                                     | Response Shape                                    | Purpose                                                                                                                                                                                        |
| :------- | :-------------------------- | :---------------------------------------------------- | :------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **POST** | `/threads`                  | `title`, `initial_message`, `team_preset`, `metadata` | `{ thread_id, status, nickname }`                 | Dispatches initial `ingest` to worker graph.                                                                                                                                                   |
| **GET**  | `/threads`                  | `?offset=0&limit=50`                                  | `{ threads: [ThreadSummary], total }`             | Paginated list of all threads.                                                                                                                                                                 |
| **GET**  | `/threads/{id}/metadata`    | _(none)_                                              | `ThreadMetadata`                                  | Full provenance context (source branch, feature tag).                                                                                                                                          |
| **GET**  | `/threads/{id}/state`       | _(none)_                                              | `ThreadStateSnapshot`                             | **CRITICAL FOR RECONNECTION**. Returns `last_sequence`, materialized `messages`, `tool_calls`, `artifacts`, `plan`, and `pending_permissions` directly from the LangGraph SQLite checkpointer. |
| **POST** | `/threads/{id}/messages`    | `content`, `agent_id`                                 | HTTP 202 Accepted                                 | Dispatches user message to the worker.                                                                                                                                                         |
| **POST** | `/threads/{id}/cancel`      | _(none)_                                              | `{ thread_id, status, cancelled: true }`          | Dispatches a hard cancellation to the graph worker.                                                                                                                                            |
| **GET**  | `/team/status`              | _(none)_                                              | `{ agents, active_threads, pending_permissions }` | Lightweight global state query.                                                                                                                                                                |
| **GET**  | `/teams`                    | _(none)_                                              | `{ presets: [TeamPresetSummary] }`                | Returns available multi-agent topologies (e.g., from TOML files).                                                                                                                              |
| **POST** | `/permissions/{id}/respond` | `option_id`, `kind`                                   | `{ request_id, accepted: bool }`                  | Submits a user decision. Dispatches `Command(resume=option_id)` to unblock the interrupted LangGraph node.                                                                                     |

## 3. Gaps & Missing Information (Cycle 1 Audit)

Based on a continuous audit of the backend schema (`src/vaultspec_a2a/api/schemas/` vs `src/vaultspec_a2a/core/state.py` and `docs/adrs/019-teamstate-enrichment-sdd-blackboard.md`), the following critical context and metadata elements are currently **missing** from the frontend edge surface:

### A. SDD Blackboard Awareness Not Exported [CRITICAL]

ADR-019 introduced four mandatory fields to the backend's internal `TeamState` to support the SDD (Software Design Document) blackboard pattern:

1. `active_feature` (string): The current feature tag.
2. `pipeline_phase` (string): The current phase (`"research"`, `"adr"`, `"plan"`, `"exec"`, etc.).
3. `vault_index` (dict[str, list[str]]): A mapping of document types to their `.vault/` paths (binding documents).
4. `validation_errors` (list[str]): Accumulated quality gate errors.

**The Gap:** None of these fields are exported in the `ThreadStateSnapshot` REST payload (`src/vaultspec_a2a/api/schemas/snapshots.py`). Furthermore, there is no WebSocket `ServerEvent` defined to push updates to the UI when the `vault_index` mutates or the `pipeline_phase` shifts.

### B. Mounted Context Visibility [HIGH]

ADR-020 introduced a `mounted_context` field to `TeamState` to hold the actual content of the `.vault/` documents currently being read by the active agent.
**The Gap:** This field is transient and entirely hidden from the UI. The frontend has no way to visualize _what_ specific context or binding documents the agent is currently "looking at" during a specific step.

### C. Context History Metadata (`ThreadMetadata`) [MEDIUM]

The `ThreadMetadata` (from ADR-014) contains `context_refs` which auto-discovers `.vault/` documents. This is accessible via `GET /threads/{id}/metadata`, but this endpoint returns static provenance data from thread creation. It does not reflect the living, breathing `vault_index` that agents mutate as they generate new plans and ADRs.

### D. Required Next Steps for the Backend Edge

To achieve a "data-rich UI" that exposes the whole context:

1. `ThreadStateSnapshot` must be expanded to include `pipeline_phase`, `active_feature`, `vault_index`, and `validation_errors`.
2. A new WebSocket event (e.g., `BlackboardUpdateEvent` or an expanded `TeamStatusEvent`) must be implemented to broadcast mutations to the `vault_index` and `pipeline_phase` in real-time.
3. The UI needs a mechanism (either a new REST endpoint or included in the snapshot) to fetch the raw contents of the paths listed in the `vault_index` so they can be visualized in an "Active Context" or "Blackboard" panel.

---

## 4. Gaps & Missing Information (Cycle 2 Audit)

The second cycle of auditing focused on the worker definitions (`src/vaultspec_a2a/core/team_config.py`, ADR-012, ADR-013), backend database models (`src/vaultspec_a2a/database/models.py`), and telemetry systems (`ADR-010`). The following additional gaps were found:

### A. Telemetry and Trace IDs Not Exported [CRITICAL]

ADR-010 mandates OpenTelemetry (OTel) integration. The backend wraps executions in Jaeger tracing contexts.
**The Gap:** The UI receives `ServerEvents` but does not receive the associated OpenTelemetry `trace_id` or `span_id`. This means the frontend cannot generate deep links into Jaeger or LangSmith to allow developers to inspect the "why" behind an agent's reasoning.

### B. Full Team Topology & Persona Blindness [HIGH]

The REST endpoint `GET /teams` returns a `TeamPresetSummary` which contains only `id`, `display_name`, `description`, `topology`, and `worker_count`.
**The Gap:** The UI has no way to fetch the actual `AgentConfig` (ADR-012) definitions for the workers. The frontend cannot know an agent's `persona.system_prompt`, its `capabilities` (e.g., `filesystem_read`, `terminal`), or its `permissions.require_approval_for` rules. The frontend is blind to the structural constraints of the team it is observing.

### C. Cost and Token Accounting Visibility [MEDIUM]

The backend tracks `CostTrackingModel` in SQLite, associating token usage (`input_tokens`, `output_tokens`) and `estimated_cost` with each thread and agent (see `src/vaultspec_a2a/database/crud.py`).
**The Gap:** This cost tracking data is never exported. Neither `ThreadSummary` nor `ThreadStateSnapshot` includes the accumulated token usage or cost. A data-rich UI needs this to show users the financial impact of their sessions.

### D. Required Next Steps for the Backend Edge (Cycle 2)

1. Add `trace_id` and `span_id` to the `EventEnvelope` base schema for WebSocket events.
2. Expand `GET /teams/{preset_id}` to return the full `TeamConfig` and all associated `AgentConfig` TOML definitions, allowing the UI to render persona and capability cards.
3. Expose cost and token metrics via a REST endpoint (e.g., `GET /threads/{id}/cost`) or embed them into the `ThreadSummary` and `ThreadStateSnapshot` payloads.

---

## 5. Gaps & Missing Information (Cycle 3 Audit)

The third cycle audited the LangGraph checkpoint persistence, the worker IPC dispatch payload (`src/vaultspec_a2a/worker/executor.py`), and Artifact handling. The following critical bugs and architectural gaps were discovered:

### A. Broken Thread Reconnection State (Missing Rehydration) [CRITICAL]

The `GET /threads/{id}/state` endpoint is the sole mechanism for the UI to recover state on WebSocket reconnect or page refresh.
**The Gap:** While the `ThreadStateSnapshot` schema defines fields for `tool_calls`, `artifacts`, `plan`, `pending_permissions`, and `agents`, the backend function `_enrich_snapshot_from_state` in `src/vaultspec_a2a/api/endpoints.py` **only populates the `messages` list**. All other fields are returned as empty lists. The UI permanently loses the entire team status, current plan, active tool calls, and artifact lists upon reconnection.

### B. Worker Dispatch Ignores Blackboard Fields (ADR-019 Broken) [CRITICAL]

The gateway sends a `DispatchRequest` to the worker process containing `active_feature`, `pipeline_phase`, and `vault_index`.
**The Bug:** In `src/vaultspec_a2a/worker/executor.py`, the `_handle_ingest()` method completely ignores these fields when constructing the initial `graph_input` for a new thread. The checkpointer starts with an empty state for the 4 mandatory ADR-019 blackboard fields, fundamentally breaking the SDD blackboard capabilities for the entire lifecycle of the thread.

### C. Missing Artifact Retrieval Endpoints [HIGH]

The backend tracks generated files via `ArtifactModel` in the SQLite database and streams `ArtifactUpdateEvent` over the WebSocket.
**The Gap:** There is no REST API endpoint to retrieve an artifact's content. A data-rich UI needs a `GET /artifacts/{id}` or `GET /threads/{id}/artifacts` endpoint to download or visualize the files generated by the agents, especially since the WebSocket stream might be missed or disconnected.

### D. Required Next Steps for the Backend Edge (Cycle 3)

1. Rewrite `_enrich_snapshot_from_state()` to map checkpointer state into `tool_calls`, `artifacts`, `plan`, `agents`, and `pending_permissions` so the UI can fully recover.
2. Fix `Executor._handle_ingest()` to correctly inject `active_feature`, `pipeline_phase`, `vault_index`, and `validation_errors` from the `DispatchRequest` into the `graph_input`.
3. Implement `GET /threads/{thread_id}/artifacts` and `GET /artifacts/{artifact_id}` in `src/vaultspec_a2a/api/endpoints.py` for direct artifact retrieval.

---

## 6. Gaps & Missing Information (Cycle 4 Audit)

Cycle 4 audited error propagation (`src/vaultspec_a2a/core/aggregator.py`), the Supervisor node logic (`src/vaultspec_a2a/core/nodes/supervisor.py`), and tool bindings.

### A. Tool Failure Blindness [HIGH]

When a LangChain tool fails (`on_tool_error` in `process_langgraph_event`), the backend catches the error string and logs it. However, it only emits a `ToolCallUpdateEvent` with `status=FAILED` and drops the error text entirely.
**The Gap:** The UI knows a tool failed but cannot show the user _why_ (e.g., "File not found", "Permission denied"). The `ToolCallUpdateEvent` schema lacks an `error` field.

### B. Supervisor Quality Gate / Validation Error Blindness [MEDIUM]

In `supervisor.py`, if the SDD `validation_errors` array is populated, the supervisor blocks the `FINISH` route, logs a warning, appends a `routing_error` to the `TeamState`, and reroutes the work back to an agent.
**The Gap:** This internal quality gate rejection is completely silent on the frontend. The `routing_error` is never emitted over WebSocket, and the user simply sees the active agent switch without any context on why the artifact was rejected.

### C. Undisclosed Agent Tools [MEDIUM]

The backend dynamically compiles LangChain tools based on `AgentCapabilitiesConfig` (e.g., `fs.writeTextFile`, `terminal`), but these exact available tools are never exported.
**The Gap:** The UI's `AgentSummary` has no field listing the agent's available tools. The UI cannot render an "Agent Toolbox" letting the user know what the agent is technically capable of executing.

### D. Required Next Steps for the Backend Edge (Cycle 4)

1. Add an optional `error: str | None = None` field to `ToolCallUpdateEvent` (and `ToolCallSnapshot`) so tool failures can be displayed in the UI.
2. Emit an `ErrorEvent` (or a new `SupervisorRoutingEvent`) when the supervisor blocks a completion due to `validation_errors` or `routing_error`.
3. Add a `tools: list[str]` field to `AgentSummary` (populated during graph compilation) so the frontend knows what capabilities an agent has at its disposal.

---

## 7. Gaps & Missing Information (Cycle 5 Audit)

Cycle 5 audited the `PlanUpdateEvent` logic within the `EventAggregator`, the worker heartbeat IPC relay, and telemetry payload shaping.

### A. Dead Code Path: Plan Updates are Never Emitted [CRITICAL]

The backend defines a `PlanUpdateEvent` and `src/vaultspec_a2a/core/aggregator.py` contains debouncing logic (`_broadcast_debounced_plan_update`) and placeholders for `_plan_update_pending`.
**The Bug:** There is absolutely no method in `EventAggregator` (like `emit_plan_update`) to actually construct or trigger a `PlanUpdateEvent`, nor is there any hook in `process_langgraph_event` that listens for LangGraph state changes to the `current_plan`. The planner's output goes into the SQLite checkpointer but is never streamed to the UI over WebSocket.

### B. Worker Liveness Opacity [HIGH]

Following ADR-019, the worker process sends HTTP POST heartbeats to the gateway (`/internal/heartbeat`), which tracks the timestamp in `app.state.worker_last_heartbeat_ts`.
**The Gap:** The frontend has no visibility into this. The `TeamStatusResponse` and WebSocket events do not report if the backend worker process is actually alive or dead. If the worker crashes, the frontend will happily accept `SEND_MESSAGE` commands (which 202 Accept and drop into the void) because the gateway API is up, even though the execution engine is dead.

### C. Trace Context Injection Format Mismatch [MEDIUM]

In `src/vaultspec_a2a/api/websocket.py`, the `_writer_loop` injects the OTel trace context into the outgoing WebSocket payload by adding a `_trace` dictionary (containing `traceparent`).
**The Gap:** This violates the strongly-typed `EventEnvelope` defined in `events.py`. The frontend's Pydantic/Zod schemas do not expect a loose `_trace` key at the root of the JSON payload. `_trace` should be formalized as a field on `EventEnvelope` or the metadata structure.

### D. Required Next Steps for the Backend Edge (Cycle 5)

1. Implement `emit_plan_update` in the `EventAggregator` and wire it into the `process_langgraph_event` or a custom state listener to actually broadcast when the `current_plan` mutates.
2. Add `worker_alive: bool` and `worker_active_threads: list[str]` to the `TeamStatusResponse` and potentially the `HeartbeatEvent` so the frontend can lock the UI if the execution engine goes offline.
3. Formalize the OpenTelemetry `_trace` dictionary as an official field on the `EventEnvelope` base model in `schemas/base.py` to ensure schema compliance on the frontend.

---

## 8. Gaps & Missing Information (Cycle 6 Audit)

Cycle 6 focused on the fundamental nature of "Planning" within the system by auditing `src/vaultspec_a2a/core/state.py` against ADR-019 (SDD Blackboard), ADR-023 (Phase Gates), and ADR-024 (Plan Approval).

### A. Architectural Mismatch: Structured Plans vs. SDD Markdown [CRITICAL]

The frontend UI and the `PlanUpdateEvent` schema (`src/vaultspec_a2a/api/schemas/events.py`) expect a plan to be a structured array of discrete steps (`entries: { content, status, priority }[]`). The backend's `TeamState` still contains a `current_plan: list[dict]` field to support this.
**The Mismatch:** Following ADR-019 and ADR-024, the backend shifted entirely to an SDD (Software Design Document) blackboard pattern. Planners do not generate JSON arrays; they write markdown files (`docs/{feature}/plan.md`) which are tracked in the `vault_index["plan"]`. The `current_plan` array in `TeamState` is now _completely dead legacy code_. It is never populated by any node. The frontend is building UI components to render an array of steps that the backend will never send.

### B. Missing `plan_approved` State Export [HIGH]

ADR-024 introduced a `plan_approved` boolean field to `TeamState`. If `vault_index["plan"]` exists but `plan_approved` is false, the supervisor blocks execution and emits a `plan_approval_request` LangGraph interrupt.
**The Gap:** This `plan_approved` boolean is not exported in the `ThreadStateSnapshot`. The frontend UI has no way to display whether the current markdown plan has been approved by the user or if it is still pending review, severely hindering the rendering of the active session's progress.

### C. Required Next Steps for the Backend Edge (Cycle 6)

1. **Decision Required:** The project must decide whether to revert to structured JSON plans (and enforce that on the LLM workers) or to deprecate `PlanUpdateEvent` and `current_plan` entirely in favor of treating the plan purely as an SDD document artifact (`ArtifactUpdateEvent` + `BlackboardUpdateEvent`).
2. Add `plan_approved: bool` to the `ThreadStateSnapshot` payload so the UI can reflect the approval gate status accurately.

---

## 9. Gaps & Missing Information (Cycle 7 Audit)

Cycle 7 audited the persistent task queue implementation (`src/vaultspec_a2a/core/task_queue.py`), ADR-021, and its impact on the internal state (`src/vaultspec_a2a/core/state.py`) versus the frontend schemas (`src/vaultspec_a2a/api/schemas/`).

### A. Active Task Blindness (`current_task_id`) [HIGH]

ADR-021 introduced a `current_task_id` pointer into the `TeamState` (`src/vaultspec_a2a/core/state.py`). This string tracks exactly which sub-task from the `plan.md` or `queue.md` the worker agent is actively executing.
**The Gap:** `current_task_id` is entirely omitted from the `ThreadStateSnapshot` in `src/vaultspec_a2a/api/schemas/snapshots.py`. The UI has no idea which task is currently assigned to the active worker. Even if the UI fetches the raw `queue.md` document, it cannot highlight or pin the active task row for the user.

### B. Pipeline Phase Transitions are Silent [CRITICAL]

The worker's execution environment constantly recalculates the `pipeline_phase` (e.g., `research`, `adr`, `plan`, `exec`) based on the documents populated in the `vault_index` (as defined in ADR-026 Pipeline Phase Population).
**The Gap:** There is absolutely no WebSocket event emitted when the `pipeline_phase` or `current_task_id` changes. The only way the frontend _might_ find out is if it polls the REST `/state` endpoint (if those fields were even exported, which they aren't per Cycle 1/7). The system lacks a `BlackboardUpdateEvent` or `PhaseTransitionEvent` to push these vital state shifts to the client.

### C. Required Next Steps for the Backend Edge (Cycle 7)

1. Export `current_task_id` in the `ThreadStateSnapshot` payload.
2. Implement a `PhaseTransitionEvent` or `TeamStateUpdateEvent` in `src/vaultspec_a2a/api/schemas/events.py` that broadcasts changes to `pipeline_phase`, `current_task_id`, and `vault_index` over the WebSocket stream in real-time.

---

## 10. Gaps & Missing Information (Cycle 8 Audit)

Cycle 8 focused on the external protocol translation layer (`src/vaultspec_a2a/protocols/mcp/server.py` and `src/vaultspec_a2a/protocols/a2a/`) and the overall context mapping across boundaries.

### A. A2A Protocol Abandonment (Dead Code) [COSMETIC]

The `src/vaultspec_a2a/protocols/a2a/` directory exists but contains only an empty `__init__.py` with a docstring calling it a "stub". ADR-006 ("Protocol Ecosystem Bridge") explicitly abandoned A2A in favor of LangGraph + MCP.
**The Gap:** The directory and related terminology in older ADRs creates confusion, but operationally, the codebase is entirely LangGraph/MCP driven. This is a cosmetic hygiene issue.

### B. MCP Server Skews Thread Metadata (ADR-014 Violation) [MEDIUM]

The `start_thread` MCP tool (`src/vaultspec_a2a/protocols/mcp/server.py`) accepts `initial_message`, `team_preset`, `autonomous`, and `workspace_root`. It passes these to the `POST /api/threads` REST endpoint.
**The Gap:** It completely omits the `metadata: ThreadMetadata` payload structure (ADR-014) from the POST request. This means threads created via the MCP server (e.g., from Cursor or Windsurf) will never have `feature_tag`, `context_refs`, or provenance tracking attached to them. This creates a two-tier system where the UI gateway can launch fully contextualized threads, but external IDEs cannot.

### C. MCP Output Missing Cost/Token Telemetry [LOW]

The `get_thread_status` MCP tool returns a human-readable text block summarizing the thread's status, messages, agents, and plan.
**The Gap:** It does not expose the token usage or cost tracking. If an IDE user runs a long autonomous task, they have no visibility into the cost incurred until they open the UI gateway.

### D. Required Next Steps for the Backend Edge (Cycle 8)

1. Add `feature_tag: str | None` and `context_refs: list[str] | None` to the `start_thread` MCP tool parameters and map them into the `metadata` object of the `POST /api/threads` request.
2. Consider removing the `src/vaultspec_a2a/protocols/a2a/` directory if no further integration is planned to reduce cognitive load.

---

## 11. Gaps & Missing Information (Cycle 9 Audit)

Cycle 9 audited the creation and streaming of `Artifacts` between the `src/vaultspec_a2a/database/crud.py`, the `src/vaultspec_a2a/core/aggregator.py`, and the `src/vaultspec_a2a/core/state.py`.

### A. Dead Code Path: Artifact Updates are Never Emitted [CRITICAL]

The backend defines an `ArtifactUpdateEvent` in `src/vaultspec_a2a/api/schemas/events.py` intended for streaming file generation to the UI. The `TeamState` also defines an `artifacts` array.
**The Bug:** I audited `src/vaultspec_a2a/core/aggregator.py` and `src/vaultspec_a2a/core/nodes/worker.py`. There is **no code** anywhere in the execution engine that actually emits an `ArtifactUpdateEvent`. When an agent writes a file (via a tool), the tool might create a database record, but it is never streamed to the UI over the WebSocket. The frontend will never see files being generated in real-time.

### B. State `artifacts` Array is Orphaned [HIGH]

The `TeamState` defines `artifacts: Annotated[list[dict[str, str]], _append_artifacts]`.
**The Gap:** None of the LangGraph nodes (`supervisor.py`, `worker.py`, `mount.py`) ever write to this array. It is initialized as empty during `_handle_ingest` and remains empty forever. Since it is empty in the checkpointer, even if `_enrich_snapshot_from_state` (Cycle 3 gap) is fixed to export the array, it will still yield nothing.

### C. Required Next Steps for the Backend Edge (Cycle 9)

1. Implement `emit_artifact_update` in the `EventAggregator` and wire it into the specific tools (e.g., `fs.writeTextFile`) or a state listener so the UI receives real-time file generation streams.
2. Ensure that when an artifact is created in the database (`create_artifact` in `src/vaultspec_a2a/database/crud.py`), a corresponding entry is appended to the `TeamState["artifacts"]` array so it persists in the LangGraph checkpointer.

---

## 12. Gaps & Missing Information (Cycle 10 Audit)

Cycle 10 audited exception handling across the worker process (`src/vaultspec_a2a/worker/executor.py`), custom exceptions (`src/vaultspec_a2a/core/exceptions.py`), and the worker graph nodes (`src/vaultspec_a2a/core/nodes/worker.py`).

### A. WorkerExecutionError is Swallowed by Executor [CRITICAL]

In `src/vaultspec_a2a/core/nodes/worker.py`, if the LLM invocation fails (e.g., context window overflow, provider outage), the code raises a custom `WorkerExecutionError`.
**The Bug:** In `src/vaultspec_a2a/worker/executor.py`, both `_handle_ingest()` and `_handle_resume()` wrap the LangGraph invocation in a generic `except Exception:` block. This block logs the exception to the terminal but **does not emit an `ErrorEvent`** over the IPC bridge or WebSocket. The orchestrator silently dies, the thread state never updates to `failed`, and the frontend UI remains permanently stuck in a "working" state, waiting for a response that will never come.

### B. Recovery Action Blindness [MEDIUM]

`src/vaultspec_a2a/core/exceptions.py` defines a sophisticated taxonomy of errors with `severity` and `recovery_action` (e.g., `RETRY_WITH_BACKOFF`, `ESCALATE_TO_USER`).
**The Gap:** The `ErrorEvent` schema (`src/vaultspec_a2a/api/schemas/events.py`) only has a boolean `recoverable: bool` field. It completely strips away the specific `recovery_action` hint. The frontend UI cannot display intelligent recovery options (like a "Retry" button vs. a "Reassign Agent" button) because the nuanced error classification is lost at the edge.

### C. Required Next Steps for the Backend Edge (Cycle 10)

1. Fix `src/vaultspec_a2a/worker/executor.py`'s `except Exception:` blocks to explicitly call `self._aggregator.emit_error()` before returning, ensuring catastrophic failures are pushed to the UI.
2. Update the `ErrorEvent` schema to include `recovery_action: str | None` and `severity: str | None`, mapping them from the `VaultspecError` base class, so the UI can render actionable error states.

---

## 13. Gaps & Missing Information (Cycle 11 Audit)

Cycle 11 audited the human-in-the-loop interruption mechanisms, specifically focusing on the implementation of ADR-024 (Plan Approval Interrupt).

### A. Supervisor Completely Skips Plan Approval [CRITICAL]

ADR-024 mandates that if an SDD plan exists but has not been approved, the `supervisor.py` node must block execution and fire a LangGraph `interrupt({"type": "plan_approval_request", ...})`.
**The Bug:** I audited `src/vaultspec_a2a/core/nodes/supervisor.py`. The required `interrupt()` call is entirely missing. The supervisor node does not check the `plan_approved` state field before routing to an executor. The human-in-the-loop plan approval gate is completely non-existent in the actual runtime.

### B. Aggregator Silently Swallows Plan Approvals [CRITICAL]

Even if the supervisor node _did_ trigger the interrupt, the UI would still never see it. In `src/vaultspec_a2a/core/aggregator.py`, the `_emit_interrupt_events()` function inspects the LangGraph suspended task.
**The Bug:** The code explicitly filters out any interrupt that is not a tool permission request: `if payload.get("type") != "permission_request": continue`. If a `plan_approval_request` were emitted by the graph, the aggregator would silently drop it. The backend thread would enter a suspended state forever, and the UI would be stuck waiting, completely unaware that a plan approval modal should be rendered.

### C. Required Next Steps for the Backend Edge (Cycle 11)

1. Implement the ADR-024 logic inside `src/vaultspec_a2a/core/nodes/supervisor.py`: import `interrupt` and trigger it when routing to an exec worker if `vault_index["plan"]` exists but `state.get("plan_approved")` is False.
2. Fix `src/vaultspec_a2a/core/aggregator.py`'s `_emit_interrupt_events` to accept `payload.get("type") in ("permission_request", "plan_approval_request")` and map the plan approval payload into a `PermissionRequestEvent` that the UI can consume.

---

## 14. Gaps & Missing Information (Cycle 12 Audit)

Cycle 12 audited the team topology state tracking, specifically focusing on the `GET /team/status` REST endpoint and the `TeamStatusEvent` WebSocket stream.

### A. REST Endpoint Hardcodes All Agents to IDLE [CRITICAL]

The gateway provides a `GET /team/status` endpoint (`src/vaultspec_a2a/api/endpoints.py`) that the frontend polls to build the "Agent Dashboard" view.
**The Bug:** In `get_team_status_endpoint()`, the response constructor loops over `node_summaries` and explicitly hardcodes `state=AgentLifecycleState.IDLE` for every single agent. The backend aggregator completely fails to track the actual running state (working, blocked, failed) of the agents in memory. If the frontend relies on this endpoint, it will forever show all agents as sleeping, even when a thread is actively spinning at 100% CPU.

### B. Dead Code Path: TeamStatusEvent is Never Emitted [CRITICAL]

The WebSocket protocol defines a `TeamStatusEvent` to push topology and agent lifecycle changes to the UI in real-time. `src/vaultspec_a2a/core/aggregator.py` provides an `emit_team_status()` method to construct this payload.
**The Bug:** A codebase-wide search reveals that `emit_team_status()` is _never called anywhere_ outside of test files. The execution engine never broadcasts topology updates. The frontend is completely starved of real-time team status changes.

### C. Required Next Steps for the Backend Edge (Cycle 12)

1. Implement an in-memory state tracker inside the `EventAggregator` (e.g., `_agent_states: dict[str, AgentLifecycleState]`) that updates whenever `emit_agent_status` is called.
2. Update `GET /team/status` in `endpoints.py` to read from this live memory tracker instead of hardcoding `IDLE`.
3. Hook `emit_team_status()` into the worker's `_handle_ingest()` startup sequence and any dynamic team scaling events so the UI receives the initial topology over WebSocket.

---

## 15. Gaps & Missing Information (Cycle 13 Audit)

Cycle 13 audited the Context Compaction layer (`src/vaultspec_a2a/core/context.py`) and its interactions with the LangGraph state (`TeamState`), specifically evaluating how ADR-002 (Context Management) impacts the frontend's view of the message history.

### A. Silent UI Message Truncation (Amnesia) [CRITICAL]

`src/vaultspec_a2a/core/context.py` implements a `compact_context()` function that triggers when the conversation history exceeds 80% of `CONTEXT_LIMIT` (120k tokens). It aggressively truncates the middle of the `TeamState["messages"]` list, replacing it with a single `HumanMessage` summarizing the compaction.
**The Gap:** This compacted message list is returned as a _new_ state dict for the LLM invocation, but because `worker_node` does not explicitly merge this compacted message back into the global LangGraph checkpointer state via a reducer, the checkpointer retains the _uncompacted_ history.
**The UI Bug:** However, if a future state rehydration attempt ever uses the compacted list, or if the UI relies on an event stream that reflects the compacted state, the UI will suddenly experience "amnesia"—messages will disappear from the screen and be replaced by `[Context compacted: earlier conversation history removed...]`. There is no `ContextCompactionEvent` sent to the frontend to explain this to the user.

### B. Opaque Context Window Telemetry [HIGH]

The frontend UI has no idea how close the current thread is to hitting the `CONTEXT_LIMIT`.
**The Gap:** `should_compact()` calculates the exact token usage via `estimate_tokens()`, but this metric is entirely internal to `src/vaultspec_a2a/core/context.py`. Neither `ThreadStateSnapshot` nor `HeartbeatEvent` nor `AgentStatusEvent` exposes a `current_context_tokens` or `compaction_warning` flag. The UI cannot show the user a "Memory Pressure" bar or warn them that their thread is about to undergo aggressive truncation.

### C. Required Next Steps for the Backend Edge (Cycle 13)

1. Export the current context token count (`estimate_tokens()`) in the `ThreadStateSnapshot` and potentially in a real-time event (like `TeamStatusEvent`) so the UI can render a memory pressure gauge.
2. If compaction _does_ permanently alter the checkpointer state (or if it is intended to), the backend must emit a `ContextCompactedEvent` so the frontend UI can gracefully collapse the deleted messages into an accordion rather than silently deleting them from the DOM.

---

## 16. Gaps & Missing Information (Cycle 14 Audit)

Cycle 14 audited the token accounting and cost tracking subsystems (`CostTrackingModel`, `token_usage` in `TeamState`, and the `AcpChatModel` provider layer).

### A. Dead Code Path: Token Usage is Never Written to DB [CRITICAL]

The backend database layer defines a `CostTrackingModel` (ADR-010) and provides `append_cost_record` and `sum_cost_by_thread` in `src/vaultspec_a2a/database/crud.py`.
**The Bug:** A codebase-wide search reveals that **`append_cost_record` is never called anywhere** outside of the database test files. The execution engine (`src/vaultspec_a2a/worker/executor.py`) and the LangGraph nodes (`worker.py`, `supervisor.py`) never write to the cost tracking database table. The token usage database is permanently empty.

### B. Dead Code Path: `token_usage` in TeamState is Never Updated [CRITICAL]

The LangGraph `TeamState` includes `token_usage: Annotated[dict[str, dict[str, int]], _merge_token_usage]`.
**The Bug:** None of the nodes (`worker_node`, `supervisor_node`) ever populate or update this field in their return dictionaries. The provider layer (`AcpChatModel`) tracks tokens during the stream (`chunk.usage_metadata`), but LangChain's asynchronous callbacks (`process_langgraph_event` in `aggregator.py`) do not intercept or sum this usage data into the graph state. The `token_usage` dictionary remains `{}` for the entire lifecycle of the thread.

### C. `MessageChunkEvent` Missing Token Annotations [MEDIUM]

Even if the token usage were tracked internally, the frontend has no real-time visibility into it.
**The Gap:** `MessageChunkEvent` only streams `content`, `message_id`, and `finish_reason`. It completely drops the `usage_metadata` (input/output tokens) attached to the LangChain chunks. A data-rich UI cannot show real-time token accumulation as an agent types because the data is stripped at the edge.

### D. Required Next Steps for the Backend Edge (Cycle 14)

1. Modify `AcpChatModel` or the `EventAggregator` to extract `usage_metadata` from the final `on_chat_model_end` event and append it to the `CostTrackingModel` table via an IPC call or direct database write.
2. Ensure the worker/supervisor nodes intercept the token usage from the LLM `response` object and return it in their state dict updates so the `_merge_token_usage` reducer can accumulate the totals in the LangGraph checkpointer.
3. Expose the `sum_cost_by_thread()` results on the `GET /threads/{id}` REST endpoint so the UI can display historical token costs.

---

## 17. Gaps & Missing Information (Cycle 15 Audit)

Cycle 15 audited thread cancellation (`POST /threads/{id}/cancel` -> `executor.py`) and the richness of the `ToolCallUpdateEvent` payloads.

### A. Zombie Cancellations [HIGH]

The REST API provides `POST /threads/{id}/cancel`. It updates the SQLite database status to `CANCELLED` and sends a `DispatchRequest(action="cancel")` to the worker process. The worker process calls `self._aggregator.cancel_thread(thread_id)` which sets an `asyncio.Event()`.
**The Bug:** The underlying LangChain `ainvoke()` call inside `src/vaultspec_a2a/core/nodes/worker.py` does not monitor this `asyncio.Event`. Once an LLM is spinning or a tool is executing (which could take minutes), it completely ignores the cancellation signal. The `EventAggregator` stops broadcasting events, but the worker process burns CPU and tokens in the background until the current node finishes. The UI thinks the thread is cancelled, but the backend worker is effectively a zombie.

### B. Tool Call Payloads are Stripped [CRITICAL]

The frontend defines rich tool schemas (`ToolCallContentText`, `ToolCallContentDiff`, `ToolCallContentTerminal`) to render beautiful interactive blocks for filesystem edits and terminal commands.
**The Bug:** `EventAggregator.process_langgraph_event()` intercepts `on_tool_end`. It emits a `ToolCallUpdateEvent` with `status=COMPLETED`. **It completely drops the tool's actual output/content.** It does not map `event_data["data"].get("output")` into the `content` array of the `ToolCallUpdateEvent`. The frontend knows a tool finished, but it never receives the text, diff, or terminal output to display to the user. The tool output is only ever seen by the LLM (written to the checkpointer); the UI is completely blind to it.

### C. Required Next Steps for the Backend Edge (Cycle 15)

1. In `worker_node` (`src/vaultspec_a2a/core/nodes/worker.py`), wrap `model.ainvoke()` with `asyncio.wait_for` or a similar cancellation wrapper tied to the aggregator's cancel event to actually kill the running LLM/tool task.
2. In `src/vaultspec_a2a/core/aggregator.py`, update the `on_tool_end` handler to extract the tool's output string from the LangGraph event payload, determine its `ToolCallContent` type (text vs. terminal), and inject it into the `content` array of the `ToolCallUpdateEvent`.

---

## 18. Gaps & Missing Information (Cycle 16 Audit)

Cycle 16 audited the real-time agent execution controls, specifically focusing on the `AgentControlCommand` sent from the UI over WebSocket to pause, resume, or terminate an active agent (`src/vaultspec_a2a/api/app.py`).

### A. PAUSE and RESUME are Hardcoded No-Ops [CRITICAL]

The WebSocket `ClientMessage` schema exposes an `AgentControlCommand` with `action: "pause" | "resume" | "terminate"`. The UI expects these to halt or un-halt the LangGraph worker loop dynamically.
**The Bug:** In `src/vaultspec_a2a/api/app.py`, the `_create_dispatch_control_handler()` method explicitly swallows the `PAUSE` and `RESUME` actions.

- For `PAUSE`, it logs `"Pause not supported -- ignoring"` and returns immediately.
- For `RESUME`, it logs `"WS RESUME without option_id is a no-op; use POST /permissions/{id}/respond"` and returns immediately.
**The UI Impact:** If the frontend builds a "Pause Agent" or "Resume" button, clicking it does absolutely nothing. The execution engine does not support dynamic pausing outside of hardcoded LangGraph interrupts.

### B. TERMINATE is Mapped to Thread Cancel, Not Agent Termination [MEDIUM]

When the UI sends `AgentControlCommand(action="terminate", agent_id="coder")`, it intends to kill the active agent and return control to the supervisor.
**The Bug:** The control handler maps `TERMINATE` directly to the `cancel` dispatch action, which kills the _entire thread_ via `_aggregator.cancel_thread()`. There is no mechanism to kill an unruly sub-agent and recover; the entire session is destroyed.

### C. Required Next Steps for the Backend Edge (Cycle 16)

1. **Decision Required:** Remove `PAUSE` and `RESUME` from the `AgentControlCommand` schema entirely to prevent the frontend from building dead UI buttons, or implement true dynamic graph interruption inside `src/vaultspec_a2a/worker/executor.py`'s `astream_events` loop.
2. Consider implementing a true "Agent Termination" signal that injects a `routing_error` and forces the active worker node to crash gracefully back to the supervisor, rather than nuking the entire orchestrator thread.

---

## 19. Gaps & Missing Information (Cycle 17 Audit)

Cycle 17 audited the mapping of LangGraph tool invocation metadata into the `ToolCallStartEvent` and `ToolCallUpdateEvent` models, specifically checking how the backend handles `ToolCallLocation` and the `ToolCallContent` structures (text/diff/terminal).

### A. Dead Code Path: Tool Locations are Never Sent [HIGH]

The `ToolCallLocation` schema (`path`, `line`) is intended to allow the UI to show exactly _where_ in the codebase a tool is operating (e.g. `src/main.ts:42`).
**The Bug:** In `src/vaultspec_a2a/core/aggregator.py`, the `emit_tool_call_start` function initializes `locations=[]` (via the default factory) and the `emit_tool_call_update` function never sets `locations`. The backend entirely fails to parse the tool arguments (e.g., extracting the `file_path` arg from a file-edit tool) to construct a `ToolCallLocation`. The UI will never receive file location hints for tool calls.

### B. Dead Code Path: Rich Tool Content is Never Sent [CRITICAL]

The `ToolCallContent` union (`ToolCallContentText`, `ToolCallContentDiff`, `ToolCallContentTerminal`) allows the UI to render tool arguments and outputs using rich components (like syntax highlighters or diff viewers).
**The Bug:** In `src/vaultspec_a2a/core/aggregator.py`, `emit_tool_call_start` and `emit_tool_call_update` **never** populate the `content` list.

- During `on_tool_start`, the `event_data["data"].get("input")` containing the tool's arguments (what the LLM generated) is completely ignored.
- During `on_tool_end`, the `event_data["data"].get("output")` containing the result (what the tool returned) is completely ignored.
The UI receives a `ToolCallUpdateEvent` that only says `status="completed"`. It never receives the arguments passed to the tool, nor the result returned by the tool.

### C. Required Next Steps for the Backend Edge (Cycle 17)

1. Update `EventAggregator.process_langgraph_event` to parse `event_data["data"].get("input")` on `on_tool_start`. Map arguments like `file_path` to `ToolCallLocation` and format the arguments into a `ToolCallContent` block.
2. Update `EventAggregator.process_langgraph_event` to parse `event_data["data"].get("output")` on `on_tool_end`. Wrap the output string in a `ToolCallContentText` block and append it to the `content` list in the `ToolCallUpdateEvent`.

---

## 20. Gaps & Missing Information (Cycle 18 Audit)

Cycle 18 audited the concurrency control mechanisms between the gateway and the worker process, specifically focusing on how the system handles simultaneous `ingest` (new message) and `resume` (permission response) requests.

### A. Concurrent Dispatch Collision [HIGH]

The worker's `Executor` uses `_mark_ingest_active(thread_id)` to ensure only one LangGraph execution runs per thread.
**The Bug:** When a thread is suspended at a LangGraph `interrupt` (awaiting user permission), it is considered "not ingesting". If a user types a new message into the UI _while_ a permission request is pending, the gateway will dispatch an `ingest` action. The worker will accept this, effectively "forking" the thread's future or overwriting the current suspended state in the checkpointer.
**The UI Impact:** The user might respond to a permission request _after_ they've already sent a new message, causing the graph to resume in a corrupted or stale state. The backend does not lock the thread for `resume` while an `ingest` is pending, or vice versa.

### B. Opaque State Versioning / Checkpoint Pins [MEDIUM]

LangGraph supports explicit state versioning via `checkpoint_id`.
**The Gap:** The `DispatchRequest` and `ServerEvent` schemas do not support pinning a command to a specific checkpoint ID. If the UI sends a `RESUME` command, it is applied to the _latest_ checkpoint. In a fast-moving multi-agent thread, the "latest" checkpoint might have moved beyond the one the user was looking at when they hit "Approve".
**The Risk:** Race conditions where user actions are applied to the wrong version of the graph state.

### C. Required Next Steps for the Backend Edge (Cycle 18)

1. Implement a "Thread Lock" state in the database or aggregator. While a thread has `pending_permissions`, the REST API should reject `POST /messages` with a `409 Conflict` (or the UI should disable the input).
2. Add `checkpoint_id: str | None` to the `AgentControlCommand` and `PermissionResponseRequest` to ensure human interventions are only applied to the exact state version they were generated for.
3. Export the `checkpoint_id` in every `ServerEvent` so the frontend can track the exact version history of the session.

---

## 21. Gaps & Missing Information (Cycle 19 Audit)

Cycle 19 audited the persistence and provenance of message history within `src/vaultspec_a2a/database/models.py`, `src/vaultspec_a2a/database/crud.py`, and the snapshot enrichment logic in `src/vaultspec_a2a/api/endpoints.py`.

### A. Message History is Not Persisted in SQL [HIGH]

The backend's SQL schema (`ThreadModel`, `ArtifactModel`, etc.) contains no table for messages.
**The Gap:** All conversation history is stored exclusively inside the LangGraph SQLite checkpointer. This is a "single source of truth" for the graph state, but it makes historical auditing, global message search, and cross-thread analytics impossible without loading every single thread's graph state into memory. The backend is effectively treating messages as transient "state" rather than durable "records".

### B. Mismatch Between Streaming `message_id` and Snapshot `message_id` [CRITICAL]

The system uses different identification strategies for the same messages depending on whether they are streamed or fetched as a snapshot.

- **Streaming:** In `src/vaultspec_a2a/core/aggregator.py`, `MessageChunkEvent` uses the LangGraph `run_id` (the ID of the model invocation) as the `message_id`.
- **Snapshot:** In `src/vaultspec_a2a/api/endpoints.py`, `_enrich_snapshot_from_state` attempts to read `m.id` from the persisted message. If `m.id` is missing (common for checkpointer messages), it falls back to a **deterministic hash of role + content**.
**The Bug:** The deterministic hash will **never** match the `run_id` used during the stream.
**The UI Impact:** When a user refreshes the page, the message IDs will change. The frontend's deduplication logic will fail, leading to duplicate messages in the UI or loss of UI state linked to the original streaming message (e.g., collapsed states, local annotations).

### C. Required Next Steps for the Backend Edge (Cycle 19)

1. Ensure that the `EventAggregator` and `endpoints.py` use a unified strategy for message identification. The `run_id` from the model invocation should be persisted as the message ID in the LangGraph state so it can be reliably recovered.
2. Consider implementing a `MessageModel` in the main SQL database to provide a high-performance, queryable record of the conversation that is independent of the LangGraph checkpointer internals.
3. Update `MessageSnapshot` to include the `run_id` or `invocation_id` to maintain provenance.

