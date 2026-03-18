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
| 8 | #42 | WS-G01+APP-N03: WS dispatch errors + phantom thread | MED | FIXED |
| 9 | #41 | DOCKER-01: docker-compose restart/healthcheck | HIGH | FIXED |
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

- **CLI-I06** (LOW): closed. `vaultspec mcp tools` and `vaultspec mcp status`
  now derive their tool list and count from the live FastMCP registration
  surface via `mcp.list_tools()` instead of a hardcoded duplicate table.
- **WRK-K06** (LOW): closed. Worker `/dispatch` now enforces the same internal
  bearer-token contract as gateway `/internal/*`, the gateway-owned worker
  client sends the token by default, and direct tests cover `401` invalid/missing
  auth plus loud `500` non-development misconfiguration.
- **WRK-K01** (LOW): closed. The empty `worker/health.py` placeholder was
  removed; the real worker health contract remains in `worker/app.py` and
  `worker/ipc.py`.
- **DCK-L04** (MED): closed as stale. `docker-compose.prod.yml` already
  requires `VAULTSPEC_INTERNAL_TOKEN` via required-variable interpolation, and
  `docker/README.md` now documents it explicitly as a required production env.
- **APP-N03** (MED): WS dispatch proceeds with phantom/null thread — no 404
  guard. Fixed via #42: WebSocket command rejection is now repair-aware and
  distinguishes `THREAD_STATE_DRIFT`, `THREAD_STATE_UNVERIFIED`, and
  `THREAD_NOT_FOUND` instead of assuming the thread is fully gone.

### Pass M+N Findings Summary (Endpoints + App)

All findings from Passes M (endpoints.py) and N (app.py) have tasks:

| Finding | Severity | Task | Status |
|---------|----------|------|--------|
| DCK-L09+APP-N04: SPA path wrong in Docker | CRIT | #50 | FIXED (uncommitted) |
| EP-M01+M08: Terminal thread 500 | HIGH | #51 | FIXED (uncommitted) |
| EP-M02: Health leaks exceptions | MED | #53 | FIXED (uncommitted) |
| EP-M04: Permission on terminal thread | MED | #54 | FIXED (uncommitted) |
| APP-N01: stderr DEVNULL + read | MED | #52 | FIXED — gateway-managed worker stderr now goes to a deterministic runtime log, `/health` and `/api/health` expose the log path, and live crash-recovery verification proves restart records carry actionable diagnostics |
| APP-N03: WS phantom thread | MED | #42 | FIXED — accepted WebSocket connections now receive structured recoverable error events, and missing thread rows are classified against durable checkpoint residue instead of being treated as safe absence |

### Pass O Findings (Providers + Docker)

| Finding | Severity | Task | Status |
|---------|----------|------|--------|
| PROV-O02: _PROJECT_ROOT wrong in Docker non-editable install | HIGH | #55 | FIXED (uncommitted) |
| PROV-O01: Docker worker does not yet certify the full Claude/Gemini ACP provider matrix | HIGH | #55 | PARTIAL — worker image now includes Node.js + `claude-agent-acp` plus a pinned Gemini CLI runtime; remaining gap is explicit credential-backed Docker provider certification |

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
| Claude/Gemini Docker provider path incomplete | HIGH | #55 | PARTIAL — `_PROJECT_ROOT`, Claude Node ACP runtime, and Gemini CLI runtime are fixed; remaining gap is credential-backed Docker provider certification and auth-material verification |
| No restart policies, no healthcheck deps | HIGH | #41 | FIXED — current prod/dev/integration compose paths already use service restart policies and `service_healthy` dependency ordering where required |
| No VAULTSPEC_INTERNAL_TOKEN in compose | MED | DCK-L04 | FIXED — prod compose already hard-fails without the token, and Docker docs now call out the requirement explicitly |
| VAULTSPEC_AUTO_SPAWN_WORKER not disabled | HIGH | #50 | YES — added to API stage ENV |

---

## Task Queue Refresh (2026-03-09)

The queue below reflects the next audit/implementation cycle after the durable
orchestration pass. It promotes partial, skipped, and newly-surfaced work into
the active queue rather than leaving those items implicit.

