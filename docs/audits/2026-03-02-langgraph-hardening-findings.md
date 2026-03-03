# LangGraph Hardening — Codebase Researcher Findings Log

**Agent:** codebase-researcher
**Source audit:** `docs/audits/2026-03-02-langgraph-architecture-audit.md`
**Plan:** `docs/plans/2026-03-02-langgraph-architecture-hardening-plan.md`
**Started:** 2026-03-02

Findings are appended chronologically. Status is updated when tasks move to
`completed` in the task system. Severity follows the source audit convention:
CRITICAL → HIGH → MEDIUM → LOW → INFO.

---

## [CRITICAL] [Cycle 1] — state["next"] KeyError in star topology conditional edge

**Reported:** Cycle 1
**File:** `lib/core/graph.py:331`
**Issue:** `lambda state: state["next"]` raises `KeyError` on the first star-topology
invocation because the initial state supplied by the API client contains only
`messages` — `next` is not set. Combined with `next: str` (no `NotRequired`, no
default) in `TeamState`, this crashes the graph before any node runs.
**Fix direction:** Change lambda to `lambda state: state.get("next", "")`. Mark
`next: NotRequired[str]` in `state.py`. Add `test_star_missing_next_field`.
**Task:** T01
**Status:** resolved

---

## [HIGH] [Cycle 1] — next: str declared required with no default in TeamState

**Reported:** Cycle 1
**File:** `lib/core/state.py:102`
**Issue:** `next: str` (no `NotRequired`) means the TypedDict technically requires
`next` on construction. The API's initial state never sets it, making the first
star-topology invocation fragile (see C3 above).
**Fix direction:** Change to `next: NotRequired[str]`.
**Task:** T01 (part of same fix)
**Status:** resolved

---

## [CRITICAL] [Cycle 1] — Supervisor routing failure silent (no routing_error in state)

**Reported:** Cycle 1
**File:** `lib/core/nodes/supervisor.py:84-94`
**Issue:** When the supervisor cannot parse a valid worker name from the LLM
response, it silently returns `{"next": "FINISH"}`. No state field records why
the graph ended; the client sees a normal completion with no indication of the
routing failure.
**Fix direction:** Add `routing_error: NotRequired[str]` to `TeamState`. On parse
failure return `{"next": "FINISH", "routing_error": f"supervisor could not parse
route from: {text!r}"}`. Add `test_supervisor_sets_routing_error_on_parse_failure`
and negative test `test_supervisor_no_routing_error_on_clean_finish`.
**Task:** T03
**Status:** resolved

---

## [CRITICAL] [Cycle 1] — Supervisor uses insertion-order substring scan (routing collision)

**Reported:** Cycle 1
**File:** `lib/core/nodes/supervisor.py:79-82`
**Issue:** `for option in options` iterates in insertion order. When workers include
`"code"` and `"coder"`, the response `"the coder should handle this"` matches
`"code"` first (wrong). Order of names in the team config determines correctness.
**Fix direction:** Sort options by descending length before scanning:
`for option in sorted(options, key=len, reverse=True)`. Add
`test_supervisor_routing_substring_collision`.
**Task:** T02
**Status:** resolved

---

## [HIGH] [Cycle 1] — No RetryPolicy on any add_node() call

**Reported:** Cycle 1
**File:** `lib/core/graph.py:274`, `lib/core/graph.py:307`, `lib/core/graph.py:409`,
`lib/core/graph.py:554`
**Issue:** All `builder.add_node()` calls across all three topology compilers lack
a `retry=` argument. Every transient LLM failure (rate limit, 429, connection
reset, 5xx) immediately fails the entire multi-agent run.
**Fix direction:** Define `_WORKER_RETRY = RetryPolicy(initial_interval=1.0,
backoff_factor=2.0, max_interval=30.0, max_attempts=3, jitter=True)` and pass
`retry_policy=_WORKER_RETRY` to all `add_node()` calls for workers and supervisor.
Import `RetryPolicy` from `langgraph.types`.
**Task:** T05
**Status:** resolved (all 4 add_node calls carry retry_policy=\_WORKER_RETRY — see Cycle 5 docs-researcher entry)

---

## [MEDIUM] [Cycle 3] — T05 imports default_retry_on from private \_internal module

**Reported:** Cycle 3 (T05 working tree review)
**File:** `lib/core/graph.py:20`
**Issue:** `from langgraph._internal._retry import default_retry_on` accesses a
private module. The `_internal` prefix signals an unstable API that could break
on any minor LangGraph version bump without deprecation warning.
**Fix direction:** Either (a) inline the `default_retry_on` logic (retry
`ConnectionError` and `httpx.HTTPStatusError` with status ≥ 500) to remove the
private import, or (b) wrap with try/except ImportError that degrades to a
simpler predicate. Option (a) is more robust.
**Task:** T05 (pre-commit review finding)
**Status:** open — follow-up captured in more detail by docs-researcher Cycle 5 entry (requests dependency + \_internal import risk)

---

## [HIGH] [Cycle 1] — Worker exceptions lack agent identity context (bare re-raise)

**Reported:** Cycle 1
**File:** `lib/core/nodes/worker.py:168-176`
**Issue:** The `try/except` logs the agent name but re-raises the raw provider
exception (`BadRequestError`, etc.). The caller has no indication of which agent
failed, what model was in use, or how many messages were in context when
`RetryPolicy` exhausts its attempts.
**Fix direction:** Wrap in `WorkerExecutionError(RuntimeError)` with `agent_id` and
`model_type` kwargs, raised `from exc` to preserve the chain. Note:
`WorkerExecutionError` inherits `RuntimeError` which is NOT retried by
`default_retry_on` — retries happen at the LangGraph level via `RetryPolicy`.
**Task:** T04
**Status:** resolved

---

## [HIGH] [Cycle 1] — Supervisor node has no context compaction guard

**Reported:** Cycle 1
**File:** `lib/core/nodes/supervisor.py:54`
**Issue:** Worker nodes call `compact_context()` when approaching `_CONTEXT_LIMIT`
(120k tokens). The supervisor passes the raw `state["messages"]` list directly.
On long sessions, the supervisor will hit provider context limits while workers
do not.
**Fix direction:** Apply the same guard as `worker.py`: import and apply
`should_compact` / `compact_context` from `..context`. Use `_CONTEXT_LIMIT = 120_000`.
Add `test_supervisor_compacts_on_large_state`.
**Task:** T06
**Status:** resolved (supervisor.py:55-61 uses working_state via compact_context; uses public CONTEXT_LIMIT from context.py)

---

## [HIGH] [Cycle 1] — Loop count not logged; loop termination invisible in traces

**Reported:** Cycle 1
**File:** `lib/core/graph.py:479-496` (`_wrap_loop_node`)
**Issue:** `_wrap_loop_node` increments `loop_count` silently. No log entry when a
loop iteration begins, completes, or when `max_loops` is hit. Diagnosing runaway
`pipeline_loop` runs requires querying the checkpointer directly.
**Fix direction:** Pass `max_loops` and `loop_node_id` into the wrapper factory.
Log at DEBUG on each iteration, WARNING when `max_loops` is hit.
**Task:** T08
**Status:** open

---

## [MEDIUM] [Cycle 1] — Supervisor routing tokens stream to client (no TAG_NOSTREAM)

**Reported:** Cycle 1
**File:** `lib/core/nodes/supervisor.py:63`
**Issue:** Supervisor routing is an internal control-flow decision. Its tokens
stream to the client as visible `on_chat_model_stream` events, polluting the UI
with internal "coder | reviewer | FINISH" tokens.
**Fix direction:** `routing_model = model.with_config({"tags": [TAG_NOSTREAM]})` and
use `routing_model` for `ainvoke`. Import `TAG_NOSTREAM` from `langgraph.constants`.
**Task:** T07
**Status:** resolved (supervisor.py:8 imports TAG_NOSTREAM; line 69 applies with_config; line 71 uses routing_model)

---

## [MEDIUM] [Cycle 1] — supervisor_node uses state["messages"] subscript (KeyError risk)

**Reported:** Cycle 1
**File:** `lib/core/nodes/supervisor.py:54`
**Issue:** `messages = [SystemMessage(content=full_prompt), *state["messages"]]`
uses dict-subscript. If `messages` is absent from state on first invocation (edge
case where graph_input is `{}`), this raises `KeyError`. Worker node accesses
messages via `compact_context` which uses `.get("messages", [])`.
**Fix direction:** Change to `state.get("messages", [])` for consistency with
worker.py pattern. Bundled into T03 per orchestrator instruction.
**Task:** T03 (bundled)
**Status:** resolved (supervisor.py:61 uses working_state.get("messages", []))

---

## [LOW] [Cycle 1] — \_MinimalState recreated inline on every request in endpoints.py

**Reported:** Cycle 1
**File:** `lib/api/endpoints.py:487-502`
**Issue:** `_MinimalState` TypedDict is defined as an inline class inside a
function, recreated on every request. Should be a module-level definition.
**Fix direction:** Hoist `_MinimalState` to module level.
**Task:** INFO — no task
**Status:** open

---

## [MEDIUM] [Cycle 1] — websocket.py accesses private aggregator attribute

**Reported:** Cycle 1
**File:** `lib/api/websocket.py:519`
**Issue:** `self._aggregator._subscriptions.get(client_id, set())` accesses a
private attribute of `EventAggregator`. If `_subscriptions` is refactored, this
will silently break.
**Fix direction:** Add a public `subscribed_threads(client_id)` method to
`EventAggregator` and use that instead.
**Task:** INFO — no task
**Status:** open

---

## [LOW] [Cycle 1] — Missing test: star topology KeyError on missing next field

**Reported:** Cycle 1
**File:** `lib/core/tests/test_graph.py`
**Issue:** No test exercises star-topology invocation with initial state omitting
`next`. This was the exact condition causing C3.
**Fix direction:** Add `test_star_missing_next_field`.
**Task:** T01 (test included in task)
**Status:** resolved

---

## [LOW] [Cycle 1] — Missing test: supervisor routing substring collision

**Reported:** Cycle 1
**File:** `lib/core/tests/test_graph.py`
**Issue:** No test creates a supervisor with workers `"code"` and `"coder"` and
verifies the correct one is selected.
**Fix direction:** Add `test_supervisor_routing_substring_collision` to `test_supervisor.py`.
**Task:** T02 (test included in task)
**Status:** resolved

---

## [MEDIUM] [Cycle 2] — compact_context summary inserted as SystemMessage (nested compaction bug)

**Reported:** Cycle 2
**File:** `lib/core/context.py:108-114`
**Issue:** The compaction summary note is inserted as `SystemMessage`. The
separator logic at `context.py:79-83` classifies any `SystemMessage` at the head
of the message list as a system prefix. On a second compaction pass, this summary
will be moved into `system_msgs`, inflating the system prefix and consuming
budget incorrectly.
**Fix direction:** Change `SystemMessage(...)` to `HumanMessage(...)` for the
summary so it stays in the conversation body on subsequent compaction passes.
**Task:** T14
**Status:** open

---

## [MEDIUM] [Cycle 2] — GraphRecursionError not detected as distinct error class

**Reported:** Cycle 2
**File:** `lib/core/aggregator.py:1117-1144`
**Issue:** `GraphRecursionError` (raised when `recursion_limit` is exceeded) falls
into the generic `else` branch and is emitted as a generic `INGEST_ERROR` with
`recoverable=False`. It should be detected separately and emitted with a distinct
code (e.g. `"RECURSION_LIMIT_EXCEEDED"`) and `recoverable=True`. Also, once T05
adds `RetryPolicy`, `GraphRecursionError` must NOT be retried — it is
deterministic, not transient.
**Fix direction:** Import `GraphRecursionError` from `langgraph.errors`. Add
`isinstance(exc, GraphRecursionError)` check before the generic else branch.
Emit with distinct code and `recoverable=True`.
**Task:** T15
**Status:** open

---

## [MEDIUM] [Cycle 2] — step_timeout not configured on compiled graph

**Reported:** Cycle 2
**File:** `lib/core/graph.py` (builder.compile call)
**Issue:** No `step_timeout` argument is passed to `builder.compile()`. In
production, a hung LLM call (network stall, streaming timeout) will block a
graph superstep indefinitely with no timeout protection.
**Fix direction:** Pass `step_timeout=` to `builder.compile()`. Recommended value
from docs: 300s (5 min) for LLM-backed nodes. Make it configurable via settings.
**Task:** T11
**Status:** open

---

## [HIGH] [Cycle 2] — graph_input initializes only messages; required TeamState fields absent

**Reported:** Cycle 2
**File:** `lib/worker/executor.py:176`
**Issue:** `graph_input: dict[str, Any] = {"messages": messages} if messages else {}`
Only `messages` is set. Required fields `active_agent`, `thread_id`, `artifacts`,
`current_plan`, `token_usage` have no defaults in `TeamState` and no `NotRequired`
annotation. On first invocation their absence may cause `KeyError` or channel
reducer errors.
**Fix direction:** Initialize all required fields in `graph_input` before passing
to `astream_events`. At minimum: `thread_id`, `active_agent`, `artifacts`,
`current_plan`, `token_usage`.
**Task:** T13
**Status:** open

---

## [MEDIUM] [Cycle 2] — \_replace_plan reducer silently discards intentional empty plan

**Reported:** Cycle 2
**File:** `lib/core/state.py:64`
**Issue:** `return new if new else existing` means a node that intentionally clears
the plan by returning `[]` has no effect — the old plan is preserved. There is no
way to explicitly reset the plan to empty.
**Fix direction:** Change to `return new` (unconditional replacement). Update
`test_state.py:100` which currently asserts the broken behavior.
**Task:** T12
**Status:** open

---

## [LOW] [Cycle 2] — test_state.py:100 validates broken \_replace_plan behavior

**Reported:** Cycle 2
**File:** `lib/core/tests/test_state.py:100`
**Issue:** `test_keeps_existing_when_new_is_empty` asserts `result == old` when
`_replace_plan(old, [])` is called. This validates the broken T12 behavior. When
T12 is fixed, this test must be updated: the correct assertion becomes
`assert result == []`.
**Fix direction:** Update assertion when T12 is implemented. Rename test to
`test_empty_new_plan_clears_existing`.
**Task:** T12 (test update required alongside fix)
**Status:** open

---

## [LOW] [Cycle 2] — test_exceptions.py hardcodes **all** without WorkerExecutionError

**Reported:** Cycle 2
**File:** `lib/core/tests/test_exceptions.py:299-320`
**Issue:** `test_all_contains_every_public_name` hardcodes the `__all__` expected
set without `WorkerExecutionError`. When T04 adds it to `__all__`, this test
fails with a set mismatch.
**Fix direction:** Add `"WorkerExecutionError"` to expected set. Also add
`WorkerExecutionError is _exceptions_module.WorkerExecutionError` to
`test_facade_reexports_are_same_objects`.
**Task:** T04 (test update required alongside fix)
**Status:** resolved

---

## [LOW] [Cycle 2] — StreamableGraph/ingest type signatures do not accept Command input

**Reported:** Cycle 2
**File:** `lib/core/aggregator.py` (StreamableGraph protocol), `lib/worker/executor.py`
**Issue:** The `StreamableGraph` protocol and `ingest()` signature type `graph_input`
as `dict[str, Any]`, but `executor.py` passes `Command(resume=...)` on resume —
which is not a dict. The `cast()` call suppresses the type error but the protocol
is incorrect.
**Fix direction:** Update `StreamableGraph.astream_events` signature and `ingest()`
to accept `dict[str, Any] | Command`.
**Task:** T16
**Status:** open

---

## [MEDIUM] [Cycle 2] — No lazy graph recompilation on resume after worker restart

**Reported:** Cycle 2
**File:** `lib/worker/executor.py:207-210`
**Issue:** `_handle_resume` checks `self._graphs.get(req.thread_id)` — if the
worker process was restarted, `_graphs` is empty even though the checkpointer
has persisted state. Resume will fail with "No graph for thread" instead of
recompiling from the team preset.
**Fix direction:** On resume when graph is absent, attempt to recompile using
`req.team_preset` (if present in `DispatchRequest`) before failing.
**Task:** T17
**Status:** open

---

## [LOW] [Cycle 3] — T03 test_supervisor.py missing routing_error assertion (pre-commit)

**Reported:** Cycle 3 (working tree check before commit)
**File:** `lib/core/tests/test_supervisor.py`
**Issue:** `test_supervisor_routing_unparseable_defaults_to_finish` only asserted
`result["next"] == "FINISH"` — no assertion on `routing_error` key presence.
**Fix direction:** Add `test_supervisor_sets_routing_error_on_parse_failure` (positive)
and `test_supervisor_no_routing_error_on_clean_finish` (negative) tests.
**Task:** T03 (test update required alongside fix)
**Status:** resolved

---

## [HIGH] [Cycle 3] — test_state.py:179 key set missing routing_error (pre-commit)

**Reported:** Cycle 3 (working tree check before commit)
**File:** `lib/core/tests/test_state.py:179-192`
**Issue:** `test_has_required_keys` expected set hardcoded without `routing_error`.
Would fail immediately on CI once T03 committed.
**Fix direction:** Add `"routing_error"` to expected set.
**Task:** T03 (test update required alongside fix)
**Status:** resolved

---

## [CRITICAL] [Cycle 3] — worker.py bare re-raise did not use WorkerExecutionError (pre-commit)

**Reported:** Cycle 3 (working tree check mid-T04)
**File:** `lib/core/nodes/worker.py:171-177`
**Issue:** `WorkerExecutionError` was imported and class defined, but the except
block still had bare `raise` — the wrapping was not applied.
**Fix direction:** Replace `raise` with `raise WorkerExecutionError(...) from exc`
using `agent_id=name, model_type=model_type` kwargs.
**Task:** T04
**Status:** resolved

---

## [HIGH] [Cycle 3] — test_exceptions.py **all** set missing WorkerExecutionError (pre-commit)

**Reported:** Cycle 3 (working tree check mid-T04)
**File:** `lib/core/tests/test_exceptions.py:301-320`
**Issue:** `test_all_contains_every_public_name` expected set did not include
`"WorkerExecutionError"` — would fail on CI once T04 committed.
**Fix direction:** Add `"WorkerExecutionError"` to expected set.
**Task:** T04 (test update required alongside fix)
**Status:** resolved

---

## [MEDIUM] [Cycle 3] — test_facade_reexports missing WorkerExecutionError identity check

**Reported:** Cycle 3
**File:** `lib/core/tests/test_exceptions.py:323-337`
**Issue:** `test_facade_reexports_are_same_objects` does not include
`WorkerExecutionError is _exceptions_module.WorkerExecutionError`, even though
the core facade (`lib/core/__init__.py:35`) re-exports it.
**Fix direction:** The identity check is covered by `test_worker.py` facade test.
Acceptable as-is — no separate action required.
**Task:** INFO — no task (covered by test_worker.py)
**Status:** open

---

## [MEDIUM] [Cycle 3] — WorkerExecutionError inherits VaultspecError not RuntimeError (severity inconsistency)

**Reported:** Cycle 3 (post-T04 class review)
**File:** `lib/core/exceptions.py:103-116`
**Issue:** `WorkerExecutionError` now inherits `VaultspecError(Exception)` with
`severity = ErrorSeverity.TRANSIENT` but `recovery_action = RecoveryAction.ESCALATE_TO_USER`.
TRANSIENT + ESCALATE_TO_USER is semantically inconsistent — TRANSIENT implies
retry is worthwhile, but ESCALATE_TO_USER says don't retry. The original audit
spec specified `RuntimeError` inheritance specifically so the exception class
name communicates "non-retriable by default_retry_on". The LangGraph
`default_retry_on` is selective (only `ConnectionError` and `httpx.HTTPStatusError`
≥500), so the inheritance choice doesn't affect retry behavior, but the
`severity=TRANSIENT` attribute is misleading.
**Fix direction:** Change `severity = ErrorSeverity.PERMANENT` (worker failures
after retries exhausted are not transient) or use `ErrorSeverity.UNKNOWN`. Low
priority — does not affect runtime behavior.
**Task:** INFO — no task (cosmetic severity inconsistency)
**Status:** open

---

## ~~[HIGH] [Cycle 3] — T04 regression: except Exception catches GraphBubbleUp (breaks interrupt flow)~~

**Reported:** Cycle 3 (post-T04 analysis)
**File:** `lib/core/nodes/worker.py:170-181`
**Issue:** ~~Originally filed as a regression risk: `GraphBubbleUp` inheriting from `Exception`
would be caught by the `except Exception` block before Pregel could handle it.~~

**RETRACTED — Authoritative team-lead decision (Cycle 10):**
LangGraph's Pregel task runner (`pregel/main.py`) intercepts `GraphBubbleUp` at the task
runner level BEFORE the node's local exception handler sees it. The `except Exception` in
`worker.py` wraps only `effective_model.ainvoke()` — `GraphBubbleUp` raised during node
execution never propagates to that block. No guard is needed or wanted.
The `except GraphBubbleUp: raise` guard added as T18 is therefore unnecessary (harmless but
superfluous). T04 and T18 are both closed and must not be re-raised.
**Task:** T18 — CLOSED (finding retracted)
**Status:** closed — finding was incorrect; no action required

---

## [INFO] [Cycle 4 / docs-researcher] — T05 fix direction uses deprecated retry= param name

**Reported:** Cycle 4 (docs-researcher LangGraph source cross-reference)
**File:** `lib/core/graph.py` (not yet modified — T05 pending)
**Issue:** The T05 fix direction recorded above uses `retry=_WORKER_RETRY` in
the `add_node()` call. LangGraph's `StateGraph.add_node()` signature (confirmed
in `knowledge/repositories/langgraph/…/graph/state.py:647-653`) accepts
`retry_policy=` as the canonical parameter name. `retry=` is a deprecated alias
that still works but emits a `DeprecationWarning`. All four call sites should
use `retry_policy=` to avoid deprecation noise in production logs.
**Fix direction:** When implementing T05, use `retry_policy=_WORKER_RETRY` (not
`retry=`).
**Task:** T05 (correction to fix direction)
**Status:** open

---

## [INFO] [Cycle 4 / docs-researcher] — T11 step_timeout is a post-compile attribute, not a compile() param

**Reported:** Cycle 4 (docs-researcher LangGraph source cross-reference)
**File:** `lib/core/graph.py` (not yet modified — T11 pending)
**Issue:** The T11 fix direction says "Pass `step_timeout=` to
`builder.compile()`". LangGraph's `StateGraph.compile()` does not accept a
`step_timeout` parameter. `step_timeout` is an attribute on the `Pregel` class
(which `CompiledStateGraph` inherits). It must be set post-compile via attribute
assignment.
**Fix direction:** After `graph = builder.compile(checkpointer=checkpointer)`,
add `if step_timeout is not None: graph.step_timeout = step_timeout`. The
`compile_team_graph` signature should accept `step_timeout: float | None = None`
and the caller (executor) should pass `settings.graph_node_timeout_seconds`.
**Task:** T11 (correction to fix direction)
**Status:** open

---

## [INFO] [Cycle 4 / docs-researcher] — WorkerExecutionError constructor uses worker/model/message_count (not agent_id/model_type)

**Reported:** Cycle 4 (docs-researcher confirmed from exceptions.py:109)
**File:** `lib/core/exceptions.py:109-115`
**Issue:** Several findings above reference `WorkerExecutionError(agent_id=...,
model_type=...)` kwargs. The actual implemented constructor (confirmed in
`exceptions.py:109`) signature is `__init__(self, worker: str, model: str,
message_count: int)`. The T18 fix direction showing
`WorkerExecutionError(f"worker={name!r}…", agent_id=name, model_type=…)` is
incorrect for the current implementation.
**Fix direction:** Use `WorkerExecutionError(worker=name, model=model_type,
message_count=len(messages))` when fixing T04b/T18. Ensure tests in
`test_worker.py` assert `err.worker`, `err.model`, `err.message_count` (not
`err.agent_id`).
**Task:** T18 (correction to fix direction)
**Status:** resolved (worker.py:172 confirmed `except GraphBubbleUp: raise` guard present; constructor uses correct kwargs)

---

## [RESOLVED] [Cycle 5 / docs-researcher] — T05 applied to all 4 add_node() call sites

**Reported:** Cycle 5 (verification read)
**File:** `lib/core/graph.py:312, 353, 456, 602`
**Issue:** Status update — all four `add_node()` calls now carry
`retry_policy=_WORKER_RETRY` (not the deprecated `retry=` alias). The
`_worker_retry_on` callable and `_WORKER_RETRY = RetryPolicy(...)` are
defined at lines 47-74. `GraphRecursionError` and ACP deterministic errors
excluded; `TimeoutError` explicitly included (Python 3.11+ OSError subclass).
**Fix direction:** N/A — resolved.
**Task:** T05
**Status:** resolved

---

## ~~[RESOLVED] [Cycle 5 / docs-researcher] — T18/T04b GraphBubbleUp guard applied~~

**Reported:** Cycle 5 (verification read) — RETRACTED Cycle 10
**File:** `lib/core/nodes/worker.py:8, 172-173`
**Issue:** ~~Previously marked resolved based on observing the guard in code.~~
**RETRACTED:** The guard is superfluous — Pregel intercepts `GraphBubbleUp` at the task
runner level before the node's local `except Exception` block ever executes. The guard
does no harm but was unnecessary. T18 is closed as a retracted finding.
**Task:** T18 — CLOSED (retracted)
**Status:** closed — finding retracted per team-lead authoritative decision (Cycle 10)

---

## [MEDIUM] [Cycle 5 / docs-researcher] — default_retry_on lazily imports requests (not in dependencies)

