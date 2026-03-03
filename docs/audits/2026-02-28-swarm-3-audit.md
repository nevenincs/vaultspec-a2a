---
date: 2026-02-28
type: audit
feature: full-backend-swarm-3
description: 'Third-pass 6-agent deep audit producing ~124 findings (14 CRITICAL, 35 HIGH, 45 MEDIUM, 28 LOW) covering background task cancellation, chunk_queue deadlock, DB test isolation, and glob injection.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
  - docs/adrs/2026-02-28-014-thread-metadata-context-injection-adr.md
---

# Third-Pass Deep Audit — Swarm Report

**Date:** 2026-02-28
**Auditors:** 6 parallel Sonnet agents (core, api, providers, db-protocol,
utils-telemetry-workspace, test-quality)
**Scope:** Full `lib/`backend, MCP server, all ADRs (001–015), security,
implementation gaps, test quality
**Prior audits:**`2026-28-02-full-backend-audit.md`(101 findings, all
resolved),`2026-28-02-swarm-audit-2.md`

---

## Executive Summary

| Severity  | Count    |
| --------- | -------- |
| CRITICAL  | 14       |
| HIGH      | 35       |
| MEDIUM    | 45       |
| LOW       | 28       |
| **Total** | **~124** |

### By Module

| Agent                | Module(s)                                        | C   | H   | M   | L   | Total |
| -------------------- | ------------------------------------------------ | --- | --- | --- | --- | ----- |
| core-auditor         | `lib/core/`                                      | 3   | 6   | 9   | 6   | 24    |
| api-auditor          | `lib/api/`                                       | 2   | 5   | 8   | 4   | 19    |
| providers-auditor    | `lib/providers/`                                 | 2   | 5   | 6   | 4   | 17    |
| db-protocol-auditor  | `lib/database/`, `lib/protocols/`                | 2   | 5   | 5   | 4   | 18    |
| utils-auditor        | `lib/utils/`, `lib/telemetry/`, `lib/workspace/` | 3   | 7   | 6   | 4   | 20    |
| test-quality-auditor | Cross-cutting test quality                       | 2   | 7   | 11  | 6   | 26    |

---

## 1.`lib/core/`— Core Module Audit

### CRITICAL

### CORE-C1: Pipeline loop worker early-exit is dead code

- File:`lib/core/graph.py` (`_loop_router`)
- The `_loop_router`checks for`state.get("next") == "FINISH"`to exit the
  pipeline loop, but`worker_node`never sets`"next"`in its return dict. The
  early-exit branch is unreachable dead code — the only way to exit the loop is
  via`loop_count >= max_loops`.

### CORE-C2: Unguarded `KeyError`in`_compile_pipeline`

- File: `lib/core/graph.py`, lines ~303, ~390
- `agent_configs[agent_id]`bare dict lookup with no error context. A typo in a
  TOML config file produces an opaque`KeyError`instead of a
  descriptive`ConfigurationError`.

### CORE-C3: `feature_tag`glob pattern injection

- File:`lib/core/metadata.py`, lines ~105–117
- `feature_tag`is injected into glob patterns without sanitization.
  A`feature_tag`containing`*`, `?`, `[`, or `..`could traverse or match
  unintended paths during`.vault/`auto-discovery.

### HIGH

### CORE-H1:`worker_node`missing explicit`__name__`assignment

- File:`lib/core/nodes/worker.py`
- `_loop_node_with_counter`wrapper overwrites the function name, breaking
  LangGraph node identification.

### CORE-H2:`put_nowait`at line ~425 unguarded against`asyncio.QueueFull`

- File: `lib/core/aggregator.py`
- If the event queue is full, `put_nowait`raises`QueueFull`which propagates
  uncaught, crashing the aggregator loop.

### CORE-H3: Degenerate single-node`pipeline_loop`compiles as infinite self-loop

- File:`lib/core/graph.py`
- A pipeline_loop with one agent produces a graph where the single node loops to
  itself indefinitely (up to `max_loops`), consuming resources without
  meaningful work.

### CORE-H4: `_emit_interrupt_events`always called in`finally`block

- File:`lib/core/aggregator.py`
- `_emit_interrupt_events`performs`aget_state`I/O on every normal completion,
  not just on interrupt. Unnecessary I/O on the happy path.

### CORE-H5:`agent_id`in`load_agent_config`not validated before path construction