### Promoted Partial / Skipped Tasks

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #56 | MANDATE: Replace mock API test conftest | CRIT | FIXED — API harness now uses real file-backed SQLite + AsyncSqliteSaver + in-process ASGI worker via `app.state` injection, with no `dependency_overrides` or `:memory:` DBs |
| #57 | MOCK-02: MCP server tests mock removal | CRIT | FIXED — MCP/API in-process fixtures now inject real DB/checkpointer/worker state through `app.state`, `get_db(request)` honors `app.state.db_session_factory`, and the MCP suite passes without `dependency_overrides` |
| #58 | MOCK-03: core/test_graph.py unittest.mock removal | CRIT | FIXED — graph tests now validate provider/capability/fallback precedence through a pure production helper instead of the old `Provider.MOCK` path |
| #59 | MOCK-04: worker tests MockTransport removal | CRIT | FIXED — worker IPC tests no longer use `MockTransport`; requests go through real ASGI wiring |
| #60 | SKIP-01: pytest.skip → hard fails | MED | FIXED — no remaining `pytest.skip`/`skipif`/`xfail` usage remains under `src/vaultspec_a2a`; provider and CLI skip paths were rewritten around truthful runtime contracts |
| #64 | TEST-STUB-01: test_executor.py stubs | CRIT | FIXED — `MockTransport`/stub patterns are gone and `_build_graph_input` is now a static production helper, removing the old `object.__new__(Executor)` bypass |
| #66 | TEST-STUB-01b: test_supervisor.py model-double removal | LOW | FIXED — `_StubChatModel` is gone, the supervisor suite now hits deterministic production helpers directly, and `just verify-core` proves the slice on the repo-safe temp/cache path |
| #35 | TESTING-03: IPC + heartbeat integration | HIGH | FIXED — live Postgres suite now proves worker heartbeat truth, `/api/team/status` active-thread visibility, real cancel semantics, and eventual active-thread clearing |
| #36 | TESTING-04: MCP E2E integration | HIGH | FIXED — live MCP stdio suite now launches the real server, lists tools, starts a real thread, and queries live thread state through the gateway |

### New Tasks From Orchestration Durability Review

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #67 | REPAIR-VERIFY-01: Add live recovery tests for pre-existing running/input_required/cancelling threads across restart | HIGH | FIXED — live Postgres suites now prove durable `input_required` restart recovery plus deterministic restart classification for pre-existing `running` (`reconciling/needs_reconciliation`) and `cancelling` (`cancelling/cancel_pending`) threads |
| #68 | REPAIR-PROJ-01: Expand checkpoint projection beyond `channel_values` into interrupt/control-aware repair projection | HIGH | FIXED — gateway now projects checkpoint parent/source/step metadata, updated channels, pending-write channels/count, bounded history depth, and persisted interrupts; the remaining `tasks/next` gap is closed by the worker-owned `execution_state_projection` path and live Postgres restart verification |
| #69 | REPAIR-STATE-01: Remove or formally redefine orphaned `created` lifecycle state across DB, API, tests, and docs | MED | FIXED — runtime enum/transition support removed, snapshot/CLI/schema references cleaned up, and migration `0003` rewrites legacy `threads.status='created'` rows to `submitted` |
| #70 | REPAIR-APPROVAL-01: Replace `plan_approved` boolean with durable approval-state/request linkage | HIGH | FIXED — thread-level approval state, stable request identity, DB/API surfaces, supervisor runtime routing, and live Postgres restart verification now all pass; duplicate approval responses remain idempotent across gateway restart |
| #71 | AUDIT-LOOP-01: Re-run code review after each implementation slice and sync findings back into audit queue/docs | HIGH | Pending |

### New Tasks For Phased Postgres Production Path

