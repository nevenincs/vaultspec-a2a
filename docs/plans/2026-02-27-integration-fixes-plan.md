---
date: 2026-02-27
type: plan
feature: integration-fixes
description: 'Critical path fixes to achieve end-to-end orchestration, resolving async I/O, git mutex, terminal sandbox, CORS, and checkpointer integration issues identified in the architectural audit.'
related_adrs:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-25-002-llm-context-provider-abstraction-adr.md
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-006-protocol-ecosystem-bridge-adr.md
  - docs/adrs/2026-02-26-007-tech-stack-deployment-adr.md
  - docs/adrs/2026-02-26-008-orchestration-topology-pipeline-adr.md
related_research:
  - docs/research/2026-02-27-backend-gaps-research.md
  - docs/research/2026-02-26-langgraph-gap-audit-research.md
---

# Integration Fixes Plan — Critical Path to End-to-End Orchestration

**Date:** 2026-02-27
**Type:** Implementation Plan
**Status:** Proposed
**Supersedes:** None (extends `2026-02-27-backend-foundational-gaps-plan.md`)
**Source Audit:** `docs/audits/2026-02-27-architectural-review-audit.md`

---

## References

### Binding ADRs

| ADR     | Path                                                    | Relevance to This Plan                                         |
| ------- | ------------------------------------------------------- | -------------------------------------------------------------- |
| ADR-001 | `docs/adrs/001-process-and-workspace-management.md`     | H4 (git mutex), H5 (async tools), H6 (terminal sandbox)        |
| ADR-002 | `docs/adrs/002-llm-context-provider-abstraction.md`     | Context — provider architecture                                |
| ADR-003 | `docs/adrs/003-protocol-bridging-translation.md`        | C1 (interrupt/resume requires checkpointer)                    |
| ADR-004 | `docs/adrs/004-event-aggregation-server-side-replay.md` | C1 (checkpoint-sqlite), C2 (aggregator.ingest), H2 (lifecycle) |
| ADR-005 | `docs/adrs/005-frontend-rendering-stack.md`             | Context — frontend expectations                                |
| ADR-006 | `docs/adrs/006-protocol-ecosystem-bridge.md`            | H1 (sandbox), H4 (fs write), H5 (async I/O), H6 (terminal)     |
| ADR-007 | `docs/adrs/007-tech-stack-deployment.md`                | C3 (anyio task group), H7 (database path), M2 (CORS)           |
| ADR-008 | `docs/adrs/008-orchestration-topology-pipeline.md`      | C1 (checkpointer mandate)                                      |
| ADR-009 | `docs/adrs/009-approved-module-hierarchy.md`            | Context — facade and import patterns                           |
| ADR-010 | `docs/adrs/010-observability-telemetry-integration.md`  | Context — OTel already wired                                   |
| ADR-011 | `docs/adrs/011-frontend-backend-contract.md`            | C2 (POST /threads), H3 (team status), M3 (WS rejection)        |
| ADR-012 | `docs/adrs/012-agent-definition-schema.md`              | H3 (AgentSummary from node metadata)                           |
| ADR-013 | `docs/adrs/013-team-composition-topology.md`            | H3 (team status with agent roster)                             |

### Audit and Research Documents

| Document                       | Path                                                      | Role                                   |
| ------------------------------ | --------------------------------------------------------- | -------------------------------------- |
| Architectural Review Audit     | `docs/audits/2026-02-27-architectural-review-audit.md`    | Source of all findings in this plan    |
| Prior Active Audit (Rev 2)     | `docs/audits/2026-27-02-active-audit.md`                  | Superseded — stale                     |
| Backend Foundational Gaps Plan | `docs/plans/2026-02-27-backend-foundational-gaps-plan.md` | Prior plan — 9 gaps addressed          |
| Backend Gaps Prompt            | `docs/prompts/backend-foundational-gaps.md`               | Original gap definitions               |
| Research: Backend Gaps         | `docs/research/2026-02-27-backend-gaps-research.md`       | Aggregator, SQLite, workspace patterns |
| Research: Model Matrix         | `docs/research/2026-02-27-model-capability-matrix.md`     | Provider capabilities                  |

### Reference Implementations

| File                                                                                         | Relevance                                                    |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `knowledge/repositories/toad/src/toad/acp/agent.py`                                          | Lines 348-468: Host-side RPC handler patterns for H4, H5, H6 |
| `knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py` | `AsyncSqliteSaver`bootstrap for C1, H2                       |
| `lib/core/tests/test_graph.py:19`                                                            | Correct checkpointer usage pattern (`async with`)            |

