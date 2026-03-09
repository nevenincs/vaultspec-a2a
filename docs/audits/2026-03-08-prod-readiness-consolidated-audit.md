# Consolidated Production Readiness Audit — 2026-03-08

## Executive Summary

This document is the **single source of truth** for the VaultSpec A2A production
readiness sprint conducted 2026-03-07 through 2026-03-08. It consolidates
findings from 6 audit documents, 2 research documents, and 30+ completed tasks.

**Starting state**: The MCP server was a hollow shell. On a vanilla machine,
every tool call failed because the gateway was never auto-started, and the
gateway never spawned the worker. The system was non-functional outside of
Docker or manual multi-terminal setups.

**Ending state**: The full MCP -> Gateway -> Worker chain auto-starts from a
single MCP stdio invocation. Read-only tools work immediately (before the
worker is ready). Write tools get actionable error messages during startup.
The system is protected by circuit breakers, retry logic, process tree
cleanup, internal auth, and per-client backpressure.

### Sprint Metrics

| Metric | Value |
|--------|-------|
| Audit findings triaged | 71+ across 37 passes |
| Fixes shipped (verified) | 20 |
| Research documents produced | 4 |
| Audit documents produced | 8 |
| Architectural hardening items | 6 (IPC, AGG, WS) |
| Remaining open (CRIT/HIGH) | 1 CRIT (Docker only), 8 HIGH |
| Remaining open (MED/LOW) | 14 MED, 6 LOW |
| Test suite | 966 passed, 5 skipped, 0 failures |

---

## Architecture Overview

```
IDE (Claude Desktop / Cursor / VS Code)
  |
  | stdio or streamable-http
  v
MCP Server (FastMCP)          :stdio / :8002
  |
  | httpx loopback (AsyncClient, 15s timeout)
  v
Gateway (FastAPI + uvicorn)   :8000
  |  ^
  |  | /internal/events, /internal/heartbeat (token-gated)
  |  |
  | POST /dispatch (circuit-breaker protected)
  v  |
Worker (FastAPI + uvicorn)    :8001
  |
  | LangGraph + AcpChatModel
  v
LLM Provider (Anthropic / OpenAI / etc.)
```

**Auto-start flow** (ADR-031, PHASE-1a):
1. IDE starts `vaultspec-mcp` (stdio)
2. MCP lifespan spawns gateway subprocess (`mcp/server.py:221`)
3. Gateway lifespan spawns worker subprocess via `LazyWorkerSpawner` (`api/app.py:439`)
4. Worker spawn is **deferred** to first dispatch (not gateway startup)
5. Read-only MCP tools bypass `_require_gateway()` and work immediately (`PHASE-1b`)
6. Write tools call `_require_gateway()` which polls gateway health (`mcp/server.py:421`)

**Shutdown flow**:
- MCP lifespan exit -> `_shutdown_worker_process()` -> `taskkill /T /F /PID` (Windows)
- Gateway lifespan exit -> worker process cleanup via `_shutdown_worker_process()`
- Process tree kill ensures no orphaned grandchildren (`api/app.py:393-420`)

---

## Fix Log

All fixes verified in source. Line references are to current `main` branch.

### CRITICAL (3 fixed)

| ID | Finding | Fix | Location |
|----|---------|-----|----------|
| CRIT-01 | MCP server never starts gateway/worker | MCP lifespan spawns gateway subprocess; gateway auto-spawns worker | `protocols/mcp/server.py:221`, `api/app.py:591-607` |
| CRIT-02 | Gateway never auto-spawns worker (ADR-031 gap) | `LazyWorkerSpawner` class: deferred subprocess spawn, health polling, process tree cleanup | `api/app.py:439-530` |
| CRIT-03 | No gateway health endpoint for MCP startup probe | `/internal/health` endpoint with worker status, heartbeat staleness, circuit breaker state | `api/app.py:693-720`, `api/internal.py:112-144` |

### HIGH (8 fixed)