| ID | Subject | Severity | Status |
|----|---------|----------|--------|
| #72 | PG-ARCH-01: Introduce database/checkpointer backend abstraction and SQLite hardening for phased Postgres rollout | HIGH | FIXED — backend-selectable DB/checkpointer factories shipped, the repo keeps SQLite as fallback-only, and health now exposes explicit `sqlite_fallback` diagnostics (real file existence + WAL visibility + non-certifying limitations) instead of implying correctness from backend names alone |
| #73 | PG-ARCH-02: Add Postgres-backed app DB + checkpoint factories, startup fail-fast, readiness, and dependency diagnostics | HIGH | FIXED — prod-like Docker now boots on Postgres with explicit backend/checkpoint settings, `VAULTSPEC_POSTGRES_REQUIRED=true`, direct runtime startup, stable Alembic config resolution from `settings.project_root`, corrected Jaeger v2 health probes, and successful `/api/health` + real thread create/state verification |
| #74 | PG-VERIFY-01: Add prod-like Docker/Postgres verification matrix and staged CI targets | HIGH | FIXED — prod-like Docker/Postgres verification now has a shared repo-owned CLI verifier (`uv run vaultspec test prodlike-docker`), local entry points (`just verify-prodlike-docker`, `just verify-claude-docker`, `just verify-gemini-docker`), and a GitHub Actions PR gate/workflow target in `.github/workflows/prodlike-docker.yml` |
| #75 | PLAN-REWRITE-01: Rewrite the backend production-readiness execution plan around open repair, test, Docker, and Postgres tracks | MED | FIXED — the active execution plan now reflects the actual remaining queue after repair, live verification, and Postgres/Docker closeout; only the still-open tracks remain in scope |
| #76 | PG-VERIFY-02: Make live crash-recovery restart-state verification deterministic instead of warning-based | MED | FIXED — `/health` now exposes latched restart metadata and owned worker PID; live suite kills the exact worker process and asserts hard-fail restart recovery semantics |
| #77 | LIVE-PROVIDER-01: Wire live provider credential readiness for production-certifying Postgres recovery suites | HIGH | FIXED — provider readiness is now certifying-provider aware via `src/vaultspec_a2a/providers/probes/certifying.py`; `just verify-live-provider-certifying` passes in this environment and selects a healthy real provider (`claude`) for the live Postgres recovery path |
| #78 | LIVE-APPROVAL-01: Fix the live Postgres approval path that remains durably `submitted` with no progress or interrupt evidence | HIGH | FIXED — interrupt outcome classification now derives from durable checkpoint state, the gateway preserves `tool_call` and `plan_approval_request` pause cause, and the live Postgres paused-thread restart test passes |
| #79 | REPAIR-SNAPSHOT-01: Prove explicit degraded snapshot behavior when the checkpoint backend is unavailable | HIGH | FIXED — a live two-Postgres test now kills only the checkpoint backend and verifies that `/api/threads/{id}/state` returns explicit degradation while preserving durable paused-thread truth from the app DB |
| #80 | REPLAY-VERIFY-02: Add live WebSocket reconnect/replay verification for actual disconnect and resubscribe behavior | HIGH | FIXED — a live Postgres `/ws` suite now proves snapshot-based reconnect recovery using a real WebSocket client and confirms there is no implicit replay of already-accounted-for thread events |
| #81 | TEST-STUB-02: remove remaining core fake-model/model-double usage in node and worker suites | CRIT | FIXED — the targeted core suites now validate deterministic supervisor/worker behavior through production helpers and real model types; `verify-core` and the real ACP worker integration suite both pass |
| #82 | SKIP-CLI-01: remove stale-PID `pytest.skip()` usage from CLI service tests | MED | FIXED — stale-PID tests now use a real exited child-process PID instead of a hard-coded PID plus skip |
| #83 | TEST-RUNNER-03: pytest tmp-path cleanup fails for CLI service module in current Windows environment | MED | FIXED — CLI service tests now use a repo-local runtime-dir fixture instead of pytest temp-root paths, and the stale-PID setup was corrected to use a dynamically discovered non-running PID |
| #84 | REPAIR-PROJ-02: Add a worker-owned higher-fidelity execution-state projection path for truthful `tasks/next` repair reconstruction | HIGH | FIXED — worker-owned `graph.aget_state(...)` inspection emits normalized `execution_state_projection` events, the gateway persists a latest-row `thread_execution_state` model, reconnect snapshots expose normalized `next_nodes` / task truth, degraded-only updates preserve the last good durable payload, and live Postgres paused-thread restart verification now passes. Sequential live-test contamination was fixed by isolating each test to a fresh logical Postgres database. |
| #85 | PROV-DOCKER-01: Add supported Gemini CLI provisioning path for the Docker worker image if Gemini is meant to be Docker-supported | HIGH | FIXED — worker image now installs pinned `@google/gemini-cli@0.3.3`; real worker-image build and in-container `--help` smoke passed against the package `dist/index.js` entrypoint |
| #86 | PROV-DOCKER-02: Add explicit supported Docker auth-material path and certifying verification for Claude/Gemini ACP providers | HIGH | PARTIAL — explicit provider-auth overlay, CLI verifier, `COMPOSE_DISABLE_ENV_FILE=1` hardening, and `#89` Phase 1 runtime-authority evidence are in place; a real Docker-backed Claude certification run on March 11, 2026 reached ACP `initialize` + `session/new` and then failed at `session/prompt` with provider error `Internal error: You've hit your limit · resets Mar 13, 4am (UTC)` in `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z`, so the Claude path is now narrowed to provider quota/account state rather than packaging or Docker runtime breakage. Gemini is fixed and verified on the Docker OAuth-backed path: aligning subprocess/container `HOME` with the mounted `GEMINI_CLI_HOME` restored `security.auth.selectedType=oauth-personal` inside the worker-owned Gemini CLI process, and `uv run vaultspec test prodlike-provider gemini` passed on March 11, 2026 with the success bundle at `.vault/runtime/verify-prodlike-docker/20260311T230801Z`. On March 12, 2026, the verifier path was further hardened so the Docker Gemini cert now runs from `/tmp`, mounts an auth-only temp-backed Gemini CLI home, no longer inherits workspace/user MCP noise, and still passes with the clean bundle at `.vault/runtime/verify-prodlike-docker/20260312T084628Z`. `#86` therefore remains partial only because Claude is still provider-quota blocked, and it is explicitly pending pickup on Friday, March 13, 2026 for the post-reset Claude rerun |
| #87 | PG-VERIFY-03: Prod-like Docker CLI verifier can still fail with gateway readiness timeout and too-thin startup diagnostics | HIGH | FIXED AND VERIFIED — the verifier evidence gap was fixed in `src/vaultspec_a2a/cli/_verify.py`, the gateway startup permission regression was fixed in `src/vaultspec_a2a/api/app.py`, and a fresh elevated `uv run vaultspec test prodlike-docker` rerun passed on March 11, 2026. The certifying success bundle at `.vaultspec/runtime/verify-prodlike-docker/20260311T154053Z` records healthy Postgres-backed status, `thread_id: b594e0ce071b4a36aa89e7911ea86fb9`, `readiness_probe_count: 3`, and `trace-manifest.json` reporting `vaultspec-a2a` `trace_count: 4` after the bounded verifier Jaeger query-contract fix |
| #88 | OBS-ARCH-01: Add formal log/trace correlation architecture and implementation for multi-service debugging | HIGH | IMPLEMENTATION COMPLETE FOR RUNTIME EMISSION AND VERIFIER CONSUMPTION — architecture is grounded by `docs/research/2026-03-11-observability-debug-correlation-grounding.md` and `docs/adrs/036-debug-evidence-surface.md`; `src/vaultspec_a2a/utils/logging.py` now injects automatic `trace_id` / `span_id` / `trace_sampled` / `service_name` correlation via a shared filter, the top-priority service-path logs in `src/vaultspec_a2a/api/endpoints.py`, `src/vaultspec_a2a/api/websocket.py`, and `src/vaultspec_a2a/worker/ipc.py` now carry bounded runtime-owned fields such as `thread_id`, `dispatch_id`, `request_id`, `client_id`, and `worker_id`, the same model was extended into `src/vaultspec_a2a/api/internal.py` and `src/vaultspec_a2a/worker/executor.py`, and the verifier in `src/vaultspec_a2a/cli/_verify.py` now consumes that model via correlation-aware evidence manifests; the baseline prod-like Docker verifier is now recertified via `.vaultspec/runtime/verify-prodlike-docker/20260311T154053Z`, while ACP/runtime evidence hardening remains under `#89` |
| #89 | ACP-ARCH-01: Add ADR-backed authority model for local ACP vs Dockerized provider runtime and observability boundaries | HIGH | PHASE 1 COMPLETE WITH FOLLOW-ON AUTH-EVIDENCE HARDENING — `docs/research/2026-03-11-observability-debug-correlation-grounding.md` and `docs/adrs/037-acp-runtime-authority.md` are now backed by a bounded implementation in `src/vaultspec_a2a/providers/factory.py`, `src/vaultspec_a2a/providers/_subprocess.py`, and `src/vaultspec_a2a/providers/acp_chat_model.py`: worker-owned ACP evidence now classifies runtime authority (`project_local`, `docker_bundled`, `package_bin`, `system_cli`, `explicit_executable` where applicable), emits bounded command provenance and auth-mode metadata, records subprocess spawn/termination lifecycle evidence, adds narrow initialize/session handshake context, and now also captures browser-auth handoff URLs from Gemini ACP stderr so timeout / early-exit auth failures no longer collapse into generic low-context errors. Focused auth-wait coverage in `src/vaultspec_a2a/providers/tests/test_acp_chat_model.py` passes, and a fresh host-local `uv run python -m vaultspec_a2a.providers.probes.gemini` rerun on March 12, 2026 still passed through `initialize`, `session/new`, and `session/prompt`. `AcpAuthError` now carries bounded machine-readable auth outcome classification (`watchdog_expired`, `operator_cancelled`, `auth_rejected`, `subprocess_exited_before_auth`, with `auth_failed` fallback), and `ruff` passed on the touched auth files; the remaining follow-up under `#89` is now limited to focused async verification once the host-level Windows interpreter failure importing `asyncio` (`OSError: [WinError 10106] ... _overlapped`) is cleared, while live Docker provider certification remains under `#86` |