---

## Executive Summary

The backend foundational gaps plan (9 gaps, 4 phases) has been substantially
implemented.
However, a fresh architectural audit by a 5-agent team identified **3 critical
integration
failures** that prevent the system from running end-to-end. The LangGraph
checkpointer is
never initialized, thread creation discards the user's message, and background
tasks can be
silently garbage-collected. Additionally, **7 high-severity issues** block
production use:
path traversal vulnerability, synchronous file I/O blocking the event loop,
missing git mutex
integration, empty team status endpoint, unsandboxed terminal execution, and
database path
misalignment.

This plan addresses all 17 findings (3 critical, 7 high, 7 medium) in dependency
order
across 3 phases. After Phase 1 (3 fixes), the system can run end-to-end. After
Phase 2
(7 fixes), the system is production-safe. Phase 3 addresses protocol compliance.

---

## Current State

### What works

- All 13 ADR requirements for module structure (ADR-009) are met
- Wire contract schemas (51 Pydantic types) complete (ADR-011)
- Event aggregator with debounce, chunking, backpressure, sequence numbering
  (ADR-004)
- WebSocket connection manager with heartbeat, subscribe/unsubscribe (ADR-011)
- AcpChatModel with full ACP lifecycle and 7 host-side RPC handlers (ADR-006)
- TOML agent/team config with 3 topologies (ADR-012, ADR-013)
- Database models, CRUD, WAL session (ADR-007)
- Telemetry infrastructure with OTel spans wired into aggregator and WS
  (ADR-010)
- Git workspace management with mutex and worktree support (ADR-001)

### What's broken (end-to-end path)

```text
POST /threads → compile_team_graph(NO CHECKPOINTER) → initial_message DISCARDED → nothing runs
```

---

## Phase 1: Critical Path (Unblocks End-to-End)

These 3 fixes must be done sequentially. After Phase 1, the system can create
threads,
execute graphs, stream events, and handle interrupt/resume.

### Fix 1: Initialize and Wire LangGraph Checkpointer (C1 + H2)

**Source:** Audit C1 + H2
**ADR Mandate:** ADR-004 SS2, ADR-008 SS2
**Files:** `lib/api/app.py`, `lib/api/endpoints.py`
**Reference:** `lib/core/tests/test_graph.py:19`(correct pattern)

### Requirements

1. In`_lifespan()`, create `AsyncSqliteSaver`from the application database path:

```python
 async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
     app.state.checkpointer = checkpointer
     # ... rest of lifespan
```

The `async with`manages`__aenter__`/`__aexit__`(H2).

1. Store`checkpointer`in`app.state`so endpoints can access it.

1. In`create_thread_endpoint()` (`endpoints.py`), pass
   `app.state.checkpointer`to
   `compile_team_graph()`:

   ```python
   graph = compile_team_graph(
       team_config=team_config,
       agent_configs=agent_configs,
       checkpointer=request.app.state.checkpointer,
   )
   ```

1. The database path must be derived from `settings.database_url`(see Fix 4 /
   H7) to
   ensure the application DB and checkpointer use the same file.

### Validation

-`graph.aget_state(config)`returns a non-empty`StateSnapshot`after invocation -`interrupt()`in worker.py persists state to SQLite -`Command(resume=...)` in permission endpoint resumes the correct checkpoint

---

### Fix 2: Wire Initial Message Into Graph Execution (C2)

**Source:** Audit C2
**ADR Mandate:** ADR-011 SS2.2 (`POST /threads`creates thread AND kicks off
processing)
**Files:**`lib/api/endpoints.py`(create_thread_endpoint)

### Requirements: (2)

1. After`registry.register(thread.id, graph)`, invoke the graph with the initial
   message:

   ```python
   from langchain_core.messages import HumanMessage

   await aggregator.ingest(
       thread_id=thread.id,
       graph=graph,
       input={"messages": [HumanMessage(content=body.initial_message)]},
       config={"configurable": {"thread_id": thread.id}},
   )
   ```

1. The `aggregator.ingest()`call should be the mechanism that
   starts`astream_events`
   consumption and WebSocket broadcasting (ADR-004 SS2).

1. The response must return immediately with `thread_id`— graph execution runs
   in
   the background (see Fix 3).

### Validation: (2)

-`POST /threads`with`initial_message="Hello"`starts graph execution

- WebSocket subscriber receives`AgentStatusEvent(submitted)`followed by
  streaming events