- File:`lib/core/team_config.py`
- Path traversal possible via crafted `agent_id`values in config references.

### CORE-H6:`TopologyType`not exported from`lib/core/__init__.py` `__all__`

- File: `lib/core/__init__.py`
- ADR-009 facade violation — `TopologyType`is used externally but not
  re-exported.

### MEDIUM

**CORE-M1:**`generate_nickname`doesn't sanitize`feature_tag`beyond`strip("-")`—
uppercase feature_tags fail`ThreadMetadata`validation.
**CORE-M2:**`_compile_star`topology doesn't validate supervisor agent exists
in`agent_configs`.
**CORE-M3:** `compile_team_graph`doesn't validate`topology_type`is a
known`TopologyType`enum value.
**CORE-M4:**`StateGraph`channel definitions not validated against agent output
schemas.
**CORE-M5:**`_compile_pipeline`allows empty`pipeline_order`list, producing a
graph with no worker nodes.
**CORE-M6:**`GraphInterrupt` detected by string class name (`type(e).__name__`)
instead of `isinstance`.
**CORE-M7:** `shutdown()`cancels chunk flush tasks without`await
asyncio.gather()`.
**CORE-M8:** `create_worker_node`closure captures mutable`agent_configs`dict by
reference.
**CORE-M9:**`loop_count`metadata not surfaced in any event type for frontend
visibility.

### LOW

**CORE-L1:**`_loop_router`docstring describes non-existent "FINISH" signal.
**CORE-L2:**`max_loops`default value (10) not documented in ADR-013.
**CORE-L3:**`pipeline_order`type is`list[str]`but no deduplication check.
**CORE-L4:**`_compile_pipeline_loop`reuses`_compile_pipeline`internally — no
independent test.
**CORE-L5:**`compile_team_graph`return type annotation could be more specific.
**CORE-L6:**`aggregator.py`has`# noqa: PLR0912 PLR0915`but function complexity
could be reduced.

---

## 2.`lib/api/`— API Module Audit

### CRITICAL (2)

### API-C1: Test infrastructure — split database states undermine test validity

- File:`lib/api/tests/test_endpoints.py`, lines 49–70; `lib/api/app.py`, lines
  186–249
- `_make_app()`overrides`get_db`, `get_aggregator`, `get_graph_registry`via
  FastAPI DI but does NOT override`get_checkpointer`or`get_task_group`. The real
  `_lifespan`opens the **production`vaultspec.db`** on disk. Tests pollute the
  production database and operate against a split state (in-memory SQLAlchemy +
  on-disk checkpointer). Confirmed by `vaultspec.db`appearing in`git status`as
  modified.

### API-C2:`mark_ingest_active()`return value not checked at thread creation

- File:`lib/api/endpoints.py`, line 369
- `registry.mark_ingest_active(thread.id)`return value silently discarded. Every
  other call site checks the return. If a previous failed cleanup left the
  thread ID in`_active_ingests`, a second concurrent graph execution could
  corrupt the LangGraph checkpointer state. ADR-007 §5 requires concurrent
  execution prevention.

### HIGH (2)

### API-H1: `schemas/__init__.py`facade missing three public types

- File:`lib/api/schemas/__init__.py`
- `SendMessageResponse`, `AgentStatusEntry`, `PendingPermission`are
  in`rest.py.__all__`but not re-exported from the facade. Violates ADR-009 §5.

### API-H2:`ErrorEvent`emitted with`sequence=0`

- File: `lib/api/websocket.py`, line 346
- Violates ADR-011 §5 monotonic sequence mandate (sequences start at 1). Breaks
  frontend gap detection logic.

### API-H3: `_AgentSnapshot.provider`and`_AgentSnapshot.model`are required with

no default

- File:`lib/api/schemas/snapshots.py`, lines 77–84
  | - Unlike `AgentStatusEntry`and`AgentSummary`which correctly use`Provider |
None = None`, `_AgentSnapshot`requires these fields — making the`agents`list in
  reconnection snapshots unusable when provider/model are unknown. |

### API-H4:`auth.py`module mandated by ADR-009 is missing

- File:`lib/api/`(absent)
- ADR-009 §2.2 lists`lib/api/auth.py`as required. The API has zero
  authentication. Combined with default`0.0.0.0`binding (API-L3), the
  unauthenticated API is exposed to the local network.

