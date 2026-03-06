# LangGraph Drift Tracker

**Updated:** 2026-03-03
**Scope:** Ongoing audit of `src/vaultspec_a2a/core/` modules against official LangGraph documentation.
**Auditor:** docs-researcher (continuous loop) — sources: `mcp__docs-langchain__*`, `mcp__context7__*`

---

## How to Read This Document

Each finding is tagged with:
- **Module** — file audited
- **Severity** — CRITICAL / HIGH / MEDIUM / LOW
- **Status** — Open / Redesign Required / Fix Required / Resolved
- **LG-Doc source** — URL cited from official LangGraph docs

---

## Open Findings

### LG-001 — CRITICAL — Side-Channel Drain Pattern
- **Module:** `src/vaultspec_a2a/core/task_queue.py`
- **ADR:** ADR-021
- **Status:** Redesign Required
- **Description:** Tool writes state patches to a shared-memory side channel; node drains it after tool execution. This bypasses the reducer pipeline, is not checkpointed atomically, and is not thread-safe.
- **LangGraph position:** State updates from tools must use `Command(update={...})`, propagated automatically by `ToolNode`. Side channels are not a supported or documented pattern.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/use-graph-api
- **Required fix:** Replace with `Command`-returning tool function. Revise ADR-021 §2 and §5.

---

### LG-002 — HIGH — `(tool_fn, drain_fn)` Tuple Factory
- **Module:** `src/vaultspec_a2a/core/task_queue.py`
- **ADR:** ADR-021
- **Status:** Redesign Required
- **Description:** Tool factory returns a `(tool_fn, drain_fn)` tuple. `ToolNode` and `bind_tools()` expect standard `BaseTool` instances. There is no mechanism for a companion drain function.
- **LangGraph position:** The extension point for tools writing to graph state is returning `Command` from within the tool function itself.
- **LG-Doc source:** https://langchain-ai.github.io/langgraphjs/how-tos/update-state-from-tools
- **Required fix:** Replace with single `@tool`-decorated factory returning `Command`. Revise ADR-021 §2 and §5.

---

### LG-003 — CRITICAL — Conditional `interrupt()` Inside Supervisor Node
- **Module:** `src/vaultspec_a2a/core/nodes/supervisor.py`
- **ADR:** ADR-024
- **Status:** Redesign Required
- **Description:** `interrupt()` is called conditionally inside `supervisor_node` behind a multi-condition check. The LLM is re-invoked at node replay (on resume), meaning `next_route` can differ between original call and resume. If the condition evaluates differently on replay, the interrupt is skipped — LangGraph's index-based resume matching has no interrupt at the expected index, and the stored resume value is lost or mismatched.
- **LangGraph position:** "Do not conditionally skip interrupt calls within a node. Matching is strictly index-based, so the order of interrupt calls within the node is important."
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/interrupts
- **Required fix:** Move plan approval interrupt to a dedicated `plan_approval_node` that calls `interrupt()` unconditionally. Route to it via a conditional edge from the supervisor. Revise ADR-024 §2.

---

### LG-004 — MEDIUM — `TAG_NOSTREAM` Imported from Internal Module
- **Module:** `src/vaultspec_a2a/core/nodes/supervisor.py`
- **ADR:** N/A (implementation detail)
- **Status:** Fix Required
- **Description:** `TAG_NOSTREAM` imported from `langgraph.constants` — an internal module not part of the public API. Liable to break on minor version bumps without deprecation warning.
- **LangGraph position:** Streaming suppression via internal constants is undocumented. Public API uses string tags.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/streaming
- **Required fix:** Add `# internal constant — suppresses token streaming for routing LLM calls` comment on import. Add import guard test. Monitor LangGraph changelogs.

---