---

### Fix 3: Task Retention via`anyio.create_task_group()`(C3 + M1)

**Source:** Audit C3, M1
**ADR Mandate:** ADR-007 SS5
**Files:**`lib/api/app.py`, `lib/api/endpoints.py`

### Requirements: (3)

1. In `_lifespan()`, create an `anyio.create_task_group()`and store it
   in`app.state`:

   ```python
   async with anyio.create_task_group() as tg:
       app.state.task_group = tg
       yield
   ```

   This ensures all background tasks are awaited on shutdown and cannot be GC'd.

1. Replace all `asyncio.create_task()`calls
   with`app.state.task_group.start_soon()`:
   - `app.py:102`(heartbeat or aggregator background tasks) -`endpoints.py:376`(graph invocation background task) -`endpoints.py:494`(permission resume background task)

1. Remove`# noqa: RUF006`comments — they are no longer needed.

### Validation: (3)

- No`asyncio.create_task()`calls remain in`app.py`or`endpoints.py`
- Background graph execution tasks survive for their full duration
- On server shutdown, all running tasks are properly cancelled/awaited

---

## Phase 2: Production Safety (Blocks Real Use)

These 7 fixes are independent and can be done in parallel. After Phase 2, the
system
is safe for real multi-agent coding sessions.

### Fix 4: Align Database Paths (H7)

**Source:** Audit H7
**ADR Mandate:** ADR-007 SS2
**Files:** `lib/core/config.py`, `lib/database/session.py`, `lib/api/app.py`

### Requirements: (4)

1. Define a single source of truth for the database file path in `config.py`.
2. `init_db()`in`session.py`must accept the path from settings, not use a
   hardcoded default. 3.`AsyncSqliteSaver` (Fix 1) must use the same database file.
3. Parse the SQLAlchemy URL (`sqlite+aiosqlite:///vaultspec.db`) into a plain
   path for
   `AsyncSqliteSaver.from_conn_string()`.

---

### Fix 5: Path Traversal Security Fix (H1)

**Source:** Audit H1
**ADR Mandate:** ADR-001 SS2
**Files:** `lib/providers/acp_chat_model.py`(\_sandbox_path)

### Requirements: (5)

1. Replace`str(resolved).startswith(str(cwd.resolve()))`with
   `resolved.is_relative_to(cwd.resolve())`(Python 3.9+, available in 3.13).

---

### Fix 6: Wire`GET /team/status`With Node Metadata (H3)

**Source:** Audit H3
**ADR Mandate:** ADR-012 SS6, ADR-013 SS2.6
**Files:**`lib/api/endpoints.py`(team_status_endpoint)

### Requirements: (6)

1. Query`aggregator._node_metadata`(or expose a public method like
   `aggregator.get_agent_summaries()`) to build `AgentSummary`objects.
2. Each`AgentSummary`must include`role`, `display_name`, `description`sourced
   from
   the node metadata set during`builder.add_node(...,
metadata={...})`in`graph.py`.
3. Include `provider`and`model`from the resolved agent config.

---

### Fix 7: Integrate Git Mutex Into`fs/write_text_file`(H4)

**Source:** Audit H4
**ADR Mandate:** ADR-001 SS2
**Files:**`lib/providers/acp_chat_model.py`(\_on_fs_write_text_file)

### Requirements: (7)

1.`_on_fs_write_text_file`must acquire the global git mutex before writing. 2. The mutex is in`workspace/git_manager.py`. Either:

- Inject a reference to the mutex into `AcpChatModel`, or
- Use a module-level shared lock accessible from providers.

1. Wrap the write in `try/finally`to guarantee lock release (ADR-001 SS5).

---

### Fix 8: Async File I/O (H5)

**Source:** Audit H5
**ADR Mandate:** ADR-001 SS5
**Files:**`lib/providers/acp_chat_model.py`(\_on_fs_read_text_file,\_on_fs_write_text_file)

### Requirements: (8)

1. Replace`file_path.read_text()`with`await
asyncio.to_thread(file_path.read_text)`.
2. Replace `file_path.write_text()`with`await
asyncio.to_thread(file_path.write_text, content)`.
3. Alternative: use `aiofiles`if already in dependencies.

---

### Fix 9: Terminal Command Validation (H6)

**Source:** Audit H6
**Files:**`lib/providers/acp_chat_model.py`(\_on_terminal_create)

### Requirements: (9)

1. At minimum, validate that the command executable exists in the agent's`cwd`or
   PATH.