### API-H5: WebSocket`SEND_MESSAGE`and REST content fields have no length validation

- File:`lib/api/schemas/commands.py`, lines 47–53
- `content: str`has no`max_length`. A 1 MiB message body flows directly into the
  LLM context window, causing excessive token consumption or LLM API errors.

### MEDIUM (2)

**API-M1:** Tests write to real `vaultspec.db`on disk (consequence of API-C1).
**API-M2:**`GraphRegistry._active_ingests`is a plain`set`with no`asyncio.Lock`—
check-then-add is not atomic under asyncio concurrency.
**API-M3:**`POST /threads/{id}/messages`graph execution path not tested.
**API-M4:**`schemas/tests/__init__.py`missing`__all__`; no round-trip tests for
`SendMessageResponse`, `AgentStatusEntry`, `PendingPermission`.
**API-M5:** WebSocket `SEND_MESSAGE`, `AGENT_CONTROL`, and oversized frame path
not tested.
**API-M6:** `GET /threads/{id}/state` enriched snapshot path
(`_enrich_snapshot_from_state`) not tested — critical for reconnection protocol.
**API-M7:** Duplicate `engine`/`session_factory`fixtures between test files —
no`conftest.py`.
**API-M8:** `GET /team/status`returns hardcoded
empty`pending_permissions`always.

### LOW (2)

**API-L1:** TypeScript types are hand-written, not generated from OpenAPI
(ADR-011 §2.4).
**API-L2:** Circular import between`lib/api/`and`lib/core/aggregator`violates
ADR-009 independence.
**API-L3:**`main()`binds to`0.0.0.0`by default — exposes unauthenticated API to
local network.
**API-L4:** No`conftest.py`in`lib/api/tests/`.

---

## 3. `lib/providers/`— Providers Module Audit

### CRITICAL (3)

### PROV-C1: Background RPC tasks never cancelled on session cleanup

- File:`lib/providers/acp_chat_model.py`, lines 530–536 (spawn), 405–444
  (cleanup)
- `_dispatch_packet()`creates`asyncio.Task`for every server RPC, stored
  in`ctx.background_tasks`. `_cleanup_session()`cancels
  only`stdout_task`and`stderr_task`— never iterates or
  cancels`ctx.background_tasks`. An in-flight `session/request_permission`task
  continues after process kill, holds dead`ctx.stdin`references, and
  produces`BrokenPipeError`or hangs on`drain()`. ADR-001 §5 requires all spawned
  tasks to be supervised.

### PROV-C2: `_process_stdout_loop`blocks on`chunk_queue.put()`— potential deadlock

- File:`lib/providers/acp_chat_model.py`, lines 960–965
- `_handle_session_update()`is awaited directly in the stdout loop with`await
ctx.chunk_queue.put(...)` on a bounded queue (maxsize=1024). If the consumer
  (`_yield_chunks`) is slow, the queue fills, blocking the stdout loop. If the
  ACP subprocess waits for an RPC response before sending more data, the entire
  pipeline deadlocks with no timeout and no error.

### HIGH (3)

### PROV-H1: `prompt_error_ref`is dead code

- File:`lib/providers/acp_chat_model.py`, line 562 (write), 224 (field), 337
  (init)
- `ctx.prompt_error_ref`is written to but never read. The real error path flows
  through`prompt_future.result()["error"]`. Dead secondary error accumulator
  creates maintenance confusion.

### PROV-H2: `assert`used for runtime stream validation — stripped under`-O`flag

- File:`lib/providers/acp_chat_model.py`, lines 327–328, 487, 1175–1270
- `assert process.stdin is not None`is not a runtime guard — stripped by Python
  optimizer. Should be explicit`if ... is None: raise RuntimeError(...)`.

### PROV-H3: Terminal kill paths use `process.kill()`instead

of`_kill_process_tree`on Windows

- File:`lib/providers/acp_chat_model.py`, lines 868–871, 949–951, 413–416
- `terminal/kill`, `terminal/release`, and session cleanup all use
  `process.kill()`for terminal subprocesses. On Windows, grandchild processes
  (from`python`, `node`, `npm`, `pytest`in the allowlist) survive as orphans.
  ADR-001 §5 mandates`_kill_process_tree`for Windows.

### PROV-H4: Gemini provider detection fails for full-path commands

