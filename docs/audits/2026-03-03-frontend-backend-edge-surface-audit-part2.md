## 44. Gaps & Missing Information (Cycle 42 Audit)

Cycle 42 audited the state recovery and linear history enforcement within the `src/vaultspec_a2a/worker/executor.py` and `src/vaultspec_a2a/api/endpoints.py`.

### A. No State Rewind or "Undo" Mechanism [HIGH]

The system tracks detailed history via LangGraph checkpoints, but the edge surface only supports linear resumption.
**The Gap:** There is no REST API endpoint or WebSocket command to resume a thread from a specific `checkpoint_id`. The backend always targets the `latest` checkpoint.
**The UI Impact:** The frontend cannot offer a "Rewind to this step" or "Undo last agent action" feature. If an agent performs a destructive or incorrect action (e.g., deleting code it shouldn't have), the user has no way to roll back the orchestrator's mental state to a previous point in time.

### B. Opaque Version History [MEDIUM]

The `ThreadStateSnapshot` includes the `latest_checkpoint_id`, but there is no endpoint to list the history of checkpoints for a thread.
**The UI Impact:** The UI can only show the current state. It cannot render a "History Timeline" or allow the user to browse previous states of the blackboard or conversation.

### C. Required Next Steps for the Backend Edge (Cycle 42)

1. Add a `checkpoint_id` optional field to the `DispatchRequest` schema.
2. Update `Executor._handle_resume()` to use the provided `checkpoint_id` when loading the graph state, allowing point-in-time resumption.
3. Implement a `GET /threads/{id}/history` endpoint that returns a list of available checkpoints with their associated timestamps and event summaries.

---

## 45. Gaps & Missing Information (Cycle 43 Audit)

Cycle 43 audited the `EventAggregator`'s handling of complex LangGraph topologies, specifically subgraphs and parallel node execution.

### A. Subgraph Blindness [HIGH]

LangGraph supports nested graphs (subgraphs) for modularity.
**The Bug:** The `EventAggregator.process_langgraph_event` method explicitly filters out events that are not in its narrow list of recognized kinds. It has **no handlers for `on_subgraph_start` or `on_subgraph_end`**.
**The System Failure:** If a team preset uses a subgraph for a specific task (e.g., a "Security Subgraph"), the UI will remain completely static while that subgraph executes. No status updates, no node transitions, and no sub-agent metadata will be emitted.
**The UI Impact:** The user will see the supervisor pass control to a "Subgraph Node" and then nothing will happen for several minutes until the subgraph returns.

### B. Parallel Event Interleaving Risks [MEDIUM]

LangGraph allows multiple nodes to run concurrently. The `EventAggregator` correctly attributes events to their originating node via `metadata.get("langgraph_node")`.
**The Gap:** The `EventAggregator` uses a single per-thread `last_sequence` counter.
**The Risk:** If two nodes are streaming `MessageChunkEvents` simultaneously, their chunks will be interleaved into a single chronological stream with sequential IDs. While the `agent_id` is present, the UI must implement sophisticated "multi-cursor" rendering to prevent the two agents' text from jumbling together in the same bubble.
**The UI Impact:** Without specific UI support for "Concurrent Agent Bubbles", the conversation view will become unreadable during parallel execution.

### C. Required Next Steps for the Backend Edge (Cycle 43)

1. Implement handlers for `on_subgraph_*` events in the `EventAggregator` to allow the UI to "dive" into nested execution contexts.
2. Add a `parent_run_id` or `depth` field to `ServerEvent` to allow the UI to render the hierarchy of nested graph calls.
3. Formally document and test the behavior of the WebSocket stream during parallel node execution to ensure the frontend's TanStack/Zustand logic can handle interleaved chunks from different agents.

---

## 46. Gaps & Missing Information (Cycle 44 Audit)

Cycle 44 audited the ACP (Agent Control Protocol) provider layer (`src/vaultspec_a2a/providers/acp_chat_model.py`) specifically for its handling of structured metadata and streaming notifications.

### A. Provider-Level Plan Swallowing [CRITICAL]

The `AcpChatModel` communicates with external agent subprocesses. These agents stream planning updates via the `session/update` method with `type: "plan"`.
**The Bug:** In `_handle_session_update()`, the code explicitly catches the `plan` update but **only logs it** (`logger.debug("ACP plan update: %d steps received")`). It does not yield any chunk or custom event that the `EventAggregator` can consume.
**The System Failure:** This is the root cause of the "Dead Plan Updates" identified in Cycle 5. The source data from the agent is being swallowed at the provider level. Even if the aggregator is fixed, the UI will never see a plan because the model provider never emits it.

### B. Usage Metadata and Stop Reason Loss [MEDIUM]

LangChain chunks support `usage_metadata` (token counts) and `response_metadata` (stop reasons, fingerprints).
**The Bug:** The `ChatGenerationChunk` objects yielded by `AcpChatModel` only include the `content` string. All other metadata returned by the ACP agent (e.g., `input_tokens`, `output_tokens`, `stopReason`) is discarded.
**The UI Impact:** The UI cannot show the user why a response stopped (e.g., "Max Tokens Reached" vs. "End of Turn") or provide real-time cost feedback.

### C. Required Next Steps for the Backend Edge (Cycle 44)

1. Modify `AcpChatModel._handle_session_update` to yield a `ChatGenerationChunk` with a `custom_event` or metadata flag when a plan update is received.
2. Update the chunk constructor to extract and include `usage_metadata` and `stop_reason` from the ACP agent's JSON-RPC responses.
3. Ensure the `EventAggregator` is updated to listen for these new chunk metadata fields and forward them to the UI.

---

## 47. Gaps & Missing Information (Cycle 45 Audit)

Cycle 45 audited thread identity management and nickname immutability (`src/vaultspec_a2a/core/metadata.py` and `src/vaultspec_a2a/database/crud.py`).

### A. Thread Identity Immutability [HIGH]

The system generates a human-friendly nickname at thread creation (e.g., "auth-flow-star-a3f2") and persists it in the `ThreadMetadata` JSON.
**The Gap:** There is no REST API endpoint (e.g., `PATCH /threads/{id}`) to rename a thread.
**The UI Impact:** Users are stuck with the generated or initial nickname forever. The UI cannot offer a "Rename Thread" feature, which is a standard requirement for session-based tools.

### B. Nickname Collision Races [LOW]

`generate_nickname` uses the first 4 characters of the UUID to prevent collisions.
**The Gap:** While highly unlikely, the system does not implement a retry loop if a nickname conflict occurs in the database. The `create_thread` call will simply fail with a `NicknameConflictError`.

---

## 48. Gaps & Missing Information (Cycle 46 Audit)

Cycle 46 audited project awareness and the static nature of context discovery (`src/vaultspec_a2a/core/metadata.py` and `src/vaultspec_a2a/core/preamble.py`).

### A. Static Context Awareness [MEDIUM]

`discover_context_refs()` runs once when a thread is created to find all `.vault/` documents matching the `feature_tag`.
**The Gap:** These results are baked into the `ThreadMetadata`. If a user (or another agent) adds new ADRs or research documents to the filesystem *after* the thread has started, the agents in that thread will **never discover them**.
**The UI Impact:** The user might see new files in the "Blackboard" (Cycle 1 gap), but the agents will remain blind to them because their "Grounding Preamble" is based on a stale snapshot of the filesystem.

---

## 49. Gaps & Missing Information (Cycle 47 Audit)

Cycle 47 audited the worker process concurrency limits and resource management (`src/vaultspec_a2a/worker/executor.py`).

### A. Unbounded Concurrent Threads [HIGH]

The worker's `Executor` tracks active threads in `self._active_ingests` to prevent double-ingest on a single thread.
**The Gap:** There is **no global limit** on the total number of concurrent active threads across the worker process.
**The Risk:** If a user spawns many threads and sends messages to all of them, the worker will attempt to launch an ACP agent subprocess and a LangGraph loop for every single one simultaneously. This will lead to rapid memory exhaustion and process handle leaks on the host machine.
**The UI Impact:** The UI has no way to show a "Server Busy" or "Capacity Reached" status.

---

## 50. Gaps & Missing Information (Cycle 48 Audit)

Cycle 48 audited the database initialization and migration strategy (`src/vaultspec_a2a/database/session.py`).

### A. Missing Migration Framework [MEDIUM]

The backend uses `Base.metadata.create_all` and manual `ALTER TABLE` statements for "idempotent migration" during `init_db()`.
**The Gap:** There is no real migration framework (like Alembic).
**The Risk:** As the schema grows more complex (adding the many fields identified in this audit), manual SQL strings will become unmaintainable and prone to data corruption. The project lacks a durable way to manage schema evolution alongside the ADRs.

---

## 51. Gaps & Missing Information (Cycle 49 Audit)

Cycle 49 audited the persistence of the thread "Objective" vs. conversation history (`src/vaultspec_a2a/worker/executor.py` and `src/vaultspec_a2a/core/context.py`).

### A. Core Objective Loss via Compaction [HIGH]

The thread's `initial_message` is injected as a standard `HumanMessage` at the start of the conversation history.
**The Gap:** Following Cycle 13 (Context Compaction), if a conversation grows very long, the middle of the history is truncated. If the thread continues further, the *initial message* (the core objective of the entire session) may eventually be lost or collapsed into a generic summary.
**The UI Impact:** Agents might "forget" what they were originally asked to do after a long debugging session. The backend lacks a pinned `objective` field in `TeamState` that is exempt from compaction and always visible to the agents.

### B. Required Next Steps for the Backend Edge (Cycles 45-49)

1. Implement `PATCH /threads/{id}` to allow updating the `nickname` and `feature_tag` in the SQL metadata.
2. Update the `preamble` logic to re-run `discover_context_refs` on every agent invocation so that project awareness stays in sync with the filesystem.
3. Implement a `MAX_CONCURRENT_THREADS` setting in the worker to prevent resource exhaustion.
4. Integrate a real migration tool (Alembic) to manage the upcoming schema expansions.
5. Add a `pinned_objective: str` field to `TeamState` and `CreateThreadRequest` to ensure the session goal survives context compaction.