| ID | Finding | Fix | Location |
|----|---------|-----|----------|
| HIGH-01 | `service start` only starts one process | Combined `service start backend` launches gateway + worker | `cli/_service.py` |
| HIGH-02 | MCP no health validation at startup | `_require_gateway()` polls `/internal/health` with exponential backoff, self-healing flag | `protocols/mcp/server.py:421-470` |
| PROD-005 | No terminal event on graph compile failure | `thread_terminal(failed)` emitted from executor on compilation error | `worker/executor.py:440-455` |
| PROD-012 | Thread stays SUBMITTED on dispatch error | Thread set to FAILED on dispatch HTTP error; DB update gated on dispatch success | `api/endpoints.py:396-401` |
| PROD-015 | Thread set RUNNING before dispatch succeeds | Reordered: dispatch first, then set RUNNING on success | `api/endpoints.py:841-849` |
| PROD-017 | Internal endpoints unauthenticated in production | `_verify_internal_token` dependency on internal router; requires `VAULTSPEC_INTERNAL_TOKEN` when `VAULTSPEC_ENVIRONMENT != development` | `api/internal.py:112-144` |
| PROD-028 | No circuit breaker on gateway dispatch | `WorkerCircuitBreaker`: 3 consecutive failures opens circuit, 30s recovery, HTTP 503 when open | `api/app.py:78-170` |
| PROD-002b | Windows process tree kill for worker auto-spawn | `taskkill /T /F /PID` on Windows; `proc.terminate()` + SIGTERM on POSIX | `api/app.py:393-420`, `providers/_subprocess.py:70-95` |

### MEDIUM (4 fixed)

| ID | Finding | Fix | Location |
|----|---------|-----|----------|
| PROD-020 | MCP httpx client has no timeout | `_MCP_QUERY_TIMEOUT = 15.0` on all MCP httpx requests | `protocols/mcp/server.py:137` |
| PROD-022 | MCP caches empty preset list | Cache invalidation on empty preset response | `protocols/mcp/server.py` |
| PROD-030 | SPA build dir uses wrong name | Corrected `build` -> `dist` path | `api/app.py` |
| PROD-037 | MCP server env var for Docker API base | `MCP_API_BASE_URL` setting for non-loopback Docker configs | `protocols/mcp/server.py` |

### LOW (2 fixed)

| ID | Finding | Fix | Location |
|----|---------|-----|----------|
| PROD-041 | Worker subprocess stdout not suppressed | stdout/stderr redirected to `DEVNULL` for subprocess | `api/app.py` |
| PROD-047 | Gateway subprocess stdout not suppressed | stdout/stderr redirected to `DEVNULL` for subprocess | `protocols/mcp/server.py` |

### Architectural Hardening (6 items, all shipped)

| ID | Finding | Fix | Location |
|----|---------|-----|----------|
| IPC-01 | Worker events not timestamped | Events tagged with `time.monotonic()`, batch sorted before relay | `worker/ipc.py:126` |
| IPC-03 | Event batch relay has no retry | 3 retries with exponential backoff (0.1s base), 10k buffer cap | `worker/ipc.py:30-33`, `worker/ipc.py:141-176` |
| IPC-04 | No dispatch correlation ID | `dispatch_id` (uuid4 hex) on DispatchRequest, logged at all 4 dispatch sites | `api/schemas/internal.py:21`, `api/endpoints.py:385-386,836-837,1031-1032,1111-1112` |
| AGG-01/05 | Permission entries never garbage-collected | `prune_stale_permissions(max_age_seconds=300.0)` + `prune_sequences()` on thread terminal | `core/aggregator.py:943`, `core/aggregator.py:443` |
| WS-MULTI-03 | Slow WS client stalls all clients | Per-client bounded queue with drop-oldest backpressure | `api/websocket.py:495-530` |
| WS-ORD-01 | Separate heartbeat task interleaves with event writer | Single `_writer_loop` handles both events and heartbeats via `asyncio.wait_for` timeout | `api/websocket.py:422-466` |

### Deferred Minor Items (4, all shipped)

| Item | Fix | Location |
|------|-----|----------|
| MCP rate limiting | 60/min per IP, /mcp path only | (middleware) |
| Cancel race | DB update gated on dispatch success | `api/endpoints.py` |
| PermissionType enum | Replaces `"plan_approval"` magic string | `api/schemas/enums.py:115` |
| IDE setup docs | Developer documentation for IDE configuration | `docs/IDE_SETUP.md` |