- File:`lib/providers/acp_chat_model.py`, line 318
- `"gemini" in self.command`is list membership (not substring). A command
  like`["/usr/local/bin/gemini", ...]`doesn't match — token refresh is skipped,
  causing the silent hang from gemini-cli issue #13853.

### PROV-H5: ADR-002 vs. ADR-006 contradiction on Claude command invocation is unresolved

- File:`lib/providers/factory.py`, line 88; ADR-002 §2; ADR-006 §5.1
- ADR-002 mandates `node.exe dist/index.js`direct invocation. ADR-006
  mandates`create_subprocess_shell("claude-agent-acp")`. Implementation follows
  ADR-006 but ADR-002 is not marked as superseded.

### MEDIUM (3)

**PROV-M1:** `stdout_task`/`stderr_task`cancellation is fire-and-forget —
no`await asyncio.gather()`before killing process.
**PROV-M2:**`GraphBubbleUp`after`end_turn`is silently swallowed — race
between`prompt_done`and interrupt`None`sentinel.
**PROV-M3:** Terminal`env`parameter not sanitized for variable name validity
—`_ENV_NAME_RE`check missing.
**PROV-M4:**`gemini_auth.py`error message exposes full OAuth error response body
(ADR-002 §5).
**PROV-M5:**`_ProbeSession.handle_server_rpc()`writes to stdin without lock
(concurrent write race).
**PROV-M6:** No non-live unit tests for security-critical`AcpChatModel` paths
(`_sandbox_path`, allowlist, capability gate, `GraphBubbleUp`propagation).

### LOW (3)

**PROV-L1:**`_FakeWriter`inline stubs in`test_protocol.py`contradict no-mocks
mandate.
**PROV-L2:**`session/cancel`skipped when`GraphBubbleUp`races with`end_turn`.
**PROV-L3:** `factory.py`raises opaque`KeyError`for unsupported`(provider,
model)`combinations.
**PROV-L4:**`gemini_auth.py`runs blocking`os.fsync()`on async event loop thread
without`to_thread`.

---

## 4. `lib/database/`+`lib/protocols/`— DB & Protocol Audit

### CRITICAL (4)

### DB-C1:`"active"`status string not in`ThreadStatus`enum

- File:`lib/api/endpoints.py`, line 628
- `update_thread_status(db, thread_id, "active")`—`"active"`is not a
  valid`ThreadStatus`value. Should be`"running"`.

### DB-C2: ADR-014 §2.5 prescribes wrong column name

- ADR-014 §2.5 says `metadata`as attribute name but implementation correctly
  uses`thread_metadata`(SQLAlchemy reserves`metadata`). The ADR needs updating
  to match the implementation.

### HIGH (4)

**DB-H1:** `crud.py` `get_thread`returns`None`for missing threads — no 404 path
tested.
**DB-H2:**`onupdate=_utcnow`on`updated_at`— in-memory value is stale after flush
due to`expire_on_commit=False`.
**DB-H3:** `IntegrityError`catch path (TOCTOU nickname protection) is completely
untested.
**MCP-H1:** MCP tool error handling does not distinguish network vs. application
errors.
**MCP-H2:**`_KNOWN_PRESETS`hardcoded fallback activates silently in packaged
deployments where preset TOML files are absent.

### MEDIUM (4)

**DB-M1:** Cross-module import
of`NicknameConflictError`from`lib.core.exceptions`violates ADR-009 independence.
**DB-M2:**`crud.py`missing`update_thread_metadata`function — metadata update
requires raw SQLAlchemy.
**DB-M3:**`session.py` `get_db`async generator yield does not handle generator
cleanup exceptions.
**MCP-M1:**`_PRESET_TEAMS_DIR`uses`Path(__file__)`-relative navigation
incompatible with wheel packaging.
**MCP-M2:** WebSocket URL parsed twice; credentials in `api_base_url`would leak.

### LOW (4)

**DB-L1:**`models.py` `__repr__`methods not implemented — debugging is opaque.
**DB-L2:**`crud.py`functions don't use type annotations for return values
consistently.
**DB-L3:**`session.py` `init_db`doesn't validate SQLite version compatibility.
**MCP-L1:** MCP server`__all__`missing from`server.py`.

---

## 5. `lib/utils/`+`lib/telemetry/`+`lib/workspace/`— Utilities Audit

### CRITICAL (5)

### UTIL-C1:`enums.py`missing`__all__`declaration