### LG-005 — LOW — Two `SystemMessage` Objects in Single `ainvoke` Call
- **Module:** `src/vaultspec_a2a/core/nodes/supervisor.py`, `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** ADR-022
- **Status:** Fix Required
- **Description:** Persona prompt and anchoring context are injected as two separate `SystemMessage` objects at positions [0] and [1]. Documented pattern uses a single `SystemMessage`. Some providers do not handle multiple system messages correctly.
- **LangGraph position:** Single `SystemMessage` at head of message list is the documented pattern.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/quickstart
- **Required fix:** Merge into single `SystemMessage(content=full_prompt + "\n\n" + anchoring)`.

---

### LG-006 — LOW — LLM Re-invocation on Interrupt Resume Is Non-Deterministic
- **Module:** `src/vaultspec_a2a/core/nodes/supervisor.py`
- **ADR:** ADR-024
- **Status:** Resolved by LG-003 fix
- **Description:** On resume, supervisor re-invokes the routing LLM unconditionally before reaching the interrupt check. Non-deterministic `next_route` amplifies LG-003 risk. Resolved when `plan_approval_node` is extracted (LG-003 fix) since the dedicated node does not re-invoke the LLM.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/interrupts

### LG-007 — HIGH — Side-Channel `drain_fn()` in worker_node (Confirmed)
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** ADR-021
- **Status:** Redesign Required (same root cause as LG-001/LG-002)
- **Description:** `drain_fn()` called in worker_node after tool execution; result spread into return dict. Drain-on-interrupt path (line 187–188) explicitly discards updates on interrupt — any task completion signalled during an interrupted ACP turn is silently lost.
- **LangGraph position:** State updates from tools must use `Command(update={...})`.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/use-graph-api
- **Required fix:** Resolved by ADR-021 redesign (LG-001/LG-002 fix).

---

### LG-008 — MEDIUM — `except GraphBubbleUp` from Internal `langgraph.errors`
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `GraphBubbleUp` imported from `langgraph.errors` (internal module). Functionally correct today as the base class of `GraphInterrupt`, but undocumented. If LangGraph changes its exception hierarchy, the guard could fail to catch future interrupt types, causing them to be swallowed by `except Exception` and wrapped as `WorkerExecutionError` — silently breaking interrupt/resume.
- **LangGraph position:** Docs recommend catching specific non-interrupt exception types, not internal base classes.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/interrupts
- **Required fix:** Add comment documenting why `GraphBubbleUp` is caught. Add test asserting `interrupt()` raises a subclass of `GraphBubbleUp`. Monitor LangGraph changelogs.

---

### LG-009 — LOW — In-Place Mutation of LLM Response Object
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `response.name = name` mutates the `AIMessage` object in-place after `ainvoke`. Documented pattern constructs `AIMessage` with `name=` at creation time. Pydantic v2 frozen models would break this.
- **LangGraph position:** `AIMessage(content=..., name="agent_name")` is the documented multi-agent attribution pattern.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langchain/streaming/frontend
- **Required fix:** Replace with `response.model_copy(update={"name": name})` or construct new `AIMessage`.

---

### LG-010 — LOW — Three `SystemMessage` Objects Per `ainvoke` in worker_node
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** ADR-022
- **Status:** Fix Required (same as LG-005, amplified)
- **Description:** Up to 3 `SystemMessage` objects (system_prompt + anchoring + mounted_context). Documented pattern uses single `SystemMessage`.
- **LangGraph position:** Single `SystemMessage` at head of message list.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/quickstart
- **Required fix:** Merge all three into single `SystemMessage` with section separators. Resolve together with LG-005.

---

### LG-012 — HIGH — `RetryPolicy` Imported from Internal Module
- **Module:** `src/vaultspec_a2a/core/graph.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `from langgraph.pregel._retry import RetryPolicy` uses an internal underscore-prefixed module. Public API is `from langgraph.types import RetryPolicy`.
- **LangGraph position:** All official docs show `from langgraph.types import RetryPolicy`.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/use-graph-api
- **Required fix:** Change import to `from langgraph.types import RetryPolicy`. One-line fix.

---