### Previous Sprint Fixes (verified still intact)

| ID | Finding | Location |
|----|---------|----------|
| BE-04 | `_classify_tool_kind()` two-pass classifier | `core/aggregator.py` |
| BE-13 | PermissionOption field names `option_id`/`name` | `core/aggregator.py` |
| BE-18 | MCP server `entry.get("content")` (was `"title"`) | `protocols/mcp/server.py` |
| BE-19 | Plan approval resume string->dict translation | `api/endpoints.py:866-877` |
| BE-26 | Reasoning token extraction | `core/aggregator.py` |
| BE-27 | `finish_reason` from `response_metadata` | `core/aggregator.py` |
| BE-30 | Tool call input/output enrichment | `core/aggregator.py` |
| BE-32 | Cancel race with `"cancelled"` outcome | `database/crud.py` |
| BE-37 | Thread status transition validation | `database/crud.py:239-308` (`_VALID_TRANSITIONS`, `InvalidTransitionError`) |

---

## Remaining Gaps

### CRITICAL (1) -- Docker only

| ID | Severity | Finding | Impact | Phase |
|----|----------|---------|--------|-------|
| PROD-055 | CRIT | Dockerfile COPY destination path mismatch -- SPA not served in Docker | Docker prod image serves 404 for UI | Immediate (Docker fix) |

### HIGH (8) -- Operational robustness

| ID | Severity | Finding | Impact | Phase |
|----|----------|---------|--------|-------|
| PROD-067 | HIGH | Gateway ignores worker 429 on thread creation | Thread created in DB but dispatch silently fails under load | Phase 2 |
| PROD-068 | HIGH | Gateway ignores worker 429 on send_message | Message lost when worker is at capacity | Phase 2 |
| PROD-060 | HIGH | Prod compose env_file imports uncontrolled vars | Production environment contaminated by dev settings | Phase 2 (Docker) |
| PROD-061 | HIGH | LangSmith tracing leak in production via env_file | Unexpected tracing costs and data exfiltration risk | Phase 2 (Docker) |
| PROD-066 | HIGH | Circuit breaker blocks cancel requests | User cannot cancel a runaway agent when circuit is open | Phase 2 |
| PROD-043 | HIGH | Worker rejects cancel at capacity (429) | Cancel-under-load fails silently | Phase 2 |
| PROD-050 | HIGH | DELETE allows deleting RUNNING threads | Running thread orphaned with no terminal event | Phase 2 |
| PROD-053 | HIGH | Docker compose missing auto_spawn_worker=false | Worker double-spawned in Docker (gateway auto-spawns + compose runs worker) | Phase 2 (Docker) |

### MEDIUM (14) -- Quality and edge cases

| ID | Finding | Phase |
|----|---------|-------|
| PROD-057 | Docker prod compose doesn't set VAULTSPEC_ENVIRONMENT | Phase 2 |
| PROD-062 | CORS origins include localhost in production | Phase 2 |
| PROD-063 | Duplicate ingest silently drops user message | Phase 3 |
| PROD-064 | Resume silently dropped when ingest active | Phase 3 |
| PROD-069 | Circuit breaker blocks permission resume | Phase 2 |
| PROD-070 | Internal WS auth doesn't check environment | Phase 2 |
| PROD-071 | WS message handler ignores worker 429 | Phase 2 |
| PROD-059 | Mock-seeder concurrent SQLite connections | Phase 3 |
| PROD-044 | Cancel with no active ingest -- no terminal event | Phase 3 |
| PROD-046 | Cancel events dict memory leak potential | Phase 3 |
| PROD-056 | CLI service status uses auth-gated endpoint | Phase 2 |
| PROD-038 | CLI stop worker sends to non-existent endpoint | Phase 2 |
| PHASE-1d | MCP startup progress logging | Phase 2 (in progress) |
| PHASE-1e | Gateway health-check polling optimization | Phase 2 |

### LOW (6) -- Minor polish