- File:`lib/utils/enums.py`
- Violates ADR-009 §5.3. Every sub-sub-module must declare `__all__`.

### TEL-C2: OTel SDK optional-import guards violate ADR-015

- File: `lib/telemetry/instrumentation.py`
- `try/except ImportError`guards for OTel SDK still present. ADR-015 makes the
  SDK a mandatory dependency — these guards should be removed.

### WS-C3:`merge_worktree()`and`has_conflicts()`accept unvalidated`target_branch`

- File: `lib/workspace/git_manager.py`
- `target_branch`parameter not validated against`_BRANCH_NAME_RE`. Git flag
  injection possible via `--flag`values.

### HIGH (5)

**WS-H1:** Credential scrub list missing`ZHIPU_API_KEY`, `LANGCHAIN_API_KEY`,
and `VAULTSPEC_*`prefixed variants.
**TEL-H2:**`opentelemetry-instrumentation-fastapi`declared as dependency
but`FastAPIInstrumentor`never invoked.
**WS-H3:** Zero tests for credential scrubbing in`resolve_env_vars()`.
**UTIL-H4:** `printer.py` `safe_print`swallows all exceptions silently
—`UnicodeEncodeError`handling too broad.
**TEL-H5:** Module-level tracer in`middleware.py`may bind to no-op provider if
imported before`configure_telemetry()`.
**WS-H6:** No tests for `_AGENT_ID_RE`/`_BRANCH_NAME_RE`validation or path
traversal rejection.
**WS-H7:**`MergeStrategy.REBASE`is logically inverted (rebases target onto
worktree instead of worktree onto target) and entirely untested.

### MEDIUM (5)

**TEL-M1:**`ws_span`creates spans even when OTel SDK is disabled — unnecessary
overhead.
**WS-M2:**`list_worktrees`parsing logic has off-by-one in`entry_index`for bare
repos.
**WS-M3:**`resolve_env_vars()`silently inherits caller's`VIRTUAL_ENV`when
no`.venv`found.
**UTIL-M4:**`logging.py` `JSONFormatter`doesn't handle`extra`dict fields
from`logger.info("msg", extra={...})`.
**TEL-M5:** Module-level `_SDK_DISABLED`constant evaluated at import time —
cannot be overridden in tests.
**UTIL-M6:**`__init__.py`in`lib/utils/`missing re-exports for`enums`module.

### LOW (5)

**WS-L1:**`resolve_venv`traversal bound (10 levels) is arbitrary with no
documentation.
**TEL-L2:**`TelemetryConfig`fields could use`Field(description=...)`for
auto-documentation.
**WS-L3:**`WorktreeInfo` `is_main`logic comment is confusing — describes
implementation trick not rationale.
**UTIL-L4:**`printer.py` `format_event`has hardcoded ANSI color codes — not
configurable.

---

## 6. Cross-Cutting Test Quality Audit

### CRITICAL (6)

### TEST-C1: Fake/stub LangGraph objects in aggregator tests

- File:`lib/core/tests/test_aggregator.py`
- 6 fake/stub classes (`_FakeNode`, `_FakeGraph`, `FakeChunk`, `BigChunk`,
  `_FakeInterrupt`, `_FakeTask`, `_FakeState`) violate the no-mocks mandate.
  Tests exercise stubs instead of real LangGraph primitives.

### TEST-C2: `_FakeWriter`stubs bypass real asyncio I/O in protocol tests

- File:`lib/providers/probes/tests/test_protocol.py`
- `_FakeWriter`defined 5 times inline. Replaces
  real`asyncio.StreamWriter`behavior (buffer management,
  backpressure,`drain()`side effects).

### HIGH (6)

**TEST-H1:** Vacuous`assert isinstance(cfg.sdk_enabled, bool)`assertions in
telemetry tests — always true.
**TEST-H2:**`test_configure_telemetry_sdk_disabled`monkeypatches env var after
module import — tests import-time constant, not runtime behavior.
**TEST-H3:** Three telemetry tests have`isinstance(bool)`assertions that can
never fail.
**TEST-H4:**`inject_trace_context`tests only assert`isinstance(carrier, dict)`—
always true since carrier was just created as a dict.
**TEST-H5:**`test_start_thread_default_preset_not_unknown` asserts absence not
presence.
**TEST-H6:** MCP tool tests use vacuous keyword-in-result disjunctions (`"x" in
r or "y" in r`— always one of many words matches).
**TEST-H7:**`test_ws_span_with_thread_id`has no assertion on span attribute
being set.