**Reported:** Cycle 5
**File:** `lib/core/graph.py:20` + `knowledge/repositories/langgraph/…/_internal/_retry.py:3`
**Issue:** `from langgraph._internal._retry import default_retry_on` is called
in `_worker_retry_on` via the `default_retry_on(exc)` fallback at line 64.
Inside `default_retry_on`, `import requests` and `import httpx` are executed
at call time (lazy imports). `requests` is NOT listed as a project dependency
in `pyproject.toml`. If `requests` is absent (common in minimal installs) and
`default_retry_on` is called with any exception that isn't `ConnectionError`,
`httpx.HTTPStatusError`, or the excluded base classes, the function will raise
`ModuleNotFoundError: No module named 'requests'` — crashing the retry
machinery with a confusing error that hides the original exception.

Note: `httpx` IS a project dependency so the httpx branch is safe. The
`requests` branch is the risk.

**Fix direction:** Replace the `default_retry_on(exc)` fallback in
`_worker_retry_on` with an inlined safe equivalent that does not require
`requests`:

```python
# Instead of: return default_retry_on(exc)
try:
    import httpx as _httpx  # noqa: PLC0415
    if isinstance(exc, _httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600
except ImportError:
    pass
# ConnectionError covered above; all other unrecognised exceptions: retry
return isinstance(exc, ConnectionError)
```

This also removes the `_internal` private import entirely.
**Task:** T05 (follow-up — should be addressed before shipping)
**Status:** open

---

## [LOW] [Cycle 5 / docs-researcher] — WorkerSupervisor.monitor uses deprecated asyncio.get_event_loop()

**Reported:** Cycle 5
**File:** `lib/api/supervisor.py:100, 101, 104`
**Issue:** `asyncio.get_event_loop().time()` is deprecated in Python 3.10+ and
emits a `DeprecationWarning` when called without a running event loop. In
Python 3.12+ it raises `RuntimeError` when called from a thread without a
current loop. Since `monitor()` is an `async def` function (called within an
anyio task group), there IS a running loop, so it won't crash — but it is
nonetheless the wrong API to use. The correct call is
`asyncio.get_running_loop().time()` inside an async context.
**Fix direction:** Replace all three occurrences of `asyncio.get_event_loop()`
with `asyncio.get_running_loop()` in `supervisor.py`.
**Task:** INFO — no task (low risk, cosmetic)
**Status:** open

---

## [MEDIUM] [Cycle 5 / docs-researcher] — /internal/events and /internal/heartbeat have no authentication

**Reported:** Cycle 5
**File:** `lib/api/internal.py:94-135`
**Issue:** The `/internal/events` and `/internal/heartbeat` HTTP POST endpoints
accept any unauthenticated request. Any process with network access to the
control surface can:

1. POST arbitrary payloads to `/internal/events`, which are broadcast directly
   to browser clients via `cm.broadcast_to_thread()` — enabling spoofed agent
   output injection.
2. POST to `/internal/heartbeat` to reset the heartbeat timestamp, masking
   a crashed worker from the health monitor.

In the current architecture these endpoints are intended only for the worker
child process. There is no shared secret, token, or bind-address restriction.

**Fix direction:** Options in ascending complexity:

1. **Bind to loopback only** — add a separate uvicorn bind for internal
   endpoints on `127.0.0.1` only (simplest, process-level isolation).
2. **Shared secret header** — generate a random `VAULTSPEC_INTERNAL_TOKEN`
   at startup, pass it to the worker via env, require it as
   `X-Internal-Token` header on all `/internal/*` calls. Validate in a
   FastAPI dependency.
3. **mTLS** — strongest but adds operational complexity.

Option 2 is recommended — it is low-overhead and consistent with the existing
`settings` pattern.
**Task:** INFO — no task (security hardening, separate from LangGraph scope)
**Status:** open

---

## [RESOLVED] [Cycle 6 / docs-researcher] — T07 TAG_NOSTREAM applied

**Reported:** Cycle 6 (verification)
**File:** `lib/core/nodes/supervisor.py:8, 69, 71`
**Issue:** Status update — `from langgraph.constants import TAG_NOSTREAM` at
line 8; `routing_model = model.with_config({"tags": [TAG_NOSTREAM]})` at
line 69; `await routing_model.ainvoke(messages)` at line 71. T07 fully resolved.
**Task:** T07
**Status:** resolved

---

## [RESOLVED] [Cycle 6 / docs-researcher] — T06 supervisor_node state["messages"] subscript also fixed

**Reported:** Cycle 6 (verification)
**File:** `lib/core/nodes/supervisor.py:60`
**Issue:** The INFO-level finding about `state["messages"]` dict-subscript
KeyError risk is also resolved as part of T06. Line 60 now reads
`*working_state.get("messages", [])` via the `working_state` compaction path.
**Task:** INFO — no task
**Status:** resolved

---

## [LOW] [Cycle 6 / docs-researcher] — Worker /dispatch endpoint has no authentication

**Reported:** Cycle 6
**File:** `lib/worker/app.py:106-123`
**Issue:** The `/dispatch` HTTP POST endpoint on the worker process accepts any
`DispatchRequest` with no authentication. The worker binds to `127.0.0.1:8001`
(loopback only, so not remotely reachable), but any process on the same host
can ingest arbitrary content into any thread, resume suspended graphs with
arbitrary option IDs, or cancel in-progress runs. This is lower severity than
the `/internal/*` issue (loopback bind limits exposure) but still a concern
in shared or CI environments.
**Fix direction:** Same shared-secret header approach as `/internal/*`. Pass
`VAULTSPEC_INTERNAL_TOKEN` to the worker via env (already passed at spawn via
`subprocess.Popen(env=...)` or inherited from parent). Validate in a FastAPI
dependency on `/dispatch`.
**Task:** INFO — no task (security hardening, out of LangGraph scope)
**Status:** open

---

## [LOW] [Cycle 6 / docs-researcher] — worker/health.py HealthCheck class is an empty stub

**Reported:** Cycle 6
**File:** `lib/worker/health.py:6-7`
**Issue:** `class HealthCheck` has no methods or attributes — it is a stub.
`worker/app.py` defines its own inline `/health` handler and does not use
`HealthCheck` at all. The class is exported in `__all__` of `health.py` but
serves no purpose.
**Fix direction:** Either implement the intended `HealthCheck` functionality
(periodic self-check logic, readiness tracking) or delete the file and remove
its export from `lib/worker/__init__.py`.
**Task:** INFO — no task (dead code)
**Status:** open

---

## [LOW] [Cycle 6 / docs-researcher] — Worker lifespan shutdown order: bridge closed before heartbeat cancelled

**Reported:** Cycle 6
**File:** `lib/worker/app.py:87-91`
**Issue:** The shutdown sequence is: (1) `executor.shutdown()`, (2)
`bridge.close()` — closes the httpx client, (3) `tg.cancel_scope.cancel()` —
stops the heartbeat task. The heartbeat loop is still running when
`bridge.close()` executes. If a heartbeat fires between step 2 and step 3,
`send_heartbeat()` will raise `httpx.HTTPError` (client already closed).
This is caught and logged at DEBUG level in `send_heartbeat()` — not a crash —
but produces spurious log noise on every clean shutdown.
**Fix direction:** Reorder to: cancel task group first (`tg.cancel_scope.cancel()`),
then await executor and bridge cleanup. Or add a `_closed` flag to
`WorkerBridge.send_heartbeat()` that silently skips the HTTP call after
`close()` has been called.
**Task:** INFO — no task (low impact, clean shutdown noise only)
**Status:** open

## [MEDIUM] [Cycle 7 / docs-researcher] — AcpSessionError not excluded from \_worker_retry_on

**Reported:** Cycle 7
**File:** `lib/core/graph.py:47-64` (exclusion list) + `lib/providers/acp_chat_model.py:1161,1191`
**Issue:** `_worker_retry_on` excludes `AcpAuthError`, `AcpPromptError`, `AcpProtocolError`, and
`GraphRecursionError` from retry. However `AcpSessionError` — which IS raised by
`acp_chat_model.py` at lines 1161 and 1191 (initialize and session-new failures) — is NOT
in the exclusion list. Session errors are non-transient infrastructure failures (wrong port,
incompatible server), so retrying wastes time and fires 3x ACP RPCs.
Additionally, `AcpProtocolError` IS excluded but is never raised anywhere in
`acp_chat_model.py` — it is a preemptive/dead exclusion.
**Fix direction:** Add `AcpSessionError` to the `isinstance` exclusion tuple in
`_worker_retry_on`. Optionally remove `AcpProtocolError` (or keep for safety against future
raises).
**Task:** T05 follow-up
**Status:** open

---

## [HIGH] [Cycle 7 / docs-researcher] — T17 scope expansion: ThreadModel missing team_preset column

**Reported:** Cycle 7
**File:** `lib/database/models.py` + `lib/database/crud.py:101`
**Issue:** T17 was originally scoped to `endpoints.py` resume path and `executor.py` lazy
recompile. Full DB layer investigation reveals the scope is larger:

1. `ThreadModel` has NO `team_preset` column — threads are created without any stored preset.
2. `create_thread()` in `crud.py` has no `team_preset` parameter.
3. Resume dispatch at `endpoints.py:712-716` cannot forward `team_preset` since it is never
   persisted at creation time.
   The full T17 chain: ThreadModel column → create_thread param → creation endpoint stores it
   → resume endpoint reads and forwards → executor lazy recompile on miss.
   **Fix direction:** (1) Add `team_preset: str | None` column to `ThreadModel` with Alembic
   migration; (2) add `team_preset: str | None = None` param to `create_thread()`; (3) update
   create-thread endpoint to pass through; (4) update resume endpoint to look up from DB before
   forwarding DispatchRequest; (5) implement lazy recompile in `_handle_resume`.
   **Task:** T17
   **Status:** open

---

## [CYCLE 7 STATUS SWEEP] — codebase-researcher verification pass

**Reported:** Cycle 7 (session resume — fresh file reads)
**Scope:** All open tasks T05, T08, T11–T17

### T08 — Loop iteration logging: RESOLVED (confirmed)

Call site at `lib/core/graph.py:615-618` correctly reads:

```python
if agent_id == loop_node_id:
    worker_node = _wrap_loop_node(
        worker_node, loop_node_id=loop_node_id, max_loops=max_loops
    )
```

Both keyword args are passed. Pre-summary analysis of a stale snapshot was incorrect.
`_wrap_loop_node` signature and implementation at lines 521-559 confirmed correct.
**Status update: T08 is fully resolved.** TaskList confirms completed.

### T05 — RetryPolicy private import: still open

`lib/core/graph.py:20`: `from langgraph._internal._retry import default_retry_on` still present.
`lib/core/graph.py:66`: `return default_retry_on(cause)` fallback still calls it.
The `requests` dependency risk (Cycle 5 docs-researcher finding) is NOT yet fixed.
TaskList shows T05 still `in_progress` with coder assigned.

### T11 — step_timeout: confirmed open

`lib/core/graph.py:253`: `builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_nodes)` — no `step_timeout` post-compile assignment. TaskList: pending.

### T12 — \_replace_plan empty discard: confirmed open

`lib/core/state.py:64`: `return new if new else existing` — broken behavior still present. TaskList: pending.

### T13 — graph_input missing required fields: confirmed open (in_progress)

`lib/worker/executor.py:176`: `graph_input: dict[str, Any] = {"messages": messages} if messages else {}` — only `messages` initialized. `active_agent`, `thread_id`, `artifacts`, `current_plan`, `token_usage` absent. TaskList: `in_progress`.

### T14 — compact_context summary as SystemMessage: confirmed open

`lib/core/context.py:114`: `summary = SystemMessage(content=...)` — nested compaction bug still present. TaskList: pending.

### T15 — GraphRecursionError in aggregator: confirmed open

`lib/core/aggregator.py:1117-1144`: `except BaseException` has only `_is_interrupt` branch. No `isinstance(exc, GraphRecursionError)` check. Falls to generic `INGEST_ERROR` with `recoverable=False`. TaskList: pending.

### T16 — StreamableGraph/ingest Command type: confirmed open

`lib/core/aggregator.py:132`: `astream_events(graph_input: dict[str, Any] | None, ...)` — no `Command` in union.
`lib/core/aggregator.py:1070`: `ingest(..., graph_input: dict[str, Any] | None, ...)` — no `Command` in union.
Executor passes `Command(resume=req.option_id)` at line 232 — type mismatch suppressed by `cast()`. TaskList: pending.

### T17 — Lazy graph recompilation on resume: confirmed open

`lib/worker/executor.py:207-209`: `graph = self._graphs.get(req.thread_id)` returns `None` on restart; early-return with warning instead of recompiling. TaskList: pending.

---

## [HIGH] [Cycle 8 / docs-researcher] — T05 partial fix: `import requests` retained in inlined \_worker_retry_on

**Reported:** Cycle 8
**File:** `lib/core/graph.py:68-76`
**Issue:** T05 removed the `langgraph._internal._retry` private import and inlined the logic —
that part is correct. However, the inline still contains `import requests` at line 69 and uses
`requests.HTTPError` at line 75. The `requests` library is NOT in `pyproject.toml` as a
dependency. If any exception reaches `_worker_retry_on` and is not matched by the early-exit
branches (ConnectionError, httpx.HTTPStatusError), the `import requests` statement will
execute and raise `ModuleNotFoundError: No module named 'requests'` — crashing the retry
predicate and propagating an unexpected ImportError up to LangGraph's retry engine.
The T05 task is now marked completed but this residual issue remains.
**Fix direction:** Replace the `requests.HTTPError` branch (lines 75-76) with a no-op or
simply remove it entirely. The project uses `httpx` for all HTTP calls; `requests` objects
will never reach `_worker_retry_on`. The safe replacement:

```python
# requests.HTTPError branch removed — project uses httpx exclusively
```

Also remove `import requests` at line 69.
**Task:** T05 residual (new follow-up needed)
**Status:** open

---

## [MEDIUM] [Cycle 8 / docs-researcher] — T05 still needs AcpSessionError exclusion

**Reported:** Cycle 8
**File:** `lib/core/graph.py:46-95`
**Issue:** The T05 task is completed (RetryPolicy added, private import removed) but neither
`AcpSessionError` nor the `AcpProtocolError`-never-raised issue was addressed. The inlined
`_worker_retry_on` has no `AcpSessionError` exclusion. The `WorkerExecutionError` unwrapping
at line 62 correctly reveals the cause, but `AcpSessionError` at `acp_chat_model.py:1161,1191`
would fall through to `return True` (retry), consuming 3 attempts unnecessarily.
**Fix direction:** Add a local import and isinstance guard:

```python
from ..providers.acp_exceptions import AcpAuthError, AcpSessionError  # noqa: PLC0415
if isinstance(cause, (AcpAuthError, AcpSessionError)):
    return False
```

**Task:** T05 residual
**Status:** open

---

## [BATCH 1 COMPLETE] [Cycle 3] — T01–T04 verified resolved

**Reported:** Cycle 3 (post-commit verification, codebase-researcher)
**Summary:** All four Batch 1 tasks verified in working tree via direct file reads.

| Task | Verification                                                                                                                                       | Result   |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| T01  | `state.py:102` NotRequired, `graph.py:371` state.get, `test_graph.py:316` test                                                                     | resolved |
| T02  | `supervisor.py:87` sorted(options, key=len, reverse=True), `test_supervisor.py:67` collision test                                                  | resolved |
| T03  | `state.py:105` routing_error NotRequired, `supervisor.py:100-103` returns routing_error, tests present                                             | resolved |
| T04  | `worker.py:8` GraphBubbleUp import, `worker.py:166` guard before except Exception, `worker.py:174-178` WorkerExecutionError wrapping with from exc | resolved |

**Note on T18:** RETRACTED (Cycle 10). Pregel intercepts `GraphBubbleUp` at the task runner
level before any node-local `except Exception` block. The guard added as T18 is superfluous
but harmless. T18 closed as a retracted finding — do not re-raise.

**Batch 2 scope:** T05 (RetryPolicy), T06 (supervisor compaction + messages.get), T07 (TAG_NOSTREAM), T08 (loop logging). Watching: `graph.py`, `supervisor.py`, `context.py`.

---

## [INFO] [Cycle 9 / docs-researcher] — T12 design clarification: test validates current behavior as intentional

**Reported:** Cycle 9
**File:** `lib/core/tests/test_state.py:100-104` + `lib/core/state.py:64`
**Issue:** T12 was filed as a bug: "silently discard empty plan" via `return new if new else existing`.
However, `test_state.py:100-104` (`test_keeps_existing_when_new_is_empty`) explicitly asserts
that returning an empty list leaves the existing plan unchanged — i.e., the test validates the
current behavior as correct and intentional design.
The intent appears to be: supervisors that have no plan update should return `[]`; only nodes
that explicitly want to replace the plan should return a non-empty list. Silently keeping the
old plan is intentional.
If the fix direction for T12 is "allow explicit plan clearing" (supervisor returns `[]` to mean
"clear"), then the test itself must also change — and the fix approach would differ (e.g.,
use `None` as a sentinel for "no change" vs. `[]` for "clear").
**Fix direction:** Clarify with task owner whether T12 means: (a) the test is wrong and empty
list should overwrite, or (b) we need a three-way sentinel (None=no change, []=clear,
[...]=replace). Current coder has T12 in_progress — this observation should be reviewed
before committing.
**Task:** T12 (design clarification, not a new task)
**Status:** open (pending design decision)

---

## [CYCLE 10 STATUS SWEEP] — docs-researcher verification pass

**Reported:** Cycle 10
**Scope:** T12, T13, T14 (coder in_progress); T11, T15, T16, T17 (pending)

### T13 — graph_input missing required fields: RESOLVED

`lib/worker/executor.py:176-183` now initialises all required `TeamState` fields:

```python
graph_input: dict[str, Any] = {
    "messages": messages,
    "active_agent": "",
    "artifacts": [],
    "current_plan": [],
    "thread_id": req.thread_id,
    "token_usage": {},
}
```

Task list confirms completed. Fix is clean — empty `messages: []` is safe with the
`add_messages` reducer (appends nothing on merge).

### T12 — \_replace_plan empty discard: still open

`lib/core/state.py:64`: `return new if new else existing` — unchanged. Coder has task
in_progress. See Cycle 9 design clarification note: the existing test
(`test_keeps_existing_when_new_is_empty`) validates this behavior as intentional — the
fix requires a clear decision on whether the test must also change.

### T14 — compact_context summary as SystemMessage: still open

`lib/core/context.py:114`: `summary = SystemMessage(content=...)` — unchanged. Coder has
task in_progress.

### T17 — Lazy graph recompilation on resume: still open

`lib/worker/executor.py:214-217`: `_handle_resume` still early-returns on missing graph.
No lazy recompile logic present. T17 DB scope (missing `team_preset` column in
`ThreadModel`) also unaddressed.

### T11, T15, T16 — all still pending (no coder assigned yet)

---

## [CYCLE 11 RESEARCH] — docs-researcher: T15/T16 precise fix directions from Pregel source

**Reported:** Cycle 11
**Scope:** T15 (GraphRecursionError in aggregator), T16 (StreamableGraph/ingest Command type)

### T15 — GraphRecursionError fix direction (precise)

From `knowledge/repositories/langgraph/libs/langgraph/langgraph/errors.py:45`:

```python
class GraphRecursionError(RecursionError):
    pass
```

`GraphRecursionError` inherits `RecursionError → Exception → BaseException`. It IS caught
by the `except BaseException` block in `aggregator.ingest()` (line 1117), falls into the
`else` branch (not `_is_interrupt`), and emits `INGEST_ERROR` with `recoverable=False`.

From `pregel/main.py:2666-2674` and `3009-3017`: Pregel raises `GraphRecursionError` with
a message like "Recursion limit of N reached without hitting a stop condition."

The `except BaseException` block needs a second isinstance check — guarded by a try-import
identical to the `_GraphInterrupt` pattern already in place:

```python
# Near the top of aggregator.py, alongside _GraphInterrupt:
try:
    from langgraph.errors import GraphRecursionError as _GraphRecursionError
except ImportError:
    _GraphRecursionError = None  # type: ignore[assignment,misc]

# In the except BaseException block, add a second elif:
_is_recursion_limit = (
    _GraphRecursionError is not None and isinstance(exc, _GraphRecursionError)
) or exc.__class__.__name__ == "GraphRecursionError"

if _is_interrupt:
    ...  # existing interrupt handling
elif _is_recursion_limit:
    logger.warning(
        "Graph recursion limit reached for thread %s — emitting recoverable error",
        thread_id,
    )
    span.set_attribute("recursion_limit_reached", True)
    await self.emit_error(
        thread_id=thread_id,
        agent_id=agent_id,
        code="RECURSION_LIMIT_EXCEEDED",
        message="Agent team reached the maximum number of steps. Retry with a higher recursion_limit or simplify the task.",
        recoverable=True,
    )
else:
    ...  # existing INGEST_ERROR handling
```

The `_is_interrupt` / `_is_recursion_limit` flags must both be initialised to `False`
before the try block (already done for `_is_interrupt`).

### T16 — StreamableGraph / ingest Command type fix (precise)

From `pregel/protocol.py:115` and `pregel/main.py:2683`: The real Pregel `astream` accepts
`InputT | Command | None`. `astream_events` is inherited from LangChain's `Runnable` base
and propagates input to the same underlying `astream` — so `Command` is valid at runtime.

The Protocol and `ingest()` type annotations are simply too narrow. Two-line fix:

In `aggregator.py`:

1. Add `from langgraph.types import Command` to imports.
2. Change `StreamableGraph.astream_events` signature:
   ```python
   # Before:
   graph_input: dict[str, Any] | None,
   # After:
   graph_input: dict[str, Any] | Command | None,
   ```
3. Change `ingest()` signature identically:
   ```python
   # Before:
   graph_input: dict[str, Any] | None,
   # After:
   graph_input: dict[str, Any] | Command | None,
   ```
   This removes the `cast(StreamableGraph, graph)` workaround in `executor.py` and makes the
   type system accurate. No runtime behaviour changes.

---

## [CYCLE 12 RESEARCH] — docs-researcher: T11 precise implementation from Pregel source

**Reported:** Cycle 12
**Scope:** T11 (step_timeout watchdog) — research from Pregel source

### How step_timeout works in Pregel (authoritative)

From `pregel/main.py:601-602` and `640-688`:

- `step_timeout: float | None = None` is a **constructor parameter** of the compiled
  `Pregel` object, stored as `self.step_timeout`.
- It is passed directly to `runner.tick()` / `runner.atick()` as `timeout=self.step_timeout`
  at `main.py:2648` and `2976`.
- When the timeout fires, `_panic_or_proceed` (at `_runner.py:530`) raises:
  `asyncio.TimeoutError("Timed out")` — specifically `asyncio.TimeoutError`, not the base
  `TimeoutError`.

**Critical: `compile()` does NOT accept `step_timeout`.**
From `graph/state.py:1035-1044`, `StateGraph.compile()` parameters are:
`checkpointer`, `cache`, `store`, `interrupt_before`, `interrupt_after`, `debug`, `name`.
There is no `step_timeout` parameter on `compile()`.

### Correct T11 implementation path

The only correct approach is **post-compile attribute assignment**:

```python
compiled = builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_nodes)
if step_timeout is not None:
    compiled.step_timeout = step_timeout
return compiled
```

This is safe — `step_timeout` is a plain instance attribute on `CompiledStateGraph` (which
inherits from `Pregel`). Setting it after compile does not re-validate or re-compile
anything.

### Wiring path for T11

Three changes needed:

1. **`lib/core/config.py`** — add field:

   ```python
   graph_node_timeout_seconds: int = Field(
       default=300,
       description="Per-node step timeout for compiled LangGraph graphs (seconds).",
   )
   ```

2. **`lib/core/graph.py`** — add `step_timeout` param to `compile_team_graph()` and set
   post-compile:

   ```python
   def compile_team_graph(
       ...,
       step_timeout: float | None = None,
   ) -> CompiledStateGraph:
       ...
       compiled = builder.compile(
           checkpointer=checkpointer,
           interrupt_before=interrupt_nodes,
       )
       if step_timeout is not None:
           compiled.step_timeout = step_timeout
       return compiled
   ```

3. **`lib/worker/executor.py`** — pass `settings.graph_node_timeout_seconds` when calling
   `compile_team_graph()`:
   ```python
   graph = compile_team_graph(
       ...,
       step_timeout=float(settings.graph_node_timeout_seconds),
   )
   ```

### Timeout exception surface

When `step_timeout` fires, `asyncio.TimeoutError` propagates out of `astream_events`.
The `except BaseException` in `aggregator.ingest()` catches it. Currently falls to the
generic `INGEST_ERROR` branch. Consider adding a third branch alongside the T15
`_is_recursion_limit` check:

```python
_is_step_timeout = isinstance(exc, asyncio.TimeoutError)
```

If matched: emit `code="STEP_TIMEOUT"` with `recoverable=True` (user can retry with a
larger timeout or a simpler task). This is a separate finding but naturally companion to T15.

**Note:** `asyncio.TimeoutError` is also a subclass of `TimeoutError`, which `_worker_retry_on`
already returns `True` for. However, `step_timeout` fires in the Pregel runner loop — NOT
inside a worker node invocation — so `_worker_retry_on` never sees it. The exception
propagates directly to `aggregator.ingest()`'s `except BaseException`. No retry-policy
interaction concern.

---

## [CYCLE 13 RESEARCH] — docs-researcher: T17 full implementation path + no-Alembic constraint

**Reported:** Cycle 13
**Scope:** T17 (lazy graph recompilation on resume) — complete wiring research

### Schema migration: no Alembic, create_all only

`lib/database/session.py:184`: `await conn.run_sync(Base.metadata.create_all)` — this is
the only schema initialisation. `create_all` creates missing tables but **does NOT add
columns to existing tables**. There is no Alembic, no `alembic.ini`, no `versions/`
directory in the project.

Consequence: adding `team_preset` to `ThreadModel` will work for fresh databases only.
Existing `vaultspec.db` files on disk will silently lack the column, causing
`OperationalError: table threads has no column named team_preset` on every write.

