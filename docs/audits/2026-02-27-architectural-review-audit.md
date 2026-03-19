---
date: 2026-02-27
type: audit
feature: architectural-review
description: 'Five-agent architectural review of the full codebase against all 13 ADRs confirming end-to-end orchestration viability with 0 critical violations and 6 identified gaps.'
related:
  - docs/adrs/2026-02-26-001-process-workspace-management-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-007-tech-stack-deployment-adr.md
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Architectural Review Audit — 2026-02-27

**Date:** 2026-02-27
**Audited By:** 5-agent audit team (3 Sonnet codeview + Opus orchestrator + Opus
senior auditor)
**Scope:** Full codebase against all 13 ADRs, backend-foundational-gaps plan,
and end-to-end orchestration viability
**Method:** Read-only inspection. All 13 ADRs read cover-to-cover by every agent
before code inspection.
**Supersedes:** `docs/audits/2026-27-02-active-audit.md`(Rev 2, stale — written
mid-session)

---

## Audit Team Composition

| Agent              | Model  | Domain                                                          | Findings                   |
| ------------------ | ------ | --------------------------------------------------------------- | -------------------------- |
| codeview-core      | Sonnet | `src/vaultspec_a2a/core/`(graph, state, team_config, nodes, aggregator)       | 0 critical, 2 minor        |
| codeview-providers | Sonnet | `src/vaultspec_a2a/providers/`(AcpChatModel, factory, probes, facade)         | Report delivered           |
| codeview-serving   | Sonnet | `src/vaultspec_a2a/api/`, `src/vaultspec_a2a/database/`, `src/vaultspec_a2a/telemetry/`, `src/vaultspec_a2a/workspace/` | 0 critical, 4 gaps         |
| orchestrator       | Opus   | Compiled unified report from 3 codeview agents                  | Unified gap analysis       |
| auditor            | Opus   | Final architectural authority                                   | Prioritized findings below |

---

## Reference Documents

| Document               | Path                                                      |
| ---------------------- | --------------------------------------------------------- |
| ADR-001                | `docs/adrs/001-process-and-workspace-management.md`       |
| ADR-002                | `docs/adrs/002-llm-context-provider-abstraction.md`       |
| ADR-003                | `docs/adrs/003-protocol-bridging-translation.md`          |
| ADR-004                | `docs/adrs/004-event-aggregation-server-side-replay.md`   |
| ADR-005                | `docs/adrs/005-frontend-rendering-stack.md`               |
| ADR-006                | `docs/adrs/006-protocol-ecosystem-bridge.md`              |
| ADR-007                | `docs/adrs/007-tech-stack-deployment.md`                  |
| ADR-008                | `docs/adrs/008-orchestration-topology-pipeline.md`        |
| ADR-009                | `docs/adrs/009-approved-module-hierarchy.md`              |
| ADR-010                | `docs/adrs/010-observability-telemetry-integration.md`    |
| ADR-011                | `docs/adrs/011-frontend-backend-contract.md`              |
| ADR-012                | `docs/adrs/012-agent-definition-schema.md`                |
| ADR-013                | `docs/adrs/013-team-composition-topology.md`              |
| Prior Audit            | `docs/audits/2026-27-02-active-audit.md`                  |
| Plan                   | `docs/plans/2026-02-27-backend-foundational-gaps-plan.md` |
| Prompt                 | `docs/prompts/backend-foundational-gaps.md`               |
| Research: Backend Gaps | `docs/research/2026-02-27-backend-gaps-research.md`       |
| Research: Model Matrix | `docs/research/2026-02-27-model-capability-matrix.md`     |

---

## CRITICAL (Blocks All Progress)

### C1: LangGraph Checkpointer Is Never Initialized or Wired

**ADR Violations:** ADR-004 SS2, ADR-008 SS2
**Files:**`src/vaultspec_a2a/api/app.py`(lifespan),`src/vaultspec_a2a/api/endpoints.py:194`
**Impact:** The entire interrupt/resume flow, state persistence, and
reconnection protocol are non-functional.

### Details