2. Consider an allowlist of permitted commands or a configurable sandbox policy.
3. Log all terminal commands for audit trail.
4. For v1, at minimum ensure`cwd`is set and commands cannot escape the workspace
   root
   (reuse the`_sandbox_path`logic after Fix 5).

---

### Fix 10: Checkpointer Lifecycle in Lifespan (H2)

**Note:** This is addressed as part of Fix 1. Listed separately for tracking.

---

## Phase 3: Protocol Compliance

These fixes address ADR violations that don't block production but should be
resolved.

### Fix 11: Reject`PermissionResponseCommand`Over WebSocket (M3)

**Source:** Audit M3
**ADR Mandate:** ADR-011 SS3.1
**Files:**`lib/api/websocket.py`

### Requirements: (10)

1. When `PERMISSION_RESPONSE`is received over WebSocket, send
   an`ErrorEvent`back:

```python
 error = ErrorEvent(
     type=ServerEventType.ERROR,
     thread_id=cmd.thread_id,
     agent_id=None,
     timestamp=datetime.now(UTC),
     sequence=0,
     code="INVALID_CHANNEL",
     message="Permission responses must be submitted via REST: POST /api/permissions/{id}/respond",
 )
 await websocket.send_json(error.model_dump(mode="json"))
```

---

### Fix 12: Restrict CORS Origins (M2)

**Source:** Audit M2
**ADR Mandate:** ADR-007
**Files:** `lib/api/app.py`

### Requirements: (11)

1. Change `allow_origins=["*"]`to`allow_origins=["http://localhost:5173",
"http://127.0.0.1:5173"]`.
2. Optionally make configurable via `settings.cors_origins`.

---

### Fix 13: State Snapshot Timestamps (M5)

**Source:** Audit M5
**Files:** `lib/api/endpoints.py`(\_enrich_snapshot_from_state)

### Requirements: (12)

1. Use actual message creation timestamps from the LangGraph state rather than
   `datetime.now(UTC)`.

---

### Fix 14: Specific Exception Handling in `POST /threads`(M7)

**Source:** Audit M7
**Files:**`lib/api/endpoints.py`

### Requirements: (13)

1. Catch `AgentConfigNotFoundError`and`TeamConfigNotFoundError`specifically.
2. Return`404`for config not found, let unexpected errors propagate to the
   global handler.

---

### Fix 15:`AgentControlCommand`Implementation (M4)

**Source:** Audit M4
**Files:**`lib/api/websocket.py`

### Requirements: (14)

1. Wire `AGENT_CONTROL`command to graph cancellation: -`pause`→ not directly supported by LangGraph (defer) -`cancel`→ call`aggregator.cancel(thread_id)`which should terminate the
   `astream_events`task -`resume`→ re-invoke the graph from the last checkpoint

---

### Fix 16: Static Asset Cache-Control Headers (L4)

**Source:** Audit L4
**ADR Mandate:** ADR-007 SS5
**Files:**`lib/api/app.py`

### Requirements: (15)

1. Add middleware or configure `StaticFiles`to set`Cache-Control: public,
max-age=31536000`
   for hashed asset files (`.js`, `.css`with content hash in filename).
2. Set`Cache-Control: no-cache`for`index.html`.

---

## Phased Implementation Order

```text
Phase 1 (Sequential — unblocks end-to-end):
  Fix 1: Checkpointer init + lifecycle (C1 + H2)
      ↓
  Fix 2: Wire initial_message into aggregator.ingest() (C2)
      ↓
  Fix 3: anyio.create_task_group() for task retention (C3 + M1)

Phase 2 (Parallel — production safety):
  Fix 4: Database path alignment (H7)
  Fix 5: Path traversal fix (H1)
  Fix 6: Team status from node metadata (H3)
  Fix 7: Git mutex in fs/write (H4)
  Fix 8: Async file I/O (H5)
  Fix 9: Terminal command validation (H6)

Phase 3 (Parallel — protocol compliance):
  Fix 11: WS permission rejection error event (M3)
  Fix 12: CORS origin restriction (M2)
  Fix 13: Snapshot timestamps (M5)
  Fix 14: Specific exception handling (M7)
  Fix 15: AgentControlCommand (M4)
  Fix 16: Static asset caching (L4)
```

---

## Dependency Graph

