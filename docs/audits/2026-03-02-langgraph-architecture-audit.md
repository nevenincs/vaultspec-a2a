# LangGraph Architecture Audit — 2026-03-02

Synthesised from two parallel investigations:

1. **Docs agent** — exhaustive read of the LangGraph source in
   `knowledge/repositories/langgraph/` covering state channels, error handling,
   `Command`/`Send` routing, streaming semantics, interrupt mechanics, and
   `RetryPolicy` internals.
2. **Codebase audit agent** — line-level review of all core orchestration files
   (`graph.py`, `worker.py`, `supervisor.py`, `state.py`, `context.py`, all
   presets, all tests, provider integration).

Where findings from both sources overlap they are marked **⚠ confirmed**.

---

## Already Correct — Do Not Change

| Item                                                        | Location        | Status                                                |
| ----------------------------------------------------------- | --------------- | ----------------------------------------------------- |
| `messages` uses `add_messages` reducer                      | `state.py:101`  | ✓ ID-based dedup prevents ghost duplicates on retry   |
| `loop_count` is last-write-wins (no reducer)                | `state.py:98`   | ✓ Sequential pipeline_loop — no concurrent write race |
| `interrupt_before=[]` always                                | `graph.py:186`  | ✓ ADR-013 override in force                           |
| `model_copy()` per invocation for permission_callback       | `worker.py:151` | ✓ Isolates callback reference correctly               |
| `artifacts` uses custom dedup reducer                       | `state.py:84`   | ✓                                                     |
| Logging added to `worker.py` / `supervisor.py` / `graph.py` | recent          | ✓                                                     |

---

## CRITICAL

### C1 — Supervisor routing failure is silent (no state field, only a log)

**File:** `lib/core/nodes/supervisor.py:88-92`

The warning log added in the latest session is not visible to callers, the API,
or the frontend. When the supervisor cannot parse a valid worker name from the
LLM response it silently returns `{"next": "FINISH"}`, which ends the graph.
There is no state field that records _why_ the graph ended; the client sees a
normal completion.

**Doc mandate:** Nodes that fail to produce intended state should surface the
failure in state (or raise) so the checkpointer persists it and the API can
expose it.

**Fix direction:** Add an optional `routing_error: NotRequired[str]` field to
`TeamState`. On parse failure, return
`{"next": "FINISH", "routing_error": f"supervisor could not parse route from: {text!r}"}`.

---

### C2 — Supervisor uses fragile text parsing; structured output is the canonical approach

**File:** `lib/core/nodes/supervisor.py:72-82`

`with_structured_output(RouteSchema)` is the LangGraph-recommended way to
enforce a valid routing decision. The current substring scan over `options`
breaks when:

- Worker names are substrings of each other (e.g. `"code"` / `"coder"`)
- The model produces a chain-of-thought preamble before the keyword
- The model responds in a different language or uses synonyms

Longer-term this should become `Command(goto=response.next)` which collapses
routing state + edge dispatch into one step.

**Doc mandate:**

> "Structured output fails loudly (Pydantic validation error) rather than
> silently misrouting."

**Fix direction (two-phase):**

1. _Short term_: sort `options` by descending length before substring scan so
   longer names always match first (prevents `"code"` eating `"coder"`).
2. _Medium term_: switch supervisor to `llm.with_structured_output(RouteSchema)`
   where `RouteSchema` is a Pydantic model with
   `next: Literal["worker1", "worker2", ..., "FINISH"]`.

---

### C3 — `state["next"]` KeyError crashes graph on first star-topology invocation

**File:** `lib/core/graph.py:299` (conditional edge lambda)

```python
lambda state: state["next"]   # raises KeyError if next not in state
```

The initial state supplied by the API client contains only `messages`. `next`
is not in `TeamState` as `NotRequired`, it has no default value, and the client
has no obligation to set it. On the first star-topology run `state["next"]` is
undefined → `KeyError` propagates through LangGraph as an uncaught exception.

**Fix direction:**

1. Change the lambda to `lambda state: state.get("next", "")`.
2. Mark `next` as `NotRequired[str]` in `TeamState` and document that
   the supervisor always sets it before any conditional edge reads it.

---

## HIGH

### H1 — No `RetryPolicy` on any node

**Files:** `lib/core/graph.py:267-283`, `lib/core/graph.py:363-378`,
`lib/core/graph.py:508-516`

All three topology compilers call `builder.add_node()` without a `retry`
argument. Every transient LLM failure (rate limit, 429, connection reset,
5xx) immediately fails the entire multi-agent run.

**Doc internals** (`pregel/_retry.py`):

- `default_retry_on` retries on `ConnectionError` and
  `httpx.HTTPStatusError` with status ≥ 500.