- `src/vaultspec_a2a/api/app.py`lifespan never creates an`AsyncSqliteSaver`instance. -`src/vaultspec_a2a/api/endpoints.py:194`calls`compile_team_graph()`without passing
  a`checkpointer`argument (defaults to`None`).
- Without a checkpointer, `graph.aget_state()` returns nothing meaningful
  (`endpoints.py:321`), breaking `GET /threads/{id}/state`.
- Without a checkpointer, LangGraph's `interrupt()`mechanism
  in`worker.py:47`cannot function — the graph has no place to persist suspended
  state, so`Command(resume=...)`on`POST /permissions/{id}/respond`is dead code.

**Fix Required:** In`_lifespan()`, initialize
`AsyncSqliteSaver.from_conn_string(db_path)`, manage its
`__aenter__`/`__aexit__`lifecycle, store it in`app.state.checkpointer`. Pass it
to `compile_team_graph()`from`create_thread_endpoint()`.

---

### C2: `POST /threads`Does Not Invoke the Graph

**ADR Violations:** ADR-011 SS2.2, ADR-004 SS2
**Files:**`src/vaultspec_a2a/api/endpoints.py:133-211`
**Impact:** Creating a thread compiles the graph but never starts execution. The
user sends `initial_message`but it is discarded.

### Details: (2)

-`create_thread_endpoint()`compiles the graph, registers it, but never
calls`aggregator.ingest()`with the`body.initial_message`.

- The `CreateThreadRequest`has an`initial_message: str`field, but the endpoint
  ignores it after thread creation.
- The user must separately call`POST /threads/{id}/messages`to trigger any graph
  execution, contradicting ADR-011 intent.

**Fix Required:** After`registry.register(thread.id, graph)`, call
`aggregator.ingest()`with a`HumanMessage(content=body.initial_message)`to start
the graph.

---

### C3: Fire-and-Forget`asyncio.create_task`With No Reference Retention

**ADR Violations:** ADR-007 SS5
**Files:**`src/vaultspec_a2a/api/app.py:102`, `src/vaultspec_a2a/api/endpoints.py:376`,
`src/vaultspec_a2a/api/endpoints.py:494`
**Impact:** Graph execution tasks can be silently garbage-collected
mid-execution, causing lost work.

### Details: (3)

- All use `asyncio.create_task()`without storing the returned Task reference.
  Per Python docs, the event loop only holds a weak reference to tasks — if no
  strong reference exists, the task may be GC'd.
- The`# noqa: RUF006`comments acknowledge this linter warning but do not fix it.
- ADR-007 SS5 explicitly mandates`anyio.create_task_group()`for managing
  background tasks in the lifespan.

**Fix Required:** Use`anyio.create_task_group()`(ADR-mandated) or maintain
a`set()`of active tasks
with`task.add_done_callback(active_tasks.discard)`pattern.

---

## HIGH (Blocks Production Use)

### H1:`_sandbox_path`Uses String Prefix Comparison (Path Traversal Risk)

**ADR Violations:** ADR-001 SS2 (workspace isolation)
**Files:**`src/vaultspec_a2a/providers/acp_chat_model.py:470`
**Impact:** Potential filesystem escape in ACP RPC handlers.

### Details: (4)

- `str(resolved).startswith(str(cwd.resolve()))`is vulnerable to path prefix
  confusion. If`cwd`is`/home/user`and a path resolves to`/home/user2/secret`,
  the startswith check passes.
- On Windows, less exploitable due to drive letter prefixes, but architecturally
  wrong.

**Fix Required:** Use `resolved.is_relative_to(cwd.resolve())`(Python 3.9+).

---

### H2: No LangGraph Checkpointer Lifecycle Management

**ADR Violations:** ADR-004 SS2
**Files:**`src/vaultspec_a2a/api/app.py`(lifespan)
**Impact:** Even when C1 is fixed, the
checkpointer's`__aenter__`/`__aexit__`lifecycle is not managed.

### Details: (5)

-`AsyncSqliteSaver`is a context manager. It must be entered (sets up SQLite
connection) and exited (closes it). -`test_graph.py:19`correctly uses`async with
AsyncSqliteSaver.from_conn_string(...)`. The lifespan must do the same.