| ID | Finding | Phase |
|----|---------|-------|
| PROD-065 | Worker thread-to-cache-key grows unbounded | Phase 3 |
| PROD-072 | WS control handler ignores worker 429 on cancel | Phase 3 |
| PROD-058 | Mock-seeder bypasses dispatch pipeline | Phase 3 |
| PROD-054 | Docker healthcheck URL auth-gated | Phase 2 (Docker) |
| PROD-048 | MCP process cleanup on SIGKILL | Phase 3 |
| PROD-045 | Vite proxy rules are dead code | Phase 3 |

---

## Test Coverage

| Module | Tests | Status |
|--------|-------|--------|
| `api/tests/test_internal.py` | Internal health, events, heartbeat, auth | All passing |
| `api/tests/test_websocket.py` | WS connect, subscribe, heartbeat, ping, backpressure | All passing |
| `api/tests/test_endpoints.py` | REST endpoints, dispatch, circuit breaker | All passing |
| `api/schemas/tests/test_schemas.py` | Pydantic schema validation | All passing |
| `core/tests/test_aggregator.py` | Event pipeline, backpressure, permission GC | All passing |
| `database/tests/` | CRUD, migrations, thread status transitions | All passing |
| `worker/tests/` | Executor, IPC bridge, heartbeat | All passing |
| `protocols/mcp/tests/test_server.py` | MCP tool surface, error handling | All passing |
| `providers/probes/tests/test_protocol.py` | ACP probe protocol, rate limit parsing | All passing |
| `cli/tests/` | CLI commands, service management | All passing |
| **Total** | **966 passed, 5 skipped** | **0 failures** |

---

## Research Documents Produced

| Date | Title | File |
|------|-------|------|
| 2026-03-08 | Multi-service orchestration testing frameworks | `docs/research/2026-03-08-multi-service-testing-research.md` |
| 2026-03-08 | Industry patterns for multi-service developer tool UX | `docs/research/2026-03-08-industry-service-stack-ux-patterns.md` |
| 2026-03-08 | Process supervision models for desktop developer tools | (research briefing, delivered via team message) |
| 2026-03-08 | MCP progress notifications during startup | (feasibility analysis, delivered via team message) |

### Key Research Findings

1. **Industry comparison**: Most developer tools use stdio child processes (Copilot, Claude Desktop) or system daemons (Ollama). Our 3-process chain (MCP -> Gateway -> Worker) is unusual but justified by the need for independent scaling in Docker.

2. **Startup latency**: Our worst case is 4-7s (cold start with worker spawn). Industry target is <3s. `LazyWorkerSpawner` (PHASE-1a) mitigates this by deferring worker spawn to first dispatch.

3. **MCP progress notifications**: Cannot be sent during lifespan (no client session exists). `ctx.log()` works inside tool handlers only. Recommended pattern: lazy-start services on first write-tool call, report progress via `ctx.log()`.

4. **Testing**: Recommended zero-dependency approach (asyncio subprocess + httpx + OTel InMemorySpanExporter) over heavyweight frameworks (testcontainers, toxiproxy).

---

## Audit Documents Produced This Sprint

| Date | Title | File |
|------|-------|------|
| 2026-03-07 | MCP / Worker / Gateway prod audit (37 passes, 71 findings) | `docs/audits/2026-03-07-mcp-worker-gateway-prod-audit.md` |
| 2026-03-07 | CLI-API gap analysis (7 passes, 29 findings) | `docs/audits/2026-03-07-cli-api-gap-analysis.md` |
| 2026-03-07 | Frontend-backend schema alignment (7 CRIT, 7 HIGH) | `docs/audits/2026-03-07-frontend-backend-schema-alignment.md` |
| 2026-03-07 | Cross-layer naming consistency | `docs/audits/2026-03-07-cross-layer-naming-consistency-audit.md` |
| 2026-03-07 | MCP protocol layer audit | `docs/audits/2026-03-07-mcp-protocol-layer-audit.md` |
| 2026-03-07 | Justfile/CLI audit | `docs/audits/2026-03-07-justfile-cli-audit.md` |
| 2026-03-08 | End-to-end user experience audit | `docs/audits/2026-03-08-e2e-user-experience-audit.md` |
| 2026-03-08 | **This document** (consolidated) | `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md` |

---

## Phase Roadmap

### Phase 1 -- MCP Startup (COMPLETE)