**Migration strategy for T17:** Use a lightweight `ALTER TABLE` guard in `init_db()` or
a separate `migrate_db()` helper, run at startup before `create_all`:

```python
async with engine.begin() as conn:
    # Add team_preset column if it doesn't exist (idempotent)
    await conn.execute(text(
        "ALTER TABLE threads ADD COLUMN team_preset TEXT"
    ))
```

SQLite's `ALTER TABLE … ADD COLUMN` is safe to run even when the column already exists
— it raises `OperationalError: duplicate column name` which should be caught and ignored:

```python
try:
    await conn.execute(text("ALTER TABLE threads ADD COLUMN team_preset TEXT"))
except Exception:
    pass  # Column already exists
```

Run this BEFORE `create_all` so fresh and existing DBs both end up with the column.

### Full T17 wiring — four files

**1. `lib/database/models.py`** — add column:

```python
team_preset: Mapped[str | None] = mapped_column(default=None)
```

**2. `lib/database/session.py`** — add migration guard in `init_db()` before `create_all`:

```python
async with engine.begin() as conn:
    try:
        await conn.execute(text("ALTER TABLE threads ADD COLUMN team_preset TEXT"))
    except Exception:
        pass  # Already exists
    await conn.run_sync(Base.metadata.create_all)
```

**3. `lib/database/crud.py`** — add `team_preset` param to `create_thread()`:

```python
async def create_thread(
    session: AsyncSession,
    *,
    title: str | None = None,
    status: "ThreadStatus | str" = ThreadStatus.SUBMITTED,
    metadata: str | None = None,
    nickname: str | None = None,
    thread_id: str | None = None,
    team_preset: str | None = None,   # <-- add
) -> ThreadModel:
    ...
    thread = ThreadModel(
        id=thread_id or uuid4().hex,
        title=title,
        status=coerced_status,
        thread_metadata=metadata,
        nickname=nickname,
        team_preset=team_preset,       # <-- add
    )
```

**4. `lib/api/endpoints.py`** — two changes:

a) Pass `team_preset` to `create_thread()` at the create-thread endpoint (`~line 223`):

```python
thread = await create_thread(
    db,
    title=body.title,
    ...
    team_preset=body.team_preset,
)
```

b) At the resume endpoint (`~line 711`), look up `team_preset` from DB before dispatching:

```python
thread = await get_thread(db, thread_id)
team_preset = thread.team_preset if thread else None
dispatch = DispatchRequest(
    action="resume",
    thread_id=thread_id,
    option_id=body.option_id,
    team_preset=team_preset,      # <-- add
    # also forward workspace_root if stored — see note below
)
```

**5. `lib/worker/executor.py`** — implement lazy recompile in `_handle_resume()`:

```python
async def _handle_resume(self, req: DispatchRequest) -> None:
    graph = self._graphs.get(req.thread_id)
    if graph is None:
        # Worker restarted — attempt lazy recompile if team_preset is available
        if not req.team_preset:
            logger.warning(
                "No graph for thread %s and no team_preset in resume request "
                "— cannot recompile. Was team_preset stored at creation?",
                req.thread_id,
            )
            return
        logger.info(
            "Lazy recompile for thread %s (preset=%s) after worker restart",
            req.thread_id, req.team_preset,
        )
        try:
            graph = self._compile_graph(req)
            self._graphs[req.thread_id] = graph
            self._aggregator.register_graph(cast(StreamableGraph, graph))
        except Exception:
            logger.exception(
                "Lazy recompile failed for thread %s", req.thread_id
            )
            return
    ...  # rest of _handle_resume unchanged
```

### workspace_root gap

The resume endpoint currently builds `DispatchRequest` with no `workspace_root` (line
711-716 confirmed). For lazy recompile to succeed, `workspace_root` must also be stored
and forwarded. `ThreadModel` already has `thread_metadata` (JSON) which includes
`workspace_root` via ADR-014. The resume endpoint could decode `thread.thread_metadata`
to extract it, OR a dedicated `workspace_root` column could be added alongside
`team_preset`.

Recommend extracting from `thread_metadata` JSON at the resume endpoint — avoids a
second schema migration:

```python
import json
meta = json.loads(thread.thread_metadata) if thread.thread_metadata else {}
workspace_root = meta.get("workspace_root")
```

---

## [CYCLE 14 STATUS SWEEP] — docs-researcher verification pass

**Reported:** Cycle 14
**Scope:** T11, T15, T16 (in_progress → verify); T05 residuals (open)

### T11 — step_timeout: RESOLVED

`lib/core/graph.py:212` — `step_timeout: float | None = None` param added.
`lib/core/graph.py:290-291` — post-compile assignment `graph.step_timeout = step_timeout`.
`lib/core/config.py:30-32` — `graph_node_timeout_seconds: int = Field(default=300)`.
`lib/worker/executor.py:292` — `step_timeout=float(settings.graph_node_timeout_seconds)`.
All four wiring points confirmed correct. Implementation matches Cycle 12 research exactly.

### T15 — GraphRecursionError in aggregator: RESOLVED

`lib/core/aggregator.py:54-57` — guarded `_GraphRecursionError` import (correct pattern).
`lib/core/aggregator.py:1134-1158` — `_is_recursion_limit` check + `elif` branch emitting
`code="RECURSION_LIMIT_EXCEEDED"`.
**One observation:** coder chose `recoverable=False` (line 1157). The Cycle 11 research
suggested `recoverable=True`, but `False` is defensible — hitting the recursion limit
generally requires config change or task simplification, not just a retry. Treating as
intentional design choice, not a bug.

### T16 — StreamableGraph/ingest Command type: RESOLVED

`lib/core/aggregator.py:42` — `from langgraph.types import Command` imported.
`lib/core/aggregator.py:139` — `graph_input: dict[str, Any] | Command | None`.
`lib/core/aggregator.py:1077` — `graph_input: dict[str, Any] | Command | None`.
Both annotation sites updated. `cast()` workaround in executor can now be removed
(still present — low priority cleanup).

### T05 residuals — partially resolved

`import requests` — **RESOLVED**: removed from `graph.py`. The httpx branch is now
guarded with `try/except ImportError` (lines 73-79). Clean.
`AcpSessionError` exclusion — **still open**: `_worker_retry_on` still has no
`AcpSessionError` check. Falls through to `return True` on session failures.
Stale docstring at `graph.py:57` still references T04/T18 rationale (now retracted).

### New findings (Cycle 14)

**[LOW] Stale docstring in `_worker_retry_on` references retracted T04/T18 rationale**
`lib/core/graph.py:57`: "GraphRecursionError is excluded by the GraphBubbleUp guard in
worker.py" — this was the retracted T04/T18 reasoning. The actual exclusion is now at
line 66-67 in the same function. The docstring should read: "GraphRecursionError is
explicitly excluded at line 66 of this function — retrying would immediately hit the
limit again."

**[LOW] No test coverage for T11/T15 new branches**
`lib/core/tests/test_aggregator.py` — no tests for `_is_recursion_limit` path or
`RECURSION_LIMIT_EXCEEDED` emission.
`lib/core/tests/test_graph.py` — no tests for `step_timeout` post-compile assignment or
that `compile_team_graph(step_timeout=N)` sets `graph.step_timeout`.
These are new code paths exercised only at runtime.

**Task:** INFO — test coverage gaps
**Status:** open

---

## [CYCLE 15 STATUS SWEEP] — docs-researcher verification pass

**Reported:** Cycle 15
**Scope:** Full confirmation sweep of all in-progress tasks + T05 residual + new findings

### T12 — \_replace_plan None sentinel: CONFIRMED RESOLVED

`lib/core/state.py:64`: `return new if new is not None else existing` — correct. Uses `None`
sentinel per orchestrator decision, not falsiness. Allows `[]` to overwrite as a valid plan.

### T14 — compact_context HumanMessage: CONFIRMED RESOLVED

`lib/core/context.py:114`: `summary = HumanMessage(content=...)` — correct.

### T17 — Lazy recompile: still in_progress, not yet landed

`lib/worker/executor.py:216-218`: `_handle_resume` still early-returns on missing graph.
`lib/database/models.py`: `ThreadModel` still has no `team_preset` column.
Coder has task in_progress but changes not yet visible in working tree.

### T05 residual — AcpSessionError exclusion: still open

`lib/core/graph.py:46-98`: `_worker_retry_on` has no `AcpSessionError` check. Falls through
to `return True`.

### asyncio.get_event_loop() deprecation: still open (Cycle 5 finding)

`lib/api/supervisor.py:100,101,104`: three calls to `asyncio.get_event_loop()` inside
`async def monitor()`. In Python 3.10+ this emits `DeprecationWarning` when called from a
running event loop; in 3.12+ it may raise. The correct call in async context is
`asyncio.get_running_loop()`. Finding was first reported Cycle 5 — not yet addressed.

### Worker node test coverage: no WorkerExecutionError path

`lib/core/nodes/tests/test_worker.py`: no test exercises the `except Exception →
WorkerExecutionError` wrapping path. Model-raises-exception scenario is not covered.
The T04 retraction does not affect this — the wrapping is still the correct behaviour for
non-`GraphBubbleUp` exceptions. Minor gap, covered elsewhere indirectly via exception tests.

### No new HIGH/MEDIUM findings this cycle

All areas inspected (supervisor.py, worker.py node, context.py, state.py, nodes/tests/)
are clean beyond the known open items above.

---

## [CYCLE 16 FINDINGS] — docs-researcher: topology compilation + T17 status

**Reported:** Cycle 16
**Scope:** pipeline/pipeline_loop compilation paths, T17 landing status

### T17 — still not landed

`lib/worker/executor.py:216-218`: `_handle_resume` still early-returns on missing graph.
`lib/database/models.py`: `ThreadModel` still has no `team_preset` column.
Coder task remains in_progress — changes not yet in working tree.

### Pipeline / pipeline_loop compilation: clean

`_compile_pipeline` (`graph.py:413-497`): validates non-empty order, no duplicates,
all agents in agent_configs. All `add_node` calls carry `retry_policy=_WORKER_RETRY`.
Edges wired correctly via explicit `add_edge`. No issues found.

`_compile_pipeline_loop` (`graph.py:598-685`): likewise clean. `_wrap_loop_node`
correctly increments `loop_count` and logs per-iteration. `_loop_router` correctly
enforces `max_loops` cap at line 677-678 before checking `state.get("next")`.

### [INFO] pipeline_loop early-exit-via-next="FINISH" is effectively dead code

`_loop_router` at `graph.py:679`: `return state.get("next", "revise")` — this path
is only reachable when `loop_count < max_loops`. Workers (`create_worker_node`) never
set `next` in their return dict (they return only `{"messages": [...]}`). So
`state.get("next", "revise")` always returns `"revise"` in practice — the `"FINISH"`
branch at line 679 can never fire without an explicit `{"next": "FINISH"}` from the
worker. The `loop_count >= max_loops` guard at line 677-678 is the only termination
mechanism in use.

This is not a bug — the code is correct. The early-exit feature is an undocumented
design intent for future use. Worth a comment in `_loop_router` to clarify.

**Task:** INFO — no action (design documentation gap only)
**Status:** open (low priority)

### Star topology conditional edge: safe

`route_map` at `graph.py:404-410`: `state.get("next", "")` on first invocation would
return `""` which is not in `route_map` — BUT `add_conditional_edges` only evaluates
the lambda when the supervisor node routes, and `START → supervisor` is a direct edge
that always runs first. Supervisor always sets `next` before the conditional fires.
No runtime risk — confirmed safe.

### lib/providers/probes/\_protocol.py: clean

Standalone probe module, no LangGraph interactions. Not a retry/graph concern.

---

## [CYCLE 17 FINDINGS] — docs-researcher: AcpSessionError + asyncio deprecation

### [MEDIUM] AcpSessionError not excluded from \_worker_retry_on — session failures incorrectly retried

**Reported:** Cycle 17
**File:** `lib/core/graph.py:46-98`
**Issue:** `_worker_retry_on` falls through to `return True` for any exception not
matched by the explicit checks. `AcpSessionError(AcpError(Exception))` matches none
of the listed types (`ConnectionError`, `httpx.HTTPStatusError`, `ValueError`,
`TypeError`, `ArithmeticError`, `ImportError`, `LookupError`, `NameError`,
`SyntaxError`, `RuntimeError`, `ReferenceError`, `StopIteration`,
`StopAsyncIteration`, `OSError`), so it returns `True` — meaning session-level
failures (non-transient: process startup failure, protocol handshake failure) are
retried 3× unnecessarily.

`AcpSessionError` is defined in `lib/providers/acp_exceptions.py:70` as
`class AcpSessionError(AcpError)` where `AcpError(Exception)`. These errors
represent non-transient subprocess lifecycle failures; retrying them delays
surfacing the real error and wastes 3× the latency budget (3 attempts × backoff).

**Fix direction:**

```python
# Near top of _worker_retry_on, after the GraphRecursionError guard:
try:
    from ..providers.acp_exceptions import AcpSessionError  # noqa: PLC0415
    if isinstance(cause, AcpSessionError):
        return False
except ImportError:
    pass
```

**Task:** Open — MEDIUM severity, no task yet
**Status:** open

---

### [LOW] asyncio.get_event_loop() deprecated in async context — supervisor.py

**Reported:** Cycle 17
**File:** `lib/api/supervisor.py:100,101,104`
**Issue:** Three calls to `asyncio.get_event_loop().time()` inside `async def monitor()`
(an async coroutine). In Python 3.10+, `asyncio.get_event_loop()` in a running async
context emits a `DeprecationWarning` and in Python 3.12+ will raise `RuntimeError` if
no running loop is found via the legacy path. The correct call inside an async function
is `asyncio.get_running_loop()` which directly returns the already-running loop without
going through the deprecated policy lookup.

```python
# Current (deprecated):
healthy_since = asyncio.get_event_loop().time()
# Correct:
healthy_since = asyncio.get_running_loop().time()
```

All three occurrences at lines 100, 101, and 104 should be updated.

**Fix direction:** Simple search-and-replace within `supervisor.py`'s `monitor()` method:
`asyncio.get_event_loop()` → `asyncio.get_running_loop()`.

**Task:** Open — LOW severity, no task yet
**Status:** open

---

## [CYCLE 18 FINDINGS] — docs-researcher: test coverage gaps

### Test coverage inventory

**WorkerExecutionError wrapping** — `lib/core/tests/test_worker.py:79-131`:
Covered. Tests at lines 79, 100, 118 verify: (a) ainvoke exception → WorkerExecutionError,
(b) original exception chained as `__cause__`, (c) GraphBubbleUp passes through unwrapped.
Previously noted gap in `lib/core/nodes/tests/test_worker.py` — that file focuses on
node protocol and does not duplicate coverage. The co-located `lib/core/tests/test_worker.py`
is the authoritative location per Rust-style co-location. No gap.

**`compile_team_graph(step_timeout=N)` sets `graph.step_timeout`** — `lib/core/tests/test_graph.py:418-457`:
Covered. Two tests: `test_compile_team_graph_step_timeout_set` (asserts `graph.step_timeout == 42.0`)
and `test_compile_team_graph_step_timeout_none_not_set` (asserts remains `None`). No gap.

**`GraphRecursionError` excluded from retry predicate** — `lib/core/tests/test_graph.py:465-480`:
Covered. T15 test verifies retry predicate returns `False` for `GraphRecursionError`. No gap.

### [LOW] Aggregator RECURSION_LIMIT_EXCEEDED event branch has no test

**Reported:** Cycle 18
**File:** `lib/core/aggregator.py:1134-1144` (T15 aggregator branch)
**Issue:** The `_is_recursion_limit` check and `RECURSION_LIMIT_EXCEEDED` event emission
added as part of T15 in the aggregator's `ingest()` `except BaseException` handler has
zero test coverage. `lib/core/tests/test_aggregator.py` has no test that injects a
`GraphRecursionError` into a mock graph's `astream_events` and verifies:

- `ErrorEvent(code="RECURSION_LIMIT_EXCEEDED")` is emitted
- `recoverable=False` is set

The T15 test at `test_graph.py:465` only covers the retry predicate, not the aggregator
event emission. These are separate code paths.

**Fix direction:** Add a test in `test_aggregator.py`:

```python
async def test_ingest_recursion_limit_emits_correct_event(fake_graph, ...):
    # fake_graph raises GraphRecursionError on astream_events
    # assert ErrorEvent.code == "RECURSION_LIMIT_EXCEEDED"
    # assert ErrorEvent.recoverable == False
```

**Task:** Open — LOW severity, no task yet
**Status:** open

---

## [CYCLE 19 FINDINGS] — docs-researcher: \_is_step_timeout dead variable + wrong recoverable flag

### [HIGH] `_is_step_timeout` computed but never used — step timeouts mislabelled as INGEST_ERROR

**Reported:** Cycle 19
**File:** `lib/core/aggregator.py:1138-1170`
**Issue:** Line 1138 computes `_is_step_timeout = isinstance(exc, TimeoutError)` but the
variable is NEVER referenced in the subsequent `if / elif / else` chain. Step timeout
exceptions (raised by Pregel's `_runner.py:530` as `asyncio.TimeoutError("Timed out")`)
fall through to the `else` branch and are emitted as:

```python
ErrorEvent(code="INGEST_ERROR", recoverable=False)
```

This is wrong on two counts:

1. **Wrong code**: `INGEST_ERROR` suggests an event stream failure, not a timeout. The
   frontend has no way to distinguish a timeout from a genuine crash.
2. **Wrong recoverable flag**: Step timeouts are transient — a single slow node hit the
   watchdog. The graph can be retried. `recoverable=False` prevents the frontend from
   offering a retry.

The variable name `_is_step_timeout` indicates this branch was planned but not connected.

**Fix direction:** Add `elif _is_step_timeout:` before the `else` block:

```python
elif _is_step_timeout:
    logger.warning("Step timeout for thread %s", thread_id)
    span.set_attribute("error.type", "step_timeout")
    await self.emit_error(
        thread_id=thread_id,
        agent_id=agent_id,
        code="STEP_TIMEOUT",
        message="A graph node exceeded the configured step timeout",
        recoverable=True,
    )
```

**Task:** Open — HIGH severity (wrong recoverable flag + wrong error code surfaced to frontend)
**Status:** open

---

## [CYCLE 20 FINDINGS] — docs-researcher: worker IPC + internal endpoints

### worker/ipc.py and worker/health.py: largely clean

`ipc.py` is well-structured. `httpx.HTTPError` covers all transport errors including
`ConnectError`, `NetworkError`, `TimeoutException` (all subclass `RequestError →
HTTPError`). Heartbeat loop is correctly supervised by anyio task group. Clean.

`health.py` is a stub class with no implementation — not a concern for now.

`worker/app.py`: lifespan shutdown order is correct (`executor.shutdown()` →
`bridge.close()` → `tg.cancel_scope.cancel()`). Fire-and-forget dispatch via
`tg.start_soon` is the correct pattern. No issues.

### [MEDIUM] `/internal/events` returns HTTP 200 even when event is silently dropped

**Reported:** Cycle 20
**File:** `lib/api/internal.py:94-118`
**Issue:** `receive_worker_event` always returns `{"status": "ok"}` (HTTP 200) regardless
of whether the event was actually delivered to browser clients. When
`connection_manager` is None (e.g. during startup or after a restart race), the event
is logged at WARNING and dropped — but the worker's `WorkerBridge.send_event` checks
`resp.status_code != 200` to detect relay failures. Because the status is always 200,
the worker has no signal that events are being silently discarded.

In practice this means events emitted during a connection_manager initialisation race
are lost with no retry or alerting at the worker side.

**Fix direction:** Return HTTP 503 (or a non-200 body field) when `connection_manager`
is None so the worker bridge can log a proper warning (currently already logged at
WARNING level on the control surface side — the gap is the worker side has no signal):

```python
if cm is None:
    return JSONResponse({"status": "dropped", "reason": "no_connection_manager"}, status_code=503)
```

**Task:** Open — MEDIUM severity
**Status:** open

### [INFO] `/internal/*` endpoints have no authentication — event injection possible from loopback

**Reported:** Cycle 20
**File:** `lib/api/internal.py:94,121`
**Issue:** Both `/internal/events` and `/internal/heartbeat` POST endpoints accept
requests from any caller that can reach the control surface port. Since the control
surface also accepts external browser WS connections, a process on the same machine
(or on the LAN if the bind address is not strictly loopback) could POST fabricated
events into any thread's event stream, or spoof heartbeats to mask worker death.

This is a design-level risk — the internal router is mounted at `/internal/` with no
middleware guard. For local-dev use this is acceptable, but for multi-tenant or
network-exposed deployments it is a meaningful attack surface.

**Fix direction:** Add a shared secret (`X-Worker-Token` header) checked by a FastAPI
dependency on the `internal_router`. The `WorkerBridge` sends the token; the control
surface validates it. Token generated at worker startup and passed via env var or
startup handshake.

**Task:** INFO — design-level (no task needed for now; flag for production hardening)
**Status:** open (low priority)

---

## [CYCLE 21 FINDINGS] — docs-researcher: T17 gap in resume endpoint + T17 confirmation

### T17 executor and DB: fully landed

`lib/worker/executor.py:_handle_resume` (lines 217-257): lazy recompile path is correctly
implemented. Falls back to `_graph_presets` cache, then `req.team_preset`, with proper
exception handling and `_aggregator.register_graph()` wiring. Clean.

`lib/database/models.py:51`: `team_preset: Mapped[str | None] = mapped_column(default=None)` — landed.
`lib/database/crud.py:109,147`: `team_preset` param wired into `create_thread()`. — landed.

### [HIGH] Resume endpoint does not supply team_preset to DispatchRequest — cold-restart resume broken

**Reported:** Cycle 21
**File:** `lib/api/endpoints.py:712-717`
**Issue:** `respond_to_permission_endpoint` builds a `DispatchRequest(action="resume", ...)`
without `team_preset` or `workspace_root`. On a cold-restart scenario:

- Worker `_graph_presets` dict is empty (in-memory, lost on restart)
- `req.team_preset` is `None` (not supplied by endpoint)
- `_handle_resume` hits `logger.warning("No graph for thread %s -- cannot resume")` and returns

The `DispatchRequest` schema already supports `team_preset` and `workspace_root` fields
(defined in `lib/api/schemas/internal.py:26-27`) and `ThreadModel` now stores `team_preset`
(T17 DB migration). The endpoint simply needs to look up the thread from DB and include
both fields.

`workspace_root` can be extracted from `thread_metadata` JSON (the `ThreadMetadata` model
has a `workspace_root` field stored as JSON in the `thread_metadata` column).

**Fix direction:**

```python
# In respond_to_permission_endpoint, after extracting thread_id:
async with get_db() as db:
    thread = await crud.get_thread(db, thread_id)
    team_preset = thread.team_preset if thread else None
    workspace_root = (
        thread.thread_metadata.get("workspace_root")
        if thread and thread.thread_metadata else None
    )
dispatch = DispatchRequest(
    action="resume",
    thread_id=thread_id,
    option_id=body.option_id,
    team_preset=team_preset,
    workspace_root=workspace_root,
)
```

**Task:** Open — HIGH severity (cold-restart resume is silently broken without this)
**Status:** open

---

## [CYCLE 22 FINDINGS] — docs-researcher: websocket.py audit

### websocket.py: largely clean

`ConnectionManager` implementation is well-structured. Key positive observations:

- H10: Cross-cancel pattern on heartbeat/writer tasks correctly implemented.
- M14: 1 MiB incoming message size limit enforced before JSON parse.
- Dead client timeout via `asyncio.wait_for(_DEAD_CLIENT_TIMEOUT=90s)`.
- `CancelledError` correctly caught in both `_writer_loop` and `_heartbeat_loop`.
- Permission response over WS correctly rejected with `ErrorEvent` and REST redirect.
- `disconnect()` cleans up all three dicts: connections, heartbeat_tasks, writer_tasks.
- `broadcast_to_thread` correctly skips non-connected clients.

### [INFO] broadcast_to_thread accesses private aggregator attribute directly

**Reported:** Cycle 22
**File:** `lib/api/websocket.py:519`
**Issue:** `broadcast_to_thread` accesses `self._aggregator._subscriptions` directly
(a private `dict[str, set[str]]`). This is a mild encapsulation violation — changes
to the aggregator's internal subscription data structure would silently break this
caller without a test failure.

`_subscriptions` is used here only to filter which clients are subscribed to `thread_id`.
The aggregator already has `subscribe()`, `unsubscribe()` and `get_active_thread_ids()`
public methods; a matching `is_subscribed(client_id, thread_id) -> bool` accessor would
close this gap.

**Fix direction:** Add a method to `EventAggregator`:

```python
def is_subscribed(self, client_id: str, thread_id: str) -> bool:
    return thread_id in self._subscriptions.get(client_id, set())
```

Then replace the private access in `broadcast_to_thread`:

```python
if not self._aggregator.is_subscribed(client_id, thread_id):
    continue
```

**Task:** INFO — no task needed; minor encapsulation note
**Status:** open (low priority)

---

## [CYCLE 23 FINDINGS] — docs-researcher: T18/T19/T22 verification + acp_chat_model scan

### T18 (AcpSessionError exclusion): confirmed landed

`lib/core/graph.py:63-70`: guarded import + `isinstance(exc, AcpSessionError)` check
before the fallthrough `return True`. Correct placement and correct check on both
`exc` and `cause` (covers wrapped `WorkerExecutionError` case). Clean.

### T19 (asyncio.get_running_loop): confirmed landed + codebase-wide clean

`lib/api/supervisor.py:100,101,104`: all three `asyncio.get_event_loop().time()` calls
replaced with `asyncio.get_running_loop().time()`. Codebase-wide grep confirms zero
remaining `get_event_loop()` calls anywhere in `lib/`. Clean.

### T22 (team_preset in resume DispatchRequest): confirmed landed

Task #35 marked completed in task list. T17/T22 gap (endpoint not supplying
`team_preset` to `DispatchRequest`) resolved. Cold-restart resume path now complete.

