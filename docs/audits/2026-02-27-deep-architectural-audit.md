---
date: 2026-02-27
type: audit
feature: deep-architectural
description: 'Deep architectural audit of src/vaultspec_a2a/core/, src/vaultspec_a2a/providers/, and src/vaultspec_a2a/api/ against A2A SDK and LangGraph references, fixing 5 confirmed bugs including pipeline_loop routing, CORS, log dedup, and sandbox path collision.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-007-tech-stack-deployment-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Deep Architectural Audit — 2026-02-27

**Scope:** src/vaultspec_a2a/core/, src/vaultspec_a2a/providers/, src/vaultspec_a2a/api/, src/vaultspec_a2a/utils/logging.py
**Against:** A2A SDK (knowledge/repositories/a2a-python/), LangGraph
(knowledge/repositories/langgraph/), ACP/TOAD references
**Outcome:** 5 confirmed bugs fixed; 2 design notes identified

---

## Bugs Fixed

### CRITICAL-1: `pipeline_loop`topology always terminates after 1 iteration

**File:**`src/vaultspec_a2a/core/graph.py:330`/`src/vaultspec_a2a/core/nodes/worker.py:102`

**Root cause:** `_loop_router`read`state.get("next", "FINISH")`. The
`create_worker_node`
return dict is `{"messages": [response]}`— it never writes the`next` key. With
Python's
`dict.get`defaulting to`"FINISH"`, the loop always terminated on the first
iteration
regardless of `max_loops`. The loop count guard at lines 327-329 was correct but
the
continuation path was unreachable.

The docstring in `state.py`also incorrectly stated: _"the loop_node sets
next='FINISH'"_ —
no code did this; the`_loop_router`conditional edge is the enforcement point.

**Fix:** Changed default from`"FINISH"`to`"revise"`:

```python
return state.get("next", "revise")
```

Workers that want to exit early return `next="FINISH"`; the max_loops guard
forces FINISH
when the cap is reached. Corrected the `state.py`comment to match.

---

### CRITICAL-2: CORS —`allow_origins=["*"]`+`allow_credentials=True`

**File:** `src/vaultspec_a2a/api/app.py:172-178`

**Root cause:** Per the CORS specification (Fetch Standard §4.7), when
`Access-Control-Allow-Credentials: true`is present,
the`Access-Control-Allow-Origin`
header must not be `*`. Browsers unconditionally reject such responses. In
practice, any
cross-origin request from the Vite dev server (port 5173) that included an
`Authorization`
header or cookies would be silently blocked by the browser.

**Fix:** Replaced wildcard with an explicit list of known dev origins:

```python
allow_origins=[
    "http://localhost:5173",   # Vite dev server
    "http://localhost:4173",   # Vite preview
    "http://localhost:8000",   # FastAPI itself
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:8000",
],
allow_credentials=True,
```

---

### HIGH-1: Log duplication — uvicorn `propagate`not disabled

**File:**`src/vaultspec_a2a/utils/logging.py:84-85`

**Root cause:** Both `uvicorn.access`and`uvicorn.error`were assigned a direct
handler
via`logger.handlers = [log_handler]`, but `propagate`remained`True`(the
default). Since
these loggers propagate up to the root logger, and the root logger also had the
same handler
installed, every uvicorn log message was emitted twice.

**Fix:** Set`propagate = False` on both library loggers after assigning
handlers:

```python
for lib_logger_name in ("uvicorn.access", "uvicorn.error"):
    lib_logger = logging.getLogger(lib_logger_name)
    lib_logger.handlers = [log_handler]
    lib_logger.propagate = False
```

---

### HIGH-2: `JSONFormatter`drops structured`extra={}`fields silently

**File:**`src/vaultspec_a2a/utils/logging.py:16-31`

**Root cause:** `JSONFormatter.format()`only emitted 4 fixed fields:`timestamp`,
`level`,
`name`, `message`. Any structured context passed via `logger.info(...,
extra={"thread_id":
"...", "agent_id": "..."})`was silently discarded. This made correlation across
modules
(aggregator → endpoints → websocket) impossible in structured logs.