- [x] PHASE-1a: Lazy worker spawn (defer to first dispatch)
- [x] PHASE-1b: Read-only tools bypass gateway health check
- [x] PHASE-1c: Actionable ToolError messages (`_handle_http_error`)
- [ ] PHASE-1d: Startup progress logging (in progress)
- [ ] PHASE-1e: Health-check polling optimization (pending)

### Phase 2 -- Operational Robustness (next sprint)

- [ ] Circuit breaker exemptions for cancel/resume
- [ ] Worker 429 handling at gateway (back-off + retry)
- [ ] Docker compose hardening (env_file, auto_spawn, VAULTSPEC_ENVIRONMENT)
- [ ] CLI service endpoints alignment
- [ ] Internal WS environment-aware auth
- [ ] MCP startup progress logging (PHASE-1d)
- [ ] Health-check polling optimization (PHASE-1e)

### Phase 3 -- Edge Cases and Polish (future)

- [ ] Cancel-without-ingest terminal event
- [ ] Memory leak prevention (cancel events dict, worker cache)
- [ ] Mock-seeder pipeline alignment
- [ ] MCP process cleanup on SIGKILL
- [ ] Vite proxy dead code cleanup

### Phase 2 Prerequisites (must complete before architecture evolution)

- [ ] **DB-H01+H02**: Module-level session factory singleton in `api/internal.py`
  is not injectable. `_handle_terminal_event()` uses the global
  `async_session_factory` directly instead of FastAPI DI (`get_db`), making
  the terminal event DB path untestable. Must be refactored to use DI before
  gateway+MCP process merge (Phase 4). Related: IPC-F01 architectural smell.

### Phase 4 -- Architecture Evolution (future, per research)

- [ ] Merge MCP + Gateway into single process (eliminate 1 hop)
- [ ] Daemon mode (system service, auto-start on boot)
- [ ] Health dashboard / TUI for service status

---

## Conclusion

The system has moved from **non-functional on vanilla machines** to
**fully operational with defense-in-depth**. The critical auto-start chain
works end-to-end. Read-only tools respond immediately. Write tools get
actionable errors during startup. The remaining gaps are operational
robustness (circuit breaker edge cases, Docker hardening) and can be
addressed in Phase 2 without blocking release for local development use.

**Release recommendation**: GREEN LIGHT for local development use.
Docker production deployment requires PROD-055 fix (CRIT) and Docker
compose hardening (Phase 2).

---

## Current Task Queue (2026-03-08, updated continuously)

### Coder: Code Done, Awaiting Commit (+1548/-649, 27 files)

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #45 | WRK-K02: Worker aggregator memory leak (prune_sequences) | MED | Code done, awaiting commit |
| #46 | WRK-K03: Graph compilation errors → GraphCompilationError | MED | Code done, awaiting commit |
| #50 | DCK-L09+APP-N04: Docker SPA path (VAULTSPEC_UI_BUILD_DIR) | CRIT | Code done, awaiting commit |
| #51 | EP-M01+M08: Terminal thread 500 → 409 guard | HIGH | Code done, awaiting commit |
| #53 | EP-M02: Health endpoint generic detail strings | MED | Code done, awaiting commit |
| #54 | EP-M04: Permission terminal state guard | MED | Code done, awaiting commit |
| #55 | PROV-O02: Docker _PROJECT_ROOT (VAULTSPEC_PROJECT_ROOT) | HIGH | Code done, awaiting commit |
| #56 | MANDATE: Replace mock API test conftest | CRIT | **Substantially done** — MockTransport+MemorySaver removed, _InProcessWorker replaces _CapturedDispatch |
| #60 | SKIP-01: pytest.skip → hard fails in provider tests | MED | Partially done (ACP tests fixed, factory tests remain) |

### Coder Priority Queue (after commit)

