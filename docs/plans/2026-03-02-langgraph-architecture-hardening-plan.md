# LangGraph Architecture Hardening Plan — 2026-03-02

## Objective

Systematically harden the LangGraph orchestration layer against the gaps
identified in the 2026-03-02 audit, while running continuous discovery loops
to surface additional issues as implementation progresses.

Source audit: `docs/audits/2026-03-02-langgraph-architecture-audit.md`

---

## Execution Model

This plan is executed by a team of four agents:

- **orchestrator** (Opus) — owns this plan, assigns tasks, reviews diffs,
  promotes findings to tasks, synthesises cross-cutting decisions
- **docs-researcher** (Sonnet) — continuous loop: query LangGraph source +
  MCP docs → report new gaps to orchestrator
- **codebase-researcher** (Sonnet) — continuous loop: audit implementation
  files after each coder commit → report regressions or newly visible gaps
- **coder** (Sonnet) — implements tasks assigned by orchestrator, runs tests,
  marks tasks complete

Research agents run in perpetual loop until orchestrator signals shutdown.
New findings are promoted to tasks by the orchestrator before being handed
to the coder.

---

## Scope — Files Under Change

```
src/vaultspec_a2a/core/
  state.py                   # TeamState field changes
  graph.py                   # RetryPolicy, try/except, logging
  nodes/
    worker.py                # WorkerExecutionError, TAG_NOSTREAM
    supervisor.py            # compaction, structured output, TAG_NOSTREAM
  context.py                 # possible compaction fixes
  exceptions.py              # new domain exceptions
src/vaultspec_a2a/core/tests/
  test_graph.py              # new edge-case tests
  test_worker.py             # new (if absent)
  test_supervisor.py         # new (if absent)
```

---

## Known Tasks (from audit — starter set)

### BATCH 1 — Defensive correctness (XS/S, no API surface change)

**T01** — Fix `state["next"]` KeyError in star topology conditional edge

- File: `src/vaultspec_a2a/core/graph.py` (conditional edge lambda)
- Change: `lambda state: state["next"]` → `lambda state: state.get("next", "")`
- Also mark `next: NotRequired[str]` in `state.py`
- Test: add `test_star_missing_next_field` to `test_graph.py`

**T02** — Fix substring routing collision (sort options by descending length)

- File: `src/vaultspec_a2a/core/nodes/supervisor.py`
- Change: `for option in options` → `for option in sorted(options, key=len, reverse=True)`
- Test: add `test_supervisor_routing_substring_collision`

**T03** — Add `routing_error` field to `TeamState`

- File: `src/vaultspec_a2a/core/state.py`
- Change: add `routing_error: NotRequired[str]`
- File: `src/vaultspec_a2a/core/nodes/supervisor.py`
- Change: return `routing_error` on FINISH fallback
- Test: add `test_supervisor_sets_routing_error_on_parse_failure`

**T04** — Add `WorkerExecutionError` domain exception

- File: `src/vaultspec_a2a/core/exceptions.py` (add class)
- File: `src/vaultspec_a2a/core/nodes/worker.py` (wrap ainvoke catch)
- Test: add `test_worker_exception_wraps_with_context`

### BATCH 2 — Robustness additions (S, may touch API surface)

**T05** — Add `RetryPolicy` to all `add_node()` calls

- File: `src/vaultspec_a2a/core/graph.py`
- Change: define `_WORKER_RETRY = RetryPolicy(initial_interval=1.0, backoff_factor=2.0, max_interval=30.0, max_attempts=3, jitter=True)`
- Apply to all three topology builders' `add_node()` calls (workers + supervisor)
- Verify: `RetryPolicy` is in `langgraph.types`
- Test: verify node metadata preserved after adding retry param

**T06** — Add context compaction to supervisor node

- File: `src/vaultspec_a2a/core/nodes/supervisor.py`
- Change: import + apply `should_compact` / `compact_context` from `..context`
- Test: add `test_supervisor_compacts_on_large_state`

**T07** — Add `TAG_NOSTREAM` to supervisor routing model invocation

- File: `src/vaultspec_a2a/core/nodes/supervisor.py`
- Change: `routing_model = model.with_config({"tags": [TAG_NOSTREAM]})`; use for ainvoke
- Import: `from langgraph.constants import TAG_NOSTREAM`
- Test: streaming test to verify no routing tokens in `on_chat_model_stream` events

**T08** — Add loop iteration logging to `_wrap_loop_node`

- File: `src/vaultspec_a2a/core/graph.py`
- Change: pass `max_loops` and `loop_node_id` into wrapper factory; add DEBUG log per iteration, WARNING on max_loops hit

### BATCH 3 — Structured output for supervisor routing (M)

**T09** — Structured output for supervisor routing

- File: `src/vaultspec_a2a/core/nodes/supervisor.py`
- Change: replace text-parsing with `model.with_structured_output(RouteSchema)` where `RouteSchema` is a Pydantic model with `next: Literal[workers..., "FINISH"]`
- Dependency: T02 can be removed after this is in place
- Test: add `test_supervisor_structured_routing`
- Note: requires research into `with_structured_output` compatibility across AcpChatModel, ChatOpenAI, ChatGemini

### BATCH 4 — Command routing migration (L, future)

**T10** — Migrate supervisor to `Command(goto=...)` routing

- File: `src/vaultspec_a2a/core/graph.py`, `src/vaultspec_a2a/core/nodes/supervisor.py`, `src/vaultspec_a2a/core/state.py`
- Change: remove `next: str` from TeamState; supervisor returns `Command(goto=route)`
- Dependency: T09 complete
- Note: removes the conditional-edge routing table entirely; supervisor node
  becomes the sole authority over next-node dispatch

---

## Continuous Research Protocol

### docs-researcher loop

1. Pick one research topic from the queue (see below)
2. Query LangGraph source in `knowledge/repositories/langgraph/` or MCP docs
3. Map findings to the current codebase
4. Report any new gap to orchestrator with: file, line, issue, severity, fix direction
5. Repeat with next topic; signal orchestrator when queue exhausted (orchestrator
   will add new topics)

**Initial research queue:**

- `Send` API applicability — can any of our topologies benefit from parallel dispatch?
- `CachePolicy` — any deterministic nodes that could be cached?
- `step_timeout` — should we configure it on `Pregel` for production?
- `stream_mode="tasks"` — does it provide better observability than `astream_events`?
- Subgraph patterns — should coding-pipeline become a subgraph inside a star topology?
- `InMemorySaver` vs `AsyncSqliteSaver` threading guarantees — are test fixtures safe?
- `Overwrite` channel type — any field in `TeamState` that incorrectly accumulates?
- `with_structured_output` support matrix — which of our providers support it?
- `TAG_HIDDEN` vs `TAG_NOSTREAM` — are there other tags we should be using?
- `PregelTask.error` field — can we read node errors from `aget_state().tasks`?

### codebase-researcher loop

1. After each coder commit (or every N minutes), re-read the files under change
2. Check: do the new changes introduce any anti-patterns from the docs checklist?
3. Check: are there other files that reference the changed APIs and need updating?
4. Report regressions or newly visible gaps to orchestrator
5. Repeat

---

## Definition of Done

- All BATCH 1 + BATCH 2 tasks complete
- All tests passing (`pytest src/vaultspec_a2a/core/ -x -q`)
- No new CRITICAL or HIGH findings from research loops for two consecutive cycles
- Audit report updated with resolution status for each finding
- ADR-013 updated if `Command` migration (T10) is completed