---

### H3: `GET /team/status`Returns Empty Agent List

**ADR Violations:** ADR-012 SS6, ADR-013 SS2.6
**Files:**`src/vaultspec_a2a/api/endpoints.py:405-409`
**Impact:** Frontend team overview useless — always returns `agents=[]`.

### Details: (6)

- Hard-coded `agents=[]`. Does not query `aggregator._node_metadata`or
  construct`AgentSummary`objects from graph metadata.
- ADR-012 SS6 mandates`AgentSummary`with`role`, `display_name`,
  `description`sourced from node metadata.

**Fix Required:** Use`aggregator._node_metadata`(or expose a public method) to
build`AgentSummary`objects.

---

### H4:`fs/write_text_file`Does Not Respect Global Git Mutex

**ADR Violations:** ADR-001 SS2
**Files:**`src/vaultspec_a2a/providers/acp_chat_model.py:489-503`
**Impact:** Concurrent file writes from multiple agents can corrupt the git
index.

### Details: (7)

- `_on_fs_write_text_file`writes files directly without acquiring the global git
  mutex. -`workspace/git_manager.py`has the mutex implementation, but it is not
  integrated into the ACP RPC file write path.

---

### H5:`fs/read_text_file`and`fs/write_text_file`Are Synchronous I/O

**ADR Violations:** ADR-001 SS5 ("all tools must be strictly asynchronous")
**Files:**`src/vaultspec_a2a/providers/acp_chat_model.py:481`,
`src/vaultspec_a2a/providers/acp_chat_model.py:496`
**Impact:** Blocks the asyncio event loop during file I/O operations.

### Details: (8)

- `file_path.read_text()`and`file_path.write_text()`are synchronous.
- Should use`asyncio.to_thread()`or`aiofiles`.

---

### H6: `terminal/create`Does Not Sandbox Command Execution

**Files:**`src/vaultspec_a2a/providers/acp_chat_model.py:510-513`
**Impact:** Arbitrary command execution without validation. LLM outputs directly
drive subprocess execution.

### Details: (9)

- The `command`parameter from`terminal/create`is passed directly
  to`create_subprocess_exec`.
- No sandboxing, no allowlist. `cwd`is set but the command can be anything.

---

### H7: Database Path Mismatch Between`config.py`and`session.py`

**ADR Violations:** ADR-007 SS2
**Files:** `src/vaultspec_a2a/core/config.py:23`, `src/vaultspec_a2a/database/session.py:40`,
`src/vaultspec_a2a/api/app.py:73`
**Impact:** Application and LangGraph may use different databases, breaking
state coherence.

### Details: (10)

- `config.py:23`: `database_url = "sqlite+aiosqlite:///vaultspec.db"`(SQLAlchemy
  URL format) -`session.py:40`: `DEFAULT_DB_PATH = Path("data/orchestrator.db")`(plain path) -`app.py:73`: `init_db()`is called without passing`settings.database_url`, so it
  uses `data/orchestrator.db`.
- No coordination between application DB and checkpointer DB.

**Fix Required:** `init_db()`should read from`settings.database_url`.
Checkpointer should use the same file.

---

## MEDIUM (ADR Violations)

### M1: `anyio.create_task_group()`Not Used

**ADR Violations:** ADR-007 SS5
**Details:** ADR-007 SS5 explicitly mandates`anyio.create_task_group()`for
background tasks. Codebase uses raw`asyncio.create_task()`everywhere.

### M2: CORS Middleware Is`allow_origins=["*"]`

**ADR Violations:** ADR-007 SS5 (implicit — permissive dev config)
**Files:** `src/vaultspec_a2a/api/app.py:149`
**Details:** Should be `["http://localhost:5173", "http://127.0.0.1:5173"]`per
ADR-007.

### M3:`PermissionResponseCommand`Over WebSocket Silently Logged, Not Rejected

**ADR Violations:** ADR-011 SS3.1
**Files:**`src/vaultspec_a2a/api/websocket.py:268-275`
**Details:** Must send an `ErrorEvent`back to the client directing them to REST
endpoint.