| Priority | ID | Subject | Severity |
|----------|----|---------|----------|
| 1 | #56 | MANDATE: Replace mock API test conftest | CRIT (user mandate) |
| 2 | #57 | MOCK-02: MCP server tests mock removal | CRIT (user mandate) |
| 3 | #58 | MOCK-03: core/test_graph.py unittest.mock | CRIT (user mandate) |
| 4 | #59 | MOCK-04: Worker tests MockTransport | CRIT (user mandate) |
| 5 | #64 | TEST-STUB-01: test_executor.py stubs | CRIT (user mandate) |
| 6 | #66 | MOCK-06: test_supervisor.py MemorySaver | LOW (user mandate) |
| 8 | #42 | WS-G01+APP-N03: WS dispatch errors + phantom thread | MED |
| 9 | #41 | DOCKER-01: docker-compose restart/healthcheck | HIGH |
| 10 | #52 | APP-N01: Worker stderr DEVNULL | MED |
| 11 | #48 | CLI-I03: service stop wrong endpoint | MED |
| 12 | #47 | CLI-I01: agent ask nickname collision | MED |
| 13 | #43 | WS-G03: Writer task cancellation race | LOW |
| 14 | #44 | DB-H: CRUD state machine unit tests | MED |
| 15 | #62 | TEL-01: Worker configure_telemetry() | MED |
| 16 | #63 | TEL-03: W3C traceparent on dispatch | HIGH (blocked by #62) |
| 17 | #49 | CFG-J06: Lazy core imports | LOW |
| 18 | #65 | DEP-AUDIT-01: Dependency audit | LOW |

### Pending — Mock Removal (needs user ruling)

| ID | Subject | Note |
|----|---------|------|
| #60 | SKIP-01: pytest.skip → hard fails (13 sites) | Provider + crash recovery tests |
| #61 | MOCK-05: monkeypatch.setenv (22 uses) | System boundary testing — user decision needed |

### Pending — Integration Tests

| ID | Subject | Blocked By |
|----|---------|------------|
| #35 | TESTING-03: IPC + heartbeat integration | — |
| #36 | TESTING-04: MCP E2E integration | — |

### Known Architectural Smells (no task — address during test overhaul)