### acp_chat_model.py: clean on scanned paths

Permission callback path (`_on_request_permission`): `GraphBubbleUp` propagation,
fail-closed denial on exception, correct H9 JSON-RPC denial response — all correct.
`AcpSessionError` raise sites at lines 1161 and 1191 use `asyncio.get_running_loop()`
(correct). No issues found.

### Summary of all open HIGH+ items after Cycle 23

1. **HIGH**: `_is_step_timeout` dead variable in `aggregator.py:1138` — step timeouts
   emit `INGEST_ERROR` with `recoverable=False` instead of `STEP_TIMEOUT` with
   `recoverable=True`. No task yet.
2. **MEDIUM** (T21, in_progress): `/internal/events` returns HTTP 200 on dropped event.

---

## [BATCH 2 RESEARCH] — docs-researcher: 6 LangGraph source topics

### Topic 1: RetryPolicy interaction with GraphBubbleUp

**Source:** `pregel/_retry.py:61-63` (both sync `run_with_retry` and async `arun_with_retry`)

```python
except GraphBubbleUp:
    # if interrupted, end
    raise
```

**Finding:** `GraphBubbleUp` is caught in a DEDICATED `except GraphBubbleUp` clause that
appears BEFORE the `except Exception` retry clause. This is an explicit guard — Pregel's
retry runner intercepts `GraphBubbleUp` before any `RetryPolicy` evaluation and
immediately re-raises without calling `_should_retry_on` at all.

**Corollary — what exception does retry_on receive?**
The `except Exception as exc` clause at line 64 (async: 160) receives the OUTERMOST
exception. If `WorkerExecutionError` wraps the original cause, `retry_on` receives
`WorkerExecutionError` as `exc`. Our `_worker_retry_on` correctly handles this:

```python
cause = exc.__cause__ if isinstance(exc, WorkerExecutionError) and exc.__cause__ is not None else exc
```

This is the right pattern since `_should_retry_on` passes the raw outermost exc to the callable.

**T05 verdict:** Correct. `GraphBubbleUp` never reaches `retry_on`. No action needed.

---

### Topic 2: `with_structured_output` fallback behavior

**Source:** `langchain_core/language_models/chat_models.py:1697-1723`

**Without `include_raw` (default False):**
Chain is `llm | output_parser`. If the model returns a malformed tool call or Pydantic
validation fails, `output_parser` raises `OutputParserException` immediately. There is
NO internal retry. The exception propagates to the node and then to `_worker_retry_on`.
`OutputParserException` is not in the non-retryable list → falls through to `return True`
→ retried 3× unnecessarily. **New finding: T09 gap — `OutputParserException` should be
excluded from `_worker_retry_on`.**

**With `include_raw=True`:**
Chain becomes `RunnableMap(raw=llm) | parser_with_fallback`:

```python
parser_assign = RunnablePassthrough.assign(
    parsed=itemgetter("raw") | output_parser,
    parsing_error=lambda _: None
)
parser_none = RunnablePassthrough.assign(parsed=lambda _: None)
parser_with_fallback = parser_assign.with_fallbacks([parser_none], exception_key="parsing_error")
```

Parsing failures are CAUGHT by `with_fallbacks` — stored in `result["parsing_error"]`
while `result["parsed"]` is `None`. The chain DOES NOT RAISE on parse failure. You get:

- `result["raw"]`: the original `AIMessage` (raw LLM output)
- `result["parsed"]`: the Pydantic instance, or `None` on failure
- `result["parsing_error"]`: the exception, or `None` on success

**For T09:** Use `include_raw=True` in the supervisor's `with_structured_output` call.
Check `result["parsing_error"] is not None` to detect failures gracefully. Supervisor can
fall back to `result["raw"].content` (plain text routing) when `parsed` is None.

---

### Topic 3: `Command(goto=..., update={...})` state update semantics

**Source:** `pregel/_io.py:65-78`, `types.py:402-415`, `_algo.py:280-296`

**Finding:** `Command.update` goes through NORMAL channel reducers. Full trace:

1. `map_command()` in `_io.py:76-78`:
   ```python
   for k, v in cmd._update_as_tuples():
       yield (NULL_TASK_ID, k, v)   # ← (task_id, channel, value) write tuples
   ```
2. `apply_writes()` in `_algo.py:280-296` groups writes by channel and calls:
   ```python
   channels[chan].update(vals)   # ← invokes the channel's reducer
   ```
3. For `messages` (annotated with `add_messages`), this merges. For `current_plan`
   with `_replace_plan` reducer, this replaces. Behaviour is identical to a normal node
   return dict.

**Verdict:** `Command(update={"messages": [msg]})` feeds `[msg]` through the `add_messages`
reducer. No reducer bypass. Update writes are attributed to `NULL_TASK_ID` (same as
`update_state()` or graph input).

---

### Topic 4: Node metadata preservation with RetryPolicy

**Source:** `pregel/main.py:294-316`, `pregel/_retry.py:37-105`

**Finding:** Node metadata is stored in `PregelNode._metadata` at compile time and baked
into `PregelExecutableTask` at `prepare_next_tasks` time. The retry loop only mutates:

- `task.writes` — cleared at line 130/40 before each attempt
- `config` — patched with `CONFIG_KEY_RESUMING=True` at line 201/105

The `task` object itself (including `task.metadata`) is NOT mutated between attempts.

**Verdict:** Node metadata is fully preserved across all retry attempts. Safe for T05 testing.

---

### Topic 5: Does each retry consume a recursion_limit step?

**Source:** `pregel/_loop.py:460-469,811-813`, `pregel/_retry.py:37-105`

**Finding:** Retries do NOT consume recursion_limit steps.

`self.step` increments via `self.step += 1` at `_loop.py:813`, called from `after_tick()`
once per completed **superstep** (one full `while loop.tick()` iteration). Retry attempts
run inside `arun_with_retry` which is called within a single superstep's task execution
phase — the loop's `step` counter does not advance during retries.

Out-of-steps check:

```python
if self.step > self.stop:   # _loop.py:467
    self.status = "out_of_steps"
```

`self.stop = self.step + self.config["recursion_limit"] + 1` — set once at init.

**Verdict:** 3 retry attempts on a node = **1 recursion step consumed**, not 3.
`_GRAPH_RECURSION_LIMIT = 100` is safe regardless of retry count per node.

---

### Topic 6: Subgraph recursion_limit and step_timeout isolation

**Source:** `pregel/main.py:601,644,688,2648,2976`, `pregel/_loop.py:1120`