- It does NOT retry `RuntimeError`, `ValueError`, `OSError` — auth errors and
  model-not-found errors (like the Zhipu `BadRequestError` we hit) fall through
  immediately, which is correct behaviour (they are not transient).
- `task.writes.clear()` before each retry — no partial-write pollution.
- `GraphBubbleUp` (interrupt/Command) is never retried — permission flows are safe.

**Fix direction:**

```python
from langgraph.types import RetryPolicy

_WORKER_RETRY = RetryPolicy(
    initial_interval=1.0,
    backoff_factor=2.0,
    max_interval=30.0,
    max_attempts=3,
    jitter=True,
)

builder.add_node(agent_cfg.id, worker_node, retry=_WORKER_RETRY, metadata={...})
```

Apply the same policy to the supervisor node. Do NOT apply to nodes with
irreversible side effects.

---

### H2 — Worker exceptions propagate without agent identity in the exception

**File:** `lib/core/nodes/worker.py:168-176`

The `try/except` added in the latest session logs the agent name, but the
re-raised exception is the raw provider exception (e.g. `BadRequestError`).
LangGraph's stream caller receives this exception with no indication of which
agent failed, what model was in use, or how many messages were in context.

When `RetryPolicy` exhausts its attempts it raises the final exception to
the caller — that exception should carry enough context to make the error
actionable without needing to inspect Jaeger traces.

**Fix direction:** Wrap in a domain exception:

```python
class WorkerExecutionError(RuntimeError):
    """Raised when a worker node's model invocation fails after all retries."""

# In worker_node():
except Exception as exc:
    _logger.exception("worker[%s] model=%s raised", name, model_type)
    raise WorkerExecutionError(
        f"worker={name!r} model={model_type} messages={len(messages)}"
    ) from exc
```

Note: `WorkerExecutionError` inherits `RuntimeError`, which is NOT retried by
`default_retry_on`. This is intentional — retries are handled by `RetryPolicy`
at the LangGraph level; the domain exception is raised only after all retries
are exhausted.

---

### H3 — Supervisor node receives full message history (no context compaction)

**File:** `lib/core/nodes/supervisor.py:52-54`

Worker nodes call `compact_context()` when approaching `_CONTEXT_LIMIT`
(120k tokens). The supervisor node passes the raw `state["messages"]` list
directly to the model. On a long coding session the supervisor will eventually
hit provider context limits while workers do not.

**Fix direction:** Apply the same compaction guard used in `worker.py`:

```python
working_state = (
    compact_context(state, _CONTEXT_LIMIT)
    if should_compact(state, _CONTEXT_LIMIT)
    else state
)
messages = [SystemMessage(content=full_prompt), *working_state["messages"]]
```

Import `_CONTEXT_LIMIT`, `compact_context`, `should_compact` from
`..context`.

---

### H4 — `next: str` declared required in `TeamState`; no default

**File:** `lib/core/state.py:102`

`next: str` (no `NotRequired`) means the TypedDict technically requires `next`
to be present on construction. In practice the API's initial state never sets
it. Combined with C3 (the `state["next"]` lambda), the first graph invocation
on a star topology is fragile.

**Fix direction:** Change to `next: NotRequired[str]` and update the lambda
(see C3).

---

### H5 — Loop count not logged; loop termination invisible in traces

**File:** `lib/core/graph.py:479-496` (`_loop_node_with_counter`)

The wrapper increments `loop_count` silently. There is no log entry when a
loop iteration begins, completes, or when `max_loops` is hit. Diagnosing
runaway pipeline_loop topologies requires querying the checkpointer directly.

**Fix direction:** Add a `_logger` reference into `_wrap_loop_node()` (it needs
access to `team_config.id`, `loop_node_id`, and `max_loops`) and log at DEBUG
on each iteration, and at WARNING when the loop terminates due to `max_loops`.

---

## MEDIUM

### M1 — Supervisor routing LLM tokens are visible to users

**File:** `lib/core/nodes/supervisor.py:52`

Supervisor routing is an internal control-flow decision. Its tokens stream to
the client as visible `on_chat_model_stream` events, polluting the UI with
internal "coder | reviewer | FINISH" tokens.

**Doc mandate:** Use `TAG_NOSTREAM` on the routing model to suppress streaming:

```python
from langgraph.constants import TAG_NOSTREAM

routing_model = model.with_config({"tags": [TAG_NOSTREAM]})
response = await routing_model.ainvoke(messages)
```

---

### M2 — `Command` objects not used; older `state["next"]` pattern

**File:** `lib/core/graph.py:293-299`, `lib/core/nodes/supervisor.py:67`

The current pattern is:

1. Supervisor returns `{"next": route_name}` → writes to state channel.
2. Conditional edge reads `state["next"]` → dispatches to worker.

The canonical LangGraph pattern is `Command(goto=route_name)` which:

- Collapses update + dispatch into one step (no intermediate state write).
- Eliminates the `state["next"]` field entirely from `TeamState`.
- Makes routing intent explicit and type-safe.

This is a medium-term refactor, not an urgent fix. The existing pattern works
but is two steps where one suffices.

---

### M3 — Routing options use insertion-order substring scan

**File:** `lib/core/nodes/supervisor.py:77-82`

When `options = ["coder", "code", "reviewer", "FINISH"]` and the supervisor
says `"the code agent should handle this"`, the current loop returns `"coder"`
(first match) — correct by luck. If `options = ["code", "coder", ...]` it
returns `"code"` — wrong.

**Fix direction (short term):** Sort `options` by descending length before
the substring loop:

```python
for option in sorted(options, key=len, reverse=True):
    if option.lower() in text.lower():
        next_route = option
        break
```

---

### M4 — `_wrap_loop_node` captures no `max_loops` reference for logging

**File:** `lib/core/graph.py:439-456`

`_wrap_loop_node()` only receives the `worker_node` callable. It has no
reference to `max_loops` or `loop_node_id`, preventing meaningful loop-progress
logging without restructuring the wrapper signature.

**Fix direction:** Pass `max_loops` and `loop_node_id` into the wrapper factory
so the inner function can log `"loop iteration {n}/{max}"`.

---

### M5 — No test coverage for star topology KeyError on missing `next`

**File:** `lib/core/tests/test_graph.py`

No test exercises what happens when a star-topology graph is invoked with
initial state that omits the `next` field. This is the exact condition that
causes C3.

---

### M6 — No test for supervisor routing ambiguity (substring collision)

**File:** `lib/core/tests/test_graph.py`

No unit test creates a supervisor with workers named `"code"` and `"coder"`
and verifies the correct one is selected when the supervisor responds
`"the coder should handle this"`.

---

## LOW

### L1 — Log truncation at 80/120 chars may hide routing information

**File:** `lib/core/nodes/supervisor.py:90-92`

`text[:120]` in the warning log may cut off the actual routing keyword if the
model produces a long preamble. Increase to 500 chars or log full response at
DEBUG and truncated at WARNING.

---

### L2 — `_resolve_supervisor_model` capability log uses `.value` without guard

**File:** `lib/core/graph.py:101`

`capability.value if capability else "default"` — already correct after the
recent logging additions. Confirm this guard is present (verified: it is).

---

### L3 — `recursion_limit` defaults are low for multi-agent pipelines

**Files:** `lib/core/tests/test_e2e_live.py:136`, `probes/probe_graph_openai.py:91`

Pipeline tests use `recursion_limit: 20`. A three-agent pipeline with one
loop iteration consumes at minimum 3 supersteps. With `RetryPolicy` retries,
each retry is a separate superstep. For the star topology with 5 worker
dispatches, `recursion_limit: 15` may be insufficient. Default of 25 is
usually fine for pipelines, but document the budget calculation.

---

## Prioritised Action Plan

| Priority | ID        | Work item                                                                          | Effort |
| -------- | --------- | ---------------------------------------------------------------------------------- | ------ |
| 1        | C3        | `state.get("next", "")` in conditional edge lambda + `NotRequired`                 | XS     |
| 2        | C2-phase1 | Sort options by descending length (M3)                                             | XS     |
| 3        | H1        | Add `RetryPolicy` to all `add_node()` calls                                        | S      |
| 4        | C1        | Add `routing_error: NotRequired[str]` to `TeamState`; return it on FINISH fallback | S      |
| 5        | H2        | `WorkerExecutionError` domain exception                                            | S      |
| 6        | H3        | Context compaction in supervisor node                                              | S      |
| 7        | M1        | `TAG_NOSTREAM` on supervisor routing model                                         | XS     |
| 8        | H5 + M4   | Loop count logging with `max_loops` in wrapper                                     | S      |
| 9        | C2-phase2 | Structured output (`with_structured_output`) for supervisor routing                | M      |
| 10       | M2        | Migrate routing to `Command(goto=...)`                                             | L      |

XS = < 30 min, S = 30–90 min, M = half-day, L = full-day.

---

## ADR Impact

| ADR          | Impact                                                                                          |
| ------------ | ----------------------------------------------------------------------------------------------- |
| ADR-013 §2.5 | `Command(goto=...)` replaces `state["next"]` + conditional edge (M2) — future ADR update needed |
| ADR-013 §2.3 | No change — provider resolution chain is correct                                                |
| ADR-013 §2.7 | No change — `interrupt_before=[]` is confirmed correct                                          |
| ADR-008      | `routing_error` field addition to `TeamState` is backward-compatible (NotRequired)              |
| ADR-002      | Supervisor compaction (H3) is consistent with existing context management strategy              |