### LG-013 — HIGH — `graph.recursion_limit` Set as Post-Compile Mutable Property
- **Module:** `src/vaultspec_a2a/core/graph.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `graph.recursion_limit = N` sets a global mutable attribute on the compiled graph. Undocumented. Thread-unsafe — concurrent invocations of the same graph instance share this value. Documented pattern passes `recursion_limit` via `config={"recursion_limit": N}` at invocation time.
- **LangGraph position:** `graph.invoke(inputs, config={"recursion_limit": N})` is the documented pattern.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/graph-api
- **Required fix:** Remove post-compile assignment. Pass via `config` dict in `aggregator.py` at each `astream()`/`ainvoke()` call.

---

### LG-014 — MEDIUM — `graph.step_timeout` Set as Post-Compile Mutable Property
- **Module:** `src/vaultspec_a2a/core/graph.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `graph.step_timeout = N` — undocumented `Pregel` internal attribute. Same thread-safety concern as LG-013. Documented alternative is wrapping `astream()` in `asyncio.wait_for()`.
- **LangGraph position:** Undocumented. Per-step timeout should be applied at invocation layer.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/graph-api
- **Required fix:** Apply timeout at the invocation layer.

---

### LG-015 — LOW — `StateGraph(cast(Any, TeamState))` Hides Type Errors
- **Module:** `src/vaultspec_a2a/core/graph.py`
- **ADR:** ADR-019
- **Status:** Fix Required
- **Description:** `cast(Any, TeamState)` suppresses all type checking on the `StateGraph` argument. Should be replaced with `# type: ignore` plus an explanation of why the cast is needed.
- **LangGraph position:** `StateGraph(State)` is the documented pattern — no cast.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/use-graph-api
- **Required fix:** Replace `cast(Any, TeamState)` with `TeamState  # type: ignore[arg-type]` and a comment.

---

### LG-016 — MEDIUM — `NotRequired[Annotated[type, reducer]]` Combination — Undocumented, Potentially Unsafe
- **Module:** `src/vaultspec_a2a/core/state.py`
- **ADR:** ADR-019
- **Status:** Fix Required
- **Description:** `vault_index: NotRequired[Annotated[dict[str, list[str]], _merge_vault_index]]` and `validation_errors: NotRequired[Annotated[list[str], _append_validation_errors]]` use an undocumented combination. If the field is absent from state and a node returns an update for it, LangGraph passes `existing=None` to the reducer — causing `AttributeError` in `_merge_vault_index` (`None.items()`) and `TypeError` in `_append_validation_errors` (`None + list`).
- **LangGraph position:** Docs show `Annotated[type, reducer]` for required fields, plain `NotRequired[type]` for optional. The combination is not documented.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/use-graph-api
- **Required fix:** Add `existing = existing or {}` / `existing = existing or []` guards to both reducers.

---

### LG-017 — LOW — `_replace_plan` Reducer Has Dead `None` Guard
- **Module:** `src/vaultspec_a2a/core/state.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `return new if new is not None else existing` — LangGraph never passes `None` as the `new` value to a reducer. Nodes omit a key to leave it unchanged; they cannot signal "no update" via `None`. The guard is dead code that implies an incorrect mental model.
- **LangGraph position:** Reducer is not called when a node omits the key. `return new` is sufficient.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/persistence
- **Required fix:** Simplify to `return new`.

---

### LG-011 — INFO — `_interrupt_permission_callback` Unconditional `interrupt()` Is Correct
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`
- **ADR:** ADR-013
- **Status:** No action needed
- **Description:** Permission callback calls `interrupt()` unconditionally when entered. Conditional logic is in the ACP model, not in the interrupt call. Sequential multiple-interrupt-per-node scenario handled correctly via index-based resume matching.
- **LangGraph position:** Consistent with documented pattern.

---