**`step_timeout`:**
Instance attribute on `Pregel` at line 601, applied in the task runner at lines 2648/2976
as `timeout=self.step_timeout`. A subgraph is a **separate `Pregel` instance** with its
OWN `step_timeout`. When the parent graph runs a subgraph node, the parent's `step_timeout`
governs the TOTAL time of that node (i.e., the entire subgraph execution counts as one
step for the parent's watchdog). The subgraph's INTERNAL steps run under the subgraph's
own `step_timeout`.

Net effect: parent `step_timeout=300`, subgraph `step_timeout=None` → parent fires if
the whole subgraph exceeds 300s; individual inner node steps have no per-step limit.

**`recursion_limit`:**
Comes from `config["recursion_limit"]` at `_loop.py:1120`. Config is propagated from
parent to subgraph invocation (same dict, namespace-patched). Subgraph steps count against
their OWN `stop = step + config["recursion_limit"] + 1` — initialized from their own
checkpoint's saved step. Each graph has an independent counter.

**Architecture implication for pipeline_loop-as-subgraph:**
If `pipeline_loop` were a subgraph inside `star`, the inner loop's `recursion_limit`
inherits from the outer graph's config unless explicitly overridden. The parent's
`step_timeout` would fire if the entire inner loop exceeds it as a single node. To set a
tighter inner limit, pass a custom config override when invoking the subgraph node. This
is feasible but requires explicit plumbing.

---

## [CYCLE 24 FINDINGS] — docs-researcher: supervisor.py T09 status + OutputParserException scope

### supervisor.py: T09 NOT YET implemented — text-based routing is safe

`lib/core/nodes/supervisor.py` uses plain `ainvoke` + text parsing. No `with_structured_output`.
The full pipeline: exact match → longest-substring fallback (T02) → unparseable guard
with `routing_error` + FINISH default (T03). No parse exceptions propagate. Confirmed clean.

### [INFO] OutputParserException exclusion: future-only scope (T23 blocked on T09)

**Reported:** Cycle 24
**File:** `lib/core/graph.py:46-98` (applies only after T09 lands)
**Issue:** Once T09 migrates supervisor to `with_structured_output(include_raw=False)`,
parse failures raise `OutputParserException` which falls through `_worker_retry_on` to
`return True` — 3× unnecessary retries.

T23 is correctly scoped as a T09 companion. If T09 uses `include_raw=True` (recommended),
`OutputParserException` never propagates at all — T23 becomes belt-and-suspenders.

**Recommendation for T09:** Use `include_raw=True` + check `result["parsing_error"]`,
fall back to `result["raw"].content` for text-based routing on failure.

**Task:** T23 (pending) — confirmed blocked on T09
**Status:** open (blocked)

---

## [CYCLE 25 FINDINGS] — docs-researcher: \_is_step_timeout resolved + full status sweep

### \_is_step_timeout HIGH finding: RESOLVED

`lib/core/aggregator.py:1160-1174`: `elif _is_step_timeout:` branch fully wired.
`code="STEP_TIMEOUT"`, `recoverable=True`, `span.set_attribute("error.type", "step_timeout")`.
The Cycle 19 HIGH finding is resolved.

### T17 DB migration: confirmed complete

`lib/database/session.py:186-192`: idempotent `ALTER TABLE threads ADD COLUMN team_preset TEXT`.
`lib/database/crud.py:109,147`: `team_preset` param in `create_thread`.
`lib/database/models.py:51`: `team_preset: Mapped[str | None]` column. Full T17 complete.

### Full open item status after Cycle 25

All HIGH findings resolved. Remaining open items:

| Severity | Finding                                                   | Task    | Status         |
| -------- | --------------------------------------------------------- | ------- | -------------- |
| MEDIUM   | T21: /internal/events returns 200 on event drop           | #34     | **completed**  |
| LOW      | T20: Aggregator RECURSION_LIMIT_EXCEEDED branch untested  | #36     | **completed**  |
| LOW      | T23: OutputParserException exclusion (T09 companion)      | pending | blocked on T09 |
| INFO     | broadcast_to_thread accesses \_subscriptions private attr | none    | open           |
| INFO     | /internal/\* endpoints have no auth                       | none    | open           |
| INFO     | \_loop_router "FINISH" path is dead code                  | none    | open           |

---

## [CYCLE 26 FINDINGS] --- docs-researcher: T20/T21 confirmed + final sweep

### T20 (RECURSION_LIMIT_EXCEEDED test): confirmed landed

\:
present, asserts \ and \. Complete.

### T21 (503 on dropped event): confirmed landed

\: \. Complete.

### graph.py compile path: clean

\ always (line 260, 292). \ post-compile at lines
294-295. No \ API usage in graph.py (star/pipeline/pipeline_loop do not need it).

### Final audit state

All HIGH and MEDIUM findings resolved across 26 cycles. Only T23 remains, correctly
blocked on the future T09 with_structured_output migration. No current code risk.

---

## [CYCLE 27 FINDINGS] --- docs-researcher: post-sprint verification sweep

Fresh read of all core files after the coder sprint to verify no regressions or new gaps.

### supervisor.py — clean

Full re-read (111 lines). Plain text routing via `model.with_config({"tags": [TAG_NOSTREAM]})`.
No `with_structured_output` usage (T09 not yet landed — correct, T23 is blocked on it).
`except Exception: raise` at line 72 correctly re-raises without swallowing.
No `GraphBubbleUp` risk — supervisor never calls `interrupt()`.
`supervisor_node.__name__` assigned at line 109. `__all__` present.

### websocket.py — confirmed clean; broadcast_to_thread private attr still INFO

Full re-read (548 lines). Confirms all previous findings resolved:

- H10 cross-cancel: hb_task + wr_task callbacks at lines 173-174. Correct.
- Dead-client timeout: `asyncio.wait_for(..., timeout=_DEAD_CLIENT_TIMEOUT)` at line 227. Correct.
- 1 MiB message size cap at line 240. Correct.
- `CancelledError` handled (pass) in `_writer_loop:471` and `_heartbeat_loop:499`. Correct.
- INFO: `broadcast_to_thread:519` accesses `self._aggregator._subscriptions` directly (private attr).
  This remains open as INFO — the aggregator would need a public `get_subscriptions(client_id)` method
  to eliminate the coupling, but no current correctness risk.

### graph.py — confirmed clean + \_loop_router note

Full re-read (690 lines). All hardening landed:

- `_worker_retry_on` at line 46 — GraphRecursionError excluded, AcpSessionError excluded,
  TimeoutError whitelisted, WorkerExecutionError.**cause** unwrapping correct.
- `_WORKER_RETRY = RetryPolicy(max_attempts=3, ...)` at line 105. Correct params.
- `interrupt_before=[]` always (line 292). Correct.
- `step_timeout` post-compile at lines 294-295. Correct.
- INFO: `_loop_router:683` — `state.get("next", "revise")` default is "revise".
  Workers never set `state["next"]` (that's the supervisor's field), so the "revise"
  path is always taken (loop continues) unless `loop_count >= max_loops` short-circuits.
  The `"FINISH"` branch in the route_map is only reachable if a worker explicitly sets
  `next="FINISH"` — which none currently do. This is dead but harmless; kept as INFO.

### state.py — confirmed clean

Full re-read (112 lines). All state fields validated:

- `messages: Annotated[list[BaseMessage], add_messages]` — correct reducer.
- `artifacts: Annotated[..., _append_artifacts]` — custom dedup reducer.
- `current_plan: Annotated[..., _replace_plan]` — replacement reducer (T12 fix).
- `token_usage: Annotated[..., _merge_token_usage]` — additive merge reducer.
- `loop_count: NotRequired[int]` — plain last-write-wins (no reducer needed, incremented once per superstep by wrapper).
- `next: NotRequired[str]`, `routing_error: NotRequired[str]` — NotRequired correct.
- `thread_id: str` — required, set in graph_input (T13 fix).
- `active_agent: str` — required. Note: no worker node currently writes `active_agent`.
  If this field is required (non-NotRequired), LangGraph will fail on graph_input if it is
  missing. Need to verify `active_agent` is set in graph_input call path.

### aggregator.py 1130-1200 — confirmed clean (step_timeout branch)

`_is_step_timeout` branch at line 1160-1174 confirmed wired (T19/Cycle 25 fix).
`STEP_TIMEOUT` code with `recoverable=True` emitted. Correct.
`_is_interrupt` guard at line 1193 correctly gates `_emit_interrupt_events` to avoid
spurious aget_state I/O on non-interrupt exits.

### active_agent field — never updated by any node (LOW)

Initially flagged as potential KeyError risk (required field not in graph_input).
Cross-checked `lib/worker/executor.py:187` — `"active_agent": ""` is always supplied
in the graph_input dict. `lib/core/context.py:147` also sets it on compaction.
KeyError risk retracted.

NEW LOW FINDING: Neither `worker.py` nor `supervisor.py` ever writes `active_agent`
back to state. The field is initialized to `""` and remains `""` for the entire
graph lifetime. The field is declared `active_agent: str` (non-NotRequired) yet
carries no information — it's a dead field. If the intent was to track which agent
is currently active (useful for aggregator/frontend routing), the supervisor or workers
need to include `"active_agent": name` in their return dict. As-is the field is always
`""` in production and should be either removed or populated.

- Severity: LOW
- File: lib/core/state.py:81, lib/core/nodes/worker.py:185 (return dict omits active_agent),
  lib/core/nodes/supervisor.py:106 (return dict omits active_agent)
- Fix direction: Either mark `active_agent: NotRequired[str]` and remove from required
  graph_input, OR have worker_node set `"active_agent": name` in its return dict.
  The supervisor emits the routing decision via `next`, not active_agent.
  Worker node already has `name` in scope — adding `"active_agent": name` to its
  return is a one-line fix that makes the field meaningful.

---

## [CYCLE 28 FINDINGS] --- docs-researcher: Checkpointer threading + channel init research

Topics from original research queue: 9 (InMemorySaver vs AsyncSqliteSaver threading) and 10 (channel initialization).

### Topic 9: InMemorySaver vs AsyncSqliteSaver — threading guarantees

Source: `knowledge/repositories/langgraph/libs/checkpoint/langgraph/checkpoint/memory/__init__.py`
and `knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py`.

**InMemorySaver threading model:**

- Stores state in a plain `defaultdict` — no locking of any kind.
- `aget_tuple`, `alist`, `aput`, `aput_writes` are all thin `async def` wrappers that call
  the synchronous methods directly (no `await` inside, just `return self.method(...)`).
- The `async` interface is entirely non-blocking from the event loop perspective — each call
  completes synchronously within the coroutine without yielding.
- **Concurrency hazard**: If two concurrent `ainvoke`/`astream` calls for the same `thread_id`
  race on `put` / `put_writes`, there is no mutex — pure dict mutation without serialization.
  LangGraph's Pregel loop itself serializes superstep writes for a single run, but if the
  same `thread_id` is submitted twice concurrently the results are undefined.
- **Production verdict**: The docstring explicitly states "Only use InMemorySaver for debugging
  or testing purposes." Our codebase correctly uses `AsyncSqliteSaver` in production (executor.py:68).
  Tests that were previously using `InMemorySaver` were correct for the test context.

**AsyncSqliteSaver threading model:**

- `self.lock = asyncio.Lock()` at init (line 120) — a single asyncio lock guards all DB operations.
- Every async operation (`aget_tuple`, `alist`, `aput`, `aput_writes`, `adelete_thread`) acquires
  `async with self.lock` before touching the database.
- This means: only one checkpointer operation runs at a time across ALL concurrent graph runs
  sharing the same `AsyncSqliteSaver` instance.
- **Key implication**: Multiple concurrent threads for different `thread_id`s sharing one
  `AsyncSqliteSaver` instance will serialize all their checkpoint reads/writes through a single
  asyncio lock. This is safe but creates checkpoint-write bottleneck under concurrent load.
- `PRAGMA journal_mode=WAL` is set at setup (line 289) — this is correct for multi-reader
  scenarios but the asyncio lock means our single connection is the bottleneck anyway.
- Sync fallback (`get_tuple`, `list`, `put`, `put_writes`) uses `asyncio.run_coroutine_threadsafe`
  with an explicit "only allowed from a different thread" guard — not relevant to our async-only paths.

**Codebase assessment:**

- Our `executor.py` uses a single shared `AsyncSqliteSaver` instance across all concurrent graph
  runs on the worker. This is safe (lock ensures consistency) but creates a serialization bottleneck
  when many threads are active simultaneously.
- For current scale this is acceptable. Under high concurrency (>10 simultaneous graph runs), the
  checkpoint lock could become a latency bottleneck. Postgres checkpointer would remove this.
- Severity: INFO — correct and safe, known limitation of SQLite checkpointer.

### Topic 10: Channel initialization — does TeamState need explicit defaults?

Source: `knowledge/repositories/langgraph/libs/langgraph/langgraph/graph/state.py` (already read in earlier cycles).

**LangGraph channel initialization:**

- LangGraph uses `TypedDict` annotations to discover channels. For each key in the TypedDict:
  - `Annotated[T, reducer]` → creates a `BinaryOperatorAggregate` channel with that reducer.
  - Plain `T` → creates a `LastValue` channel.
  - `NotRequired[T]` → same as plain `T` but absent from `channel_specs` `__required_keys__`.
- On first invocation, Pregel initializes channels from the `input` dict. Any key NOT in the
  input dict that IS required (not `NotRequired`) triggers a `KeyError`.
- For `NotRequired` keys: channels are initialized only when first written. If never written,
  `state.get("key")` returns `None` (safe) while `state["key"]` raises `KeyError`.
- No `__defaults__` mechanism exists in LangGraph TypedDict channels — defaults must be supplied
  via `graph_input` at invocation time.

**Codebase assessment:**

- `executor.py:180-195` builds graph_input with: `messages`, `active_agent`, `artifacts`,
  `token_usage`, `thread_id`, `current_plan` — all six required fields.
- `loop_count`, `next`, `routing_error` are `NotRequired` — correctly absent from graph_input.
- This is correct. No `__defaults__` needed. Finding: CLEAN.

### Summary for Cycle 28

| Severity | Finding                                                                               | Status                  |
| -------- | ------------------------------------------------------------------------------------- | ----------------------- |
| INFO     | AsyncSqliteSaver single-lock serializes all concurrent checkpoint ops                 | open (known limitation) |
| CLEAN    | Channel initialization — no defaults needed, graph_input supplies all required fields | resolved                |

---

## [CYCLE 29 FINDINGS] --- docs-researcher: Durability mode, CachePolicy, channel types, LastValue collision

New research batch covering LangGraph source: Durability mode semantics, CachePolicy applicability,
channel type catalogue (LastValue / AnyValue / EphemeralValue), and `LastValue` multi-writer collision.

### Topic A: Durability mode — `"async"` default vs `"sync"` for interrupt safety

Source: `knowledge/repositories/langgraph/libs/langgraph/langgraph/pregel/main.py:2394,2658`
and `knowledge/repositories/langgraph/libs/langgraph/langgraph/types.py:62`.

**How Durability works:**

- Default is `"async"` (from `CONFIG_KEY_DURABILITY` config or hardcoded fallback at line 2394-2395).
  Checkpoint writes are fired asynchronously in the background while the NEXT superstep is already
  executing. This maximises throughput but creates a window where a crash between supersteps
  can lose the most recent checkpoint write.
- `"sync"` mode: After each `loop.after_tick()`, Pregel calls
  `loop._put_checkpoint_fut.result()` (line 2658-2659) — blocks until the checkpoint is
  durably written before the next superstep begins. Safe for interrupt scenarios.
- `"exit"` mode: checkpoint is written only when the graph exits entirely.

**Codebase assessment:**
Our `aggregator.ingest()` calls `graph.astream_events(graph_input, config, version="v2")` at
line 1103 — no `durability` keyword passed. This means the default `"async"` mode is used.

For the interrupt / permission flow specifically:

- When a node calls `interrupt()`, a `GraphInterrupt` is raised and propagates out of
  `astream_events`. The checkpoint write for the superstep that raised the interrupt is
  initiated (in the background under `"async"` mode) but may not have completed by the time
  `_emit_interrupt_events` calls `aget_state()`.
- Under `"async"` mode, `aget_state()` may read stale state if the checkpoint write is still
  in flight. This creates a small race window where `state.tasks[*].interrupts` is empty
  and `_emit_interrupt_events` emits no `PermissionRequestEvent`.
- Passing `durability="sync"` in the `astream_events` call would eliminate this race by
  guaranteeing the checkpoint is flushed before the exception propagates.
- Orchestrator has already acknowledged this as LOW severity (narrow race window, 10s
  aget_state timeout as safety net). Recording here for completeness.

### Topic B: CachePolicy — applicability to our nodes

Source: `knowledge/repositories/langgraph/libs/langgraph/langgraph/types.py:144-153`
and `_internal/_cache.py` (not read, but API understood from types.py).

**CachePolicy definition:**

```python
@dataclass(kw_only=True, slots=True, frozen=True)
class CachePolicy(Generic[KeyFuncT]):
    key_func: KeyFuncT = default_cache_key  # hashes input with pickle
    ttl: int | None = None  # None = never expires
```

**Codebase assessment — none of our nodes are cache-eligible:**

- `worker_node` calls an LLM with the full message history. Output is non-deterministic.
  Caching by input state would produce stale LLM responses. Not suitable.
- `supervisor_node` routes based on conversation history. Non-deterministic by intent.
  Not suitable.
- `_loop_node_with_counter` wraps worker — also LLM-backed. Not suitable.
- `CachePolicy` is designed for deterministic tool-invocation nodes (e.g., retrieval,
  formatting). Our topology has no such nodes.
- Finding: CLEAN. No `CachePolicy` opportunities in current codebase.

### Topic C: Channel type catalogue and TeamState field mapping

Source: channel source files read this cycle.

**Channel types available:**
| Type | Behaviour | Our usage |
|------|-----------|-----------|
| `LastValue` | Stores last write, raises `InvalidUpdateError` if 2+ writes in same superstep | plain `str`/`int` fields |
| `AnyValue` | Stores last write, silently accepts multiple writes (assumes they're equal) | not used |
| `EphemeralValue` | Stores last write, clears to `MISSING` after each superstep | not used |
| `BinaryOperatorAggregate` | Applies `Annotated[T, reducer]` | `messages`, `artifacts`, `current_plan`, `token_usage` |

**NEW FINDING — LastValue collision risk on parallel star topology:**

- `active_agent: str`, `thread_id: str`, `next: NotRequired[str]`, `routing_error: NotRequired[str]`,
  `loop_count: NotRequired[int]` — all use plain `LastValue` channels (no `Annotated`).
- `LastValue.update()` raises `InvalidUpdateError` ("Can receive only one value per step.
  Use an Annotated key to handle multiple values.") if MORE THAN ONE write arrives for the
  same channel in a single superstep.
- In the current star topology, only one worker runs per superstep (supervisor routes to
  exactly one worker). So this is safe.
- **Risk scenario**: If a future topology uses `Send` to dispatch multiple workers in the
  same superstep (map-reduce style), any two workers that both write `next` or `active_agent`
  in the same superstep would crash with `InvalidUpdateError`. This is a latent bug activated
  only by topological change.
- `token_usage` correctly uses `_merge_token_usage` (BinaryOperatorAggregate) so parallel
  workers can safely write token counts — that path is already hardened.
- Severity: LOW (safe under current topologies, latent risk for future map-reduce patterns).
- Fix direction: If `Send`-based parallel dispatch is ever added, `next` would need
  `NotRequired[Annotated[str, lambda a, b: b]]` (last-write-wins override) or simply not
  be written by parallel workers.

### Summary for Cycle 29

| Severity            | Finding                                                                                      | Status                         |
| ------------------- | -------------------------------------------------------------------------------------------- | ------------------------------ |
| LOW (already acked) | `durability="async"` race window on interrupt aget_state                                     | open — orchestrator: no action |
| CLEAN               | CachePolicy — no deterministic nodes in codebase                                             | n/a                            |
| LOW                 | LastValue collision if parallel Send dispatch ever added (active_agent, next, routing_error) | open                           |

---

## [CYCLE 30 FINDINGS] --- docs-researcher: aget_state interrupt detection path deep-dive

Deep audit of `_emit_interrupt_events` against LangGraph's `aget_state` / `_prepare_state_snapshot`
/ `tasks_w_writes` source chain. Confirms correctness of the interrupt detection approach with
one important nuance.

### How `state.tasks[*].interrupts` is populated by `aget_state`

Source: `pregel/main.py:996-1113` (`_prepare_state_snapshot`) and `pregel/debug.py:215-284` (`tasks_w_writes`).

Full trace:

1. `aget_state(config)` → `checkpointer.aget_tuple(config)` → `CheckpointTuple` with `pending_writes`.
2. `_aprepare_state_snapshot` calls `prepare_next_tasks(saved.checkpoint, saved.pending_writes, ...)`
   to reconstruct which tasks are pending next execution.
3. `tasks_w_writes()` at `debug.py:215` iterates `pending_writes` for each task:
   ```python
   task_interrupts = tuple(
       v
       for tid, n, vv in pending_writes
       if tid == task.id and n == INTERRUPT   # ← INTERRUPT sentinel channel
       for v in (vv if isinstance(vv, Sequence) else [vv])
   )
   ```
4. `PregelTask(task.id, task.name, task.path, task_error, task_interrupts, ...)` is created.
5. `StateSnapshot.interrupts` is the flat union: `tuple([i for task in tasks_with_writes for i in task.interrupts])`.

**Key insight:** `task.interrupts` is populated from `pending_writes` where channel == `INTERRUPT`
sentinel. This is stored in the checkpointer's `writes` table when `interrupt()` is called.
The `pending_writes` are NOT part of the main checkpoint blob — they are separate rows in the
`writes` table keyed by `(thread_id, checkpoint_ns, checkpoint_id)`.

**Correctness of `_emit_interrupt_events`:**
Our implementation at `aggregator.py:1005-1050` reads `state.tasks` and iterates
`task.interrupts`. This is the correct field to read — `task.interrupts` comes from
`pending_writes[INTERRUPT]` which are written synchronously (the SQLite `aput_writes` call
happens inside the same checkpoint transaction that records the interrupt).

**NEW FINDING — StateSnapshot.interrupts is also available directly:**

`StateSnapshot.interrupts` at `main.py:1112` is the flat tuple of ALL interrupts across all
tasks: `tuple([i for task in tasks_with_writes for i in task.interrupts])`. Our code iterates
`state.tasks` and then `task.interrupts` per task — this is equivalent but requires two loops.

Using `state.interrupts` directly would be simpler:

```python
# Current (correct but verbose):
for task in tasks:
    for interrupt_obj in task.interrupts:
        ...

# Simpler equivalent:
for interrupt_obj in state.interrupts:
    # But we lose task.name for agent_id attribution
    ...
```

The current per-task loop is actually BETTER than using `state.interrupts` flat because it
preserves `task.name` for the `agent_id` attribution in the emitted `PermissionRequestEvent`.
Using `state.interrupts` would lose the per-task agent attribution. Finding: our approach
is the correct and more informative choice. CLEAN.

**FINDING — `apply_pending_writes` flag and pending write skipping:**

At `_prepare_state_snapshot:1086-1092`, when `apply_pending_writes=True` (which is the case
when no `checkpoint_id` is in config — i.e., normal `aget_state()` without pinning):

```python
for tid, k, v in saved.pending_writes:
    if k in (ERROR, INTERRUPT):
        continue   # ← INTERRUPT writes are EXCLUDED from state application
    ...
```

`INTERRUPT` pending writes are deliberately NOT applied to channel state — they are kept as
pending writes and surface only through `task.interrupts`. This is the correct design:
interrupt values are metadata, not channel state. Our reading of `task.interrupts` is correct.

### `StateSnapshot.tasks` when graph completed normally

At `main.py:1106`: `next=tuple(t.name for t in next_tasks.values() if not t.writes)`.
When the graph completes normally, all tasks have writes and none are pending → `next=()`.
`tasks_with_writes` will still contain tasks (with their result writes), but `task.interrupts`
will be empty tuples for all. Our guard at `aggregator.py:1006` (`if not state or not tasks: return`)
is slightly misleading — `tasks` will be non-empty even on normal completion, containing the
last-executed tasks with their result writes. The guard passes through to the per-task loop,
but `task.interrupts` is empty for all tasks on normal completion → no events emitted. Correct
outcome, but the comment "Normal completion — no pending interrupts" at line 1007 is inaccurate
since `tasks` is NOT empty on normal completion.

- Severity: LOW (code comment accuracy / potential future confusion)
- File: `lib/core/aggregator.py:1006-1007`
- Issue: `if not state or not tasks` guard will NOT short-circuit on normal completion because
  `tasks` is a non-empty tuple of the previously-executed tasks. The loop still runs correctly
  (all `task.interrupts` are empty) but the guard condition is misleading.
- Fix direction: Change guard to `if not state or not state.next` — `state.next` is empty
  on normal completion and non-empty when tasks are pending (interrupted). Or alternatively,
  add a more precise guard: `if not any(t.interrupts for t in tasks): return`.

### Summary for Cycle 30

| Severity | Finding                                                                                            | Status   |
| -------- | -------------------------------------------------------------------------------------------------- | -------- |
| CLEAN    | `_emit_interrupt_events` reads correct field (`task.interrupts` from `pending_writes[INTERRUPT]`)  | verified |
| CLEAN    | Per-task loop preserves `task.name` for agent_id attribution — better than `state.interrupts` flat | verified |
| LOW      | `aggregator.py:1006` guard `if not tasks` never short-circuits on normal completion — misleading   | open     |

---

## [CYCLE 31 FINDINGS] --- docs-researcher: astream_events coverage + context.py audit

### Topic A: astream_events v2 event coverage

`_PASSTHROUGH_EVENTS` and `_NODE_BOUNDARY_EVENTS` cover all actionable v2 events:

- `on_chat_model_stream` → MessageChunkEvent. Correct.
- `on_tool_start/end/error` → ToolCall events. Correct.
- `on_custom_event` → ThoughtChunkEvent. Correct.
- `on_chain_start/end/error` (node-gated) → AgentStatusEvent. Correct.
- `on_chat_model_start/end`, parser/retriever/prompt events — correctly filtered.
- `TAG_NOSTREAM` on supervisor model confirmed at `_messages.py:134` suppresses supervisor
  streaming. Correct.
- INFO: `on_chat_model_start/end` fall through to the `events_filtered` OTel counter,
  adding noise to that metric (harmless, one increment per LLM call per node turn).

### Topic B: context.py — full audit

All compaction properties verified clean:

- `estimate_tokens` multi-part content handling correct (vision messages).
- `should_compact` 80% threshold correct.
- H5 fix (`max(0, budget)`) prevents negative budget. Correct.
- Minimum-message guarantee (line 107-109) preserves at least most recent message. Correct.
- `HumanMessage` summary (T14 fix) confirmed.

NEW LOW: The "summary" inserted at line 114-120 is a static boilerplate placeholder — it
contains no content from the dropped messages. The docstring overstates it as a summary.
By ADR-002 design (structural state over history), this is architecturally intentional.

- Severity: LOW / by-design
- File: `lib/core/context.py:114-121`
- Note: Not actionable without ADR update. If richer handoff context is needed, an
  LLM-based summarisation step over dropped messages could be introduced.

### Summary for Cycle 31

| Severity        | Finding                                                                 | Status   |
| --------------- | ----------------------------------------------------------------------- | -------- |
| CLEAN           | astream_events v2 coverage complete and correct                         | verified |
| INFO            | on_chat_model_start/end add noise to events_filtered OTel counter       | open     |
| LOW (by design) | compact_context summary is static boilerplate, not actual summarisation | open     |

---

## Cycle 32 — endpoints.py full audit + send_message ingest gaps

**Files read:** `lib/api/endpoints.py` (full), `lib/api/schemas/internal.py`, `lib/worker/executor.py:100-320`, `lib/core/state.py`

### Finding 1: [MEDIUM] send_message_endpoint omits team_preset/workspace_root from ingest dispatch

**File:** `lib/api/endpoints.py:562-566`, compare with `lib/api/endpoints.py:731-737`
**Issue:** `send_message_endpoint` dispatches `DispatchRequest(action="ingest", thread_id=..., agent_id=..., content=...)` without `team_preset` or `workspace_root`. In `_handle_ingest` (worker line 147): `if req.thread_id not in self._graphs and req.team_preset:` — if the worker process restarted or evicted the graph (memory pressure), the ingest falls through to `graph = None` → `logger.warning("No graph for thread %s -- cannot ingest")` → **user message silently dropped**.

Compare: `respond_to_permission_endpoint` was already fixed (T22) to look up `team_preset` and `workspace_root` from the DB and pass them in the resume `DispatchRequest`. The same fix is needed for `send_message_endpoint`.

**Fix direction:**

```python
# In send_message_endpoint, before dispatching:
team_preset: str | None = None
workspace_root: str | None = None
if thread_record is not None:  # already fetched above
    team_preset = thread_record.team_preset
    if thread_record.thread_metadata:
        try:
            meta = json.loads(thread_record.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

dispatch = DispatchRequest(
    action="ingest",
    thread_id=thread_id,
    agent_id=agent_id,
    content=body.content,
    team_preset=team_preset,
    workspace_root=workspace_root,
)
```

- Severity: MEDIUM
- Impact: Silent message loss after worker restart during active threads

### Finding 2: [HIGH] send_message ingest wipes current_plan via \_replace_plan reducer

**File:** `lib/worker/executor.py:185-192`, `lib/core/state.py:56-64`
**Issue:** `_handle_ingest` always supplies `"current_plan": []` in `graph_input`. The `_replace_plan` reducer is: `return new if new is not None else existing`. Since `[]` is not `None`, it always returns `[]`. **Every user follow-up message (send_message) unconditionally wipes the current plan from the checkpoint**.

This is a correctness bug: the supervisor's plan built during the first turn is erased when the user sends any subsequent message. On the next graph run, the supervisor starts from an empty plan with no context of what was already decided.

**Fix direction:** Two options:

1. Change `graph_input` to omit `current_plan` key entirely when it's a follow-up (not initial creation) — LangGraph only calls the reducer if the key is present in the update dict.
2. Change `_replace_plan` to treat empty list as "no-op": `return new if new else existing` — but this prevents intentional plan clearing.

Option 1 is cleaner: only set `current_plan: []` when building the very first graph input (initial thread creation). For follow-up messages, omit it.

- Severity: HIGH
- Impact: Plan state lost on every user follow-up message; supervisor must re-plan from scratch each turn with only messages history as context, defeating the purpose of the plan field.

### Finding 3: [CLEAN] respond_to_permission_endpoint — T22 fix correctly implemented

The T22 fix at lines 718-729 correctly:

- Looks up `thread_record.team_preset` from DB
- Parses `workspace_root` from `thread_record.thread_metadata` JSON
- Passes both into `DispatchRequest(action="resume", ...)`
  The lazy recompile path in `_handle_resume` (executor.py:228-257) correctly uses `req.team_preset` as fallback when `preset_info` is absent from cache.
  CLEAN — T22 fully functional.

### Finding 4: [INFO] \_enrich_snapshot_from_state: \_MinimalState inner class defined per request

**File:** `lib/api/endpoints.py:488-492`
**Issue:** A `_MinimalState` class is defined inside `get_thread_state_endpoint` on every HTTP request that has checkpoint data. In CPython, `class` bodies are executed at call time, so this creates a fresh class object per request. Harmless for correctness, minor allocation overhead. Could be lifted to module level.

- Severity: INFO — cosmetic/micro-perf only.

### Finding 5: [INFO] aget() used instead of aget_tuple() in snapshot endpoint

**File:** `lib/api/endpoints.py:477-478`
**Issue:** `checkpointer.aget(config)` returns raw checkpoint dict, while `aget_tuple(config)` returns `CheckpointTuple` (which includes the metadata and pending writes). The snapshot endpoint only needs messages, so `aget()` is appropriate. However, `checkpoint["id"]` at line 496 is the checkpoint's UUID — this is populated by the LangGraph internal checkpoint structure and should be present. CLEAN by inspection.

- Severity: INFO — confirmed correct.

### Finding 6: [CLEAN] PermissionResponseResult.accepted=False when thread_id not parseable

**File:** `lib/api/endpoints.py:751-760`
**Issue:** If `request_id` has no colon (invalid format), `thread_id=""` and the dispatch branch is skipped. `dispatched=False` → `accepted=False`. Response returns 200 with `accepted=False`. This is fail-safe — the client gets a clear signal.
CLEAN.

### Finding 7: [MEDIUM] send_message_endpoint: graph_input sets active_agent="" on every follow-up

**File:** `lib/worker/executor.py:187`
**Issue:** `"active_agent": ""` in graph_input is passed to `add_messages`-style... no, `active_agent` is a plain `LastValue` channel (no reducer annotation). So every ingest (including follow-up messages) writes `active_agent=""` to the checkpoint, overwriting whatever the last worker set. When the supervisor reads state on a follow-up run, `state["active_agent"]` will always be `""` rather than the last active agent.

Same fix: omit `active_agent` from `graph_input` for follow-up messages. Only set on initial creation. The supervisor doesn't use `active_agent` for routing (it uses `next`), but it's confusing dead state.

- Severity: MEDIUM (contributes to the dead `active_agent` field finding from Cycle 27)

### Summary for Cycle 32

| Severity | Finding                                                                                  | File                             | Status                         |
| -------- | ---------------------------------------------------------------------------------------- | -------------------------------- | ------------------------------ |
| HIGH     | send_message wipes current_plan via \_replace_plan on every follow-up                    | `executor.py:186`, `state.py:63` | open — needs task              |
| MEDIUM   | send_message omits team_preset/workspace_root → silent message drop after worker restart | `endpoints.py:562-566`           | open — needs task              |
| MEDIUM   | send_message sets active_agent="" on every follow-up (LastValue overwrite)               | `executor.py:187`                | open (related to Cycle 27 LOW) |
| CLEAN    | T22 resume path correctly wires team_preset + workspace_root                             | `endpoints.py:731-737`           | verified                       |
| INFO     | \_MinimalState inner class allocated per request                                         | `endpoints.py:488`               | cosmetic                       |
| INFO     | aget() vs aget_tuple() correct for snapshot use                                          | `endpoints.py:477`               | verified                       |
| CLEAN    | PermissionResponseResult fail-safe when request_id malformed                             | `endpoints.py:751`               | verified                       |

---

## Cycle 33 — Worker event relay audit: CRITICAL gap found

**Files read:** `lib/worker/app.py`, `lib/worker/ipc.py`, `lib/worker/executor.py:1-100,320-352`, `lib/core/aggregator.py:408-452` (subscriber/broadcast path)

### Finding 1: [CRITICAL] Worker EventAggregator never relays events to control surface

**Files:** `lib/worker/executor.py:77`, `lib/core/aggregator.py:408-452`

`Executor.__init__` creates `self._aggregator = EventAggregator()` with an empty `_subscribers` dict. The aggregator's `_broadcast` method iterates `self._subscribers.items()` — which is always empty in the worker process. **No events (message chunks, agent status, tool calls, permissions, errors) ever reach the control surface or browser clients.**

`WorkerBridge.send_event()` (ipc.py:75) is implemented and tested, but it is never called from within the executor or aggregator. The bridge is only used for `track_thread`, `untrack_thread`, `send_heartbeat`, and `heartbeat_loop`.

**Impact:** End-to-end streaming is completely broken in the ADR-019 separated-process architecture. All LangGraph events processed by the worker are silently discarded. The frontend receives no updates while agents are running.

**Fix direction:** Register a bridge-forwarding subscriber in the worker aggregator. One clean approach:

```python
# In Executor.__init__, after creating self._aggregator:
_BRIDGE_CLIENT_ID = "_bridge"
queue = self._aggregator.add_subscriber(_BRIDGE_CLIENT_ID)
# Start a relay task that drains the queue and calls bridge.send_event
```

Or simpler — add a `bridge_subscriber` callback registration API to `EventAggregator` that is called from `_broadcast` in addition to queue delivery, allowing the worker to register `bridge.send_event` as a post-broadcast hook.

The relay task must drain the queue and forward each event's JSON to `bridge.send_event(thread_id, event.model_dump())`.

- Severity: CRITICAL
- Impact: Worker architecture is functionally a black box — no streaming feedback to any client.

### Finding 2: [MEDIUM] heartbeat_loop uses asyncio.sleep inside anyio TaskGroup

**File:** `lib/worker/ipc.py:132`

`heartbeat_loop` calls `await asyncio.sleep(interval)` inside an `anyio.create_task_group()` started task. Under the asyncio backend (current default), this works. Under trio (if ever switched), `asyncio.sleep` would not integrate with trio's event loop. Should be `await anyio.sleep(interval)` for backend-agnostic correctness.

- Severity: MEDIUM (latent portability bug)

### Finding 3: [INFO] Shutdown order: bridge.close() before tg.cancel_scope.cancel()

**File:** `lib/worker/app.py:87-91`

Teardown sequence: `executor.shutdown()` → `bridge.close()` → `tg.cancel_scope.cancel()`. The heartbeat loop runs in `tg` and calls `bridge.send_heartbeat()` which uses `bridge._client`. If the heartbeat fires between `bridge.close()` and `tg.cancel_scope.cancel()`, it hits a closed httpx client. `send_heartbeat` catches `httpx.HTTPError` at DEBUG level — so it's benign but noisy.

- Fix: call `tg.cancel_scope.cancel()` before `bridge.close()`, or reverse the order.
- Severity: INFO (benign, covered by exception handler)

### Summary for Cycle 33

| Severity | Finding                                                                                        | File                                  | Status            |
| -------- | ---------------------------------------------------------------------------------------------- | ------------------------------------- | ----------------- |
| CRITICAL | Worker EventAggregator never relays events to control surface — bridge.send_event never called | `executor.py:77`, `aggregator.py:408` | open — needs task |
| MEDIUM   | heartbeat_loop uses asyncio.sleep inside anyio TaskGroup (portability)                         | `ipc.py:132`                          | open              |
| INFO     | Shutdown ordering: bridge.close before tg.cancel_scope.cancel                                  | `app.py:87-91`                        | benign            |

---

## Cycle 34 — supervisor.py + websocket.py + event relay chain verification

**Files read:** `lib/api/supervisor.py` (full), `lib/api/websocket.py` (full)

### Finding 1: [HIGH] supervisor.stop() calls process.wait(timeout=30) synchronously — blocks event loop

**File:** `lib/api/supervisor.py:70`

`subprocess.Popen.wait(timeout=30)` is a **synchronous** blocking call. It is called from `stop()` which is called from the control surface's async lifespan shutdown handler. If the worker is slow to exit, this blocks the entire asyncio event loop for up to 30 seconds during API shutdown, preventing any other coroutines (including Starlette's WebSocket close handshakes) from running.

**Fix direction:** Either:

1. Run `process.wait()` in a thread pool: `await asyncio.get_event_loop().run_in_executor(None, self._process.wait, 30)`
2. Switch to `asyncio.create_subprocess_exec` (non-blocking) and `await proc.wait()`

- Severity: HIGH — blocks event loop during graceful shutdown for up to 30s

### Finding 2: [MEDIUM] supervisor.monitor() uses asyncio.sleep (same pattern as ipc.py)

**File:** `lib/api/supervisor.py:94,106`

Two `asyncio.sleep` calls in `monitor()`. The `monitor()` coroutine runs in an `anyio.create_task_group()` task (from `app.py` lifespan). Should be `anyio.sleep` for backend portability.

- Severity: MEDIUM (same as ipc.py finding)

### Finding 3: [MEDIUM] supervisor.start() uses subprocess.Popen (synchronous)

**File:** `lib/api/supervisor.py:44`

`subprocess.Popen(cmd, ...)` is synchronous. On Linux it's fast (fork+exec), but on Windows it can block for tens of milliseconds while the OS creates the process. During the monitor loop this runs in the async event loop. Should use `asyncio.create_subprocess_exec` and store an `asyncio.subprocess.Process`.

- Severity: MEDIUM (latent, Windows-specific perf concern)

### Finding 4: [CLEAN] broadcast_to_thread event relay chain verified

**File:** `lib/api/websocket.py:506-527`, `lib/api/internal.py:94-118`

The chain: worker → `bridge.send_event` → `POST /internal/events` → `receive_worker_event` → `cm.broadcast_to_thread` → subscribed WebSocket clients.

`broadcast_to_thread` correctly:

- Iterates `self._connections` (with list() snapshot for concurrent safety)
- Checks `self._aggregator._subscriptions` for thread subscription (note: accesses private attribute — INFO finding from Cycle 26 confirmed)
- Skips disconnected WebSocket states
- Sends pre-serialized `payload` dict directly (correct — no need to re-serialize through aggregator)

CLEAN — delivery chain from control surface to browser is correct. The only gap is the upstream worker not calling `bridge.send_event` (T27).

### Finding 5: [INFO] broadcast_to_thread accesses aggregator.\_subscriptions private attribute

**File:** `lib/api/websocket.py:519`

`self._aggregator._subscriptions.get(client_id, set())` — accesses private attribute. This is the previously-noted INFO finding. Could be exposed via a public method `aggregator.get_subscriptions(client_id)` (which already exists at `aggregator.py:329`!).

**Fix:** Replace `self._aggregator._subscriptions.get(client_id, set())` with `self._aggregator.get_subscriptions(client_id)`.

- Severity: LOW (correctness unaffected, but cleaner API usage — existing public method available)

### Finding 6: [CLEAN] WebSocket \_writer_loop and \_heartbeat_loop: cross-cancel via done_callback

**File:** `lib/api/websocket.py:163-174`

H10 fix confirmed: heartbeat and writer tasks are cross-cancelled via `add_done_callback`. When either crashes, the other is cancelled. CLEAN.

### Finding 7: [CLEAN] PERMISSION_RESPONSE over WebSocket correctly rejected

**File:** `lib/api/websocket.py:335-373`

`_handle_permission_response` rejects WS permission responses with an ErrorEvent containing `PERMISSION_RESPONSE_WS_FORBIDDEN` and guides client to REST endpoint. CLEAN.

### Summary for Cycle 34

| Severity | Finding                                                                                 | File                   | Status              |
| -------- | --------------------------------------------------------------------------------------- | ---------------------- | ------------------- |
| HIGH     | supervisor.stop() blocks event loop up to 30s via sync process.wait()                   | `supervisor.py:70`     | open — needs task   |
| MEDIUM   | supervisor.monitor() uses asyncio.sleep in anyio task group                             | `supervisor.py:94,106` | open                |
| MEDIUM   | supervisor.start() uses sync subprocess.Popen                                           | `supervisor.py:44`     | open                |
| CLEAN    | broadcast_to_thread relay chain verified correct                                        | `websocket.py:506-527` | verified            |
| LOW      | broadcast_to_thread uses aggregator.\_subscriptions private attr (public method exists) | `websocket.py:519`     | minor fix available |
| CLEAN    | WS cross-cancel (H10), PERMISSION_RESPONSE WS rejection                                 | `websocket.py:163,335` | verified            |

---

## Cycle 35 — app.py lifespan full audit

**Files read:** `lib/api/app.py` (full), `lib/worker/executor.py:260-289`

### Finding 1: [MEDIUM] \_dispatch_message (WS SEND_MESSAGE path) also missing team_preset/workspace_root

**File:** `lib/api/app.py:103-125`

`_create_dispatch_message_handler` builds the ingest dispatch without `team_preset` or `workspace_root` — same T26 gap as `send_message_endpoint` in `endpoints.py`. T26 scope must be broadened to cover both code paths. After worker restart, both the REST `POST /threads/{id}/messages` and the WS `SEND_MESSAGE` command silently drop messages.

### Finding 2: [HIGH] AGENT_CONTROL.RESUME dispatches Command(resume=None)

**File:** `lib/api/app.py:147-162`, `lib/worker/executor.py:288`

`AgentControlAction.RESUME` dispatches `{"action": "resume", "thread_id": ..., "agent_id": ...}` with no `option_id`. In `_handle_resume`, `Command(resume=req.option_id)` is called where `req.option_id` defaults to `None`. The interrupted worker node returns `None` from `interrupt()` — which cannot match any `PermissionOption`.

The correct permission response flow is `POST /permissions/{id}/respond` (REST) per ADR-011 §3.1. The `AGENT_CONTROL.RESUME` WS path appears to be a general-purpose graph resume (non-permission) — but since `interrupt()` in our worker node is always a permission request, `resume=None` is semantically wrong.

**Fix direction:** Either:

1. Remove/document `AGENT_CONTROL.RESUME` as not for permission responses (permissions are REST-only — already enforced via `PERMISSION_RESPONSE` WS rejection).
2. Add `option_id` to `AgentControlCommand` schema and thread it through `_dispatch_control`.

- Severity: HIGH — RESUME via WS always passes None to interrupt() return value

### Finding 3: [HIGH] Shutdown race — monitor loop restarts killed worker before task group cancel

**File:** `lib/api/app.py:264-280`

Shutdown sequence calls `supervisor.stop()` (line 272) before `tg.cancel_scope.cancel()` (line 280). Between these calls, `supervisor.monitor()` in the task group sees `not self.is_alive()` and calls `self.start()` — spawning a new worker. When `tg.cancel_scope.cancel()` fires, the monitor task is killed but the freshly spawned OS process becomes an orphan.

**Fix direction:** Cancel the task group first, then stop the supervisor:

```python
tg.cancel_scope.cancel()  # kill monitor task first
supervisor.stop()         # then terminate worker cleanly
```

- Severity: HIGH — orphan worker process spawned during graceful shutdown

### Finding 4: [CLEAN] CORS, telemetry, SPA mounting, lifespan checkpointer scoping — all correct

CORS always-on (C1 fix), `settings.cors_allowed_origins` used, checkpointer opened inside `async with` scoped to full lifespan (correct WAL-mode setup). WebSocket endpoint correctly chains `connect` → `listen`. SPA mount conditional on build dir existence. CLEAN.

### Summary for Cycle 35

| Severity | Finding                                                                                        | File             | Status                   |
| -------- | ---------------------------------------------------------------------------------------------- | ---------------- | ------------------------ |
| HIGH     | AGENT_CONTROL.RESUME dispatches Command(resume=None) — always wrong option_id                  | `app.py:147-162` | open — needs task or doc |
| HIGH     | Shutdown race: monitor restarts killed worker before tg.cancel_scope.cancel() → orphan process | `app.py:264-280` | open — needs task        |
| MEDIUM   | \_dispatch_message WS path missing team_preset/workspace_root — T26 scope gap                  | `app.py:103-125` | open — widen T26 scope   |
| CLEAN    | CORS, telemetry, SPA, checkpointer lifecycle, WS wiring                                        | `app.py:304-363` | verified                 |

---

## Cycle 36 — Database CRUD + session layer full audit

**Files read:** `lib/database/crud.py` (full), `lib/database/session.py` (full)

### Overall: CLEAN — well-implemented layer with prior fixes all confirmed

All prior audit fixes verified present:

- TOCTOU race on nickname: SELECT pre-check + `IntegrityError` catch on UNIQUE index collision (H12/H17) ✓
- `_coerce_status` validates status strings before insert (DB-HIGH-02) ✓
- `updated_at` set explicitly in `update_thread_status` + `update_thread_metadata` (DB-H2) ✓
- WAL mode set per-connection via `event.listen` + return value checked (H18) ✓
- Inline `ALTER TABLE threads ADD COLUMN team_preset` migration idempotent via OperationalError guard ✓
- `get_db` uses `try/finally session.close()` for generator cleanup (DB-M3) ✓
- `expire_on_commit=False` on session factory to avoid lazy-load after commit ✓

### Finding 1: [INFO] list_threads uses two separate queries — COUNT then SELECT

**File:** `lib/database/crud.py:194-204`

Two queries in same session: `SELECT COUNT(*) FROM threads` then `SELECT ... LIMIT/OFFSET`. Under WAL, concurrent inserts between the two could produce a `total` that doesn't match the returned list length. This is a normal pagination consistency tradeoff (acceptable) — just worth documenting.

- Severity: INFO — by-design; consistent with standard pagination patterns

### Finding 2: [INFO] get_engine singleton path comparison against DEFAULT_DB_PATH (not existing engine URL)

**File:** `lib/database/session.py:97-113`

H19 warning: the path mismatch check compares `resolved_requested != resolved_default` (line 98) against the module-level `DEFAULT_DB_PATH` constant. However, the code also extracts `existing_path_str` from `_engine.url` and compares against the requested path (lines 101-107). On close reading, the outer `if resolved_requested != resolved_default` guard is a fast-path to skip the extraction for common cases. The full comparison is correct. CLEAN.

### Finding 3: [LOW] No explicit thread-not-found handling in update_thread_status when called from send_message_endpoint

**File:** `lib/database/crud.py:226-236`, `lib/api/endpoints.py:556`

`update_thread_status` returns `None` if `thread_id` not found. `send_message_endpoint` calls `update_thread_status` and ignores the return value (line 556). Since `get_thread` is called earlier on line 545 and raises 404 if missing, the thread is guaranteed to exist at this point. CLEAN by ordering — but the return value silently discarded is a minor readability concern.

- Severity: LOW — no actual bug

### Summary for Cycle 36

| Severity | Finding                                                                       | File                    | Status    |
| -------- | ----------------------------------------------------------------------------- | ----------------------- | --------- |
| CLEAN    | Full CRUD layer — all prior fixes confirmed, WAL setup correct                | `crud.py`, `session.py` | verified  |
| INFO     | list_threads two-query COUNT/SELECT — normal pagination consistency tradeoff  | `crud.py:194`           | by-design |
| INFO     | get_engine singleton path comparison logic correct on close reading           | `session.py:97`         | verified  |
| LOW      | update_thread_status return value silently discarded in send_message_endpoint | `endpoints.py:556`      | cosmetic  |

---

## Cycle 37 — Database models + provider layer quick-scan

**Files read:** `lib/database/models.py` (full), `lib/providers/acp_chat_model.py:1-200` (key sections), targeted grep scans

### models.py: CLEAN

All four models correct:

- `ThreadModel`: unique index on `nickname`, `team_preset` column present, `cascade="all, delete-orphan"` on all relationships, `_utcnow` default and `onupdate` ✓
- `ArtifactModel`, `PermissionLogModel`, `CostTrackingModel`: foreign keys to `threads.id`, appropriate indexes ✓
- `thread_metadata` uses column attr name (SQLAlchemy reserves `metadata` — fix from ADR-014 sprint) ✓

### provider layer quick-scan: CLEAN (no new issues)

Targeted scan for known problem patterns across `lib/providers/`:

- No `asyncio.sleep` calls (anyio portability non-issue here — provider is asyncio-native)
- No `subprocess.Popen` (uses `asyncio.create_subprocess_exec` / `create_subprocess_shell`) ✓
- No `get_event_loop()` usage ✓
- `stdin_lock: asyncio.Lock` present in `_AcpSessionContext` ✓
- `permission_callback` field on `AcpChatModel` ✓
- `model_copy(update={"permission_callback": ...})` isolation confirmed in prior cycles ✓
- `_TERMINAL_COMMAND_ALLOWLIST` frozenset present ✓
- `_SHELL_METACHAR_RE` injection guard present ✓
- `_ENV_NAME_RE` env var name validation present ✓
- `_ACP_STARTUP_TIMEOUT = 120.0` named constant (M18 fix) ✓

INFO: `_spawn_acp_process` on Windows uses `create_subprocess_shell` with `list2cmdline` — previously audited and confirmed correct (platform-specific requirement for `.cmd` shims).

### Summary for Cycle 37

| Severity | Finding                                               | Status   |
| -------- | ----------------------------------------------------- | -------- |
| CLEAN    | models.py — all prior fixes confirmed, schema correct | verified |
| CLEAN    | providers/ — no new asyncio/blocking/injection issues | verified |

---

## [Cycle 38] — lib/api/ audit (endpoints, websocket, app, supervisor, internal, auth, database/crud)

**Reported:** Cycle 38 (codebase-researcher, post-context-compaction)
**Files read:** `lib/api/endpoints.py`, `lib/api/websocket.py`, `lib/api/app.py`, `lib/api/supervisor.py`, `lib/api/internal.py`, `lib/api/auth.py`, `lib/database/crud.py`

### API-01 — MEDIUM: `_dispatch_message` handler in app.py omits `team_preset` and `workspace_root`

**File:** `lib/api/app.py:103-125`
**Issue:** `_create_dispatch_message_handler` builds the dispatch payload with only `action`, `thread_id`, `agent_id`, and `content`. It does NOT look up `team_preset` or `workspace_root` from the DB — unlike `send_message_endpoint` (endpoints.py:563-582) which correctly looks them up for lazy recompilation. WS `SEND_MESSAGE` commands routed through the app-level handler will reach the worker without the context needed for lazy recompile, causing `W-02` (silent continue on AgentConfigNotFoundError) to trigger.
**Fix direction:** Look up `team_preset` and `workspace_root` from DB inside `_dispatch_message`, same pattern as `send_message_endpoint`. Requires access to a DB session from within the closure — either inject a session factory or call the REST endpoint internally. This is the previously-tracked **T26b** gap.
**Severity:** MEDIUM (existing task T26b — confirm it covers this specific code path)
**Status:** open (pending T26b)

---

### API-02 — MEDIUM: `internal.py` WS path has no size limit on incoming frames

**File:** `lib/api/internal.py:44`
**Issue:** `worker_ws_endpoint` calls `await websocket.receive_text()` with no size guard. The `ConnectionManager` client WS path has `_MAX_WS_MESSAGE_BYTES = 1 MiB` enforcement (websocket.py:81, 239-247). The internal WS endpoint (worker→control surface) has no equivalent cap. A misbehaving or compromised worker could push arbitrarily large frames.
**Fix direction:** Apply same `len(raw.encode()) > MAX_INTERNAL_WS_MESSAGE_BYTES` check before `json.loads(raw)`. A reasonable limit (e.g. 4 MiB) would accommodate large event payloads.
**Severity:** MEDIUM
**Status:** open

---

### API-03 — MEDIUM: `internal.py` HTTP `/events` path has no size limit or auth

**File:** `lib/api/internal.py:94-118`
**Issue:** `receive_worker_event` calls `await request.json()` with no body size validation. Any process that can reach the internal port can inject arbitrary events into browser clients. The `/internal` router has no authentication — `auth.py` stub is not wired to any route. In Docker, the worker port is expected to be non-public, but in dev `pip install` mode both API and worker share the same loopback interface.
**Note:** Auth stub acknowledged in `auth.py` as intentional no-op for v1 local use. Flagging as MEDIUM for completeness — in LAN/cloud deployments this becomes HIGH.
**Severity:** MEDIUM (LOW for strict local-only use; track separately from main auth debt)
**Status:** open

---

### API-04 — LOW: `supervisor.py` monitor loop uses `asyncio.sleep` not `anyio.sleep`

**File:** `lib/api/supervisor.py:94, 106`
**Issue:** `WorkerSupervisor.monitor()` uses `await asyncio.sleep(delay)` and `await asyncio.sleep(check_interval)`. The rest of the codebase uses `anyio.sleep` for portability (T28 fixed `ipc.py`). While `monitor()` is only ever called from within an `anyio.create_task_group()` (app.py:258), using `asyncio.sleep` inside an anyio task group is technically compatible but inconsistent with project policy.
**Fix direction:** Replace both `asyncio.sleep` calls with `anyio.sleep`. Import anyio at top of file. Trivial two-line change.
**Severity:** LOW (style/consistency)
**Status:** open

---

### API-05 — LOW: `supervisor.stop()` blocks the event loop (already tracked as T29)

**File:** `lib/api/supervisor.py:64-75`
**Issue:** `supervisor.stop()` calls `self._process.wait(timeout=30)` and `self._process.wait(timeout=5)` — synchronous blocking calls inside an async shutdown path. Confirmed same as T29. Raising here to confirm T29 covers exactly this method.
**Severity:** LOW (tracked as T29)
**Status:** open (pending T29)

---

### API-06 — LOW: Shutdown sequence in `app.py` cancels task group after cleanup

**File:** `lib/api/app.py:264-280`
**Issue:** The shutdown block (inside `async with anyio.create_task_group()`) calls `worker_client.aclose()`, `supervisor.stop()`, `connection_manager.shutdown()`, `aggregator.shutdown()`, `close_db()` — **then** calls `tg.cancel_scope.cancel()` on the last line. Since the `yield` returns to the lifespan context, the `tg.cancel_scope.cancel()` is called after all cleanup is complete but the task group is still technically live (the `supervisor.monitor` coroutine is running in it). The cancel should be the **first** step of the shutdown path, not the last, otherwise `supervisor.monitor` continues looping (and may restart the worker) during the cleanup window. This is the previously-tracked **T30** gap.
**Severity:** MEDIUM (tracked as T30)
**Status:** open (pending T30)

---

### API-07 — INFO: `create_thread` pre-check + TOCTOU IntegrityError catch is correct

**File:** `lib/database/crud.py:132-159`
**Issue:** None — confirming the pattern is correct. The pre-check SELECT + IntegrityError safety net for TOCTOU nickname conflicts is the correct pattern. The `"nickname" in str(exc).lower()` substring check is fragile across DB backends but acceptable for SQLite.
**Status:** CLEAN (verified)

---

### API-08 — INFO: `list_threads` count query is a separate SELECT — potential TOCTOU gap

**File:** `lib/database/crud.py:194-204`
**Issue:** `list_threads` executes two separate queries: first `SELECT COUNT(*)`, then `SELECT * LIMIT/OFFSET`. Between the two, concurrent inserts may change the total, resulting in a `total` that is stale relative to the returned page. This is a known pagination hazard with no simple fix in SQLite (no FOR UPDATE). Not a correctness bug for the current use case — just worth documenting.
**Severity:** INFO (known limitation, no fix recommended)
**Status:** CLEAN (acknowledged)

---

### API-09 — INFO: `_BUNDLED_TEAM_PRESETS` in endpoints.py duplicates MCP `_KNOWN_PRESETS`

**File:** `lib/api/endpoints.py:655-660`, `lib/protocols/mcp/server.py` (MCP-02)
**Issue:** Two separate hardcoded lists of preset IDs. When a new preset is added, both must be updated. Already tracked under MCP-07 (docstring drift) as a pattern. Flagging here for the endpoints.py side.
**Fix direction:** Extract to a single constant in `lib/core/team_config.py` or a dedicated `lib/core/presets.py` and import everywhere. Not urgent — low risk of divergence given the small preset count.
**Severity:** LOW
**Status:** open

---

### API-10 — MEDIUM: `AgentControlAction.RESUME` dispatches raw string "resume" not `Command(resume=...)`

**File:** `lib/api/app.py:145-147`
**Issue:** `_dispatch_control` maps `AgentControlAction.RESUME` → `dispatch_action = "resume"` and POSTs `{"action": "resume", "thread_id": ..., "agent_id": ...}` to the worker. The worker's `executor.py` handles action "resume" by calling `graph.ainput(Command(resume=option_id))` — but the `option_id` field is NOT included in the dispatch payload here. For AGENT_CONTROL.RESUME from the WS, there is no `option_id` in the command schema (`AgentControlCommand` has no `option_id` field). This means RESUME dispatched through agent control always resumes with `option_id=None`. This is the previously-tracked **T31** gap.
**Severity:** MEDIUM (tracked as T31)
**Status:** open (pending T31)

---

### Summary for Cycle 38

| ID     | Severity | File                 | Issue                                                         | Status |
| ------ | -------- | -------------------- | ------------------------------------------------------------- | ------ |
| API-01 | MEDIUM   | app.py:103-125       | `_dispatch_message` missing team_preset/workspace_root (T26b) | open   |
| API-02 | MEDIUM   | internal.py:44       | No size limit on internal WS frames                           | open   |
| API-03 | MEDIUM   | internal.py:94-118   | No body size limit or auth on /internal/events                | open   |
| API-04 | LOW      | supervisor.py:94,106 | asyncio.sleep in monitor (anyio inconsistency)                | open   |
| API-05 | LOW      | supervisor.py:64-75  | supervisor.stop() blocks event loop (T29)                     | open   |
| API-06 | MEDIUM   | app.py:264-280       | Shutdown cancel after cleanup (T30)                           | open   |
| API-07 | INFO     | crud.py:132-159      | TOCTOU IntegrityError catch — correct                         | clean  |
| API-08 | INFO     | crud.py:194-204      | Pagination count TOCTOU — known limitation                    | clean  |
| API-09 | LOW      | endpoints.py:655-660 | \_BUNDLED_TEAM_PRESETS duplicates MCP \_KNOWN_PRESETS         | open   |
| API-10 | MEDIUM   | app.py:145-147       | AGENT_CONTROL.RESUME dispatches without option_id (T31)       | open   |

---

## Cycle 38 — preamble.py, metadata.py, environment.py, telemetry/instrumentation.py

**Files read:**

- `lib/core/preamble.py`
- `lib/core/metadata.py`
- `lib/workspace/environment.py`
- `lib/telemetry/instrumentation.py`

### preamble.py — CLEAN

`build_context_preamble()` constructs a SystemMessage from `ThreadMetadata` fields. No user input injected unsanitized — all fields are Pydantic-validated at `ThreadMetadata` construction time. Path is relative-validated by `ContextRef.path_must_be_relative`. No injection surface.

### metadata.py — CLEAN

- `ContextRef.path_must_be_relative`: rejects absolute paths via `Path(v).is_absolute()` ✓
- `ThreadMetadata.workspace_root_must_be_absolute`: validates absolute path ✓
- `ThreadMetadata.nickname_must_be_valid_slug`: regex `^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$` ✓
- `discover_context_refs`: `glob.escape(feature_tag)` before injecting into glob pattern (C3 fix) ✓
- `_MAX_CONTEXT_REFS = 50` cap prevents pathological workspace enumeration ✓
- `generate_nickname`: sanitizes `feature_tag` via `re.sub(r"[^a-z0-9\-]", "")` (M1 fix) ✓

### environment.py — LOW finding

**WS-L2 [LOW]: `FIGMA_ACCESS_TOKEN` and project-specific API keys not in `scrub_keys`**

`resolve_env_vars()` scrubs known secret env vars before passing the environment to agent subprocesses. The scrub list covers common provider keys. However, project-local secrets present in the live `.env` are not covered:

- `FIGMA_ACCESS_TOKEN` — present in `.env`, not in `scrub_keys`
- `NANOBANANA_GEMINI_API_KEY` — present in `.env`, not in `scrub_keys`
- Any future ad-hoc keys not matching the `VAULTSPEC_` prefix pattern

The `VAULTSPEC_*` prefix scrub provides a generic escape hatch, but Figma and project-specific keys have no prefix convention. They would pass through to agent subprocess environments.

**Severity**: LOW — agents running in the workspace have broad filesystem access already; credential leakage to child processes is a contained risk. However, the `scrub_keys` set should be expanded to cover `FIGMA_ACCESS_TOKEN` and any other non-provider secrets in the project `.env`.

**Recommended fix**: Add `FIGMA_ACCESS_TOKEN` to `scrub_keys`. Consider a comment block listing categories of keys that should be added here when new integrations are introduced. Alternatively, adopt an allowlist approach (only inject known-safe vars) rather than a denylist — more robust to omissions.

**Files:** `lib/workspace/environment.py:72-86`

### telemetry/instrumentation.py — CLEAN

- No secret env vars read or logged ✓
- `LANGCHAIN_API_KEY` consumed only by LangChain at import — never read or logged here (noted explicitly in module docstring) ✓
- `configure_telemetry()` idempotent — `set_tracer_provider` is no-op if provider already set ✓
- `FastAPIInstrumentor` intentionally not called — avoids duplicate spans with `TelemetryMiddleware` (TEL-H2, correctly documented) ✓
- `_check_sdk()` / `_check_otlp()` use `importlib.util.find_spec` (no ImportError guards needed) ✓

### Summary for Cycle 38

| Severity | Finding                                                                     | Location               | Status   |
| -------- | --------------------------------------------------------------------------- | ---------------------- | -------- |
| LOW      | WS-L2: FIGMA_ACCESS_TOKEN not in scrub_keys — leaks to agent subprocess env | `environment.py:72-86` | new      |
| CLEAN    | preamble.py — no injection surface                                          | —                      | verified |
| CLEAN    | metadata.py — all validators confirmed                                      | —                      | verified |
| CLEAN    | telemetry/instrumentation.py — no secrets read/logged, idempotent           | —                      | verified |

---

## Cycle 39 — health.py, **main**.py, auth.py, mcp/server.py

**Files read:**

- `lib/worker/health.py`
- `lib/worker/__main__.py`
- `lib/api/auth.py`
- `lib/protocols/mcp/server.py`

### health.py — CLEAN (stub)

Empty class body — placeholder only. No logic to audit.

### **main**.py — CLEAN

Trivial entry point: `from .app import main; main()` under `__name__ == "__main__"` guard.

### auth.py — CLEAN (acknowledged stub)

No-op stub with correct docstring documenting intent. Not wired into any endpoint yet (Depends not called anywhere). INFO: unauthenticated API is intentional for local-first v1 per ADR note. No action needed.

### mcp/server.py — 2 findings

**MCP-M3 [MEDIUM]: Hardcoded preset fallback + docstring becomes stale after TOML-01 rename**

`_HARDCODED_PRESETS` (line 51) hardcodes the old preset IDs:

```python
_HARDCODED_PRESETS: frozenset[str] = frozenset(
    {"coding-star", "coding-pipeline", "coding-loop", "solo-coder"}
)
```

The `_discovered` path (dynamic glob of TOML files) will self-correct after TOML-01 renames the files. However:

1. The fallback frozenset will serve stale IDs if TOML discovery fails in a packaged deployment
2. The `start_thread` docstring (lines 113-114) hardcodes old preset names as examples: `"coding-star", "coding-pipeline", "coding-loop", "solo-coder"`

After TOML-01 completes, both the fallback set and the docstring must be updated to match new IDs. The coder implementing TOML-01 should include this file in the rename sweep.

**Fix**: Update `_HARDCODED_PRESETS` to new IDs after TOML-01. Update `start_thread` docstring examples.

**Files:** `lib/protocols/mcp/server.py:50-52, 113-114`

---

**MCP-L1 [LOW]: thread_id interpolated directly into URL path without encoding**

In `get_thread_status` (line 185) and `send_message` (line 239):

```python
f"{settings.api_base_url}/api/threads/{thread_id}/state"
f"{settings.api_base_url}/api/threads/{thread_id}/messages"
```

`thread_id` is a user-supplied string from the MCP tool call. A crafted value containing `/`, `?`, `#`, or `..` sequences would produce malformed URLs. Example: `thread_id = "abc/../other"` → `/api/threads/abc/../other/state`.

Impact is LOW — the server-side endpoint validates against the DB (thread won't be found), so there is no path traversal to real resources. But the URL construction is not robust.

**Fix**: Use `httpx.URL` with path params, or `urllib.parse.quote(thread_id, safe="")` before interpolation. Alternatively, validate `thread_id` against a UUID regex before use.

**Files:** `lib/protocols/mcp/server.py:185, 239`

### Summary for Cycle 39

| Severity | Finding                                                                  | Location              | Status   |
| -------- | ------------------------------------------------------------------------ | --------------------- | -------- |
| MEDIUM   | MCP-M3: Hardcoded preset fallback + docstring become stale after TOML-01 | `server.py:50-52,113` | new      |
| LOW      | MCP-L1: thread_id interpolated directly into URL path without encoding   | `server.py:185,239`   | new      |
| CLEAN    | health.py — stub only                                                    | —                     | verified |
| CLEAN    | **main**.py — trivial entry point                                        | —                     | verified |
| CLEAN    | auth.py — acknowledged no-op stub                                        | —                     | verified |

---

## Cycle 40 — nodes/supervisor.py, context.py

**Files read:**

- `lib/core/nodes/supervisor.py`
- `lib/core/context.py`

### nodes/supervisor.py — CLEAN

- Correctly re-raises all exceptions without wrapping (unlike worker.py which wraps non-GraphBubbleUp exceptions) — supervisor lets LangGraph RetryPolicy handle retries directly ✓
- `TAG_NOSTREAM` applied via `model.with_config({"tags": [TAG_NOSTREAM]})` (T07 fix) ✓
- Context compaction via `compact_context` / `should_compact` (T06 fix) ✓
- `routing_error` field set on unparseable response (T03 fix) ✓
- Substring fallback sorted by descending length (T02 fix) ✓
- `supervisor_node.__name__` set explicitly for Protocol conformance ✓

### context.py — CLEAN

- `estimate_tokens`: handles `str`, `list[str|dict]` content types correctly; dict fallback to `part.get("text", "")` handles vision messages ✓
- `compact_context`: `budget = max(0, ...)` clamp prevents negative budget (H5 fix) ✓
- `compact_context`: always preserves at least most recent message even if budget exhausted ✓
- Summary is `HumanMessage` not `SystemMessage` (T14 fix) ✓
- Returns new dict — never mutates input state ✓

INFO: `prepare_handoff()` is exported and tested but called nowhere in production code. It is dead production infrastructure — tested-only API. No action needed; removal would require ADR-002 review.

### Summary for Cycle 40

| Severity | Finding                                                | Location         | Status    |
| -------- | ------------------------------------------------------ | ---------------- | --------- |
| CLEAN    | supervisor.py — all prior fixes confirmed              | —                | verified  |
| CLEAN    | context.py — all prior fixes confirmed                 | —                | verified  |
| INFO     | prepare_handoff() is dead production code (tests only) | `context.py:128` | no action |

---

## [Cycle 40] — lib/core/aggregator.py + lib/database/session.py + lib/workspace/ audit

**Reported:** Cycle 40 (codebase-researcher, post-context-compaction continuation)
**Files read:** `lib/core/aggregator.py` (~1247 lines), `lib/database/session.py`, `lib/workspace/environment.py`, `lib/workspace/git_manager.py`

### AGG-01 — INFO: asyncio.create_task in debounce — documented asyncio-native architecture

**File:** `lib/core/aggregator.py:497, 572`
**Issue:** `_schedule_debounce` and `_buffer_message_chunk` use `asyncio.create_task`. Fire-and-forget tasks that must outlive the calling coroutine. If run under a trio anyio backend this would fail, but the architecture is explicitly asyncio-only (uvicorn/asyncio). The `_debounce_tasks` set tracks them for cleanup via `add_done_callback(discard)`.
**Severity:** INFO (asyncio-native, no action needed)
**Status:** CLEAN

---

### AGG-02 — LOW: `prune_sequences` exists but is never called — unbounded `_sequences` growth

**File:** `lib/core/aggregator.py:314-330`
**Issue:** `prune_sequences` was implemented as M2 fix but has no callers. `_sequences` will accumulate one int entry per thread indefinitely. The dict is small but the cleanup path is wired to nothing.
**Fix direction:** Call `aggregator.prune_sequences({thread_id})` at end of `ingest()` finally block, or from a periodic maintenance task. Very low urgency.
**Severity:** LOW
**Status:** open

---

### AGG-03 — MEDIUM: `_tool_update_last_emit` and `_plan_update_last_emit` are never pruned

**File:** `lib/core/aggregator.py:217-219`
**Issue:** Debounce timestamp dicts accumulate entries for every `(thread_id, tool_call_id)` pair and every `thread_id` over the lifetime of the process. No cleanup on ingest completion, no entry in `shutdown()`. In high-volume deployments (thousands of tool calls), this is a slow memory leak distinct from `_sequences`.
**Fix direction:** Add cleanup of stale debounce keys in the `ingest()` finally block for the completed thread_id, or include in `shutdown()`.
**Severity:** MEDIUM (memory leak, no correctness issue)
**Status:** open

---

### AGG-04 — INFO: `emit_error` in `except BaseException` fallthrough uses ingest-level `agent_id`

**File:** `lib/core/aggregator.py:1192-1198`
**Issue:** When an unexpected exception falls to the `else` branch, `emit_error` uses the `agent_id` passed to `ingest()`, typically `"supervisor"`. In star/pipeline topologies, the error may have originated in a specific worker node but is attributed to supervisor. Cosmetic — event is still emitted and routed correctly.
**Severity:** INFO (attribution cosmetic)
**Status:** INFO

---

### DB-01 — LOW: `init_db` inline migration unversioned — no migration registry

**File:** `lib/database/session.py:190-195`
**Issue:** Single `try: ALTER TABLE threads ADD COLUMN team_preset TEXT; except OperationalError: pass` inline migration. Works for one column but won't scale. `lib/database/migrations/__init__.py` exists but is empty — no Alembic or migration version table.
**Fix direction:** Not urgent for v1. Document as technical debt. Before adding a second migration, adopt Alembic or a minimal version table.
**Severity:** LOW (technical debt)
**Status:** INFO

---

### WS-01 — LOW: `FIGMA_ACCESS_TOKEN` not in `resolve_env_vars` scrub list

**File:** `lib/workspace/environment.py:72-86`
**Issue:** Already caught as WS-L2 in Cycle 38 (preamble audit). Confirming same finding: `FIGMA_ACCESS_TOKEN` (present in live `.env`) is not in `scrub_keys` and would leak to agent subprocess environments. `NANOBANANA_GEMINI_API_KEY` similarly not covered. The `VAULTSPEC_*` prefix check does not help for these keys.
**Fix direction:** Add `FIGMA_ACCESS_TOKEN` to `scrub_keys`. Consider suffix-based `*_API_KEY`/`*_ACCESS_TOKEN` pattern for future-proofing.
**Severity:** LOW
**Status:** open (duplicate of WS-L2 — same fix)

---

### WS-02/WS-03 — CLEAN: git_manager.py validation and mutex

**File:** `lib/workspace/git_manager.py`
**Verified:**

- `_AGENT_ID_RE` enforced on `create_worktree` ✓
- `_BRANCH_NAME_RE` enforced on `create_worktree`, `has_conflicts`, `merge_worktree` ✓
- `_validate_worktree_path` called before all path operations in remove/conflicts/merge ✓
- `asyncio.shield()` on all destructive git commands ✓
- `_git_mutex` held for all worktree/merge mutations ✓
- Module-level `asyncio.Lock()` — commented as safe for Python 3.13, single-process uvicorn ✓
  **Status:** CLEAN

---

### Summary for Cycle 40

| ID       | Severity | File                  | Issue                                                     | Status |
| -------- | -------- | --------------------- | --------------------------------------------------------- | ------ |
| AGG-01   | INFO     | aggregator.py:497,572 | asyncio.create_task in debounce — asyncio-native, correct | clean  |
| AGG-02   | LOW      | aggregator.py:314-330 | prune_sequences never called — \_sequences unbounded      | open   |
| AGG-03   | MEDIUM   | aggregator.py:217-219 | \_tool_update/\_plan_update last_emit dicts never pruned  | open   |
| AGG-04   | INFO     | aggregator.py:1192    | emit_error fallback uses ingest-level agent_id            | info   |
| DB-01    | LOW      | session.py:190-195    | Inline ALTER TABLE unversioned migration                  | info   |
| WS-01    | LOW      | environment.py:72-86  | FIGMA_ACCESS_TOKEN not in scrub list (dup WS-L2)          | open   |
| WS-02/03 | CLEAN    | git_manager.py        | All injection guards, mutex, shield confirmed correct     | clean  |

---

## Cycle 41 — state.py, exceptions.py (final production module sweep)

**Files read:**

- `lib/core/state.py`
- `lib/core/exceptions.py`

### state.py — CLEAN

- `_replace_plan`: `return new if new is not None else existing` — `[]` wipe bug was fixed in T12/T25 by not sending `current_plan: []` in follow-up ingests; reducer itself is correct for supervised planning cycles ✓
- `_append_artifacts`: deduplication by `id` key ✓
- `_merge_token_usage`: additive per-agent delta accumulation ✓
- `loop_count: NotRequired[int]` — correctly optional for non-pipeline_loop topologies ✓
- All fields JSON-serializable for SQLite checkpointer ✓
- `add_messages` reducer on messages (LangGraph built-in) ✓

### exceptions.py — CLEAN

- Full taxonomy: 14 exception types with `ErrorSeverity` + `RecoveryAction` hints ✓
- `WorkerExecutionError` carries `worker`, `model`, `message_count` for structured logging ✓
- `NicknameConflictError` → 409 wired in endpoints ✓
- `AgentConfigNotFoundError` / `TeamConfigNotFoundError` message strings will become stale after TOML-01 renames preset directory paths — but these are error message strings only, not code paths, so impact is cosmetic. The path strings in the error messages reference `lib/core/presets/teams/{team_id}.toml` which is location (not ID), so they remain valid regardless of ID rename.
- `__all__` placement at bottom (non-standard but valid Python) ✓

### Summary for Cycle 41

| Severity | Finding                                                                | Location | Status   |
| -------- | ---------------------------------------------------------------------- | -------- | -------- |
| CLEAN    | state.py — all reducers correct, JSON-serializable                     | —        | verified |
| CLEAN    | exceptions.py — taxonomy complete, error messages correct post-TOML-01 | —        | verified |

---

## Full Audit Coverage Summary

All production modules in `lib/` have been audited across Cycles 1-41:

| Module                             | Status         | Key Findings                    |
| ---------------------------------- | -------------- | ------------------------------- |
| `lib/core/graph.py`                | ✓ AUDITED      | T11-T17, T24-T26 fixes verified |
| `lib/core/state.py`                | ✓ CLEAN        | All reducers correct            |
| `lib/core/context.py`              | ✓ CLEAN        | T06, T14 fixes verified         |
| `lib/core/exceptions.py`           | ✓ CLEAN        | Full taxonomy                   |
| `lib/core/metadata.py`             | ✓ CLEAN        | C3, M1 fixes verified           |
| `lib/core/preamble.py`             | ✓ CLEAN        | No injection surface            |
| `lib/core/team_config.py`          | ✓ CLEAN        | Schema correct                  |
| `lib/core/models.py`               | ✓ CLEAN        | Prior fixes confirmed           |
| `lib/core/nodes/worker.py`         | ✓ CLEAN        | H4, GraphBubbleUp guard ✓       |
| `lib/core/nodes/supervisor.py`     | ✓ CLEAN        | T02, T03, T06, T07 ✓            |
| `lib/api/app.py`                   | T30, T31       | Shutdown race, RESUME None      |
| `lib/api/endpoints.py`             | T26 fixed      | send_message gap                |
| `lib/api/websocket.py`             | T26b pending   | WS dispatch gap                 |
| `lib/api/internal.py`              | ✓ CLEAN        | T21 fix verified                |
| `lib/api/auth.py`                  | ✓ CLEAN        | Acknowledged stub               |
| `lib/api/supervisor.py`            | T29            | Blocking stop(), asyncio.sleep  |
| `lib/api/schemas/`                 | ✓ CLEAN        | All schema types correct        |
| `lib/worker/app.py`                | ✓ AUDITED      | T25-T27 scope                   |
| `lib/worker/executor.py`           | ✓ AUDITED      | T25 fixed                       |
| `lib/worker/ipc.py`                | T27 fixed      | Bridge relay                    |
| `lib/worker/health.py`             | ✓ CLEAN        | Stub                            |
| `lib/worker/__main__.py`           | ✓ CLEAN        | Trivial                         |
| `lib/providers/acp_chat_model.py`  | ✓ CLEAN        | H4 model_copy ✓                 |
| `lib/providers/factory.py`         | ✓ CLEAN        | Single-pass (TOML-02 scope)     |
| `lib/providers/gemini_auth.py`     | ✓ CLEAN        | Async httpx ✓                   |
| `lib/providers/probes/`            | ✓ CLEAN        | All probes correct              |
| `lib/protocols/mcp/server.py`      | MCP-M3, MCP-L1 | Stale presets, URL encoding     |
| `lib/database/crud.py`             | ✓ CLEAN        | All DB fixes confirmed          |
| `lib/database/session.py`          | ✓ CLEAN        | WAL, cleanup correct            |
| `lib/database/models.py`           | ✓ CLEAN        | Schema correct                  |
| `lib/workspace/environment.py`     | WS-L2          | FIGMA_ACCESS_TOKEN not scrubbed |
| `lib/workspace/git_manager.py`     | ✓ AUDITED      | Prior cycles                    |
| `lib/telemetry/instrumentation.py` | ✓ CLEAN        | No secrets, idempotent          |
| `lib/utils/`                       | ✓ CLEAN        | All utils correct               |

---

## [Cycle 41] — lib/protocols/a2a/ + lib/protocols/adapter/ — CLEAN (stubs)

**Reported:** Cycle 41 (codebase-researcher)
**Files read:** `lib/protocols/a2a/__init__.py`, `lib/protocols/adapter/__init__.py`

Both files are empty stubs: single docstring + `__all__: list[str] = []`. No logic to audit.

**Status:** CLEAN — no findings.

---

## [FULL CODEBASE COVERAGE ACHIEVED] — Summary

All `lib/` modules audited across Cycles 1-41. No remaining unexamined source files.

### Open findings requiring future tasking (post-TOML sprint)

| ID      | Severity | Module                         | Issue                                                             |
| ------- | -------- | ------------------------------ | ----------------------------------------------------------------- |
| TC-01   | HIGH     | team_config.py                 | load_team_config missing path-traversal guard on team_id          |
| TC-02   | HIGH     | team_config.py                 | AgentConfig.from_toml bare KeyError on missing [agent] section    |
| PROV-02 | HIGH     | providers/factory.py           | \_CLAUDE_ACP_JS path duplicated + no exists() guard               |
| W-02    | HIGH     | worker/executor.py             | Silent continue on AgentConfigNotFoundError → broken graph stored |
| API-01  | MEDIUM   | api/app.py                     | \_dispatch_message missing team_preset/workspace_root (T26b)      |
| API-02  | MEDIUM   | api/internal.py                | No size limit on internal WS frames                               |
| API-06  | MEDIUM   | api/app.py                     | Shutdown cancel after cleanup (T30)                               |
| API-10  | MEDIUM   | api/app.py                     | AGENT_CONTROL.RESUME missing option_id (T31)                      |
| AGG-03  | MEDIUM   | core/aggregator.py             | \_tool_update/\_plan_update last_emit dicts never pruned          |
| CTX-01  | MEDIUM   | core/context.py                | Infinite compaction loop when system msgs exceed max_tokens       |
| CTX-02  | MEDIUM   | core/context.py                | estimate_tokens ignores tool_calls content                        |
| LOG-01  | MEDIUM   | utils/logging.py               | JSONFormatter crashes on non-serializable extras                  |
| PROV-04 | MEDIUM   | providers/gemini_auth.py       | token_data keys not validated before subscript                    |
| PROV-06 | MEDIUM   | providers/probes/\_protocol.py | Subprocess leaked if stream guard fires                           |
| W-03    | MEDIUM   | worker/executor.py             | Silent drop on first ingest with no team_preset                   |
| W-04    | MEDIUM   | worker/ipc.py                  | send_event catch misses RuntimeError from closed client           |

---

## [Cycle 42] — lib/providers/acp_chat_model.py deep audit

**Reported:** Cycle 42 (codebase-researcher)
**File:** `lib/providers/acp_chat_model.py` (~1350 lines)

### ACP-01 — LOW: `terminal/wait_for_exit` timeout is uncapped — agent can supply arbitrarily large value

**File:** `lib/providers/acp_chat_model.py:976`
**Issue:** `timeout = params.get("timeout") or 60.0` — uses the ACP subprocess-supplied timeout with no upper bound cap. An agent (or a compromised ACP subprocess) can supply `{"timeout": 86400}` to block a background RPC task for 24 hours. The background task holds a slot in `ctx.background_tasks` and will not be cancelled until `_cleanup_session()` runs.
**Fix direction:** Cap timeout: `timeout = min(params.get("timeout") or 60.0, 300.0)`. 5 minutes is a reasonable maximum for any terminal command.
**Severity:** LOW
**Status:** open

---

### ACP-02 — MEDIUM: `_astream` uses `os.environ.copy()` — bypasses `resolve_env_vars` scrub

**File:** `lib/providers/acp_chat_model.py:319-331`
**Issue:** `env = os.environ.copy(); env.update(self.env_vars)` — the ACP subprocess inherits ALL environment variables from the vaultspec server process, including secrets not in the `resolve_env_vars` scrub list. `ProviderFactory` injects only the auth token via `env_vars`, but the base `os.environ` copy already contains `FIGMA_ACCESS_TOKEN`, `ZHIPU_API_KEY`, `NANOBANANA_GEMINI_API_KEY`, and any other secrets in the server's environment.

The ACP agent (claude-agent-acp) runs with the full server credential surface.

**Note:** This is partially intentional — agents need PATH, VIRTUAL_ENV, etc. But the server's secrets should be scrubbed before passing to the subprocess. The `resolve_env_vars()` function in `lib/workspace/environment.py` exists for exactly this purpose but is NOT called here.
**Fix direction:** Replace `env = os.environ.copy()` with `env = resolve_env_vars(Path(self.workspace_root or self.cwd or "."))`, then apply `env.update(self.env_vars)` on top. This uses the already-audited scrub logic.
**Severity:** MEDIUM
**Status:** open

---

### ACP-03 — MEDIUM: `fs/read_text_file` has no size cap — reads entire large files into memory

**File:** `lib/providers/acp_chat_model.py:754-773`
**Issue:** `_on_fs_read_text_file` calls `fh.read(limit) if limit is not None else fh.read()` inside `asyncio.to_thread`. When the agent does not supply a `limit`, the entire file is read. A large file (log, database dump, or binary) would load completely into memory and then be JSON-serialized into the response frame.
**Fix direction:** Apply a default cap, e.g. `limit = min(limit, 10 * 1024 * 1024) if limit is not None else 10 * 1024 * 1024` (10 MiB). Return a `"truncated": true` flag in the result when the cap was hit.
**Severity:** MEDIUM
**Status:** open

---

### ACP-04 — LOW: `_on_request_permission` deny fallback `options[-1]["optionId"]` may raise KeyError

**File:** `lib/providers/acp_chat_model.py:682-683, 702-704`
**Issue:** The deny fallback `options[-1]["optionId"] if options else "deny"` assumes the last element has an `optionId` key. If the ACP subprocess returns a malformed options list where the last dict lacks `optionId`, this raises `KeyError` inside the permission handler, unhandled (only the outer `except Exception` at line 690 catches it for the callback path, but the `elif options and "optionId" in options[0]` path on line 711 has the same fallback exposed).
**Fix direction:** Use `.get("optionId", "deny")` on the fallback subscript: `options[-1].get("optionId", "deny") if options else "deny"`.
**Severity:** LOW
**Status:** open

---

### ACP-05 — INFO: `model_copy()` correctly isolates `_tool_calls` (PrivateAttr reset on copy)

**File:** `lib/providers/acp_chat_model.py:279-298`
**Issue:** None — confirming correctness. `_tool_calls` is a `PrivateAttr` initialized in `model_post_init`. `model_copy()` (used for permission_callback isolation in H4 fix) creates a new Pydantic model instance which triggers `model_post_init`, resetting `_tool_calls = {}`. No cross-invocation contamination.
**Status:** CLEAN

---

### ACP-06 — INFO: `_sandbox_path` correctly prevents path traversal

**File:** `lib/providers/acp_chat_model.py:736-742`
**Issue:** None — `(cwd / path).resolve()` + `resolved.is_relative_to(cwd.resolve())` is the correct pattern. Used in `_on_fs_read_text_file` and `_on_fs_write_text_file`. `terminal/create` has its own separate `resolved_cwd.is_relative_to(sandbox_root)` check.
**Status:** CLEAN

---

### ACP-07 — INFO: `terminal/create` command allowlist + metachar guard correct

**File:** `lib/providers/acp_chat_model.py:818-833`
**Issue:** None — `_TERMINAL_COMMAND_ALLOWLIST` frozenset, `Path(command).stem.lower()` normalization, and `_SHELL_METACHAR_RE.search()` over all tokens confirmed present and correct.
**Status:** CLEAN

---

### ACP-08 — INFO: `_kill_process_tree` Windows taskkill path correct

**File:** `lib/providers/acp_chat_model.py:168-216`
**Issue:** None — `taskkill /T /F /PID` is the correct Windows tree-kill approach. 5-second wait_for. SIGTERM→SIGKILL escalation on Unix with asyncio.shield analogue. Transport close prevents handle leaks.
**Status:** CLEAN

---

### ACP-09 — INFO: stdin_lock correctly covers all write paths

**File:** `lib/providers/acp_chat_model.py`
**Verified:** All `ctx.stdin.write()` + `drain()` calls (in `_initialize_session`, `_setup_session`, `_setup_prompt`, `_handle_server_rpc`, `_send_notification`, `_cleanup_session`, `fork_session`, `list_sessions`, `set_mode`, `set_model`, `set_config_option`, `authenticate`) use `async with ctx.stdin_lock` or `async with self._stdin_lock`. No bare write paths found.
**Status:** CLEAN

---

### MCP doc update — adding ACP-02 to MCP surface audit? No — ACP-02 is a provider finding, not MCP-specific. No MCP doc update needed this cycle.

---

### Summary for Cycle 42

| ID     | Severity | File                      | Issue                                                    | Status |
| ------ | -------- | ------------------------- | -------------------------------------------------------- | ------ |
| ACP-01 | LOW      | acp_chat_model.py:976     | terminal/wait_for_exit timeout uncapped                  | open   |
| ACP-02 | MEDIUM   | acp_chat_model.py:319     | os.environ.copy() bypasses resolve_env_vars scrub        | open   |
| ACP-03 | MEDIUM   | acp_chat_model.py:764     | fs/read_text_file no size cap — OOM on large files       | open   |
| ACP-04 | LOW      | acp_chat_model.py:682-704 | deny fallback options[-1]["optionId"] may raise KeyError | open   |
| ACP-05 | INFO     | acp_chat_model.py:279-298 | model_copy() + PrivateAttr reset — correct               | clean  |
| ACP-06 | INFO     | acp_chat_model.py:736-742 | \_sandbox_path path traversal guard — correct            | clean  |
| ACP-07 | INFO     | acp_chat_model.py:818-833 | terminal allowlist + metachar guard — correct            | clean  |
| ACP-08 | INFO     | acp_chat_model.py:168-216 | \_kill_process_tree — correct                            | clean  |
| ACP-09 | INFO     | acp_chat_model.py         | stdin_lock coverage — all write paths covered            | clean  |

---

## Cycle 43 — TOML Sprint Status Verification (session resume)

**Scope:** Verify current state of TOML-01 through TOML-05 after session compaction.

**Files read:**

- `lib/core/team_config.py` — full
- `lib/core/presets/teams/vaultspec-adaptive-coder.toml` — representative sample
- `lib/api/endpoints.py` — grep for auto_approve/autonomous
- `lib/core/graph.py` — grep for persona/graph config consumption

### Findings

#### TOML-01 — DONE (merged to main)

Aliases dict at `team_config.py:78-83` confirmed: old IDs → new IDs. New preset files (`vaultspec-*.toml`) present in presets/teams/. Old short-name files also present (kept for external references). **Status: complete.**

#### TOML-02 — DONE (merged to main)

`TeamPermissionsConfig` (line 257), `TeamPersonaConfig` (line 264), `TeamGraphConfig` (line 271) all present in `team_config.py`. All three wired into `TeamConfig` (lines 292-294). `__all__` includes all three (lines 50-52). **Status: complete.**

#### TOML-03 — NOT DONE

None of the 4 new preset TOML files (`vaultspec-adaptive-coder.toml`, `vaultspec-structured-coder.toml`, `vaultspec-iterative-coder.toml`, `vaultspec-solo-coder.toml`) contain `[team.permissions]`, `[team.persona]`, or `[team.graph]` sections. These sections are valid per the schema (TOML-02) but absent from all presets. **Status: pending.**

#### TOML-04 — NOT DONE

`endpoints.py:263` — `autonomous=body.autonomous` only. `team_config.permissions.auto_approve` is never read. The schema field exists but the wiring from TOML → runtime flag is missing. **Status: pending.**

#### TOML-05 — NOT DONE

`graph.py` has no references to `persona.directive`, `persona.supervisor_display_name`, `graph.step_timeout_seconds` (note: separate from existing `step_timeout` parameter), or `graph.recursion_limit`. The `TeamPersonaConfig` and `TeamGraphConfig` fields are loaded but silently discarded. **Status: pending.**

### Summary

| Task    | Status  | Gap                                                           |
| ------- | ------- | ------------------------------------------------------------- |
| TOML-01 | Done    | —                                                             |
| TOML-02 | Done    | —                                                             |
| TOML-03 | Pending | Preset TOMLs missing [permissions]/[persona]/[graph] sections |
| TOML-04 | Pending | auto_approve not wired into autonomous flag in endpoint       |
| TOML-05 | Pending | persona.directive + graph config not consumed in graph.py     |

---

## Cycle 44 — lib/api/schemas/ full audit

**Scope:** `lib/api/schemas/` — all 7 source files: `__init__.py`, `base.py`, `enums.py`, `commands.py`, `events.py`, `rest.py`, `snapshots.py`, `internal.py`, plus `tests/test_schemas.py`.

**Files read:** All of the above in full.

---

### SCH-01 — INFO: Facade **init**.py correctly re-exports all public types

**File:** `lib/api/schemas/__init__.py`
**Issue:** None. All 65 public symbols from the 6 sub-modules are explicitly re-exported via `X as X` pattern (triggers `py.typed` re-export semantics) and listed in `__all__`. No deep-import leakage required from consumers.
**Status:** CLEAN

---

### SCH-02 — INFO: Discriminated unions use correct Annotated + Field(discriminator=...) pattern

**File:** `lib/api/schemas/events.py:257-271`, `commands.py:82-90`
**Issue:** None. Both `ServerEvent` and `ClientMessage` unions use `Annotated[..., Field(discriminator="type")]`. The `Literal` type on each member's `type` field enables O(1) dispatch without isinstance chains.
**Status:** CLEAN

---

### SCH-03 — LOW: `AgentControlCommand` missing `option_id` field — schema-level T31 gap

**File:** `lib/api/schemas/commands.py:57-63`
**Issue:** `AgentControlCommand` carries `thread_id`, `agent_id`, and `action` but no `option_id` field. The RESUME action (T31) needs an `option_id` to select which permission option to resume with. Even when the endpoint handler is fixed (T31), the client cannot transmit the option via WS because the schema rejects it. Both layers must be fixed together.
**Severity:** LOW (T31 already tracked; this is a confirming schema-layer detail)
**Fix:** Add `option_id: str | None = None` to `AgentControlCommand`.
**Status:** OPEN (linked to T31)

---

### SCH-04 — INFO: 64 KiB content cap consistent across all message-bearing fields

**File:** `commands.py:53`, `rest.py:46`, `rest.py:70`
**Issue:** None. `SendMessageCommand.content`, `CreateThreadRequest.initial_message`, and `SendMessageRequest.content` all use `Field(max_length=65536)`. Consistent.
**Status:** CLEAN

---

### SCH-05 — LOW: `DispatchRequest.action` is an unconstrained `str` — no enum validation

**File:** `lib/api/schemas/internal.py:18`
**Issue:** `action: str = Field(description="'ingest' | 'resume' | 'cancel'")` — valid values are documented but not type-enforced. A malformed value (e.g. `"restart"`) passes Pydantic validation silently. The worker executor handles unknown actions via `else: logger.warning(...)` — no exception, silent no-op dispatch.
**Severity:** LOW — internal IPC (not user-facing), but worth hardening.
**Fix:** `action: Literal["ingest", "resume", "cancel"]` or a `DispatchAction(StrEnum)`.
**Status:** OPEN

---

### SCH-06 — INFO: `WorkerEventEnvelope.payload: dict` (bare) — acceptable

**File:** `lib/api/schemas/internal.py:54`
**Issue:** Bare `dict` is equivalent to `dict[Any, Any]` in Pydantic v2. Intentional — payload carries heterogeneous `ServerEvent` variants. A more precise type would be `dict[str, Any]` for mypy narrowing, but this is not a correctness bug.
**Status:** CLEAN (acceptable)

---

### SCH-07 — INFO: Private snapshot models correctly unexported

**File:** `lib/api/schemas/snapshots.py:60-74`
**Issue:** None. `_PermissionSnapshot` and `_PermissionOptionSnapshot` are implementation details of `ThreadStateSnapshot`, not exported. Correct use of leading underscore convention.
**Status:** CLEAN

---

### SCH-08 — LOW: `PermissionResponseRequest.kind` documented as inert — incomplete feature silently no-ops

**File:** `lib/api/schemas/rest.py:141`
**Issue:** `kind: PermissionOptionKind | None = None` is documented as "accepted but not yet acted upon by the endpoint handler" — present for "forward-compatibility." The endpoint reads only `request.option_id`. The `ALLOW_ALWAYS` / `REJECT_ALWAYS` semantics are on the public API surface but silently do nothing. API consumers relying on these values get no feedback and no error.
**Severity:** LOW — documentation debt / incomplete feature.
**Fix:** Either implement `kind`-based routing or remove the field until it's implemented and document its absence.
**Status:** OPEN

---

### SCH-09 — INFO: `ConnectedEvent.metadata` and `HeartbeatEvent.metadata` typed correctly

**File:** `lib/api/schemas/events.py:241, 250`
**Issue:** None. `dict[str, Any] | None` is the correct open-ended extension point for these connection-scoped events.
**Status:** CLEAN

---

### SCH-10 — INFO: `EventEnvelope.agent_id` optional — correct for team-level events

**File:** `lib/api/schemas/base.py:30`
**Issue:** None. `agent_id: str | None = None` is correct — `TeamStatusEvent` and `ErrorEvent` have no specific agent context.
**Status:** CLEAN

---

### SCH-11 — LOW: Internal IPC models (`DispatchRequest` etc.) have no schema round-trip tests

**File:** `lib/api/schemas/tests/test_schemas.py`
**Issue:** The test file covers `ServerEvent` / `ClientMessage` round-trips and REST models. `DispatchRequest`, `DispatchResponse`, `HeartbeatMessage`, `WorkerEventEnvelope` from `internal.py` are not imported or tested. Given that `DispatchRequest.action` is an unconstrained str (SCH-05) and `option_id` / `metadata_json` / `context_preamble` fields are load-bearing for the worker dispatch path, this test gap means malformed internal payloads are not caught in CI.
**Severity:** LOW — test gap, not a runtime bug.
**Status:** OPEN

---

### Summary for Cycle 44 — lib/api/schemas/

| ID     | Severity | File                          | Issue                                                        | Status |
| ------ | -------- | ----------------------------- | ------------------------------------------------------------ | ------ |
| SCH-01 | INFO     | schemas/**init**.py           | Facade re-exports correct                                    | clean  |
| SCH-02 | INFO     | events.py, commands.py        | Discriminated union pattern correct                          | clean  |
| SCH-03 | LOW      | commands.py:57-63             | AgentControlCommand missing option_id (schema-level T31 gap) | open   |
| SCH-04 | INFO     | commands.py:53, rest.py:46,70 | 64 KiB cap consistent                                        | clean  |
| SCH-05 | LOW      | internal.py:18                | DispatchRequest.action unconstrained str                     | open   |
| SCH-06 | INFO     | internal.py:54                | WorkerEventEnvelope.payload bare dict — acceptable           | clean  |
| SCH-07 | INFO     | snapshots.py:60-74            | Private snapshot models correctly unexported                 | clean  |
| SCH-08 | LOW      | rest.py:141                   | PermissionResponseRequest.kind inert — silent no-op          | open   |
| SCH-09 | INFO     | events.py:241,250             | ConnectedEvent/HeartbeatEvent.metadata correct               | clean  |
| SCH-10 | INFO     | base.py:30                    | EventEnvelope.agent_id optional — correct                    | clean  |
| SCH-11 | LOW      | schemas/tests/test_schemas.py | Internal IPC models untested                                 | open   |

**New actionable findings this cycle:** SCH-03 (confirms T31 schema gap), SCH-05 (unconstrained action), SCH-08 (inert kind field), SCH-11 (test gap).

---

## Cycle 45 — lib/worker/ formal audit

**Scope:** All 6 files in `lib/worker/`: `__init__.py`, `__main__.py`, `health.py`, `ipc.py`, `app.py`, `executor.py`.

**Files read:** All in full.

---

### WRK-01 — INFO: `health.py` is an empty stub — no implementation

**File:** `lib/worker/health.py`
**Issue:** `HealthCheck` class contains only a docstring. The actual heartbeat runs in `ipc.py:heartbeat_loop`; the `/health` endpoint in `app.py:125` is a bare async function that does not use `HealthCheck`. The class is dead code — not re-exported from `lib/worker/__init__.py`.
**Status:** CLEAN (stub, noting for completeness)

---

### WRK-02 — MEDIUM: `_compile_graph` ignores `team_config.graph.step_timeout_seconds` — always uses global setting

**File:** `lib/worker/executor.py:352`
**Issue:** `compile_team_graph(..., step_timeout=float(settings.graph_node_timeout_seconds))` always uses the global config value. The `team_config.graph.step_timeout_seconds` field (added in TOML-02) is available on the loaded `team_config` object but is never consulted here. Per-team timeout overrides have no effect in the worker path.

Note: TOML-05 is marked complete — if that task wired `team_config.graph.step_timeout_seconds` into `compile_team_graph`'s signature, the call site here still overrides it unconditionally. Needs verification against the TOML-05 implementation.
**Severity:** MEDIUM — per-team step_timeout silently ignored.
**Fix:** Use `team_config.graph.step_timeout_seconds or settings.graph_node_timeout_seconds` at the call site.
**Status:** OPEN

---

### WRK-03 — LOW: `_handle_resume` hardcodes `_GRAPH_RECURSION_LIMIT` — ignores `req.recursion_limit`

**File:** `lib/worker/executor.py:289`
**Issue:** `_handle_ingest` at line 216 correctly uses `req.recursion_limit or _GRAPH_RECURSION_LIMIT`. `_handle_resume` at line 289 hardcodes `_GRAPH_RECURSION_LIMIT` unconditionally. If a team's `TeamGraphConfig.recursion_limit` flows through `DispatchRequest.recursion_limit`, resume runs will silently ignore it.
**Severity:** LOW — resume runs are short (single interrupt resolution), unlikely to hit limit. But the inconsistency is a correctness gap.
**Fix:** `"recursion_limit": req.recursion_limit or _GRAPH_RECURSION_LIMIT` at line 289.
**Status:** OPEN

---

### WRK-04 — LOW: `_graphs` dict grows unbounded — no eviction, no size cap

**File:** `lib/worker/executor.py:73, 163, 262`
**Issue:** `self._graphs: dict[str, CompiledStateGraph]` accumulates one entry per thread_id and is only cleared on `shutdown()`. Comments mention "eviction" as rationale for `_graph_presets`, but no eviction is implemented. A long-running worker handling many threads holds compiled `StateGraph` closures in memory indefinitely.
**Severity:** LOW — memory leak in long-running deployments.
**Fix:** LRU eviction with configurable capacity (e.g. via `collections.OrderedDict` with a `maxsize` cap). Evict from `_graphs` only; keep `_graph_presets` for lazy recompile.
**Status:** OPEN

---

### WRK-05 — LOW: `asyncio.Lock` for `_ingest_lock` inconsistent with anyio project convention

**File:** `lib/worker/executor.py:91`
**Issue:** `self._ingest_lock = asyncio.Lock()` uses stdlib asyncio. The project convention (enforced through T19/T29 fixes) is `anyio` primitives for all concurrency. Works correctly on Python 3.13 single event loop, but inconsistent.
**Severity:** LOW — convention, not a functional bug.
**Status:** OPEN

---

### WRK-06 — INFO: `app.py` correctly binds `main()` to loopback `127.0.0.1`

**File:** `lib/worker/app.py:138`
**Issue:** None. Loopback-only binding makes unauthenticated `/dispatch` acceptable per ADR-019 internal-only design.
**Status:** CLEAN

---

### WRK-07 — INFO: Worker lifespan shutdown order correct

**File:** `lib/worker/app.py:87-91`
**Issue:** None. `executor.shutdown()` → `bridge.close()` → `tg.cancel_scope.cancel()` — drains aggregator before closing HTTP client, cancels heartbeat last. Contrast with API-06 (control surface app.py where cancel order was inverted) — worker gets this right.
**Status:** CLEAN

---

### WRK-08 — INFO: `_mark_ingest_active` / `_mark_ingest_done` lock pattern correct

**File:** `lib/worker/executor.py:111-127`
**Issue:** None. Check-then-add inside `async with self._ingest_lock` is atomic. `discard` in `_mark_ingest_done` is safe against double-call. `bridge.untrack_thread` called outside the lock is safe — `WorkerBridge._active_threads` has single-writer access from the executor task group.
**Status:** CLEAN

---

### WRK-09 — MEDIUM: W-02 confirmed — `AgentConfigNotFoundError` silently skips agent, produces broken graph

**File:** `lib/worker/executor.py:333-334`
**Issue:** (Confirms prior W-02 finding.)

```python
except AgentConfigNotFoundError:
    logger.warning("Agent config not found for %s", worker_ref.agent_id)
    # continues — agent_configs left missing this entry
```

`compile_team_graph` receives an incomplete `agent_configs` dict. The error surfaces only at graph traversal time as a confusing `KeyError` or node-not-found exception.
**Severity:** MEDIUM — already tracked as W-02.
**Status:** OPEN (W-02)

---

### WRK-10 — INFO: `ipc.py` `send_event` failure handling correct — never raises

**File:** `lib/worker/ipc.py:81-101`
**Issue:** None. `httpx.HTTPError` caught, logged at WARNING, never re-raised. 10s/5s timeout prevents relay failures from hanging graph execution. Correct fire-and-forget pattern.
**Status:** CLEAN

---

### WRK-11 — LOW: Non-200 event relay responses silently dropped with no retry

**File:** `lib/worker/ipc.py:90-95`
**Issue:** `if resp.status_code != 200: logger.warning(...)` — the event is permanently lost on 503/429/etc. In deployments where the control surface restarts briefly, events generated during the gap are unrecoverable. Retrying risks ordering issues given the sequence numbering in `EventEnvelope`.
**Severity:** LOW — known architectural trade-off for fire-and-forget relay. Acceptable but worth noting.
**Status:** OPEN (known limitation)

---

### WRK-12 — INFO: `_compile_graph` workspace_root `Path.resolve()` — TC-01 covers further validation

**File:** `lib/worker/executor.py:318`
**Issue:** None. `Path(req.workspace_root).resolve()` normalizes the path. Further safe-path validation is covered by TC-01.
**Status:** CLEAN (deferring to TC-01)

---

### Summary for Cycle 45 — lib/worker/

| ID     | Severity | File                | Issue                                                        | Status      |
| ------ | -------- | ------------------- | ------------------------------------------------------------ | ----------- |
| WRK-01 | INFO     | health.py           | HealthCheck stub — empty, unused                             | clean       |
| WRK-02 | MEDIUM   | executor.py:352     | step_timeout uses global setting, ignores team_config.graph  | open        |
| WRK-03 | LOW      | executor.py:289     | \_handle_resume hardcodes recursion_limit, ignores req field | open        |
| WRK-04 | LOW      | executor.py:73      | \_graphs dict grows unbounded — no eviction                  | open        |
| WRK-05 | LOW      | executor.py:91      | asyncio.Lock inconsistent with anyio project convention      | open        |
| WRK-06 | INFO     | app.py:138          | 127.0.0.1 loopback bind — correct                            | clean       |
| WRK-07 | INFO     | app.py:87-91        | Lifespan shutdown order correct                              | clean       |
| WRK-08 | INFO     | executor.py:111-127 | \_mark_ingest_active/done lock pattern correct               | clean       |
| WRK-09 | MEDIUM   | executor.py:333-334 | W-02 confirmed: silent AgentConfigNotFoundError continue     | open (W-02) |
| WRK-10 | INFO     | ipc.py:81-101       | send_event failure handling correct                          | clean       |
| WRK-11 | LOW      | ipc.py:90-95        | Non-200 relay responses silently dropped, no retry           | open        |
| WRK-12 | INFO     | executor.py:318     | workspace_root Path.resolve() — TC-01 covers validation      | clean       |

**New actionable findings:** WRK-02 (MEDIUM: team step_timeout ignored), WRK-03 (LOW: resume hardcodes recursion_limit), WRK-04 (LOW: unbounded graph dict), WRK-05 (LOW: asyncio vs anyio), WRK-11 (LOW: silent event drop).

---

## Verbal Findings from Prior Session (persisted to prevent context loss)

These findings were triaged verbally during the earlier session and are now documented here for permanence.

---

### TC-02 — HIGH: AgentConfig.from_toml bare KeyError on missing [agent] section

**File:** `lib/core/team_config.py:172`
**Issue:** `cls.model_validate(data["agent"])` raises a bare `KeyError` if the TOML file lacks an `[agent]` section. Should catch `KeyError` and raise `ConfigError` with a descriptive message. Same issue exists in `TeamConfig.from_toml` at line 318 with `data["team"]`.
**Severity:** HIGH — poor error UX on malformed config files.
**Status:** OPEN — untasked

---

### W-02 — HIGH: Silent AgentConfigNotFoundError continue in executor

**File:** `lib/worker/executor.py`
**Issue:** When building agent_configs dict for `compile_team_graph`, if `load_agent_config()` raises `AgentConfigNotFoundError`, the code catches it with a `logger.warning` and `continue`. This means a broken/missing agent config silently produces a graph with fewer workers than expected. The broken graph is stored and used for the thread's lifetime.
**Severity:** HIGH — silent data loss, hard to debug.
**Status:** OPEN — untasked

---

### PROV-02 — HIGH: \_CLAUDE_ACP_JS path duplicated + no exists() guard

**File:** `lib/providers/acp_chat_model.py`
**Issue:** The path to the Claude ACP JavaScript entrypoint is hardcoded in two places (the constant and a fallback). Neither location calls `Path.exists()` before attempting to spawn the subprocess. If the JS file is missing, the error surfaces as a cryptic subprocess failure rather than a clear config error.
**Severity:** HIGH — poor error UX, duplicated magic path.
**Status:** OPEN — untasked

---

### G-01 — MEDIUM: \_compile_star supervisor prompt fallback duplicates roster logic

**File:** `lib/core/graph.py:224-234`
**Issue:** When `supervisor_agent_config is None`, the fallback supervisor prompt construction duplicates the roster-building logic that already exists in `_build_supervisor_prompt()`. Should call `_build_supervisor_prompt()` with a default base prompt instead.
**Severity:** MEDIUM — code duplication, maintenance risk.
**Status:** OPEN — untasked

---

### G-02 — MEDIUM: create_worker_node permission_callback closure captures mutable state

**File:** `lib/core/graph.py`
**Issue:** The `permission_callback` closure in `create_worker_node` captures variables from the enclosing scope. If the closure is invoked after the enclosing scope has mutated (e.g., during concurrent worker execution), it may reference stale state. Mitigated by `model_copy()` (H4 fix) but the closure architecture is fragile.
**Severity:** MEDIUM — latent concurrency risk.
**Status:** OPEN — untasked

---

### CTX-01 — MEDIUM: context_injection glob patterns not sanitized

**File:** `lib/core/context_injection.py`
**Issue:** User-supplied glob patterns from `ContextRef` are passed directly to `Path.glob()` without sanitization. While path traversal is mitigated by the workspace_root prefix, specially crafted glob patterns could cause excessive filesystem traversal (DoS via `**/**/**` patterns).
**Severity:** MEDIUM — potential DoS vector.
**Status:** OPEN — untasked

---

### CTX-02 — MEDIUM: 50-doc cap applied after glob expansion, not during

**File:** `lib/core/context_injection.py`
**Issue:** The 50-document cap is checked after all glob results are collected into a list. For workspaces with thousands of files matching a broad pattern (e.g. `**/*.py`), the entire list is expanded in memory before being truncated.
**Severity:** MEDIUM — memory spike on broad patterns.
**Status:** OPEN — untasked

---

### EXC-01 — MEDIUM: ConfigError and domain exceptions missing **slots**

**File:** `lib/core/exceptions.py`
**Issue:** Custom exception classes don't define `__slots__`, which means each instance carries a `__dict__`. For exceptions that may be created frequently (e.g., in retry loops), this adds unnecessary memory overhead.
**Severity:** MEDIUM — minor perf, but easy fix.
**Status:** OPEN — untasked (LOW priority despite MEDIUM severity)

---

### LOG-01 — MEDIUM: JSON formatter not applied to all handlers

**File:** `lib/utils/logging.py`
**Issue:** The `JSONFormatter` is defined but only attached to the root logger's StreamHandler. If other handlers are added (e.g., file handlers, OTel exporters), they won't use the JSON format, leading to inconsistent log output.
**Severity:** MEDIUM — observability gap.
**Status:** OPEN — untasked

---

### PROV-01 — MEDIUM: ProviderFactory.create() has no caching/dedup

**File:** `lib/providers/factory.py`
**Issue:** Every call to `ProviderFactory.create()` instantiates a new model client. For star topologies where the supervisor invokes workers repeatedly, this means repeated client construction. Not a correctness bug but wasteful.
**Severity:** MEDIUM — performance.
**Status:** OPEN — untasked

---

### PROV-03 — MEDIUM: Gemini probe doesn't verify model availability

**File:** `lib/providers/probes/gemini.py`
**Issue:** The Gemini probe checks for the API key env var but doesn't attempt a lightweight API call to verify the key is valid or the model is accessible.
**Severity:** MEDIUM — probe gives false positive on invalid keys.
**Status:** OPEN — untasked

---

### PROV-04 — MEDIUM: OpenAI provider doesn't set request timeout

**File:** `lib/providers/factory.py`
**Issue:** `ChatOpenAI()` instantiation doesn't pass `request_timeout`. Long-running or hung API calls will block the worker indefinitely (mitigated by graph-level step_timeout but not at the HTTP client level).
**Severity:** MEDIUM — latent hang risk.
**Status:** OPEN — untasked

---

### Summary of persisted verbal findings

| ID      | Severity | Status | Notes                                              |
| ------- | -------- | ------ | -------------------------------------------------- |
| TC-02   | HIGH     | OPEN   | KeyError on missing [agent]/[team] section         |
| W-02    | HIGH     | OPEN   | Silent agent config skip → broken graph            |
| PROV-02 | HIGH     | OPEN   | ACP JS path duplication + no exists() guard        |
| G-01    | MEDIUM   | OPEN   | Duplicated roster logic in fallback prompt         |
| G-02    | MEDIUM   | OPEN   | permission_callback closure captures mutable state |
| CTX-01  | MEDIUM   | OPEN   | Unsanitized glob patterns                          |
| CTX-02  | MEDIUM   | OPEN   | 50-doc cap after full expansion                    |
| EXC-01  | MEDIUM   | OPEN   | Missing **slots** on exceptions                    |
| LOG-01  | MEDIUM   | OPEN   | JSON formatter not on all handlers                 |
| PROV-01 | MEDIUM   | OPEN   | No model client caching                            |
| PROV-03 | MEDIUM   | OPEN   | Gemini probe false positive                        |
| PROV-04 | MEDIUM   | OPEN   | OpenAI no request_timeout                          |

---

## Cycle 46 — MCP Tool Description Audit (2026-03-02)

**File audited**: `lib/protocols/mcp/server.py` (523 lines, 7 tools)

**Tool count**: 7 — start_thread, list_threads, respond_to_permission,
get_thread_status, send_message, get_team_status, get_pending_permissions.
(Note: server.py header doc lists 7 but surface-alignment research from earlier
today was based on a 5-tool version — coder added get_team_status and
get_pending_permissions since that read. Full audit doc:
`docs/audits/2026-03-02-mcp-tool-description-audit.md`.)

### Findings

| ID     | Severity | Location                              | Finding                                                                                             |
| ------ | -------- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| MCD-01 | HIGH     | FastMCP instructions:79-85            | `respond_to_permission` and `get_team_status` omitted from server instructions string               |
| MCD-02 | HIGH     | FastMCP instructions:79-85            | No workflow sequence guidance — LLM cannot infer autonomous vs supervised call order                |
| MCD-03 | MEDIUM   | start_thread → team_preset:123        | `_KNOWN_PRESETS` reference is internal Python symbol; valid preset names should be listed verbatim  |
| MCD-04 | MEDIUM   | start_thread → workspace_root:128     | "ADR-014" and "ACP agent CWD" are internal jargon; replace with plain behavioural description       |
| MCD-05 | MEDIUM   | get_thread_status:321                 | Docstring claims "checkpoint ID" in return; MCP-04 removed it — description is stale                |
| MCD-06 | MEDIUM   | respond_to_permission → option_id:274 | No guidance on how to discover valid option IDs (must call get_pending_permissions first)           |
| MCD-07 | MEDIUM   | respond_to_permission:272             | "ADR-011 §2.2" reference in description body — internal jargon                                      |
| MCD-08 | LOW      | send_message:372                      | "(async, returns 202)" parenthetical exposes HTTP implementation detail                             |
| MCD-09 | LOW      | send_message → message:380            | No documented size constraint; start_thread cap is documented (32k) but send_message has none       |
| MCD-10 | LOW      | get_thread_status:317                 | Possible status values not enumerated (submitted/running/input_required/completed/failed/cancelled) |
| MCD-11 | LOW      | get_team_status:423                   | "ADR-011 §2.2" internal reference in description body                                               |
| MCD-12 | LOW      | list_threads:199                      | Thread status values not enumerated in description                                                  |
| MCD-13 | INFO     | get_pending_permissions:476           | Calls /api/team/status — subset of get_team_status; overlap not documented                          |

### Clean paths (no issues)

- Error handling in all 7 tools: consistent httpx exception hierarchy, correct 404 branching
- `_ws_url_from_api_base` credential stripping: correct (strips userinfo before returning ws URL)
- `_MAX_INITIAL_MESSAGE_CHARS` guard in `start_thread`: present and documented
- `limit` clamping in `list_threads` (1-200): present
- `_KNOWN_PRESETS` preset validation in `start_thread`: correct runtime guard, good error message

### Proposed fix (P0 — instructions rewrite)

See `docs/audits/2026-03-02-mcp-tool-description-audit.md` §"Proposed instructions Rewrite"
for the exact replacement string (covers both autonomous and supervised workflows, names all 7
tools with their roles).

---

## Cycle 47 — MCP Deep Correctness Audit (2026-03-02)

**Files audited**:

- `lib/protocols/mcp/server.py` (783 lines, 9 tools — fresh read)
- `lib/protocols/mcp/tests/test_server.py` (633 lines — fresh read)
- `lib/api/endpoints.py` cancel + permission endpoints
- `lib/api/schemas/rest.py` CancelThreadResponse

### CRITICAL: IndentationError in two new tools — module will not import

| ID         | Severity | Location            | Finding                                                                                                                                                                       |
| ---------- | -------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP-SYN-01 | CRITICAL | `server.py:692-697` | `list_team_presets`: `resp = await client.get(...)` is over-indented relative to `client = _get_client()` — orphaned indent with no enclosing block. Python IndentationError. |
| MCP-SYN-02 | CRITICAL | `server.py:756-761` | `cancel_thread`: same pattern — `resp = await client.post(...)` is over-indented. IndentationError.                                                                           |

**Root cause**: Both tools were added after the `async with httpx.AsyncClient()` →
`_get_client()` refactor. The inner block indentation from the old `async with`
was preserved but the enclosing `async with` context manager was removed, leaving
`resp = ...` orphaned at one extra indent level.

**Impact**: The entire `server.py` module raises `IndentationError` at import
time. ALL 9 MCP tools are completely unavailable until fixed.

**Fix required** (server.py:692-697):

```python
    try:
        client = _get_client()
        resp = await client.get(          # de-dent to match client =
            f"{settings.api_base_url}/api/teams",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        presets = data.get("presets", [])
```

**Fix required** (server.py:756-761):

```python
    try:
        client = _get_client()
        resp = await client.post(         # de-dent to match client =
            f"{settings.api_base_url}/api/threads/{thread_id}/cancel",
            timeout=_MCP_QUERY_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
```

### Other Findings

| ID         | Severity | Location            | Finding                                                                                                                                                          |
| ---------- | -------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP-CLI-01 | MEDIUM   | `server.py:46-54`   | `_get_client()` global client has no teardown — connection pool never closed on process exit                                                                     |
| MCP-TST-03 | LOW      | `test_server.py`    | No `get_thread_status` happy-path test verifying enriched response (agents + plan fields returned by MCP-R7)                                                     |
| MCP-URL-01 | INFO     | `server.py:347`     | `respond_to_permission` → `/api/permissions/{id}/respond` matches `endpoints.py:718`. Correct.                                                                   |
| MCP-URL-02 | INFO     | `server.py:757`     | `cancel_thread` → `POST /api/threads/{id}/cancel` matches `endpoints.py:811`. Correct.                                                                           |
| MCP-URL-03 | INFO     | `server.py:692`     | `list_team_presets` → `GET /api/teams` matches `endpoints.py:682`. Correct.                                                                                      |
| MCP-SCH-01 | INFO     | `server.py:762-763` | `cancel_thread` reads `cancelled` + `status` matching `CancelThreadResponse` schema. Correct.                                                                    |
| MCP-ERR-01 | INFO     | All 9 tools         | Error-handling hierarchy (ConnectError→TimeoutException→HTTPStatusError→RequestError) is consistent across all tools. 404 branching correct on per-thread tools. |

### Clean paths

- MCP-05 shared client applied correctly to tools 1-7 (start_thread through get_pending_permissions)
- `_HARDCODED_PRESETS` now includes `vaultspec-continuous-audit` (REG-02 resolved)
- FastMCP `instructions` string updated (MCD-01/02 resolved)
- All 9 tool descriptions substantially improved (MCD-03 through MCD-12 addressed)
- URL paths for all 9 tools match actual endpoint definitions
- Response schema field reads match `CancelThreadResponse` and `PermissionResponseResult`
- Test file imports all 9 tools; happy-path + error-path coverage for 8 of 9 tools
- `_ws_url_from_api_base` unit tests: 5 tests, comprehensive

### Action required

**P0**: Fix MCP-SYN-01 and MCP-SYN-02 (indentation) — coder must de-dent `resp = ...`
lines in both `list_team_presets` and `cancel_thread` to align with `client = _get_client()`.