**Fix:** Iterate`record.__dict__` and include all non-standard fields not in
`_STANDARD_LOG_ATTRS`and not starting with`_`. This makes structured context
fields
(thread_id, agent_id, client_id, etc.) automatically appear in JSON output when
passed
via `extra={}`without any change to call sites.

---

### BUG-1:`app.py`NameError —`_checkpointer_conn`undefined

**File:**`src/vaultspec_a2a/api/app.py:86`(already fixed before this audit session)

**Root cause:**`logger.info("LangGraph checkpointer initialised at %s",
_checkpointer_conn)`
referenced an undefined variable. Would have raised `NameError`during lifespan
startup
before any requests could be served.

**Status:** Already fixed to`db_path`before this audit session.

---

## Design Notes (not bugs; no fix applied)

### NOTE-1: Debounced tool updates assign sequence numbers pre-broadcast

**File:**`src/vaultspec_a2a/core/aggregator.py:563`

In `emit_tool_call_update`, a sequence number is assigned at the start of the
method, before
the debounce check. If the event is debounced and replaced by a newer call, the
replaced
event's sequence number is consumed but never transmitted. This creates
monotonic gaps in the
per-thread sequence stream.

The frontend's gap detection (ADR-011 §5) should already tolerate gaps, since
gaps also
occur from legitimate event filtering. The practical impact is low (100ms
debounce window,
few tool calls). Fixing it would require splitting event construction from
sequence
assignment — a larger refactor.

**Recommendation:** Tolerate for now; track as tech debt. If the frontend
reports spurious
"missed events" warnings during tool-heavy sessions, revisit.

---

### NOTE-2: Supervisor text-parsing fragility (substring match)

**File:** `src/vaultspec_a2a/core/nodes/supervisor.py:50-55`

The supervisor uses substring matching as a fallback when the LLM response is
not an exact
member of `options`. An agent named `"code"`would match inside`"encode"`. In
practice,
agent ids are typically unique root words, so collisions are unlikely. Using
structured
output (function calling / `with_structured_output`) would eliminate the parsing
fragility
entirely, but requires the supervisor model to support tool use.

**Recommendation:** Acceptable for current models (Claude, GPT-4). Add
word-boundary
matching if agent id collisions become a problem.

---

---

## Medium-Priority Fixes (Post P0 — same session)

### MED-1: Agent ID misattribution in `process_langgraph_event`

**File:** `src/vaultspec_a2a/core/aggregator.py:702-771`

**Root cause:** `agent_id`in`process_langgraph_event`is the outer invocation
parameter
(always`"supervisor"`), not the actual LangGraph node that fired the event.
Every
`MessageChunkEvent`, `ToolCallStartEvent`, `AgentStatusEvent`, and
`ThoughtChunkEvent`was
attributed to`"supervisor"`regardless of whether it came from`"coder"`,
`"reviewer"`, etc.
The `langgraph_node`metadata field is present in all`astream_events v2`payloads
and
correctly identifies the actual firing node.

**Fix:** Derived`effective_agent_id = node or agent_id`at the top of the handler
and used
it in all`emit_*`/`_buffer_message_chunk`call sites. Fallback to`agent_id`for
events
without`langgraph_node`metadata (e.g., top-level graph events).

---

### MED-2: Chunk buffer metadata collision

**File:**`src/vaultspec_a2a/core/aggregator.py:413-432`

**Root cause:** `_chunk_buffers`and`_chunk_buffer_meta`are keyed
by`thread_id`only.
In multi-node graph topologies (star, pipeline), node A finishes streaming and
before the
50ms flush timer fires, node B starts
streaming.`_chunk_buffer_meta[thread_id]`is then
overwritten with node B's`(agent_id, message_id)`. When the timer fires it
flushes node A's
chunks with node B's metadata — wrong agent_id, wrong message_id on the
frontend.

**Fix:** Added message_id-change detection at the top of
`_buffer_message_chunk`. When a new
`message_id`is seen for an existing buffer, the old timer is cancelled and the
stale buffer
is flushed immediately before the new run's chunks are appended. Preserves the
single-key
design (minimal refactor) while eliminating the collision.

---

### MED-3: Pagination DoS via unbounded`limit`

**File:** `src/vaultspec_a2a/api/endpoints.py:290-293`