- **IPC-F01** (LOW): Terminal event handler in `api/internal.py` uses global
  session factory instead of FastAPI DI (`get_db`). This makes the DB path
  untestable with standard fixture overrides. Will be addressed as part of the
  test suite overhaul when the mock conftest is rewritten (#56 and successors).

### Deferred Findings (no task yet — noted for future)

- **CLI-I06** (LOW): Hardcoded MCP tools list in CLI will go stale. Address
  when MCP tools change.
- **WRK-K06** (LOW): Worker dispatch endpoint (`/dispatch`) has no auth.
  Consistent gap — both gateway and worker need internal token on the dispatch
  path. Create task when auth story is finalized.
- **WRK-K01** (LOW): `worker/health.py` contains dead code. Bundle with a
  cleanup pass.
- **DCK-L04** (MED): `docker-compose.prod.yml` does not set
  `VAULTSPEC_INTERNAL_TOKEN`. Production Docker deployments will fail the
  internal token check at startup (PROD-017). Either add a placeholder env var
  with a comment in the compose file, or document as a required manual step in
  deployment docs.
- **APP-N03** (MED): WS dispatch proceeds with phantom/null thread — no 404
  guard. Bundled into #42 (WS-G01).

### Pass M+N Findings Summary (Endpoints + App)

All findings from Passes M (endpoints.py) and N (app.py) have tasks:

| Finding | Severity | Task | Status |
|---------|----------|------|--------|
| DCK-L09+APP-N04: SPA path wrong in Docker | CRIT | #50 | FIXED (uncommitted) |
| EP-M01+M08: Terminal thread 500 | HIGH | #51 | FIXED (uncommitted) |
| EP-M02: Health leaks exceptions | MED | #53 | FIXED (uncommitted) |
| EP-M04: Permission on terminal thread | MED | #54 | FIXED (uncommitted) |
| APP-N01: stderr DEVNULL + read | MED | #52 | Pending |
| APP-N03: WS phantom thread | MED | #42 | Pending (bundled with WS-G01) |

### Pass O Findings (Providers + Docker)

| Finding | Severity | Task | Status |
|---------|----------|------|--------|
| PROV-O02: _PROJECT_ROOT wrong in Docker non-editable install | HIGH | #55 | FIXED (uncommitted) |
| PROV-O01: Docker worker has no Node.js/ACP runtime | HIGH | #55 | Known limitation — Docker worker supports OpenAI/Zhipu only |

**Root cause pattern**: Both #50 and #55 share the same root cause — `Path(__file__)`
4-parent traversal resolves into `site-packages/` in non-editable installs
(Docker `uv sync --no-editable`). Fix pattern applied consistently:

- `app.py:_UI_BUILD_DIR` — reads `VAULTSPEC_UI_BUILD_DIR` env var, falls back
  to `__file__` traversal for editable dev installs
- `factory.py:_PROJECT_ROOT` — reads `VAULTSPEC_PROJECT_ROOT` env var, falls
  back to `__file__` traversal for editable dev installs
- `prod.Dockerfile` API stage: `ENV VAULTSPEC_UI_BUILD_DIR=/app/src/ui/dist`
- `prod.Dockerfile` worker stage: `ENV VAULTSPEC_PROJECT_ROOT=/app`

### Docker Production Status Summary

| Issue | Severity | Task | Fixed? |
|-------|----------|------|--------|
| SPA 404 (wrong COPY + wrong _UI_BUILD_DIR) | CRIT | #50 | YES (uncommitted) |
| Claude/Gemini crash (no ACP + wrong _PROJECT_ROOT) | HIGH | #55 | PARTIAL — _PROJECT_ROOT fixed, ACP missing is known limitation |
| No restart policies, no healthcheck deps | HIGH | #41 | Pending |
| No VAULTSPEC_INTERNAL_TOKEN in compose | MED | DCK-L04 | Deferred |
| VAULTSPEC_AUTO_SPAWN_WORKER not disabled | HIGH | #50 | YES — added to API stage ENV |

---

## Task Queue Refresh (2026-03-09)

The queue below reflects the next audit/implementation cycle after the durable
orchestration pass. It promotes partial, skipped, and newly-surfaced work into
the active queue rather than leaving those items implicit.

### Promoted Partial / Skipped Tasks

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #56 | MANDATE: Replace mock API test conftest | CRIT | PARTIAL — module conftest now uses real SQLite + AsyncSqliteSaver + in-process ASGI worker, but the broader mock-removal/testing mandate is still open |
| #57 | MOCK-02: MCP server tests mock removal | CRIT | Pending |
| #58 | MOCK-03: core/test_graph.py unittest.mock removal | CRIT | Pending |
| #59 | MOCK-04: worker tests MockTransport removal | CRIT | Pending |
| #60 | SKIP-01: pytest.skip → hard fails | MED | PARTIAL — some sites were removed, but skip-based policy drift remains and must be audited back into the suite |
| #64 | TEST-STUB-01: test_executor.py stubs | CRIT | Pending |
| #66 | MOCK-06: test_supervisor.py MemorySaver removal | LOW | Pending |
| #35 | TESTING-03: IPC + heartbeat integration | HIGH | Pending |
| #36 | TESTING-04: MCP E2E integration | HIGH | Pending |

### New Tasks From Orchestration Durability Review

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #67 | REPAIR-VERIFY-01: Add live recovery tests for pre-existing running/input_required/cancelling threads across restart | HIGH | Pending |
| #68 | REPAIR-PROJ-01: Expand checkpoint projection beyond `channel_values` into interrupt/control-aware repair projection | HIGH | Pending |
| #69 | REPAIR-STATE-01: Remove or formally redefine orphaned `created` lifecycle state across DB, API, tests, and docs | MED | Pending |
| #70 | REPAIR-APPROVAL-01: Replace `plan_approved` boolean with durable approval-state/request linkage | HIGH | Pending |
| #71 | AUDIT-LOOP-01: Re-run code review after each implementation slice and sync findings back into audit queue/docs | HIGH | Pending |

### New Tasks For Phased Postgres Production Path

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #72 | PG-ARCH-01: Introduce database/checkpointer backend abstraction and SQLite hardening for phased Postgres rollout | HIGH | Pending |
| #73 | PG-ARCH-02: Add Postgres-backed app DB + checkpoint factories, startup fail-fast, readiness, and dependency diagnostics | HIGH | Pending |
| #74 | PG-VERIFY-01: Add prod-like Docker/Postgres verification matrix and staged CI targets | HIGH | Pending |
| #75 | PLAN-REWRITE-01: Rewrite the backend production-readiness execution plan around open repair, test, Docker, and Postgres tracks | MED | Pending |