```text
Phase 1:
  Fix 1 (checkpointer) ──→ Fix 2 (initial message) ──→ Fix 3 (task retention)

Phase 2 (all parallel, depends on Phase 1 complete):
  Fix 4 (db path)
  Fix 5 (path traversal)
  Fix 6 (team status)
  Fix 7 (git mutex)
  Fix 8 (async I/O)
  Fix 9 (terminal sandbox)

Phase 3 (all parallel, depends on Phase 1 complete):
  Fix 11-16 (protocol compliance)
```

---

## Validation Criteria

### After Phase 1 (End-to-End Functional)

| #   | Criterion                                                            | Source                |
| --- | -------------------------------------------------------------------- | --------------------- |
| V1  | `uvicorn lib.api.app:create_app --factory`starts without errors      | Prior plan V1         |
| V2  | `AsyncSqliteSaver`initialized in lifespan with`async with`           | Audit C1, H2          |
| V3  | `POST /threads`with`initial_message`triggers graph execution         | Audit C2              |
| V4  | WebSocket subscriber receives streaming events after thread creation | ADR-004               |
| V5  | `interrupt()`in worker.py persists state to SQLite                   | ADR-003               |
| V6  | `POST /permissions/{id}/respond`resumes graph from checkpoint        | ADR-011 SS3.1         |
| V7  | `GET /threads/{id}/state`returns meaningful`StateSnapshot`           | ADR-011 SS2.3         |
| V8  | No`asyncio.create_task()`in app.py or endpoints.py                   | Audit C3, ADR-007 SS5 |
| V9  | Background tasks survive for their full duration (no GC)             | Audit C3              |

### After Phase 2 (Production Safe)

| #   | Criterion                                                      | Source   |
| --- | -------------------------------------------------------------- | -------- |
| V10 | Single database path used by app, checkpointer, and session    | Audit H7 |
| V11 | `_sandbox_path`uses`is_relative_to()`                          | Audit H1 |
| V12 | `GET /team/status`returns`AgentSummary`list from node metadata | Audit H3 |
| V13 | `fs/write_text_file`acquires git mutex before writing          | Audit H4 |
| V14 | File read/write uses`asyncio.to_thread()`or`aiofiles`          | Audit H5 |
| V15 | `terminal/create`validates commands                            | Audit H6 |

### After Phase 3 (Protocol Compliant)

| #   | Criterion                                        | Source   |
| --- | ------------------------------------------------ | -------- |
| V16 | `PERMISSION_RESPONSE`over WS returns`ErrorEvent` | Audit M3 |
| V17 | CORS allows only`localhost:5173` origins         | Audit M2 |
| V18 | State snapshot uses actual message timestamps    | Audit M5 |
| V19 | Config loading catches specific exceptions       | Audit M7 |

### Regression Guard

| #   | Criterion                                                      | Source              |
| --- | -------------------------------------------------------------- | ------------------- |
| V20 | All existing tests pass (`pytest lib/`)                        | Prior plan V30      |
| V21 | `from lib.core import compile_team_graph`works                 | Prior plan V19      |
| V22 | `from lib.providers import AcpChatModel, ProviderFactory`works | Prior plan V20      |
| V23 | TOML preset loading still works                                | Prior plan V24, V25 |

---

## Risk Register

| #   | Risk                                                                                                                                                                                               | Severity | Mitigation                                                                                                                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| R1  | **Checkpointer + application DB sharing SQLite file.** Under high concurrency, WAL still permits only one writer. Checkpointer writes and application CRUD writes may contend.                     | MEDIUM   | Use separate`aiosqlite`connections. Protect application writes with`asyncio.Lock()`. Consider separate DB files if contention is observed.     |
| R2  | **`anyio.create_task_group()`cancellation semantics.** When the lifespan exits,`anyio`cancels all tasks in the group. Long-running graph executions may be interrupted mid-turn.                   | MEDIUM   | Implement graceful shutdown: set a flag that prevents new graph invocations, then wait for running tasks to reach a checkpoint before exiting. |
| R3  | **Git mutex acquisition from AcpChatModel.** The mutex is in`workspace/git_manager.py`but AcpChatModel is in`providers/`. Cross-module dependency may create import cycles.                        | LOW      | Pass the mutex as a parameter to `AcpChatModel`or use a shared module-level lock in`utils/`.                                                   |
| R4  | **Terminal sandbox scope.** Allowlisting commands is difficult when agents need to run arbitrary build/test commands. Over-restriction breaks functionality; under-restriction is a security risk. | MEDIUM   | For v1, log all commands and restrict `cwd`. Defer fine-grained sandboxing to v2 after real usage patterns are observed.                       |