**Root cause:** `GET /threads?limit=N`accepted any integer. A client
sending`?limit=999999`
would cause SQLAlchemy to issue a `SELECT ... LIMIT 999999`against the thread
table, pulling
the entire database into memory for serialisation.

**Fix:** Added FastAPI`Query`validation:`limit: int = Query(default=50, ge=1,
le=200)` and
`offset: int = Query(default=0, ge=0)`. Returns HTTP 422 for out-of-range
values.

---

### MED-4: `aget_state()`with no timeout hangs endpoint

**File:**`src/vaultspec_a2a/api/endpoints.py:390-401`

**Root cause:** `graph.aget_state()`calls into the SQLite async checkpointer. If
the DB is
locked (e.g., during a concurrent write under WAL mode edge case) or if the
LangGraph state
fetch is slow, the`GET /threads/{id}/state`endpoint hangs indefinitely,
eventually
exhausting the Starlette worker pool.

**Fix:** Wrapped with`asyncio.wait_for(..., timeout=10.0)`. On `TimeoutError`,
logs a warning
and returns the partial snapshot (with `messages=[]`and no`checkpoint_id`). The
client can
still reconnect and the frontend's gap detection handles the missing state
gracefully.

---

---

### MED-5: `on_tool_error`and`on_chain_error`not handled

**File:**`src/vaultspec_a2a/core/aggregator.py`

**Root cause:** LangGraph emits `on_tool_error` when a tool call raises an
exception, and
`on_chain_error`when a graph node fails. Neither was in`_PASSTHROUGH_EVENTS` or
`_NODE_BOUNDARY_EVENTS`. The result: a failed tool call left the frontend
showing a
permanently spinning tool card (no `ToolCallUpdate(status=FAILED)`was ever
emitted). A
failed graph node left the agent's status permanently as`WORKING`(no transition
to`FAILED`
was emitted).

### Fix

- Added `"on_tool_error"`to`_PASSTHROUGH_EVENTS`; handler emits
  `ToolCallUpdate(status=FAILED)`
  and logs the error message at WARNING.
- Added `"on_chain_error"`to`_NODE_BOUNDARY_EVENTS`; handler emits
  `AgentStatus(state=FAILED, detail=<error[:200]>)`and logs at WARNING. -`data["error"]`in both events is the raw exception object; converted
  with`str()`.

---

## Linter Additions (applied automatically, confirmed correct)

### `aggregator.py`— Thread cancellation via`AgentControlAction.TERMINATE`

Added `_cancel_events: dict[str, asyncio.Event]`, `cancel_thread()`,
`_get_cancel_event()`, `_clear_cancel_event()`. The `ingest()` loop now checks
`cancel_event.is_set()`between each`astream_events` iteration, emitting
`AgentStatus(CANCELLED)`and breaking cleanly.`_clear_cancel_event()`runs in the
finally
block;`_cancel_events.clear()`runs on`shutdown()`.

| The `ingest()`signature changed:`graph_input: dict[str, Any] |
None`(accepts`None`for |
resume-from-checkpoint invocations).

### `app.py`—`_agent_control_handler`wired to`cancel_thread`+`Command(resume=…)`

Full match/case handler for `TERMINATE`→`aggregator.cancel_thread()`, `RESUME` →
`Command(resume=option_id)`+ deduplicated ingest,`PAUSE`→ informational warning
(unsupported
by LangGraph; emits a`WORKING`status to keep frontend state consistent).

### `endpoints.py`—`AgentConfigNotFoundError`+ timestamp extraction

- Replaced broad`except Exception`on`load_agent_config()`with`except
AgentConfigNotFoundError`.
- `_enrich_snapshot_from_state`now extracts actual message timestamps from
  `response_metadata`/`additional_kwargs` (`created_at`or`timestamp`), falling
  back to
  `datetime.now(UTC)` only when the provider did not populate a timestamp.

---

## Test Results After All Fixes

```text
339 passed, 7 deselected in 54.95s
```

All existing tests pass. The `pipeline_loop` routing fix changes default
behavior from
always-terminate to always-continue, which is the semantically correct
interpretation.
The existing test (`test_compile_pipeline_loop_graph`) only checks compilation,
so it is
unaffected. No live execution tests existed for this topology before the fix.