### MEDIUM (6)

**TEST-M1:**`test_aggregator.py`tests exercise fake graph with fake chunks — no
real LangGraph astream_events.
**TEST-M2:**`inject_trace_context`tests only verify dict type, not actual W3C
traceparent header injection.
**TEST-M3:** Workspace tests don't exercise`resolve_env_vars`credential
scrubbing.
**TEST-M4:** No tests for`generate_nickname`edge cases (empty feature_tag,
special chars).
**TEST-M5:** MCP server tests don't verify HTTP calls are made to correct
endpoints.
**TEST-M6:** Database tests don't cover concurrent access patterns or WAL mode
behavior.
**TEST-M7:** No tests for`_enrich_snapshot_from_state`in API endpoints.
**TEST-M8:**`test_ws_span_with_thread_id` has no assertion — dead test.
**TEST-M9:** Provider factory tests don't cover error paths (unsupported
provider/model combos).
**TEST-M10:** Graph compilation tests don't verify node connectivity or edge
conditions.
**TEST-M11:** Aggregator debounce/batch/backpressure logic has no
timing-sensitive tests.

### LOW (6)

**TEST-L1:** Test file naming inconsistency
(`test_protocol.py`vs`test_server.py`).
**TEST-L2:** Missing `conftest.py`files for shared fixtures across test
directories.
**TEST-L3:** No parameterized tests for enum validation across multiple values.
**TEST-L4:** Test docstrings describe what is tested but not the expected
behavior or failure mode.
**TEST-L5:** Several test modules import unused fixtures.
**TEST-L6:** No integration test that exercises the full REST → graph → event →
WebSocket pipeline.

---

## Priority Fix Order

### Phase 1 — CRITICAL (14 findings)

Must fix immediately — these represent active bugs, security vulnerabilities, or
architectural violations that undermine system correctness:

1. **PROV-C1** — Cancel`ctx.background_tasks`in`_cleanup_session`
2. **PROV-C2** — Use `put_nowait`with`QueueFull`guard or`wait_for`timeout
   on`chunk_queue.put`
3. **API-C1** — Override `get_checkpointer`and`get_task_group`in test
   infrastructure
4. **API-C2** — Check`mark_ingest_active()`return value at thread creation
5. **DB-C1** — Replace`"active"`with`"running"`in`update_thread_status`
6. **DB-C2** — Update ADR-014 §2.5 to reflect `thread_metadata`column name
7. **CORE-C1** — Fix or remove dead`"next"`key check in`_loop_router`
8. **CORE-C2** — Add descriptive `ConfigurationError`for missing`agent_id`in
   configs
9. **CORE-C3** — Sanitize`feature_tag`before glob pattern injection
10. **WS-C3** —
    Validate`target_branch`against`_BRANCH_NAME_RE`in`merge_worktree`/`has_conflicts`
11. **UTIL-C1** — Add `__all__`to`enums.py`
12. **TEL-C2** — Remove OTel SDK `try/except ImportError`guards (ADR-015 makes
    it mandatory)
13. **TEST-C1** — Replace fake LangGraph stubs in aggregator tests
14. **TEST-C2** — Replace`_FakeWriter`stubs in protocol tests

### Phase 2 — HIGH (35 findings)

Fix next — security gaps, untested critical paths, and ADR violations:

- All`PROV-H*`, `API-H*`, `CORE-H*`, `WS-H*`, `TEL-H*`, `DB-H*`, `MCP-H*`,
  `TEST-H*`

### Phase 3 — MEDIUM + LOW (73 findings)

Fix when time permits — test quality improvements, minor gaps, cosmetic issues.

---

## Deduplication Notes

Some findings overlap between agents:

- `_FakeWriter`is flagged by both test-quality-auditor (TEST-C2) and
  providers-auditor (PROV-L1)
- Test infrastructure split-state is flagged by both api-auditor (API-C1) and
  test-quality-auditor
- Credential scrubbing gaps appear in both utils-auditor (WS-H1, WS-H3) and
  test-quality-auditor (TEST-M3)
- Missing`conftest.py` appears in both api-auditor (API-L4, API-M7) and
  test-quality-auditor (TEST-L2)

After deduplication, the effective unique finding count is approximately
**115–118**.