### LG-018 — CRITICAL — Interrupt Detection via `BaseException` + Classname String Matching
- **Module:** `src/vaultspec_a2a/core/aggregator.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `ingest()` catches `BaseException` and detects interrupts via `isinstance(exc, _GraphInterrupt) or type(exc).__name__ in ("GraphInterrupt", "NodeInterrupt")`. Documented pattern is checking `"__interrupt__"` key in stream update chunks. String-based classname fallback fires on any exception named `GraphInterrupt` regardless of module.
- **LangGraph position:** Interrupts are detected from stream data (`"__interrupt__"` in chunk), not by catching exceptions.
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/interrupts
- **Required fix:** Switch to stream-based interrupt detection via `"__interrupt__"` in the event payload.

---

### LG-019 — HIGH — `aget_state` + `asyncio.wait_for` Post-Interrupt — Undocumented, Race-Prone
- **Module:** `src/vaultspec_a2a/core/aggregator.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `_emit_interrupt_events()` calls `await asyncio.wait_for(graph.aget_state(config), timeout=5.0)` after a `GraphInterrupt` to read interrupt payload. Official pattern reads interrupt values directly from the stream event at interrupt detection time — no separate `aget_state` needed. Post-interrupt `aget_state` introduces a race condition if another invocation advances state between the interrupt and the read.
- **LangGraph position:** Interrupt payload is available in the same stream event chunk (`chunk["__interrupt__"][0].value`).
- **LG-Doc source:** https://docs.langchain.com/oss/python/langgraph/interrupts
- **Required fix:** Read interrupt values directly from the stream event. Remove `aget_state` call from interrupt path.

---

### LG-020 — MEDIUM — `ImportError` Guards on `GraphInterrupt`/`GraphRecursionError`
- **Module:** `src/vaultspec_a2a/core/aggregator.py`
- **ADR:** N/A
- **Status:** Fix Required
- **Description:** `GraphInterrupt` and `GraphRecursionError` wrapped in `ImportError` try/except. If absent, falls back to string classname matching — fragile silent degradation. These are hard dependency imports; `ImportError` path should never be reached. Fix for LG-018 renders these imports unnecessary.
- **Required fix:** Resolved by LG-018 fix (stream-based interrupt detection removes need for these imports).

---

### LG-021 — HIGH — `_tool_fn` Discarded in `worker.py` — `mark_task_complete` Never Wired to LLM + ToolNode Missing
- **Module:** `src/vaultspec_a2a/core/nodes/worker.py`, `src/vaultspec_a2a/core/task_queue.py`
- **ADR:** ADR-021
- **Status:** Fix Required — **Functional regression. Task queue completion silently non-functional.**
- **Description:** `_tool_fn, drain_fn = create_mark_task_complete_tool(...)` — `_tool_fn` assigned to throwaway `_` prefix variable and never passed to `effective_model.bind_tools()`. The LLM has no knowledge of the `mark_task_complete` tool and cannot call it. Drain side-channel works correctly but is never triggered because the LLM never invokes the tool.
- **LangGraph position:** Tools must be bound via `model.bind_tools([tool_fn])` before `ainvoke` to be accessible to the LLM.
- **Required fix (post ADR-021 redesign):** Add `ToolNode([mark_task_complete_tool])` as a per-worker tool node in graph.py. Add conditional edge from worker node: if `state["messages"][-1].tool_calls` → tool node, else → supervisor. Add edge from tool node back to worker. Worker node drops all drain logic. `except GraphBubbleUp` block (LG-008) becomes dead code and is deleted with the drain removal.

---

### LG-022 — MEDIUM — `count_tokens_approximately` from Undocumented Internal Path
- **Module:** `src/vaultspec_a2a/core/nodes/mount.py`
- **ADR:** ADR-020
- **Status:** Fix Required
- **Description:** `from langchain_core.messages.utils import count_tokens_approximately` — not in any official LangChain public API docs. Internal utility, liable to move or be removed without deprecation.
- **Required fix:** Replace with documented approach (e.g., `len(text) // 4` heuristic or tiktoken directly).

---

### LG-023 — LOW — `_filter_queue_content` Private Import Across Modules
- **Module:** `src/vaultspec_a2a/core/nodes/mount.py`
- **ADR:** ADR-021
- **Status:** Fix Required (resolve with LG-021 redesign)
- **Description:** `from ..task_queue import _filter_queue_content` imports a private function across module boundaries. Either make it public in `task_queue.__all__` or move to a shared utility.
- **Required fix:** Resolved naturally when ADR-021 is redesigned — revisit at that point.