### M4:`AgentControlCommand`Is a No-Op

**Files:**`src/vaultspec_a2a/api/websocket.py:257-265`
**Details:** Agent pause/cancel/resume not implemented. Stub only logs.

### M5: `_enrich_snapshot_from_state()`Uses`datetime.now(UTC)`Instead of Stored

Timestamp

**Files:**`src/vaultspec_a2a/api/endpoints.py:272`
**Details:** Message timestamps in state snapshot use current time rather than
actual creation time.

### M6: `compile_team_graph()`Creates ProviderFactory Instances at Compile Time

**Details:** Not a bug — ACP subprocess lifecycle (init/session/new) happens
at`ainvoke()`time. But worth noting for operational understanding.

### M7:`POST /threads`Catches Generic`Exception`for Agent Config Loading

**Files:**`src/vaultspec_a2a/api/endpoints.py:179`
**Details:** Should catch `AgentConfigNotFoundError`specifically and propagate
unexpected errors.

---

## LOW (Cleanup)

### L1:`_loop_router`Closure Captures`max_loops`by Reference

**Files:**`src/vaultspec_a2a/graph.py:305-310`
**Details:** Fine for current usage but could surprise if
`compile_team_graph`called multiple times.

### L2:`terminal/output`Concatenates stdout and stderr

**Files:**`src/vaultspec_a2a/providers/acp_chat_model.py:581`
**Details:** Acceptable for v1.

### L3: MCP Tools Are Stubs

**Files:** `src/vaultspec_a2a/protocols/mcp/server.py`
**Details:** Return documentation text, do not invoke graph engine. Deferred to
MCP integration phase.

### L4: No `Cache-Control`Headers for Static Assets

**ADR Violations:** ADR-007 SS5 (pitfall warning)
**Files:**`src/vaultspec_a2a/api/app.py:177-181`
**Details:** `StaticFiles` mounted without cache headers.

---

## End-to-End Orchestration Assessment

**Can the system run a multi-agent coding session today?** No.

The critical path is broken at step 1:

```text
POST /threads (C2: message discarded)
    → compile_team_graph (C1: no checkpointer)
        → graph.ainvoke() (never called)
            → AcpChatModel._astream() (never reached)
                → ACP subprocess (never spawned)
                    → event streaming (never happens)
                        → WebSocket (nothing to stream)
```text

The interrupt/resume path is entirely dead:

```text
interrupt() in worker.py (C1: no checkpointer → cannot persist)
    → aggregator emits PermissionRequestEvent (never reached)
        → frontend displays modal (never receives event)
            → REST POST /permissions/{id}/respond (C1: Command(resume=...) is dead code)
```text

**After fixing C1+C2+C3**, the basic path becomes viable:

- Thread creation triggers graph execution
- Graph compiles with checkpointer
- Agents can suspend via interrupt and resume via REST
- Events stream to WebSocket subscribers

**After fixing H1-H7**, the system is production-safe:

- File operations are sandboxed and async
- Git mutex prevents index corruption
- Database paths are aligned
- Team status endpoint works

---

## Strategic Fix Priority

| Priority | Finding                      | Impact When Fixed                                          |
| -------- | ---------------------------- | ---------------------------------------------------------- |
| 1        | C1 (Checkpointer)            | Unblocks state persistence, interrupt/resume, reconnection |
| 2        | C2 (Initial message)         | Unblocks thread execution                                  |
| 3        | C3 (Task retention)          | Prevents silent task GC                                    |
| 4        | H7 (Database path)           | Ensures state coherence                                    |
| 5        | H1 (Path traversal)          | Security fix                                               |
| 6        | H2 (Checkpointer lifecycle)  | Prevents connection leaks                                  |
| 7        | H3 (Team status)             | Enables frontend team overview                             |
| 8        | H4 (Git mutex)               | Safe concurrent writes                                     |
| 9        | H5 (Async file I/O)          | Unblocks event loop                                        |
| 10       | H6 (Terminal sandbox)        | Security fix                                               |
| 11       | M3 (WS permission rejection) | Protocol compliance                                        |

After the top 7 fixes, the system can run end-to-end multi-agent sessions.