---

### LG-024 — CRITICAL — Hard Phase Gate Returns Blocked Destination — Gate Is Bypassed
- **Module:** `src/vaultspec_a2a/core/nodes/supervisor.py`, `src/vaultspec_a2a/core/graph.py`
- **ADR:** ADR-023
- **Status:** Fix Required — **Phase gates are currently non-functional.**
- **Description:** When a hard phase gate fires in `supervisor_node`, it returns `{"next": next_route, "routing_error": "..."}` — `next_route` is the blocked destination. The conditional edge in `graph.py` is `lambda state: state["next"]`, which reads `next` directly without inspecting `routing_error`. The graph routes to the blocked worker regardless. `routing_error` is informational only — it does not prevent routing.
- **LangGraph position:** Conditional edge routing is determined entirely by the return value of the router function. A `routing_error` field has no effect on routing unless the router function explicitly checks it.
- **Required fix:** Hard gate must return `{"next": workers[0]}` or `{"next": "supervisor"}` — a safe fallback destination, not the blocked destination. Soft gate should use a separate `routing_warning` field, not `routing_error`.

---

## Resolved Findings

*(none yet)*

---

## Module Audit Status

| Module | Audited | Findings | Status |
|--------|---------|----------|--------|
| `src/vaultspec_a2a/core/task_queue.py` | ✅ 2026-03-03 | LG-001, LG-002 | Redesign required |
| `src/vaultspec_a2a/core/nodes/supervisor.py` | ✅ 2026-03-03 | LG-003, LG-004, LG-005, LG-006 | Redesign + fixes required |
| `src/vaultspec_a2a/core/nodes/worker.py` | ✅ 2026-03-03 | LG-007, LG-008, LG-009, LG-010, LG-011 | Redesign + fixes required |
| `src/vaultspec_a2a/core/phase.py` | ✅ 2026-03-03 | None | Clean |
| `src/vaultspec_a2a/core/nodes/mount.py` | ✅ 2026-03-03 | LG-022, LG-023 | Fixes required |
| `src/vaultspec_a2a/core/graph.py` | ✅ 2026-03-03 | LG-012, LG-013, LG-014, LG-015 | Fixes required |
| `src/vaultspec_a2a/core/aggregator.py` | ✅ 2026-03-03 | LG-018, LG-019, LG-020 | Critical fixes required |
| `src/vaultspec_a2a/core/state.py` | ✅ 2026-03-03 | LG-016, LG-017 | Fixes required |
| `src/vaultspec_a2a/core/anchoring.py` | ✅ 2026-03-03 | None | Clean |
| `src/vaultspec_a2a/core/metadata.py` | ✅ 2026-03-03 | None | Clean |
| `src/vaultspec_a2a/core/context.py` | ✅ 2026-03-03 | None | Clean |

---

## Task Queue

| Task | Owner | Blocked by | Status |
|------|-------|------------|--------|
| Revise ADR-021 §2 + §5 (Command-returning tools) | docs-researcher | — | 🔄 In progress |
| Revise ADR-024 §2 (dedicated plan_approval_node) | docs-researcher | worker.py audit | ⏳ Queued |
| Rewrite `task_queue.py` (Command pattern) | coder | ADR-021 revision approval | ⏳ Blocked |
| Rewrite supervisor plan-approval interrupt (dedicated node) | coder | ADR-024 revision approval | ⏳ Blocked |
| Fix LG-004 (TAG_NOSTREAM comment + guard) | coder | ADR redesigns | ⏳ Queued |
| Fix LG-005 (merge SystemMessages) | coder | ADR redesigns | ⏳ Queued |
| Continue LangGraph audit loop (worker.py → phase.py → mount.py → ...) | docs-researcher | — | 🔄 In progress |
| Fix 5 doc consistency findings (C-2, C-3, I-1, I-2, I-6) | docs-researcher | ADR redesigns | ⏳ Queued |
| ADR-025/023/024 conformance drifts (4 items) | codebase-researcher | — | ⏳ Report pending |
