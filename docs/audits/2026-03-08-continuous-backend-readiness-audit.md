# Continuous Backend Readiness Audit

Date: 2026-03-08
Scope: backend implementation, LangGraph service management, worker robustness, process handling, Docker deployment, service separation, production readiness, frontend/backend decoupling
Method: iterative code audit with findings appended as they are confirmed

## Findings

### 2026-03-09 10:55 - High - Deterministic crash-recovery verification exposed a real watchdog bug in the `pending` state; fixed in the same slice

- Tightening the live Postgres crash-recovery suite to kill the exact gateway-owned worker PID exposed a real state-machine defect in the gateway watchdog.
- If the auto-spawned worker died before the watchdog ever promoted `worker_status` from `pending` to `up`, the watchdog loop continued forever in `pending` instead of falling through to crash detection and restart.
- The same slice fixed that bug and replaced the warning-based restart observation with a deterministic latched restart record exposed on `/health`.

Impact:

- Before the fix, an early worker crash could leave the gateway stuck in a non-recovering `pending` state even though auto-restart was expected.
- The original warning-based test was masking that defect by racing a transient status instead of proving a durable repair signal.
- After the fix, live Postgres verification hard-fails on real restart regressions and confirms both PID rotation and latched restart metadata.

Evidence:

- `src/vaultspec_a2a/api/app.py`: `WorkerWatchdog.run()` previously continued unconditionally while `worker_status == "pending"`, even when the worker had already crashed.
- `src/vaultspec_a2a/api/app.py`: `/health` now exposes `worker_pid`, `worker_restart_count`, `worker_last_restart_reason`, timestamps, success, and attempt metadata.
- `src/vaultspec_a2a/tests/test_crash_recovery.py`: the live suite now kills the exact owned worker PID and asserts the latched restart record instead of warning on a missed transient `restarting` window.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/tests/test_crash_recovery.py`
  - `uv run pytest src/vaultspec_a2a/tests/test_crash_recovery.py -m live -q`
  - `uv run pytest src/vaultspec_a2a/database/tests/test_database.py src/vaultspec_a2a/database/tests/test_migrations.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/tests/test_internal.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py -q`
  - results: `4 passed` and `154 passed`

Resolution:

- Fixed in the same slice; no residual task remains under the original warning-based verification gap.

### 2026-03-08 10:40 - Critical - Docker readiness is wired to an internal liveness stub, not real service readiness

- `docker-compose.prod.yml` marks the gateway healthy by probing `/internal/health`, which always returns `{"status": "ok"}` if the HTTP process is up.
- That endpoint does not check the database, worker connectivity, heartbeat freshness, or circuit-breaker state.
- The real aggregated readiness logic lives on `/api/health`, which can return `degraded` when the worker or database is unavailable.

Impact:

- Production orchestration can treat the gateway as healthy while the backend is not actually ready to serve frontend write paths.
- Rolling deploys and restart automation can converge on a broken-but-green state.

Evidence:

- `docker-compose.prod.yml`: gateway healthcheck uses `http://localhost:8000/internal/health`
- `src/vaultspec_a2a/api/internal.py`: `internal_health()` always returns ok
- `src/vaultspec_a2a/api/endpoints.py`: `/api/health` performs the real gateway/database/worker aggregation

Recommendation:

- Point Docker readiness to `/api/health` and fail readiness on degraded worker/database state for production deployments, or split explicit liveness vs readiness endpoints with materially different semantics.

### 2026-03-08 10:44 - High - Top-level gateway health reports `status=ok` even when the worker is down

- The public `/health` endpoint always returns `"status": "ok"` and only exposes worker failure as auxiliary fields like `worker_connected`, `worker_status`, and `circuit_breaker`.
- This diverges from `/api/health`, which can return `"degraded"`.

Impact:

- External probes, load balancers, and operators can easily choose the wrong endpoint and conclude the service is healthy when dispatch capacity is unavailable.
- Frontend-facing uptime can look good while write-path actions are effectively broken.

Evidence:

- `src/vaultspec_a2a/api/app.py`: `health_endpoint()` hardcodes `"status": "ok"`
- `src/vaultspec_a2a/api/endpoints.py`: `/api/health` computes `ok` vs `degraded`

Recommendation:

- Either make `/health` reflect dispatch readiness or rename/document it as a pure liveness endpoint and stop using it as a readiness signal.

### 2026-03-08 10:47 - High - Production compose does not configure `VAULTSPEC_INTERNAL_TOKEN`

- Internal worker-to-gateway IPC auth is mandatory outside development in code, but the production compose file does not supply `VAULTSPEC_INTERNAL_TOKEN` to either service.
- In non-development environments, internal requests should fail with a configuration error if the token is missing.

Impact:

- A real production environment using `VAULTSPEC_ENVIRONMENT=production` will fail internal IPC unless deployers independently inject the token.
- If environment is left as development to make the stack boot, internal IPC runs without auth, which is not production-safe.

Evidence:

- `src/vaultspec_a2a/api/internal.py`: `_verify_internal_token()` requires token outside development
- `src/vaultspec_a2a/core/config.py`: `environment` defaults to development; `internal_token` defaults to none
- `docker-compose.prod.yml`: no `VAULTSPEC_INTERNAL_TOKEN` and no explicit production environment setting

Recommendation:

- Set `VAULTSPEC_ENVIRONMENT=production` explicitly in prod compose/deployment manifests and require `VAULTSPEC_INTERNAL_TOKEN` for both gateway and worker.

### 2026-03-08 10:51 - Medium - Worker standalone entry point ignores configured bind host

- The CLI and settings model support `VAULTSPEC_WORKER_HOST`, but `vaultspec_a2a.worker.app.main()` hardcodes `host="127.0.0.1"`.

Impact:

- Running the worker through the console script behaves differently from CLI-managed or Docker-managed execution.
- This creates environment-specific surprises when operators expect settings parity across entry points.

Evidence:

- `src/vaultspec_a2a/core/config.py`: `worker_host` exists
- `src/vaultspec_a2a/worker/app.py`: `main()` hardcodes `127.0.0.1`

Recommendation:

- Use `settings.worker_host` in the worker console entry point.

### 2026-03-08 10:55 - Medium - Watchdog promotes worker status to `up` before proving worker health

- In the watchdog loop, once the spawner is marked `spawned`, the status transitions from `pending` to `up` before checking heartbeat freshness or a direct worker health probe.
- A just-spawned or externally-started worker can therefore be reported as `up` before it has actually become responsive.

Impact:

- Health/status surfaces can briefly overstate readiness.
- Frontend and operator tooling can see an optimistic worker state during startup or recovery windows.

Evidence:

- `src/vaultspec_a2a/api/app.py`: `WorkerWatchdog.run()` sets `worker_status = "up"` immediately when `worker_status == "pending"` and `spawner.spawned` is true

Recommendation:

- Gate the `pending -> up` transition on a successful worker `/health` check or a fresh heartbeat.

### 2026-03-08 11:02 - High - Production container topology does not support workspace-bound thread metadata

- The create-thread path validates `metadata.workspace_root`, auto-discovers `.vault` context files, loads workspace-local team config overrides, and builds an initial vault index directly on the gateway filesystem.
- The worker then receives the same `workspace_root` path for later graph compilation and mount-node behavior.
- The production Docker topology mounts only `/app/data`; it does not mount any workspace root into either gateway or worker containers.

Impact:

- A production-style deployment cannot reliably support requests that depend on real workspace paths, which are central to the product’s coding workflow.
- This is a direct frontend/backend decoupling gap: API requests are coupled to server-local filesystem state that the deployment model does not provide.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `_process_metadata()`, `discover_context_refs()`, `load_team_config(...)`, `build_initial_vault_index(...)`
- `docker-compose.prod.yml`: only `db-data:/app/data` is mounted for gateway and worker

Recommendation:

- Either define a real workspace-volume contract for deployed stacks or move workspace-bound context discovery behind an explicit backend storage/sync layer instead of raw host paths.

### 2026-03-08 11:06 - Medium - Local service manager state is anchored to the caller's current working directory

- CLI-managed service state is written under `Path.cwd() / ".vaultspec" / "runtime"`.
- Running `vaultspec service ...` from the repo root vs a subdirectory creates different registries and log locations.

Impact:

- Operators can accidentally start or inspect services from different directories and see inconsistent status, stale PID records, or apparently "missing" tracked services.
- This makes process management less reliable than it appears, especially for IDE terminals opened in nested folders.

Evidence:

- `src/vaultspec_a2a/cli/_service.py`: `_runtime_dir()` uses `Path.cwd()`

Recommendation:

- Anchor runtime state to a stable repo root or app-state directory rather than the transient shell working directory.

### 2026-03-08 11:10 - Medium - The gateway still owns expensive workspace introspection on the write path

- On thread creation, the gateway performs filesystem validation, context discovery, preset resolution, nickname generation inputs, and vault index construction before dispatching to the worker.
- This means the control surface is not a thin API/gateway layer; it still contains substantial workspace-aware orchestration behavior.

Impact:

- Frontend write latency and failure modes remain coupled to local filesystem state on the gateway.
- Service separation is only partial: some of the most environment-sensitive logic still lives in the frontend-facing process.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `create_thread_endpoint()` and `_process_metadata()`

Recommendation:

- Push workspace-derived enrichment into the worker or a dedicated backend service boundary so the gateway can remain transport-focused and easier to harden.

### 2026-03-08 11:18 - Critical - Public API authentication is still a no-op stub

- The public API auth module explicitly does nothing and is not wired to enforce request authentication.
- The test suite currently asserts that even a request carrying an invalid bearer token must not raise.

Impact:

- The backend is not production-grade from an access-control perspective.
- Any deployment exposed beyond a trusted local environment lacks a meaningful protection layer on public routes.

Evidence:

- `src/vaultspec_a2a/api/auth.py`: `authenticate_request()` is a documented no-op stub
- `src/vaultspec_a2a/api/tests/test_auth.py`: tests assert the no-op behavior
- Search across `src/vaultspec_a2a/api`: no route dependencies are using `authenticate_request`

Recommendation:

- Implement and wire real public-route authentication before treating the backend as production-ready outside a strictly local/trusted topology.

### 2026-03-08 11:20 - Medium - Crash-recovery coverage exists but is not part of the default verification path

- The repo includes dedicated crash-recovery tests for watchdog restart behavior, but a direct targeted run selected zero tests in the current default invocation path because they are marked out of the standard subset.
- This means one of the most critical robustness areas is not part of the fast frontend/backend verification loop.

Impact:

- Regressions in worker restart, heartbeat recovery, and circuit-breaker coordination can slip past the recommended verification workflow.

Evidence:

- `src/vaultspec_a2a/tests/test_crash_recovery.py`: crash-recovery suite exists
- targeted `pytest src/vaultspec_a2a/tests/test_crash_recovery.py` selected 0 tests in this environment

Recommendation:

- Add a dedicated robust-backend verification target that explicitly includes crash-recovery scenarios, or document the exact marker needed so these tests are not silently skipped.

### 2026-03-08 11:25 - Medium - Internal dispatch contract accepts unknown actions and still returns `dispatched`

- `DispatchRequest.action` is an unconstrained string rather than an enum or literal union.
- The worker `/dispatch` endpoint schedules the task and immediately returns `{"status": "dispatched"}`.
- Unknown actions are only handled later inside `Executor.handle_dispatch()`, where they are logged as warnings rather than rejected at the boundary.

Impact:

- Malformed internal traffic is accepted as success, making integration bugs harder to detect.
- Operator-facing behavior can look successful while the worker silently drops the requested operation.

Evidence:

- `src/vaultspec_a2a/api/schemas/internal.py`: `DispatchRequest.action: str`
- `src/vaultspec_a2a/worker/app.py`: `/dispatch` returns success before executor outcome is known
- `src/vaultspec_a2a/worker/executor.py`: unknown actions only log `"Unknown dispatch action"`

Recommendation:

- Constrain `action` to the supported dispatch verbs at schema validation time and reject invalid requests with `4xx` responses.

### 2026-03-08 11:33 - High - Worker shutdown ordering can tear down bridge/executor before in-flight dispatch tasks are cancelled

- The worker stores dispatch tasks inside the lifespan task group via `tg.start_soon(executor.handle_dispatch, req)`.
- On shutdown, the lifespan code calls `await executor.shutdown()` and `await bridge.close()` before cancelling the task group.
- That ordering means in-flight dispatch tasks may still be running while the executor clears internal state and the bridge closes its HTTP client.

Impact:

- Shutdown can race with active graph execution, causing dropped terminal events, partial cleanup, or noisy shutdown failures.
- This is especially risky for process restarts and container stop events, where graceful completion ordering matters.

Evidence:

- `src/vaultspec_a2a/worker/app.py`: shutdown sequence runs `executor.shutdown()`, then `bridge.close()`, then `tg.cancel_scope.cancel()`
- `src/vaultspec_a2a/worker/app.py`: dispatches are launched into that same `TaskGroup`

Recommendation:

- Cancel and drain the task group before tearing down executor/bridge resources, or track dispatch tasks separately and await a graceful stop boundary explicitly.

### 2026-03-08 11:37 - Medium - Cancel endpoint marks threads cancelled on dispatch acceptance, not on actual cancellation

- `POST /threads/{thread_id}/cancel` updates the database status to `cancelled` immediately after the worker accepts the cancel dispatch.
- The worker `/dispatch` response only means the cancel request was queued, not that the graph has actually stopped.

Impact:

- Thread state can be optimistic and temporarily false.
- Frontend and operators may see a thread as cancelled even while work is still executing or if the cancel path later fails inside the worker.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `cancel_thread_endpoint()` sets `ThreadStatus.CANCELLED` when `/dispatch` returns success
- `src/vaultspec_a2a/worker/app.py`: `/dispatch` is fire-and-forget and returns immediately after `tg.start_soon(...)`

Recommendation:

- Treat cancel dispatch as `accepted` and move the terminal DB transition to the worker-driven terminal event path, or introduce an intermediate `cancelling` state.

### 2026-03-08 11:40 - Low - Crash-recovery tests are live-gated rather than accidentally missing

- The crash-recovery suite is marked `@pytest.mark.live`, which is why the earlier targeted run selected zero tests under the default marker configuration.

Impact:

- The gap is real, but the cause is policy: watchdog recovery coverage is excluded from the normal fast verification path.

Evidence:

- `src/vaultspec_a2a/tests/test_crash_recovery.py`: module-level `pytestmark = pytest.mark.live`

Recommendation:

- Keep the suite live-gated if runtime cost requires it, but add a documented readiness target that explicitly includes these tests for backend hardening checks.

### 2026-03-08 11:46 - Medium - Frontend/backend deployment decoupling is incomplete because the production gateway still embeds and serves the UI

- The production Docker image builds the React frontend and copies the static assets into the gateway image.
- The gateway mounts `StaticFiles` and serves the SPA itself in production mode.
- The dev stack is separated at runtime with a standalone Vite service, but the production packaging model remains coupled.

Impact:

- Backend deploys are still tied to frontend asset packaging and release cadence.
- Independent frontend hosting, CDN rollout, or split failure domains are harder than they would be with a fully decoupled production topology.

Evidence:

- `docker/prod.Dockerfile`: frontend build stage copied into the `gateway` image
- `src/vaultspec_a2a/api/app.py`: gateway mounts the built UI via `StaticFiles`

Recommendation:

- Decide explicitly whether production should remain a single deployable unit or move to a true split deployment model with the frontend hosted independently.

### 2026-03-08 11:55 - Medium - WebSocket delivery is intentionally lossy under slow-client backpressure

- Each subscribed client has a bounded queue, and the relay applies a drop-oldest policy when that queue fills.
- The gateway logs the drop, but the client receives no explicit gap/error signal at the time of loss.

Impact:

- Slow or temporarily stalled frontend clients can miss intermediate events silently.
- This is only safe if reconnect snapshots are consistently complete and timely; otherwise the UI can observe discontinuities it cannot fully reconstruct.

Evidence:

- `src/vaultspec_a2a/api/websocket.py`: `broadcast_to_thread()` drops oldest queued events when the queue is full
- `src/vaultspec_a2a/core/aggregator.py`: subscriber queues are bounded to 512

Recommendation:

- Either surface an explicit overflow/gap event to clients or guarantee a stronger snapshot/replay recovery path for missed events.

### 2026-03-08 11:58 - Medium - Thread state snapshot can silently degrade to a partial view on checkpoint timeout or read failure

- `GET /api/threads/{thread_id}/state` attempts to enrich thread state from the shared LangGraph checkpoint store, but on timeout or any exception it logs a warning and returns a basic partial snapshot.
- The response shape does not explicitly tell the client that enrichment failed.

Impact:

- Reconnecting frontends can receive an incomplete recovery payload without knowing it is incomplete.
- Combined with lossy WebSocket backpressure, this weakens the exactness of the frontend’s state reconstruction story.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` wraps `checkpointer.aget_tuple(...)` in a 10s timeout and falls back to a partial snapshot on failure

Recommendation:

- Mark snapshot completeness explicitly in the response, or fail with a recoverable degraded status instead of returning an indistinguishable partial success.

### 2026-03-08 19:06 - Medium - Internal worker-to-gateway event relay acknowledges malformed payloads as success

- The internal `/internal/events` endpoint returns `200 {"status":"ok"}` even when `thread_id` is missing, empty, or `payload` is missing/empty.
- In those malformed cases no meaningful client broadcast occurs, but the worker-facing contract still looks successful.

Impact:

- IPC observability is weakened because the worker cannot distinguish a successfully relayed event from a dropped malformed event.
- Production debugging gets harder: event loss caused by bad payload shaping can hide behind healthy-looking HTTP success metrics.

Evidence:

- `src/vaultspec_a2a/api/tests/test_internal.py`: malformed `/internal/events` cases assert `200 {"status":"ok"}`
- `src/vaultspec_a2a/api/internal.py`: relay path routes through `broadcast_to_thread()` when possible but keeps the resilient-ack behavior for malformed input

Recommendation:

- Return a 4xx for malformed internal relay payloads, or at minimum return an explicit `"accepted": false` / `"dropped": true` signal so the worker can log and count contract violations accurately.

### 2026-03-08 19:10 - Medium - Live gateway/worker readiness fixtures validate permissive liveness, not aggregate backend readiness

- The session-scoped integration fixtures wait for `{url}/health` to return `200`, and the live smoke tests also assert the top-level gateway `/health`.
- The top-level gateway `/health` always reports `"status": "ok"` while the stricter aggregate readiness logic lives at `/api/health`.

Impact:

- A backend stack can satisfy the default live startup and smoke gates even while the worker or aggregate dependency state is degraded.
- This reduces confidence that the “production-grade backend” checks are actually exercising the readiness contract the frontend depends on.

Evidence:

- `src/vaultspec_a2a/tests/conftest.py`: `_wait_for_health()` polls `{url}/health`
- `src/vaultspec_a2a/tests/test_smoke.py`: smoke tests assert the top-level gateway `/health`
- `src/vaultspec_a2a/api/app.py`: `/health` returns `"status": "ok"`
- `src/vaultspec_a2a/api/endpoints.py`: `/api/health` computes gateway/database/worker aggregate status

Recommendation:

- Move integration fixture readiness and smoke assertions to `/api/health` for the gateway, keeping `/health` as a shallow liveness probe only.

### 2026-03-08 19:21 - High - Checkpoint backfill masks real SQLite operational failures as a benign “fresh database” case

- The gateway startup path always runs `backfill_teamstate_sdd_fields(db_path)` after migrations.
- That helper catches any `sqlite3.OperationalError` from `SELECT rowid, channel_values FROM checkpoints` and returns `0`, assuming the checkpoint table simply does not exist yet.
- `sqlite3.OperationalError` also covers other cases such as locking and malformed schema/state, so real startup data issues can be silently ignored.

Impact:

- Production startup can proceed with partially upgraded or unreadable checkpoint data while logs imply nothing needed patching.
- Operators lose an early signal that the shared SQLite/checkpointer store is unhealthy or inconsistent.

Evidence:

- `src/vaultspec_a2a/api/app.py`: gateway lifespan calls `backfill_teamstate_sdd_fields(db_path)` on startup
- `src/vaultspec_a2a/database/migrations/__init__.py`: catches broad `sqlite3.OperationalError` around the checkpoint table read and returns `0`

Recommendation:

- Distinguish “table does not exist” from other SQLite operational failures, and surface the latter loudly via startup failure or at least error-level logging.

### 2026-03-08 19:25 - Medium - Worker-to-gateway event delivery is only memory-durable and degrades into oldest-event loss under sustained relay failure

- The worker bridge batches events in an in-memory list, retries failed flushes three times, then re-queues the batch back into the same bounded in-memory buffer.
- When the buffer reaches its cap, the oldest buffered events are dropped.
- There is no disk-backed spool, no per-batch acknowledgement tracking beyond HTTP 200, and no replay source if the worker process exits while the gateway is unavailable.

Impact:

- A prolonged gateway outage or malformed-but-200 relay path can cause irreversible loss of worker events, especially intermediate status and artifact updates.
- This weakens frontend/backend decoupling because the UI depends on a relay path that is resilient but not durable.

Evidence:

- `src/vaultspec_a2a/worker/ipc.py`: `_MAX_EVENT_BUFFER = 10_000`, retry loop, and drop-oldest behavior after re-queue pressure
- `src/vaultspec_a2a/worker/tests/test_ipc.py`: validates warning-and-swallow behavior for non-200 and connection-failure relay cases
- `src/vaultspec_a2a/api/schemas/rest.py`: REST layer positions some operations as retryable/guaranteed-delivery, underscoring that the event relay path is a different, weaker contract

Recommendation:

- Decide whether worker event relay is best-effort or part of the production correctness contract. If it is correctness-critical, add a durable spool or a replayable event store keyed by sequence/batch id.

### 2026-03-08 22:03 - High - The advertised WebSocket replay contract is not durable across thread completion or gateway restart

- `ThreadStateSnapshot.last_sequence` is documented as the boundary clients use to discard already-seen WebSocket events after reconnect.
- In practice, sequence counters live only in the gateway aggregator's in-memory `_sequences` map.
- Those counters are explicitly pruned when an ingest finishes and again when terminal events are processed, and they are also lost whenever the gateway process restarts.

Impact:

- Reconnecting clients cannot reliably use `last_sequence` for gap detection after a thread has gone inactive or after a gateway restart.
- The frontend-facing replay contract is therefore only conditionally true during the lifetime of a single gateway process and an actively executing thread.

Evidence:

- `src/vaultspec_a2a/api/schemas/snapshots.py`: snapshot docs say clients discard any WebSocket events with `sequence <= last_sequence`
- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` sources `last_sequence` from `aggregator.get_sequence(thread_id)`
- `src/vaultspec_a2a/worker/executor.py`: `_mark_ingest_done()` prunes sequence counters for inactive threads
- `src/vaultspec_a2a/api/internal.py`: `_handle_terminal_event()` prunes the terminal thread's sequence counter
- `src/vaultspec_a2a/api/app.py`: the gateway recreates a fresh `EventAggregator` on startup

Recommendation:

- If sequence-based replay is part of the frontend contract, persist per-thread replay cursors outside the in-memory aggregator and stop pruning them solely because execution has gone idle.

### 2026-03-08 22:07 - High - Thread state snapshots are only partially durable because agent state and pending permissions come from gateway memory, not checkpoint state

- Messages, plan, artifacts, and checkpoint_id are recovered from the LangGraph checkpoint store.
- Agent snapshots and pending permission requests are populated only from the gateway's in-memory aggregator state.
- The gateway creates a fresh aggregator on startup, and those in-memory structures are not reconstructed from the checkpoint or database on reconnect.

Impact:

- After a gateway restart, `GET /api/threads/{id}/state` can return durable checkpoint content but silently lose agent lifecycle state and outstanding permission requests.
- The endpoint is described as a "complete thread state snapshot", but completeness currently depends on the gateway never losing its live aggregator memory.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `_enrich_snapshot_from_state()` builds `agents` from `aggregator.get_node_summaries()` / `get_agent_states()` and `pending_permissions` from `aggregator.get_pending_permissions(thread_id)`
- `src/vaultspec_a2a/api/app.py`: gateway lifespan creates a new `EventAggregator()` each startup
- `src/vaultspec_a2a/protocols/mcp/server.py`: even the MCP surface documents that checkpoint-derived thread status can lag and some fields may be empty until checkpoint write time

Recommendation:

- Either narrow the documented contract to say these fields are best-effort/live-memory only, or persist/reconstruct them from durable state so the snapshot is genuinely complete after reconnects and restarts.

### 2026-03-08 22:11 - Medium - Invalid WebSocket client commands are silently dropped instead of surfacing an explicit protocol error

- Unknown or malformed client commands are logged server-side, but the WebSocket connection stays open and the client receives no error frame.
- The current tests explicitly treat this as the intended behavior.

Impact:

- Frontend protocol bugs are harder to diagnose because the server fails closed without a structured response.
- Client implementations can appear to "do nothing" instead of receiving actionable protocol feedback.

Evidence:

- `src/vaultspec_a2a/api/websocket.py`: `_handle_client_message()` catches `ValidationError`, logs a warning, and returns without sending an error event
- `src/vaultspec_a2a/api/tests/test_websocket.py`: `test_invalid_command_does_not_crash` asserts silent discard behavior

Recommendation:

- Return a recoverable WebSocket `error` event for invalid commands so frontend developers get explicit protocol feedback without crashing the connection.

### 2026-03-08 22:14 - Medium - The live self-healing test layer does not cover frontend-facing reconnect/replay semantics

- Crash-recovery live tests verify worker restart, worker_status transitions, and basic post-recovery REST dispatch.
- They do not verify that a frontend client can reconnect via WebSocket, fetch a state snapshot, and recover a coherent live view across worker or gateway disruption.

Impact:

- The stack's self-healing claims are only partially validated from a frontend integration perspective.
- Production-grade orchestration may still regress on the exact reconnect/replay path the UI depends on while passing the current live recovery suite.

Evidence:

- `src/vaultspec_a2a/tests/test_crash_recovery.py`: exercises REST health/readiness and dispatch after worker restart, but not WebSocket reconnect or snapshot replay
- `src/vaultspec_a2a/api/tests/test_websocket.py`: covers local WebSocket mechanics only, not restart/reconnect recovery against the live stack

Recommendation:

- Add a live integration scenario that spans: subscribe -> worker/gateway disruption -> REST snapshot fetch -> WebSocket resubscribe -> verification of coherent resumed state and explicit gap behavior.

### 2026-03-08 22:26 - High - Agent metadata is cached globally, so one thread's graph registration can overwrite another thread's frontend-visible agent descriptors

- The gateway aggregator stores node metadata in a single `_node_metadata` map rather than scoping it by thread or graph cache key.
- Each new `graph_registered` event replaces that global map wholesale.
- Thread snapshots and team status then read agent summaries from that single shared cache.

Impact:

- In a multi-thread or multi-preset deployment, whichever graph compiled most recently can overwrite the role, display name, and description shown for other threads.
- Frontend state reconstruction is therefore vulnerable to cross-thread metadata contamination even when each thread's checkpointed execution state is otherwise correct.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: `register_graph()` resets `self._node_metadata = {}`
- `src/vaultspec_a2a/core/aggregator.py`: `sync_worker_event()` handles `graph_registered` by replacing the same global `_node_metadata` cache
- `src/vaultspec_a2a/core/aggregator.py`: `get_node_summaries()` returns that shared cache without any thread filter
- `src/vaultspec_a2a/api/endpoints.py`: `_enrich_snapshot_from_state()` and `team_status_endpoint()` consume `aggregator.get_node_summaries()` for frontend-facing agent data
- `src/vaultspec_a2a/worker/executor.py`: `_send_graph_registered()` emits metadata on each graph compilation

Recommendation:

- Scope node metadata by thread ID or by graph cache key and make snapshot/team-status enrichment read the metadata associated with the specific thread being queried.

### 2026-03-08 22:31 - High - Pending permission requests can disappear after five minutes even if the workflow is still legitimately waiting for approval

- The gateway/worker aggregator deletes permission requests older than five minutes based only on wall-clock age.
- That pruning runs whenever an ingest completes, regardless of whether the interrupted thread is still awaiting a valid human response.
- The checkpoint layer does not reconstruct those pending permissions after they are dropped from aggregator memory.

Impact:

- A frontend can lose the ability to discover and answer a still-live permission request simply because another ingest completed after the request aged past five minutes.
- This breaks the control-plane contract for long-running supervised workflows and undermines the claim of robust, production-grade human-in-the-loop orchestration.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: `prune_stale_permissions(max_age_seconds=300.0)` deletes requests solely by age
- `src/vaultspec_a2a/worker/executor.py`: `_mark_ingest_done()` calls `self._aggregator.prune_stale_permissions()` after every ingest
- `src/vaultspec_a2a/api/endpoints.py`: thread-state and team-status endpoints surface pending permissions only from `aggregator.get_pending_permissions(...)`

Recommendation:

- Treat pending permissions as durable workflow state until they are explicitly resolved or the thread reaches a terminal state; do not expire them purely on age in the control-surface contract.

### 2026-03-08 22:36 - High - Permission-response semantics are too permissive for a path documented as guaranteed delivery

- `POST /api/permissions/{request_id}/respond` does not require the referenced permission request to still exist in the pending set before dispatching a resume.
- The endpoint also does not validate that the submitted `option_id` was actually one of the options advertised for that permission request.
- A malformed request ID without a `thread_id:` prefix returns HTTP 200 with `accepted=false` instead of a hard client error, and the current tests encode that behavior.

Impact:

- The frontend or MCP caller can get a superficially successful HTTP response for malformed or stale permission identifiers without a strict protocol failure.
- Resume actions can be dispatched against a thread based only on the embedded thread ID, which weakens correctness for human approval flows and makes permission handling less production-safe than its documentation suggests.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `respond_to_permission_endpoint()` derives `thread_id` from `request_id`, dispatches based on that, and only consults `aggregator._pending_permissions` to special-case plan-approval payload shape
- `src/vaultspec_a2a/worker/executor.py`: `_handle_resume()` passes `Command(resume=req.option_id)` directly into the graph without endpoint-side option validation
- `src/vaultspec_a2a/api/tests/test_endpoints.py`: `test_responds_dispatches_resume_to_worker()` succeeds without first creating a matching pending permission request
- `src/vaultspec_a2a/api/tests/test_endpoints.py`: `test_responds_without_thread_id_returns_not_accepted()` asserts HTTP 200 plus `accepted=False` for malformed IDs

Recommendation:

- Require the permission request to exist, ensure the chosen option belongs to that request, and return a 4xx protocol error for malformed or stale request IDs instead of a soft 200/false response.

### 2026-03-08 22:46 - High - `active_threads` has inconsistent semantics across REST and WebSocket bootstrap, making frontend reconnect state unreliable

- The REST team-status endpoint defines `active_threads` from `aggregator.get_active_thread_ids()`, which actually returns thread IDs that currently have at least one browser subscriber.
- The initial WebSocket `ConnectedEvent` prefers `worker_active_threads` from worker heartbeats, but if no heartbeat has arrived yet it falls back to that same subscriber-derived list.
- The worker heartbeat set itself only tracks threads currently being ingested on the worker, not all non-terminal or user-actionable threads.

Impact:

- The same `active_threads` field can mean "threads with subscribers", "threads currently executing on the worker", or an empty fallback depending on timing.
- Frontend bootstrap and reconnect behavior cannot safely treat `active_threads` as a production-grade source of truth for resumable/live work.
- Threads waiting on human approval are especially vulnerable to disappearing from this bootstrap set even though they remain operationally important.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: `get_active_thread_ids()` unions subscriber subscriptions, not execution state
- `src/vaultspec_a2a/api/endpoints.py`: `team_status_endpoint()` returns that subscriber-derived list as `active_threads`
- `src/vaultspec_a2a/api/websocket.py`: `connect()` sources `ConnectedEvent.active_threads` from `worker_active_threads` if present, otherwise from `aggregator.get_active_thread_ids()`
- `src/vaultspec_a2a/worker/ipc.py`: the worker heartbeat reports only `_active_threads`
- `src/vaultspec_a2a/worker/executor.py`: `_mark_ingest_done()` untracks the thread from the bridge as soon as ingest ends

Recommendation:

- Define one explicit contract for `active_threads` and implement it consistently. If the frontend needs reconnect bootstrap for non-terminal workflows, source that from durable thread state rather than subscriber bookkeeping or transient worker execution tracking.

### 2026-03-08 23:02 - High - Thread `status` is not a coherent source of truth for live workflow state

- The database status enum is the only durable owner of `thread.status`, and all list/snapshot responses surface that durable field directly.
- Initial preset-backed execution leaves the thread in `submitted` even after successful worker dispatch.
- Follow-up `send_message` requests do promote the thread to `running`, so identical execution phases are represented differently depending on which API path started them.
- The documented `input_required` state is not part of the durable thread status enum at all; it exists only as an agent lifecycle enum and in MCP prose.

Impact:

- Frontend and MCP consumers cannot safely treat `status` as the authoritative workflow state.
- A newly started supervised thread may look merely `submitted` while it is actively executing or already waiting on a permission response.
- The production control surface is therefore mixing durable DB state with transient live-memory cues instead of exposing one reliable lifecycle contract.

Evidence:

- `src/vaultspec_a2a/database/crud.py`: `ThreadStatus` includes `submitted`, `created`, `running`, `completed`, `failed`, `cancelled`, `archived` but not `input_required`
- `src/vaultspec_a2a/api/endpoints.py`: `create_thread_endpoint()` creates threads as `ThreadStatus.SUBMITTED` and does not promote them after successful ingest dispatch
- `src/vaultspec_a2a/api/endpoints.py`: `send_message_endpoint()` does promote the thread to `ThreadStatus.RUNNING` after successful dispatch
- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` returns `status=thread.status` from the DB-backed thread record
- `src/vaultspec_a2a/protocols/mcp/server.py`: MCP docs and output formatting advertise `input_required` as a thread status even though the backend does not durably store that state

Recommendation:

- Decide which component owns thread lifecycle truth, then implement one durable status model for all entrypoints. If `input_required` is part of the public contract, persist it explicitly instead of inferring it from transient agent/permission memory.

### 2026-03-08 23:07 - Medium - `ThreadSummary.agent_state` is declared in the REST schema but never populated by the thread listing endpoint

- The thread-list response model includes an `agent_state` field.
- The actual list endpoint never sets it when constructing `ThreadSummary`.
- There is also no durable source wired into the listing path that could populate it after restart.

Impact:

- Frontend consumers can reasonably assume per-thread agent lifecycle is available in the list API, but in practice the field is always absent/null.
- This weakens list-view readiness because the schema advertises richer live state than the backend actually provides.

Evidence:

- `src/vaultspec_a2a/api/schemas/rest.py`: `ThreadSummary` declares `agent_state: AgentLifecycleState | None = None`
- `src/vaultspec_a2a/api/endpoints.py`: `list_threads_endpoint()` constructs `ThreadSummary(...)` without setting `agent_state`
- `src/vaultspec_a2a/api/endpoints.py`: agent lifecycle state is only consulted in snapshot/team-status paths via `aggregator.get_agent_states()`, not in list responses

Recommendation:

- Either remove `agent_state` from the list contract until it has a reliable source, or populate it from a clearly defined live/durable state owner and document its restart semantics.

### 2026-03-08 23:14 - Medium - Several Alembic-managed tables exist as if they are durable workflow truth, but the runtime and frontend-facing reads largely bypass them

- The relational schema includes `artifacts`, `permission_logs`, and `cost_tracking` tables with CRUD helpers and migrations.
- Runtime frontend-facing state replay reads artifacts from LangGraph checkpoint `channel_values`, not from the `artifacts` table.
- Pending permission state comes from the in-memory aggregator, not from `permission_logs`.
- The helper functions for artifact creation, permission logging, and cost recording appear to be exercised only by database tests, not by the live gateway/worker runtime.

Impact:

- The database schema suggests durable ownership for artifacts, permission audit history, and cost data, but the production control plane does not currently use those tables as its source of truth.
- This creates architectural ambiguity during incident recovery and backend hardening because operators cannot infer from the schema alone which data survives restart in a user-visible way.
- Frontend/backend decoupling is weaker because some seemingly durable data classes are effectively non-contractual at runtime.

Evidence:

- `src/vaultspec_a2a/database/models.py`: defines `ArtifactModel`, `PermissionLogModel`, and `CostTrackingModel`
- `src/vaultspec_a2a/database/crud.py`: provides `create_artifact()`, `append_permission_log()`, `append_cost_record()`, and corresponding read helpers
- `src/vaultspec_a2a/api/endpoints.py`: thread snapshot enrichment reads `artifacts` from checkpoint `channel_values` and `pending_permissions` from aggregator memory
- Repository-wide references show the artifact/permission/cost CRUD helpers are otherwise only used in database tests, not in the live API/worker flow

Recommendation:

- Either wire these tables into the runtime as real durable owners for their respective domains, or demote/remove them from the production architecture so the persistence model matches reality.

### 2026-03-08 23:23 - High - There is no startup or post-crash reconciliation sweep for stale `submitted`/`running` threads

- The gateway startup path initializes the database, checkpointer, worker client, spawner, and watchdog, but does not scan existing thread rows to reconcile stale lifecycle states.
- Thread status repair currently happens only opportunistically on immediate dispatch failures or later terminal events from the worker.
- If the gateway or worker crashes mid-flight and no terminal event is emitted afterward, the durable thread row can remain stuck in a pre-crash state indefinitely.

Impact:

- Frontend thread lists and snapshots can show stale `submitted` or `running` states long after the associated execution has been lost.
- Production operators have no automated repair path that reclassifies orphaned work or requeues it on startup.
- This weakens the system's self-healing story because crash recovery restores service availability but not necessarily workflow truth.

Evidence:

- `src/vaultspec_a2a/api/app.py`: gateway lifespan startup creates services and watchdog, but there is no reconciliation pass over persisted threads
- `src/vaultspec_a2a/api/endpoints.py`: status is only updated inline on successful follow-up dispatch (`RUNNING`) or immediate dispatch failure (`FAILED`)
- `src/vaultspec_a2a/api/internal.py`: terminal status updates depend on receiving a later `thread_terminal` event from the worker
- `src/vaultspec_a2a/tests/test_crash_recovery.py`: recovery tests validate that the worker restarts and new dispatches succeed, but they do not assert repair of pre-crash thread rows

Recommendation:

- Add a startup reconciliation job that inspects persisted non-terminal threads against checkpoint state and recent worker activity, then marks them recoverable/retryable/failed according to an explicit policy.

### 2026-03-08 23:28 - High - Worker crash recovery restores future dispatch capacity, not in-flight execution continuity

- The worker executor keeps in-flight execution state only in memory: `_active_ingests`, `_thread_to_cache_key`, compiled graph cache, and bridge thread tracking.
- All of that state is lost on worker restart.
- The current lazy recompile path can reconstruct a graph for a later explicit resume or new ingest request, but there is no mechanism that automatically resumes or conclusively repairs work that was executing when the worker died.

Impact:

- A worker crash during execution can strand in-flight threads in stale pre-crash states until a user manually sends another message, manually responds to a permission, or an operator intervenes.
- The watchdog therefore provides service-process recovery, not workflow recovery.
- For frontend development against a supposedly production-grade orchestration backend, this means restart resilience is materially weaker than the top-level health signals suggest.

Evidence:

- `src/vaultspec_a2a/worker/executor.py`: in-memory `_active_ingests`, `_thread_to_cache_key`, and graph cache are the only owners of active execution context
- `src/vaultspec_a2a/worker/executor.py`: lazy recompile supports later explicit `resume`/`ingest`, but no boot-time or post-restart replay of interrupted in-flight work exists
- `src/vaultspec_a2a/api/endpoints.py`: resume dispatch reconstructs only from DB metadata (`team_preset`, `workspace_root`) when a client explicitly calls the permission endpoint
- `src/vaultspec_a2a/tests/test_crash_recovery.py`: tests assert worker restart and successful new dispatch after recovery, not continuity of pre-crash execution

Recommendation:

- Decide whether in-flight workflow continuity is a production requirement. If it is, add durable run-intent ownership plus recovery logic that can requeue or fail stranded executions deterministically after worker restart.

### 2026-03-08 23:35 - High - The checkpoint state schema does not carry enough durable run-intent metadata to support authoritative crash reconciliation

- The LangGraph `TeamState` persists messages, plan, artifacts, token usage, and several blackboard fields.
- It does not durably encode a thread-level execution lifecycle such as `submitted/running/input_required`, nor does it persist the outstanding permission request IDs that would let the gateway reconstruct exact approval state after restart.
- The gateway snapshot layer therefore combines checkpoint content with DB status and gateway-memory permissions/agent states to approximate current truth.

Impact:

- After a crash, the system lacks a single durable record that can answer basic recovery questions such as:
  - Was this thread actively executing when the worker died?
  - Was it paused on a specific permission request?
  - Is the current DB `status` stale or authoritative?
- That makes robust self-repair difficult because reconciliation logic cannot infer workflow truth from checkpoint data alone.

Evidence:

- `src/vaultspec_a2a/core/state.py`: `TeamState` includes `messages`, `current_plan`, `artifacts`, `active_agent`, `plan_approved`, `active_feature`, `pipeline_phase`, `vault_index`, `validation_errors`, and `token_usage`, but no durable thread lifecycle field or permission-request identity field
- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` builds snapshots by mixing DB `thread.status`, checkpoint channel values, and gateway-memory `pending_permissions` / agent states
- `src/vaultspec_a2a/core/aggregator.py`: pending permission request IDs live only in `_pending_permissions`
- `src/vaultspec_a2a/database/crud.py`: the DB thread row persists only a coarse `status` string, not execution-intent provenance

Recommendation:

- Add explicit durable recovery markers, such as workflow phase / interruption cause / active permission request identity, so startup reconciliation can classify and repair stranded threads without depending on gateway memory.

### 2026-03-08 23:47 - High - Dispatch acknowledgements are returned before execution or durable enqueue, so `accepted`/`running` semantics are optimistic

- The worker `/dispatch` endpoint accepts a request and immediately schedules `executor.handle_dispatch()` in the lifespan task group.
- It returns `{"status": "dispatched"}` before graph execution starts, before any checkpoint write, and before any terminal/error outcome is known.
- The gateway treats a successful HTTP response from `/dispatch` as enough to mark follow-up messages `running` or permission responses `accepted`.

Impact:

- Frontend and MCP callers can receive success semantics for work that has only been placed into an in-memory task group and may still be lost by an immediate worker crash.
- The public write-path contract is therefore more optimistic than durable.
- Repair policy is harder because an acknowledged dispatch is not equivalent to accepted-and-persisted work.

Evidence:

- `src/vaultspec_a2a/worker/app.py`: `dispatch_endpoint()` calls `tg.start_soon(executor.handle_dispatch, req)` and immediately returns `DispatchResponse(status="dispatched", ...)`
- `src/vaultspec_a2a/api/endpoints.py`: `send_message_endpoint()` updates the thread to `RUNNING` after a successful `/dispatch` HTTP response
- `src/vaultspec_a2a/api/endpoints.py`: `respond_to_permission_endpoint()` returns `accepted=dispatched` based on the `/dispatch` HTTP response, not on completed resume handling

Recommendation:

- If the API promises durable acceptance, introduce a real durable dispatch queue/outbox or narrow the contract so `accepted` explicitly means only "worker process acknowledged receipt".

### 2026-03-08 23:52 - High - `dispatch_id` is logging-only; there is no idempotency or deduplication layer for ambiguous retries

- `DispatchRequest` includes a generated `dispatch_id`.
- That identifier is logged on the gateway but is not persisted, indexed, or checked anywhere in the worker.
- As a result, clients and operators have no safe way to retry an ambiguously failed dispatch without risking duplicate execution, and the system has no durable way to prove whether a request was already acted upon.

Impact:

- Network ambiguity between gateway and worker can produce duplicate ingests/resumes/cancels or silent loss, depending on when the failure occurs.
- Production-grade self-repair is limited because replaying a request after restart is not idempotent by construction.
- This is especially risky for resume/cancel control actions, where duplicate or reordered delivery can materially change workflow behavior.

Evidence:

- `src/vaultspec_a2a/api/schemas/internal.py`: `DispatchRequest` defines `dispatch_id`
- Repository-wide references show `dispatch_id` is only used in gateway logging statements and nowhere else
- `src/vaultspec_a2a/worker/app.py`: worker `/dispatch` accepts requests without checking prior `dispatch_id` history

Recommendation:

- Either persist `dispatch_id` as an idempotency key with explicit replay rules, or document the write path as non-idempotent and avoid presenting ambiguous retries as safe recovery actions.

### 2026-03-09 00:04 - High - Follow-up `send_message` requests are acknowledged even when the worker will silently drop them as concurrent same-thread ingests

- The gateway allows `POST /api/threads/{id}/messages` for any non-terminal thread and marks the thread `RUNNING` after the worker merely acknowledges `/dispatch`.
- The worker executor rejects a second ingest for the same thread if one is already active, but only by logging a warning and returning early.
- There is no compensating error event or negative acknowledgement back to the gateway for this dropped follow-up message.

Impact:

- A frontend can receive `202 accepted` for a message that never actually enters the workflow.
- This is a direct control-plane safety issue: the user-visible contract implies queued work, while the worker is effectively best-effort dropping concurrent thread turns.
- Retrying can then create ordering ambiguity or duplicate intent without any durable marker of what was actually processed.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `send_message_endpoint()` only blocks terminal states, dispatches to the worker, then sets the DB row to `RUNNING`
- `src/vaultspec_a2a/worker/executor.py`: `_handle_ingest()` calls `_mark_ingest_active()` and on failure logs `"Ingest already active ... -- dropping"` then returns
- `src/vaultspec_a2a/worker/tests/test_executor.py`: `test_ingest_prevents_concurrent_same_thread` asserts the drop-on-concurrency behavior via logging, not a structured failure path

Recommendation:

- Either queue same-thread follow-up messages durably/in-order, or reject them at the gateway with an explicit conflict/retry response instead of acknowledging work the worker may drop.

### 2026-03-09 00:09 - High - `cancel` requests have a lost-signal window if they arrive before the ingest loop has created the thread's cancellation event

- Worker-side cancel handling is only `aggregator.cancel_thread(thread_id)`, which sets an existing in-memory cancellation event if present.
- If no cancellation event exists yet, the cancel is reduced to a debug log and then discarded.
- The ingest loop creates the per-thread cancellation event lazily when `aggregator.ingest()` begins, so an acknowledged cancel can arrive too early and evaporate.

Impact:

- The gateway can return `status="cancelling"` / `cancelled=true` even though no durable or in-memory cancellation marker survives long enough to affect the actual ingest.
- This creates a race where user intent to stop execution is silently lost.
- For production-grade orchestration, control actions need stronger ordering guarantees than "set a transient event if it exists right now."

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `cancel_thread_endpoint()` returns `cancelling` when the worker `/dispatch` call succeeds
- `src/vaultspec_a2a/worker/executor.py`: `handle_dispatch()` handles `cancel` by calling `self._aggregator.cancel_thread(req.thread_id)` only
- `src/vaultspec_a2a/core/aggregator.py`: `cancel_thread()` is a no-op when `_cancel_events` has no entry for the thread
- `src/vaultspec_a2a/core/aggregator.py`: `ingest()` creates the cancellation event lazily via `_get_cancel_event(thread_id)` at ingest start

Recommendation:

- Persist cancel intent per thread and have the ingest path consume it deterministically, rather than relying on a transient event object existing at the exact moment the cancel arrives.

### 2026-03-09 00:14 - High - `resume` success can be reported and pending permission state cleared before the worker actually applies the resume

- The gateway treats a successful `/dispatch` HTTP response as `accepted=true` for permission responses.
- It also removes the permission request from the aggregator's pending set immediately after that optimistic dispatch acknowledgement.
- On the worker, `_handle_resume()` can still drop or fail the resume later, for example if no graph is available or if the thread is already actively ingesting.

Impact:

- The control surface can tell the frontend that a permission response was accepted while the underlying workflow never actually resumed.
- Clearing pending permission state early makes recovery harder because the visible control-plane evidence of the outstanding approval disappears before successful application is confirmed.
- This is a sequencing bug in the exact path that claims guaranteed delivery semantics.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `respond_to_permission_endpoint()` sets `accepted=dispatched` from the `/dispatch` response and immediately calls `aggregator.resolve_permission(request_id)` when `dispatched` is true
- `src/vaultspec_a2a/worker/executor.py`: `_handle_resume()` can log `"No graph for thread ... -- cannot resume"` and emit failure, or log `"Ingest already active ... -- cannot resume"` and return without applying the resume
- `src/vaultspec_a2a/api/tests/test_endpoints.py`: permission-response tests only assert dispatch submission, not successful downstream resume application

Recommendation:

- Treat permission responses as pending until the worker confirms the resume was actually applied, or at minimum do not clear visible pending-permission state on optimistic dispatch acknowledgement alone.

### 2026-03-09 00:24 - High - There is no per-thread action serialization layer, so `ingest`, `resume`, and `cancel` race through different code paths with incompatible safety guarantees

- The worker receives all control actions through one `/dispatch` endpoint and immediately schedules each request in the shared task group.
- `ingest` and `resume` use `_mark_ingest_active()` to reject concurrent execution on the same thread.
- `cancel` bypasses that gate entirely and directly toggles a transient cancellation event if one happens to exist.
- There is no per-thread mailbox, ordering token, or durable action queue that serializes control intent for a given thread.

Impact:

- Same-thread actions can arrive and be processed out of order relative to the user’s intent.
- Some races are dropped with only a warning, some are treated as successful no-ops, and none produce a durable ordered action history.
- This makes robust self-repair and frontend-visible control semantics much weaker than a production-grade orchestration backend should allow.

Evidence:

- `src/vaultspec_a2a/worker/app.py`: `/dispatch` schedules every request with `tg.start_soon(executor.handle_dispatch, req)`
- `src/vaultspec_a2a/worker/executor.py`: `handle_dispatch()` routes `ingest`, `resume`, and `cancel` directly without a per-thread queue
- `src/vaultspec_a2a/worker/executor.py`: only `ingest`/`resume` participate in `_mark_ingest_active()` gating
- `src/vaultspec_a2a/worker/executor.py`: `cancel` path calls only `self._aggregator.cancel_thread(req.thread_id)`

Recommendation:

- Introduce a per-thread action queue/mailbox so control operations are serialized deterministically, with explicit rules for coalescing or rejecting stale `cancel`/`resume`/follow-up `ingest` requests.

### 2026-03-09 00:29 - High - `cancel` does not robustly cover interrupted/input-required workflows even though the control surface presents it as a general stop action

- Interrupted workflows surface `INPUT_REQUIRED` agent state and pending permission requests after the ingest loop has exited.
- Once the ingest loop exits, its cancellation event is cleared.
- A later `cancel` against that thread goes through the same transient event path, but there is no active ingest loop left to observe the signal and no alternate path that marks the interrupted thread cancelled.

Impact:

- A thread waiting on approval can look live and user-actionable, yet the advertised cancel path may not actually terminate it.
- The MCP and REST control surfaces overstate how broadly `cancel` works.
- This is especially problematic because the system’s own docs describe `cancel` as an immediate stop mechanism for stuck or no-longer-needed workflows.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: interrupted graphs emit `INPUT_REQUIRED` agent state and pending permission requests, but `ingest()` clears the cancel event in `finally`
- `src/vaultspec_a2a/core/aggregator.py`: `cancel_thread()` only sets an existing cancellation event; otherwise it is a no-op
- `src/vaultspec_a2a/protocols/mcp/server.py`: `cancel_thread()` tool documentation says it "immediately signals the worker to abort the in-progress graph execution"
- `src/vaultspec_a2a/api/endpoints.py`: `cancel_thread_endpoint()` returns `cancelling` on optimistic dispatch acknowledgement, without verifying that the thread is in an actively cancellable execution phase

Recommendation:

- Define separate handling for cancelling interrupted/input-required threads, such as a durable terminal-intent flag or explicit state transition path, instead of relying solely on an active ingest-loop cancellation event.

### 2026-03-09 00:40 - High - The follow-up message contract overpromises queued delivery even though the worker can acknowledge and then drop same-thread messages

- The MCP `send_message` tool tells clients that a follow-up message "is queued and will be picked up by the next graph iteration" and returns plain-text "Message delivered to thread ...".
- The REST endpoint only waits for the worker `/dispatch` call to succeed, then marks the thread `running` and returns `status="accepted"`.
- The worker `/dispatch` endpoint itself is fire-and-forget: it schedules background handling and immediately returns `status="dispatched"`.
- Inside the executor, follow-up `ingest` requests are rejected when that thread already has an active ingest, with only a warning log and no durable per-thread message queue.

Impact:

- Frontend and MCP clients are told a follow-up message was delivered or queued when the actual worker behavior is "optimistically accepted for dispatch, then possibly dropped as concurrent same-thread ingest."
- Retry logic becomes unsafe because the caller cannot distinguish "durably queued", "accepted but not started", and "dropped after dispatch acknowledgement."
- This is a direct frontend-facing contract gap in one of the core conversation APIs.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/server.py`: `send_message()` says the message "is queued and will be picked up by the next graph iteration" and returns `"Message delivered to thread ..."`
- `src/vaultspec_a2a/api/endpoints.py`: `send_message_endpoint()` returns `202 Accepted`, sets `thread.status=RUNNING`, and returns `status="accepted"` after only the worker `/dispatch` HTTP call succeeds
- `src/vaultspec_a2a/worker/app.py`: `/dispatch` schedules `executor.handle_dispatch` via `tg.start_soon(...)` and immediately returns `status="dispatched"`
- `src/vaultspec_a2a/worker/executor.py`: `_handle_ingest()` logs `"Ingest already active for thread ... -- dropping"` when `_mark_ingest_active()` fails

Recommendation:

- Either implement a real per-thread durable/buffered follow-up queue, or narrow the client-facing contract so it only claims dispatch submission rather than queued delivery.

### 2026-03-09 00:46 - High - Duplicate permission responses are not idempotent and can change semantic meaning after the first acknowledgement

- The permission-response endpoint does not require the `request_id` to still exist in the aggregator's pending set; it extracts `thread_id` from the opaque `"{thread_id}:{uuid}"` request ID and can dispatch `resume` purely from that.
- The endpoint only converts plan-approval responses from `"approve"/"reject"` into `{"approved": True/False}` when the pending permission event is still present in memory.
- On the first optimistic dispatch acknowledgement, the gateway immediately removes the request from `_pending_permissions`.
- A duplicate retry after that point can still dispatch another `resume`, but now with different payload shape because the original pending event is gone and the plan-approval translation no longer runs.

Impact:

- Retried permission responses do not have stable idempotent semantics; the same request can be accepted twice with different effective resume payloads.
- The visible control-plane record of the original pending request disappears before successful application is confirmed, which makes duplicate/retry behavior even harder to reconcile.
- This is especially dangerous for "guaranteed delivery" flows because retries can change meaning instead of cleanly deduplicating.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `respond_to_permission_endpoint()` derives `thread_id` from `request_id`, does not reject missing pending requests, and only translates plan approvals when `aggregator._pending_permissions.get(request_id)` returns an event
- `src/vaultspec_a2a/api/endpoints.py`: successful dispatch acknowledgement immediately triggers `aggregator.resolve_permission(request_id)`
- `src/vaultspec_a2a/core/aggregator.py`: `resolve_permission()` simply drops the request from the in-memory pending set
- `src/vaultspec_a2a/protocols/mcp/server.py`: `respond_to_permission()` reports `"Permission response accepted"` based only on the API's `accepted` boolean

Recommendation:

- Introduce durable request-state tracking and idempotency for permission responses, and validate retries against the original request record so repeated submissions cannot change resume payload semantics.

### 2026-03-09 00:53 - High - The gateway accepts mutually incompatible follow-up actions against the same paused thread, so the frontend can receive multiple "accepted" responses for competing intents

- The MCP surface explicitly tells clients to use `send_message()` on "an already-running or paused thread" and `respond_to_permission()` to unblock a paused thread.
- The REST `send_message` endpoint only rejects terminal thread states; it does not block follow-up messages when a thread is paused on a permission interrupt.
- The REST permission-response endpoint follows the same pattern: it only rejects terminal thread states and otherwise dispatches `resume`.
- Downstream, both requests enter the same worker dispatch path, where only one same-thread ingest can win `_mark_ingest_active()` and the loser is dropped or reduced to a race-dependent no-op.

Impact:

- A frontend can legitimately issue two different user intents against the same paused thread and have both requests acknowledged as accepted even though the worker can only apply one coherent next step.
- This weakens product behavior around approval UIs because "reply to the thread" and "answer the permission request" are not mutually excluded by the gateway contract.
- In a production-grade orchestration layer, paused-control mode should have a deterministic API: either only resume/cancel is allowed, or message submission must be durably queued behind the resume point.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/server.py`: `send_message()` says it is for an "already-running or paused thread"
- `src/vaultspec_a2a/protocols/mcp/server.py`: `respond_to_permission()` describes unblocking a paused thread immediately
- `src/vaultspec_a2a/api/endpoints.py`: `send_message_endpoint()` rejects only archived/completed/failed/cancelled states
- `src/vaultspec_a2a/api/endpoints.py`: `respond_to_permission_endpoint()` rejects only completed/failed/cancelled/archived states
- `src/vaultspec_a2a/worker/executor.py`: `_handle_ingest()` and `_handle_resume()` both rely on `_mark_ingest_active()` and do not provide ordered composition of message-follow-up versus permission resume

Recommendation:

- Define an explicit paused-thread control policy at the gateway boundary and reject or serialize conflicting follow-up actions before they enter the worker race window.

### 2026-03-09 01:02 - Medium - The current test surface mostly validates optimistic HTTP acceptance for control actions, not durable application or retry correctness

- The MCP/API tests for follow-up messages and permission responses mainly assert `202` or `accepted=True` for existing threads.
- The repeat-cancel test explicitly codifies "stay accepting until terminal event" rather than verifying that repeated cancels converge on a durable cancelled outcome.
- There are no targeted tests for duplicate permission responses, paused-thread `send_message` versus `respond_to_permission` races, or same-intent retry storms changing frontend-visible truth.

Impact:

- The current verification strategy would not catch several of the control-plane contract gaps already logged in this audit.
- This is directly at odds with the goal of a production-grade self-repairing orchestration backend supported by robust live integration testing without mocks or hand-waved control semantics.
- As written, the tests reinforce the optimistic-acknowledgement model instead of challenging it.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`: `test_send_message_returns_202_for_existing_thread()` only asserts HTTP `202`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`: `test_respond_to_permission_dispatches_for_existing_thread()` accepts a fake request ID and only asserts `accepted is True`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`: `test_cancel_thread_repeat_request_stays_accepting_until_terminal_event()` asserts repeated cancels remain accepted rather than verifying effective cancellation
- Repository-wide grep found no targeted tests for duplicate permission submissions, competing paused-thread follow-up actions, or retry/idempotency semantics

Recommendation:

- Add live integration tests that assert control actions are durably applied, idempotent where required, and mutually consistent under retries and same-thread action races.

### 2026-03-09 01:15 - High - There is no durable control-action journal, so restart-time reconciliation has no authoritative record of user intent

- The runtime exposes relational tables for `permission_logs` and `cost_tracking`, but repository-wide usage shows their write helpers are only exercised in database unit tests, not in the live gateway/worker paths.
- `send_message`, `cancel`, and permission-response actions are dispatched to the worker but are not durably recorded as control intents in the app-owned SQL schema.
- Gateway startup creates a brand-new in-memory `EventAggregator`; it does not rebuild a control-action log from DB rows or checkpoint history before serving frontend snapshots and control endpoints.

Impact:

- After gateway or worker restart, the system has no authoritative journal of which user actions were requested, acknowledged, applied, retried, or superseded.
- This blocks robust self-repair because reconciliation cannot distinguish "user asked to cancel", "cancel was only optimistically acknowledged", and "resume actually applied".
- Frontend-visible truth remains dependent on transient in-memory state instead of a production-grade durable control plane.

Evidence:

- `src/vaultspec_a2a/database/models.py`: defines `permission_logs` and `cost_tracking` as durable tables
- `src/vaultspec_a2a/database/crud.py`: provides `append_permission_log()` and `append_cost_record()` helpers
- Repository-wide grep found no runtime call sites for `append_permission_log()` or `append_cost_record()` outside `src/vaultspec_a2a/database/tests/test_database.py`
- `src/vaultspec_a2a/api/app.py`: startup constructs `aggregator = EventAggregator()` fresh and does not replay a persisted control journal into it

Recommendation:

- Introduce a durable control-action log for `ingest`, `resume`, `cancel`, permission requests, and permission responses, then drive restart reconciliation from that journal instead of from transient gateway memory.

### 2026-03-09 01:21 - High - Crash recovery is validated only as worker-process restoration, not as restoration or repair of existing non-terminal workflow state

- The live crash-recovery suite proves the watchdog can restart the worker and that new dispatch works afterward.
- It does not verify what happens to already-running, input-required, or recently-cancelled threads across that restart.
- Existing thread snapshots after restart are rebuilt against a fresh gateway aggregator, so frontend-facing fields that depend on gateway memory can silently disappear even while the crash-recovery tests still pass.

Impact:

- The current "self-healing" story is limited to process availability, not workflow correctness.
- A system can pass the live crash-recovery suite while still losing pending permissions, agent state, replay cursors, and control-intent visibility for the threads users actually care about.
- For frontend readiness, this means reconnect and recovery behavior after disruption is materially less trustworthy than the current tests imply.

Evidence:

- `src/vaultspec_a2a/tests/test_crash_recovery.py`: tests cover gateway surviving worker death, worker status transitions, and new dispatch working after recovery
- `src/vaultspec_a2a/tests/test_crash_recovery.py`: no assertions cover pre-existing `running` or `input_required` threads, pending permissions, replay continuity, or control-intent recovery after restart
- `src/vaultspec_a2a/api/app.py`: gateway startup creates a fresh `EventAggregator`
- `src/vaultspec_a2a/api/endpoints.py`: thread-state snapshots enrich pending permissions and agent state from the aggregator rather than reconstructing them durably

Recommendation:

- Extend live crash-recovery testing to include interrupted threads, repeated control actions around restart, and post-restart snapshot/replay correctness for pre-existing threads, not just fresh dispatch capacity.

### 2026-03-09 01:28 - High - Reconnect snapshots can silently degrade into misleading empty state after restart or checkpoint-read failure

- `GET /api/threads/{id}/state` starts from a minimal snapshot containing only `thread_id`, DB `status`, and `last_sequence` from the in-memory aggregator.
- If checkpoint loading times out or fails, the endpoint logs a warning and returns that partial snapshot instead of an explicit degraded/error response.
- Because the gateway constructs a fresh `EventAggregator` on startup, a recent restart can make `last_sequence=0` and clear in-memory agent/pending-permission enrichment even for threads that previously had live activity.

Impact:

- A reconnecting frontend can receive what looks like a legitimate empty snapshot even though the system actually lost replay cursor state or failed to read checkpoint data.
- This makes it hard for the client to distinguish "thread really has no pending permissions or agent activity" from "gateway restarted / snapshot enrichment degraded."
- For production-grade frontend/backend decoupling, degraded snapshot reconstruction needs explicit signaling rather than masquerading as authoritative empty state.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` initializes `ThreadStateSnapshot(thread_id, status, last_sequence)` before enrichment
- `src/vaultspec_a2a/api/endpoints.py`: on checkpoint timeout or exception it returns the partial snapshot after logging only a warning
- `src/vaultspec_a2a/api/endpoints.py`: `last_sequence` comes from `aggregator.get_sequence(thread_id)`
- `src/vaultspec_a2a/api/app.py`: gateway startup constructs a fresh `EventAggregator`
- `src/vaultspec_a2a/api/schemas/snapshots.py`: snapshot schema has no explicit degraded/partial flag

Recommendation:

- Surface snapshot degradation explicitly in the API contract and avoid returning indistinguishable empty-state snapshots when checkpoint or replay reconstruction is incomplete.

### 2026-03-09 01:41 - High - The durable thread status machine cannot represent paused, cancelling, or repair-needed workflow states, so restart policy is structurally ambiguous

- The DB-backed `ThreadStatus` enum only includes `submitted`, `created`, `running`, `completed`, `failed`, `cancelled`, and `archived`.
- Public-facing control surfaces and agent lifecycle semantics rely on richer non-terminal states such as `input_required` and `cancelling`.
- `GET /threads` and status filtering operate on the coarse DB status only, while richer execution truth is split across checkpoint content and gateway-memory agent states.
- The transition table contains no explicit state for "awaiting permission", "cancel requested but not yet applied", "reconciliation needed after restart", or "worker lost during execution".

Impact:

- There is no durable place to encode what repair policy should do with non-terminal threads after restart.
- Frontend-visible lifecycle semantics are forced to infer meaningful workflow distinctions from transient side channels instead of from a single authoritative state machine.
- This makes self-healing and self-repair policy underspecified: the system cannot clearly mark "paused but resumable", "cancellation pending", or "stuck and needs operator repair" in persistent storage.

Evidence:

- `src/vaultspec_a2a/database/crud.py`: `ThreadStatus` enum contains only `submitted|created|running|completed|failed|cancelled|archived`
- `src/vaultspec_a2a/database/crud.py`: `_VALID_TRANSITIONS` has no repair-oriented or paused/cancelling states
- `src/vaultspec_a2a/api/schemas/enums.py`: `AgentLifecycleState` includes `INPUT_REQUIRED`
- `src/vaultspec_a2a/protocols/mcp/server.py`: user-facing docs describe thread statuses including `input_required`
- `src/vaultspec_a2a/api/endpoints.py`: `CancelThreadResponse` returns ephemeral `status="cancelling"` even though that is not a durable `ThreadStatus`
- `src/vaultspec_a2a/api/endpoints.py`: `list_threads_endpoint()` returns `t.status` directly from the DB row

Recommendation:

- Define a durable workflow state model that explicitly covers paused/input-required, cancelling, and reconciliation-needed cases, then make restart repair policy operate on that model instead of inferring from mixed DB/checkpoint/memory signals.

### 2026-03-09 01:46 - Medium - The lifecycle model contains an orphaned `created` state that is not meaningfully exercised by the live runtime

- `ThreadStatus.CREATED` exists in the DB enum and transition table.
- The live create-thread endpoint persists new threads as `submitted` and returns that DB status directly.
- Runtime status writes observed in the gateway go from `submitted` to `running`, `failed`, or `archived`; there is no observed operational path that sets `created`.
- The `created` label still appears in schema/docs/tests, which suggests an earlier lifecycle design that is no longer implemented coherently.

Impact:

- The existence of an unused durable state makes the repair/state model harder to reason about and increases the chance that different clients or future code paths assign different meaning to the same lifecycle.
- It is a signal that the status machine is not being actively driven by a single, current workflow contract.
- For production hardening, orphaned lifecycle states are costly because they complicate migration, filtering, dashboards, and reconciliation logic without carrying real runtime value.

Evidence:

- `src/vaultspec_a2a/database/crud.py`: defines `ThreadStatus.CREATED` and allows `submitted -> created`
- `src/vaultspec_a2a/api/endpoints.py`: `create_thread_endpoint()` creates the DB row with `ThreadStatus.SUBMITTED` and returns `thread.status`
- Repository-wide search found no live gateway/worker code path setting `ThreadStatus.CREATED`
- `src/vaultspec_a2a/api/schemas/tests/test_schemas.py`: still constructs `CreateThreadResponse(..., status="created")`

Recommendation:

- Either remove `created` from the durable status model or reintroduce it with a precise runtime meaning and explicit transitions; leaving it half-alive weakens the lifecycle contract.

### 2026-03-09 01:56 - High - The codebase implements process recovery but still has no explicit workflow repair policy for non-terminal threads

- The watchdog, circuit breaker, and crash-recovery tests are all framed around worker liveness, restart, and fresh dispatch capacity.
- No code path or current documentation defines what should happen to already-existing `submitted`, `running`, `cancelling`, or permission-paused threads after a restart boundary.
- There is no durable classification of threads into "auto-fail", "auto-requeue", "await user response", or "needs operator intervention".

Impact:

- The system cannot make principled self-healing decisions for interrupted workflows; it can only bring the worker process back.
- Any future repair behavior risks becoming ad hoc because there is no current contract tying durable state to a repair action.
- This is a core production-readiness gap: liveness recovery without workflow repair policy is not true orchestration recovery.

Evidence:

- `src/vaultspec_a2a/tests/test_crash_recovery.py`: validates worker restart and new dispatch, not thread repair semantics
- `src/vaultspec_a2a/api/app.py`: watchdog/circuit-breaker logic manages worker availability only
- Repository-wide search found no live code or current docs defining restart actions such as auto-fail, auto-requeue, or operator-hold for non-terminal threads
- `src/vaultspec_a2a/database/crud.py`: durable status model contains no repair-policy states or markers

Recommendation:

- Define a restart repair matrix for each non-terminal workflow class and encode it durably enough that the gateway can apply the same decision after any restart.

### 2026-03-09 02:03 - High - Frontend-facing status surfaces cannot expose a trustworthy repair classification after restart because `input_required` is not a durable thread status

- MCP docs and tool output describe `input_required` as a meaningful thread status for users deciding whether to resume work.
- The REST list endpoint returns DB `thread.status` directly, and that DB enum does not include `input_required`.
- The detailed thread-state endpoint also keeps the DB status unchanged and only exposes paused/approval context indirectly via `pending_permissions` and agent snapshots.
- Those enrichment fields come from the gateway aggregator, which is reset on startup and is therefore not restart-stable.

Impact:

- After restart, the frontend cannot reliably tell whether a thread is truly waiting on user input, merely appears `running`/`submitted`, or has lost its paused-state evidence.
- This blocks any clean UX for self-repair because the user-facing control plane cannot distinguish "safe to resume", "should retry", and "needs investigation" from durable API truth.
- It also means the frontend/backend contract overstates lifecycle clarity in exactly the cases where recovery behavior matters most.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/server.py`: `list_threads()` and `get_thread_status()` documentation enumerate `input_required` as a thread status
- `src/vaultspec_a2a/api/endpoints.py`: `list_threads_endpoint()` returns `t.status` from the DB row
- `src/vaultspec_a2a/database/crud.py`: `ThreadStatus` enum does not include `input_required`
- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` returns DB `status` and enriches `pending_permissions` from the aggregator
- `src/vaultspec_a2a/api/app.py`: gateway startup constructs a fresh `EventAggregator`

Recommendation:

- Make "awaiting user input" a durable, restart-stable lifecycle class or expose an explicit repair/readiness field in the thread APIs so clients do not have to infer it from volatile enrichment.

### 2026-03-09 02:15 - High - The persistence model has no durable pause-reason or permission-request linkage, so restart repair cannot reconstruct why a thread is blocked

- Permission request IDs are created and tracked in the gateway aggregator's in-memory `_pending_permissions` map.
- The durable `TeamState` schema stores only a coarse `plan_approved` boolean for the plan-approval flow; it does not store a stable request ID, pause reason, option set, or paused-at marker.
- The app-owned SQL schema likewise has no thread-level fields for "awaiting permission", request linkage, or outstanding approval metadata.
- The thread-state API reconstructs pending permissions from the aggregator, not from a durable source.

Impact:

- After restart, the system cannot authoritatively explain why a thread is paused or which exact permission request a user response should satisfy.
- Repair logic cannot distinguish "waiting on plan approval", "waiting on ACP tool permission", and "not actually paused anymore" from durable state alone.
- This makes restart-safe resume UX and automatic repair policy fundamentally under-specified.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: stores permission requests only in `_pending_permissions[request_id]`
- `src/vaultspec_a2a/core/state.py`: `TeamState` includes `plan_approved` but no durable request ID / pause-reason fields
- `src/vaultspec_a2a/core/nodes/supervisor.py`: plan approval interrupt resumes by setting only `plan_approved=True`
- `src/vaultspec_a2a/core/nodes/worker.py`: ACP permission interrupts suspend via `interrupt(...)` but do not map to durable app-owned request metadata
- `src/vaultspec_a2a/api/endpoints.py`: snapshot enrichment populates `pending_permissions` from the aggregator
- `src/vaultspec_a2a/database/models.py`: `ThreadModel` has no dedicated columns for pause reason or outstanding permission linkage

Recommendation:

- Persist a durable blocked-state record per thread that includes pause reason, request ID, available options, and enough metadata to resume or reconcile safely after restart.

### 2026-03-09 02:22 - High - There is no durable record of the last requested or last applied control action, so restart repair cannot tell which command "won"

- `dispatch_id` exists on `DispatchRequest` but is only part of the transient worker-dispatch envelope and log lines.
- The durable SQL schema has no thread-level fields for last requested action, last applied action, last dispatch timestamp, or recovery epoch.
- The worker/gateway recovery path does not stamp any restart generation or repair marker onto threads when the worker crashes and comes back.

Impact:

- After a restart or ambiguous retry window, the system cannot answer whether the most recent durable intent was `ingest`, `resume`, `cancel`, or a later superseding command.
- This makes deterministic reconciliation impossible in race-heavy scenarios because there is no persistent control-action ordering record to replay.
- Frontend-visible outcomes can therefore depend on volatile timing rather than on a persisted control history.

Evidence:

- `src/vaultspec_a2a/api/schemas/internal.py`: `DispatchRequest` defines transient `dispatch_id`
- `src/vaultspec_a2a/api/endpoints.py`: control endpoints log `dispatch_id` but do not persist it or any last-action marker to the DB
- `src/vaultspec_a2a/database/models.py`: `ThreadModel` stores status, metadata, nickname, and preset only
- `src/vaultspec_a2a/api/app.py`: watchdog restart logic updates worker-process state, not per-thread recovery/action epochs

Recommendation:

- Persist a per-thread control-action journal or at minimum durable `last_requested_action`, `last_applied_action`, and recovery-generation markers so repair logic can reconcile retries and restarts deterministically.

### 2026-03-09 02:34 - High - The current gateway checkpoint-consumption path reads only business state, not a repair-oriented interrupt/control record

- The thread-state endpoint loads a checkpoint tuple and extracts only `channel_values` plus `checkpoint_id`.
- Snapshot enrichment then maps messages, plan, artifacts, tool calls, and aggregator-backed live fields, but does not reconstruct durable control intent, interrupt metadata, or restart-relevant decision state from the checkpoint structure.
- Even if LangGraph's persisted checkpoint internals contain enough low-level material to reason about suspension/resume, the current gateway architecture discards that signal at the API boundary.

Impact:

- In the current implementation, checkpoints are insufficient as the sole source of repair truth because the gateway does not consume them in a repair-aware way.
- This means a separate app-owned repair journal is effectively unavoidable unless the checkpoint-reading contract is expanded significantly.
- Frontend recovery semantics remain tied to a partial projection of checkpoint state rather than to the full durable execution record.

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`: `get_thread_state_endpoint()` reads `checkpoint_tuple.checkpoint["channel_values"]`
- `src/vaultspec_a2a/api/endpoints.py`: `_enrich_snapshot_from_state()` derives messages, plan, artifacts, tool calls, and aggregator-backed agent/permission data only
- `src/vaultspec_a2a/api/endpoints.py`: the only checkpoint metadata surfaced is `checkpoint_id`
- `src/vaultspec_a2a/core/tests/test_graph.py` and `src/vaultspec_a2a/core/tests/test_e2e_live.py`: checkpoint assertions focus on `channel_values` growth/preservation, not a durable repair/control record

Recommendation:

- Either add an explicit repair-oriented projection layer over checkpoint internals or introduce a separate app-owned reconciliation journal; the current channel-values-only approach is not enough for deterministic restart repair.

### 2026-03-09 02:40 - High - The durable plan-approval state collapses a multi-step blocked workflow into a single boolean, which is too lossy for restart repair

- The supervisor's plan-approval interrupt persists `plan_approved=True` on approval.
- On rejection, the flow persists a `routing_error` message and reroutes for revision, but there is no durable state that distinguishes "approval pending", "approval rejected", "approval request superseded", or "currently blocked awaiting a specific request".
- The state model contains only `plan_approved: bool` for this entire human-in-the-loop gate.

Impact:

- After restart, the system cannot tell whether an execution-bound plan has never been presented, is actively awaiting approval, was rejected and is being revised, or has already been approved and should not interrupt again.
- This is too little information for a production repair matrix to decide whether to re-prompt, resume, fail, or leave the thread untouched.
- The frontend can therefore lose the semantic reason a thread is blocked even when checkpoint state exists.

Evidence:

- `src/vaultspec_a2a/core/state.py`: `TeamState` includes `plan_approved` but no richer approval-status or request-linkage fields
- `src/vaultspec_a2a/core/nodes/supervisor.py`: approval path writes `plan_approved=True`; rejection path writes `routing_error` and reroutes
- `docs/adrs/024-plan-approval-interrupt.md`: describes approval persistence via `plan_approved: True` and rejection via reroute, without a richer durable blocked-state model

Recommendation:

- Replace the single `plan_approved` boolean with a durable approval-state record that can represent pending, approved, rejected, superseded, and request linkage across restarts.

### 2026-03-09 14:30 - High - The orchestration durability pass improved restart truth ownership, but live verification still proves process recovery more than workflow recovery

- The recent implementation added durable repair metadata, a control-action journal, a durable permission-request model, and startup reconciliation.
- Those changes materially reduce the original restart-repair gap, but the live verification path still does not prove recovery semantics for pre-existing `running`, `input_required`, or `cancelling` threads across restart boundaries.
- The focused verification run covered migrations, REST endpoints, internal event persistence, and schema behavior; it did not exercise live gateway+worker restart repair for already-existing threads.

Impact:

- The backend is in a better state than the earlier audit snapshot, but the strongest remaining risk is now verification drift rather than total absence of repair primitives.
- A regression in startup reconciliation or durable permission recovery could still ship while the fast suite remains green.

Evidence:

- `src/vaultspec_a2a/core/reconciliation.py`: startup reconciliation now classifies non-terminal threads and persists repair outcomes.
- `src/vaultspec_a2a/database/models.py`: durable `repair_status`, `execution_readiness`, `last_requested_action`, `last_applied_action`, `repair_generation`, and `recovery_epoch` now exist on `ThreadModel`.
- `src/vaultspec_a2a/database/models.py`: `PermissionRequestModel` and `ControlActionModel` add durable blocked-state and control history.
- Verified tests run in the current pass covered `database/tests/test_migrations.py`, `api/tests/test_endpoints.py`, `api/tests/test_internal.py`, and `api/schemas/tests/test_schemas.py`; no new live subprocess restart suite was added in this pass.

Recommendation:

- Promote live repair verification to the next execution slice: restart with pre-existing paused/running threads, assert durable repair classification, and verify idempotent permission/cancel behavior after restart.

### 2026-03-09 14:37 - Medium - The expanded durable lifecycle still retains the orphaned `created` state, so the lifecycle contract remains partially inconsistent

- The recent lifecycle expansion added `input_required`, `cancelling`, `repair_needed`, and `reconciling`, but left `created` in the durable enum and transition table.
- The live create-thread path still persists threads as `submitted`, and no reviewed runtime path assigns `created`.

Impact:

- The lifecycle contract is improved but not yet clean enough to treat the audit item as fully closed.
- Migration, filtering, and operational dashboards still carry an unused state with unclear semantics.

Evidence:

- `src/vaultspec_a2a/database/crud.py`: `ThreadStatus` still includes `CREATED`.
- `src/vaultspec_a2a/database/crud.py`: `_VALID_TRANSITIONS` still contains transitions involving `created`.
- `src/vaultspec_a2a/api/endpoints.py`: thread creation persists `submitted`, not `created`.

Recommendation:

- Remove `created` from the durable runtime model or assign it a real runtime meaning and make the gateway/worker drive it explicitly.

### 2026-03-09 14:44 - High - Snapshot degradation is now explicit, but checkpoint consumption is still centered on `channel_values` rather than a repair-aware interrupt/control projection

- The recent implementation added explicit degraded snapshot flags and repair/readiness fields, which closes the “silent partial snapshot” problem.
- The gateway still builds its checkpoint-derived snapshot primarily from `checkpoint["channel_values"]`, with only limited checkpoint metadata surfaced.
- Interrupt metadata, replay cursor durability, and control/repair-oriented checkpoint fields are still not projected into a normalized repair-aware model.

Impact:

- Frontend clients can now distinguish degraded snapshots from complete ones, which is a real improvement.
- Deterministic restart repair still depends mostly on the app-owned journal because the gateway is not yet consuming the full checkpoint structure in a repair-aware way.

Evidence:

- `src/vaultspec_a2a/api/schemas/snapshots.py`: `ThreadStateSnapshot` now includes `snapshot_complete`, `degraded_reasons`, `replay_status`, `repair_status`, and `execution_readiness`.
- `src/vaultspec_a2a/api/endpoints.py`: snapshot responses now mark checkpoint timeout/unavailability explicitly.
- `src/vaultspec_a2a/api/endpoints.py`: checkpoint loading still extracts `channel_values` and `checkpoint_id` as the primary checkpoint projection inputs.

Recommendation:

- Add a dedicated checkpoint projection layer that inspects interrupt/task/config metadata and classifies what is durable, inferred, and degraded.

### 2026-03-09 14:51 - High - Durable permission journaling now exists, but the plan-approval flow still sits outside the new blocked-state model

- The recent implementation introduced durable permission requests and durable control actions for restart-safe permission handling.
- The LangGraph plan-approval path still persists approval state as `plan_approved: bool` and is not mapped into the new durable permission-request/control-action model.
- This leaves two blocked-state systems in the codebase: the new app-owned journal for control truth, and the older boolean approval signal inside LangGraph state.

Impact:

- ACP/tool permission recovery is materially stronger than before.
- Plan approval remains too lossy for deterministic restart repair, leaving a gap exactly where human-in-the-loop workflow semantics matter most.

Evidence:

- `src/vaultspec_a2a/database/models.py`: `PermissionRequestModel` and `ControlActionModel` now provide durable blocked-state and action history.
- `src/vaultspec_a2a/api/internal.py`: permission events are persisted into the durable model.
- `src/vaultspec_a2a/core/state.py`: `TeamState` still models approval with `plan_approved: NotRequired[bool]`.
- `src/vaultspec_a2a/core/nodes/supervisor.py`: approval still writes `plan_approved=True`.

Recommendation:

- Unify plan approval with the durable blocked-state model: request identity, pending/applied/rejected/superseded states, and restart-stable linkage back to the control journal.

### 2026-03-09 14:58 - High - The production persistence migration path is still not represented as an active execution-owned program

- Earlier architecture and research material repeatedly mention SQLite for local use and Postgres as the likely production destination.
- The current active audit/task queue still centers on Docker hardening, test cleanup, and control-plane robustness; it does not yet carry concrete execution-owned tasks for the Postgres migration path.
- Without an active queue and execution plan, the production persistence destination remains a design assumption rather than an owned delivery track.

Impact:

- Production-readiness work can continue closing local/SQLite gaps while the true production persistence path remains unimplemented and unverified.
- This creates planning drift: the codebase improves, but the production destination remains structurally under-specified.

Evidence:

- `docs/audits/2026-02-25-architecture-gap-analysis-audit.md`: earlier audit noted that a migration path from SQLite to Postgres was undefined.
- `docs/research/2026-03-08-library-validation-langgraph-checkpoint.md`: research explicitly frames Postgres-backed checkpointing as the production-oriented path.
- `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`: the active queue and roadmap contain no dedicated Postgres execution track.

Recommendation:

- Promote the phased Postgres rollout into the active execution queue with explicit abstraction, migration, Docker overlay, readiness, and verification tasks.

### 2026-03-09 15:12 - Medium - The Postgres readiness slice initially left the live smoke harness broken because the Jaeger v2 fixture still probed a retired health endpoint, but the issue was fixed in-slice

- The persistence/readiness pass updated the test harness to a current Jaeger v2 image.
- The fixture still used the older admin-port probe assumption (`14269`, `GET / -> 204`), which no longer matches the current all-in-one image behavior.
- The real Jaeger container was healthy, but the smoke suite hard-failed because the probe targeted the wrong port/path.

Impact:

- The production-certifying Postgres smoke suite was blocked even though the gateway, worker, Postgres, and trace backend were otherwise booting correctly.
- This was a harness drift issue, not a backend persistence regression, but it would have hidden Phase 1 readiness progress if left unresolved.

Evidence:

- `src/vaultspec_a2a/tests/conftest.py`: the Jaeger fixture was initially switched to `cr.jaegertracing.io/jaegertracing/jaeger:2.16.0` while still probing the retired admin endpoint assumptions.
- Local direct container inspection during the slice showed Jaeger v2 listening on the OTel health extension port `13133`.
- `src/vaultspec_a2a/tests/conftest.py`: the live harness now probes `13133/status`, which matches the v2 health extension behavior and restored live smoke verification.

Resolution:

- Fixed in the same slice by moving the Jaeger probe and `requires_jaeger` gate to the v2 health endpoint on `13133/status`.

### 2026-03-09 15:18 - Medium - The aggregated readiness endpoint was incorrectly treating an informational worker-spawner field as a hard readiness gate, but the issue was fixed in-slice

- `/api/health` documents `worker_spawned` as informational lazy-spawner state.
- The readiness calculation still required `worker_spawned == "yes"` for overall `status="ok"`.
- In the live Postgres smoke stack, the worker is started as a separate real subprocess while gateway auto-spawn remains disabled, so `worker_spawned` correctly stayed `"no"` even though the worker itself was healthy.

Impact:

- The live smoke suite never observed `/api/health` becoming ready, which blocked production-certifying verification of the Postgres persistence slice.
- The readiness contract was internally inconsistent: an informational field could mark a healthy stack degraded.

Evidence:

- `src/vaultspec_a2a/tests/conftest.py`: `service_env` disables gateway auto-spawn and starts the worker independently for the live stack.
- `src/vaultspec_a2a/api/endpoints.py`: the health route initially folded `worker_spawned` into the overall readiness decision.
- `src/vaultspec_a2a/api/endpoints.py`: the readiness calculation now gates only on gateway/database/checkpoint/worker health plus a closed circuit breaker.

Resolution:

- Fixed in the same slice by excluding `worker_spawned` from the readiness decision while preserving it as operator-visible informational state.

### 2026-03-09 15:32 - Medium - The orphaned `created` lifecycle state has now been removed from the runtime contract and legacy data path, closing the remaining lifecycle drift from the durability pass

- The runtime lifecycle no longer defines or accepts `created`.
- The gateway snapshot fallback no longer treats `created` as a meaningful checkpoint-free state.
- A dedicated Alembic data migration now rewrites any legacy `threads.status='created'` rows to `submitted` so upgraded SQLite/Postgres databases remain compatible with the cleaned runtime.

Impact:

- The thread lifecycle contract is now consistent with the actual runtime: new threads start at `submitted`, and no dead intermediate state remains in the DB/API/CLI path.
- Existing databases can be upgraded without leaving unreadable legacy rows behind.

Evidence:

- `src/vaultspec_a2a/database/crud.py`: `ThreadStatus.CREATED` and its transition branch were removed.
- `src/vaultspec_a2a/api/endpoints.py`: checkpoint-free snapshot completeness now applies only to `submitted`.
- `src/vaultspec_a2a/cli/_team.py`: the CLI status filter no longer exposes `created` and now reflects the live lifecycle surface.
- `src/vaultspec_a2a/database/migrations/versions/0003_remove_created_thread_status.py`: rewrites legacy `created` rows to `submitted`.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/database/crud.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/cli/_team.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py src/vaultspec_a2a/database/tests/test_database.py src/vaultspec_a2a/database/tests/test_migrations.py src/vaultspec_a2a/database/migrations/versions/0003_remove_created_thread_status.py docs/research/2026-03-09-postgres-persistence-grounding.md`
  - `uv run pytest src/vaultspec_a2a/database/tests/test_database.py src/vaultspec_a2a/database/tests/test_migrations.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py -q`
  - result: `139 passed`

Resolution:

- Fixed in the same slice; no new review findings were identified beyond the historical `created` drift itself.

### 2026-03-09 16:02 - Medium - Checkpoint projection is no longer `channel_values`-only, but the repair-aware projection work remains partial because it still does not reconstruct full task/next/history state

- The gateway reconnect path now reads persisted interrupt data from LangGraph
  checkpoint tuples instead of treating checkpoint truth as raw
  `channel_values` only.
- The new projection layer normalizes checkpoint ID, checkpoint timestamp,
  persisted interrupt payloads from `pending_writes`, pause cause, and degraded
  projection reasons before merging them into `ThreadStateSnapshot`.
- Review of the completed slice found that this is real progress, but not final
  closure: the gateway still does not reconstruct the broader `StateSnapshot`
  task/next/history surface, so repair classification remains only partially
  checkpoint-aware.

Impact:

- Reconnecting clients can now distinguish more than "checkpoint loaded or not":
  persisted interrupt-driven pause truth and checkpoint freshness are surfaced
  directly from the checkpointer, which reduces dependence on gateway-owned
  permission state.
- However, the repair model is still incomplete for workflows whose recovery
  semantics depend on richer task scheduling or execution-history context than
  the current projection reads.

Evidence:

- `src/vaultspec_a2a/api/projection.py`: added `CheckpointProjection`,
  persisted interrupt extraction from `pending_writes`, checkpoint timestamp
  parsing, pause-cause derivation, and snapshot merge logic.
- `src/vaultspec_a2a/api/endpoints.py`: the thread-state endpoint now projects
  checkpoint tuples through the normalized projection helper instead of reading
  `channel_values` directly.
- `src/vaultspec_a2a/api/schemas/snapshots.py`: `ThreadStateSnapshot` now
  exposes `checkpoint_created_at` and `pause_cause`.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/api/projection.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/schemas/snapshots.py src/vaultspec_a2a/api/tests/test_projection.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py`
  - `uv run pytest src/vaultspec_a2a/api/tests/test_projection.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py -q`
  - result: `73 passed`

Review finding:

- The original audit task is narrowed, not closed. Persisted interrupt truth is
  now projected, but full task/next/history-aware repair reconstruction still
  remains open.

Recommendation:

- Reclassify the original projection task as `PARTIAL` and continue directly
  into the durable plan-approval/blocked-state work so the next checkpoint
  projection pass has a complete control-truth model to merge with.

### 2026-03-09 16:38 - High - The boolean-only plan approval model has been replaced in the durable/runtime path, but live restart verification for approval semantics is still missing

- The backend no longer relies on `plan_approved: bool` as the active approval
  truth model.
- Thread rows now persist durable approval state (`approval_status`,
  `approval_request_id`, reason, response action identity, timestamp), and plan
  approval requests reuse the existing durable `permission_requests` +
  `control_actions` model instead of living only in checkpoint state.
- The aggregator now preserves stable interrupt/request identity for approval
  requests instead of minting an in-memory UUID for every interrupt event.
- The supervisor now routes on `approval_status == "approved"` with a legacy
  compatibility alias for historical checkpoints that still carry
  `plan_approved`.

Impact:

- Frontend/API surfaces can now read a durable approval state from app-owned
  truth rather than inferring approval from a checkpoint boolean or a pending
  interrupt alone.
- Restart repair has a stable request identity and a stable thread-level
  approval state to reconcile against.

Evidence:

- `src/vaultspec_a2a/database/models.py`: thread-level durable approval fields.
- `src/vaultspec_a2a/database/crud.py`: `ApprovalStatus`,
  `set_thread_approval_state()`, and supersession support for older plan
  approval requests.
- `src/vaultspec_a2a/api/internal.py`: plan approval request/applied events now
  persist approval state in the DB.
- `src/vaultspec_a2a/core/aggregator.py`: interrupt events now preserve stable
  payload/interrupt request IDs instead of always generating a fresh UUID.
- `src/vaultspec_a2a/core/state.py` and
  `src/vaultspec_a2a/core/nodes/supervisor.py`: runtime path now uses
  `approval_status` with legacy `plan_approved` fallback for old checkpoints.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/database/models.py src/vaultspec_a2a/database/crud.py src/vaultspec_a2a/database/migrations/versions/0004_plan_approval_state.py src/vaultspec_a2a/api/schemas/rest.py src/vaultspec_a2a/api/schemas/snapshots.py src/vaultspec_a2a/api/projection.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/internal.py src/vaultspec_a2a/core/aggregator.py src/vaultspec_a2a/core/state.py src/vaultspec_a2a/core/nodes/supervisor.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py src/vaultspec_a2a/database/tests/test_database.py src/vaultspec_a2a/database/tests/test_migrations.py src/vaultspec_a2a/core/tests/test_state.py src/vaultspec_a2a/core/tests/test_supervisor.py`
  - `uv run pytest src/vaultspec_a2a/database/tests/test_database.py src/vaultspec_a2a/database/tests/test_migrations.py src/vaultspec_a2a/core/tests/test_state.py src/vaultspec_a2a/core/tests/test_supervisor.py src/vaultspec_a2a/api/schemas/tests/test_schemas.py -q`
  - result: `161 passed`

Review finding:

- This is still not full closure because the live Postgres restart/reconnect
  suite does not yet prove plan approval discovery, duplicate response
  idempotency, and resume semantics across gateway/worker restart.

Recommendation:

- Mark the durable approval-state task as `PARTIAL` until the Phase 2 live
  recovery suite covers approval pause/resume across restart using the real
  Postgres-backed gateway+worker stack.

### 2026-03-09 17:31 - High - The first live Postgres paused-thread recovery test now exists, but certifying `input_required` restart semantics is blocked by provider credential readiness in the live environment

- A dedicated live Postgres recovery test now exists at
  `src/vaultspec_a2a/tests/test_permission_durability_live.py`.
- The test uses the real subprocess stack, a real temporary workspace, a real
  `.vault/plan/<feature>-plan.md` artifact, and a workspace-local team override
  so the approval path runs through one explicit provider configuration instead
  of the bundled mixed-provider defaults.
- Review of the initial live execution found that the local environment has no
  `OPENAI_API_KEY` / `VAULTSPEC_OPENAI_API_KEY`, so the slice cannot yet prove
  paused-thread restart semantics end to end.
- The test now hard-fails immediately on missing provider credentials instead of
  hanging for two minutes while the thread remains `submitted`. This is the
  correct behavior under the repository’s no-skip/no-fake testing mandate, but
  it means the verification claim remains open.

Impact:

- The recovery suite is now structurally correct for certifying paused-thread
  durability on the Postgres stack, and it no longer produces ambiguous
  timeouts when provider readiness is missing.
- However, `#67` is still not closed because the required live provider path is
  not yet wired in this environment or CI, so the restart-stable
  `input_required` claim is still unproven.

Evidence:

- `src/vaultspec_a2a/tests/test_permission_durability_live.py`: real
  gateway+worker+Postgres paused-thread recovery test with real workspace
  override and hard-fail provider precondition.
- `docs/research/2026-03-09-postgres-persistence-grounding.md`: grounding note
  extended for the paused-thread live recovery slice and the provider override
  decision.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/tests/test_permission_durability_live.py`
  - `uv run pytest src/vaultspec_a2a/tests/test_permission_durability_live.py -m live -q`
  - result: hard failure with `OPENAI_API_KEY` / `VAULTSPEC_OPENAI_API_KEY`
    missing, by design

Review finding:

- The live recovery suite needs an explicit provider-readiness track for CI and
  developer environments. Without that, the repo can truthfully claim that the
  verification path exists, but not that the paused-thread restart semantics are
  yet proven in a certifying environment.

Recommendation:

- Mark `#67` as `PARTIAL`.
- Add a follow-up task for live-provider readiness and secret wiring so the
  paused-thread, running-thread, and cancelling-thread Postgres recovery suites
  can execute as real PR-gate candidates.

### 2026-03-09 17:45 - High - Live provider readiness is now executable, and it exposed the real blocker: the OpenAI credential resolves but fails the certifying probe with `429 insufficient_quota`

- The repo now has explicit executable targets for provider readiness and the
  Postgres recovery suite:
  - `just verify-live-provider openai`
  - `just verify-live-recovery-postgres`
- The paused-thread recovery test no longer checks only for the presence of an
  env var. It now requires the real OpenAI provider probe to pass before the
  live Postgres recovery scenario is allowed to proceed.
- Verification of the new target showed that this environment does have an
  OpenAI credential, but the real probe fails with `429 Too Many Requests` and
  `code=insufficient_quota`.

Impact:

- The blocker is now correctly classified as provider readiness, not “missing
  key” or “test harness flake”.
- The live recovery suite now fails for the same reason production-shaped work
  would fail: the configured provider path is not actually usable at runtime.

Evidence:

- `Justfile`: added `verify-live-provider` and
  `verify-live-recovery-postgres`.
- `src/vaultspec_a2a/tests/test_permission_durability_live.py`: now depends on
  the real OpenAI probe result rather than only env-var presence.
- Verification on 2026-03-09:
  - `just verify-live-provider openai`
  - result: hard failure from the real OpenAI probe with `429
    insufficient_quota`
  - `uv run pytest src/vaultspec_a2a/tests/test_permission_durability_live.py -m live -q`
  - result: hard failure with the probe output surfaced directly in the test
    failure

Review finding:

- `#77` is now a real implementation track, not a placeholder. It remains open
  because provider secret/billing readiness is still not sufficient for
  certifying live Postgres recovery in this environment.

Recommendation:

- Mark `#77` as `PARTIAL`.
- Treat provider quota/billing health as part of the certifying readiness
  contract for live Postgres recovery suites, not as an out-of-band operator
  assumption.

### 2026-03-09 18:40 - High - Provider readiness is no longer the blocker; the live Postgres approval-recovery path remains durably `submitted` and never reaches a real approval pause

- The certifying provider path is now provider-agnostic instead of OpenAI-only:
  - `src/vaultspec_a2a/providers/probes/certifying.py` selects the first
    healthy real provider by running the existing real probes.
  - `just verify-live-provider-certifying` now passes in this environment and
    selects `claude`.
  - `Justfile` wires `verify-live-recovery-postgres` through that selector.
- The paused-thread recovery suite was updated to consume the selected real
  provider and to use a more deterministic workspace-local team override for
  the approval scenario.
- Real verification removed the provider-readiness blocker, but the live
  Postgres approval path still does not reach `input_required`.
- After creating the thread with a healthy real Claude provider, the final
  observed snapshot remained:
  - `status='submitted'`
  - `approval_status=None`
  - `pause_cause=None`
  - `pending_permissions=0`
  - `repair_status='healthy'`
  - `execution_readiness='healthy'`

Impact:

- `#77` is no longer the active blocker for Phase 2 in this environment; a
  certifying live provider is available and executable.
- The active blocker is now the submission-to-running/interrupt path for the
  live approval scenario.
- This is a stronger and more actionable finding than the previous provider
  readiness issue because it exposes a real runtime truth gap in the
  Postgres-backed workflow path.

Evidence:

- `src/vaultspec_a2a/providers/probes/certifying.py`
- `src/vaultspec_a2a/tests/test_permission_durability_live.py`
- `Justfile`
- Verification on 2026-03-09:
  - `just verify-live-provider-certifying`
  - result: `claude`
  - `uv run pytest src/vaultspec_a2a/tests/test_crash_recovery.py -m live -q`
  - result: `4 passed`
  - `VAULTSPEC_LIVE_TEST_PROVIDER=claude uv run pytest src/vaultspec_a2a/tests/test_permission_durability_live.py -m live -q`
  - result: hard failure with `thread not yet paused for durable plan approval (status='submitted', approval_status=None, pause_cause=None, pending_permissions=0, repair_status='healthy', execution_readiness='healthy')`

Review finding:

- The new paused-thread live suite is structurally sound enough to classify the
  next defect. The remaining failure is now the lack of durable execution
  progress/interrupt truth on the actual live approval path, not test harness
  setup or provider availability.

Recommendation:

- Mark `#77` as `FIXED`.
- Keep `#67` as `PARTIAL`.
- Add a new follow-up task for the live approval path remaining durably
  `submitted` with no progress/interrupt evidence, and treat that as the next
  Phase 2 implementation target.

### 2026-03-09 19:15 - High - The paused-thread Postgres recovery path is now proven live; the real defects were interrupt outcome classification and gateway-side permission projection drift

- Grounding against the current LangGraph interrupt docs confirmed that durable
  pauses are guaranteed through checkpoint state / `__interrupt__`, not through
  any single `GraphInterrupt` exception shape on every streaming path.
- The first live defect was in the worker outcome classifier:
  - the aggregator emitted the durable plan-approval request from
    `aget_state(config).tasks[*].interrupts`
  - but still returned `"completed"` when `astream_events` ended without a
    caught `GraphInterrupt`
  - the executor therefore emitted a terminal status and the gateway persisted
    `completed` over a paused workflow
- The second live defect was gateway-side projection drift:
  - `sync_worker_event()` rebuilt pending permissions without preserving
    `tool_call`
  - durable snapshot enrichment collapsed the pause cause to the generic
    `"permission_request"` instead of the documented
    `"plan_approval_request"` cause
- Review of the fix surfaced one more edge and it was fixed in the same slice:
  if checkpoint state shows a pending interrupt but the interrupt payload is
  unreadable/untyped, the aggregator still classifies the run as interrupted
  instead of incorrectly finalizing it as completed.

Impact:

- The real paused-thread Phase 2 claim is now proven on the live Postgres path:
  a thread can reach durable `input_required`, preserve the stable approval
  request across gateway restart, and accept an idempotent duplicate approval
  response retry.
- The Phase 2 blocker has moved forward. The remaining live recovery gap is no
  longer plan approval on the paused-thread path; it is the rest of `#67`:
  pre-existing `running` and `cancelling` thread recovery semantics across
  restart.

Evidence:

- `src/vaultspec_a2a/core/aggregator.py`: interrupt outcome now derives from
  post-run checkpoint truth and preserves stable interrupt/request IDs;
  degraded unreadable interrupts still win over terminal completion.
- `src/vaultspec_a2a/api/internal.py`: durable permission recording now keeps
  the documented plan-approval pause cause and durable approval linkage.
- `src/vaultspec_a2a/core/aggregator.py`: relayed worker permission events now
  preserve `tool_call` in gateway memory.
- `src/vaultspec_a2a/api/projection.py`: durable snapshots preserve
  `pause_cause="plan_approval_request"` and stable approval linkage from the DB.
- `src/vaultspec_a2a/api/endpoints.py`: permission resume logic now treats both
  legacy and documented plan-approval pause-cause values as approval pauses.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/core/aggregator.py src/vaultspec_a2a/api/internal.py src/vaultspec_a2a/api/projection.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/tests/test_permission_durability_live.py`
  - `uv run pytest src/vaultspec_a2a/api/tests/test_projection.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/tests/test_internal.py -q`
  - `uv run pytest src/vaultspec_a2a/tests/test_permission_durability_live.py -m live -k plan_approval_survives_gateway_restart_and_response_retry -q`
  - results: `43 passed` and `1 passed`

Review finding:

- No new open blocker was introduced by this fix slice.
- The only review-surfaced issue in the diff was the unreadable-interrupt edge,
  and that was fixed before closure.

Recommendation:

- Mark `#78` as `FIXED`.
- Keep `#67` as `PARTIAL`, but narrow it to the remaining live recovery claims
  for pre-existing `running` and `cancelling` threads across restart.
- Continue directly into the next Phase 2 slice rather than reopening the
  paused-thread approval track.

### 2026-03-09 19:40 - High - Live Postgres restart recovery is now proven for pre-existing `running`, `input_required`, and `cancelling` threads; the remaining Phase 2 work has moved to replay/degradation coverage rather than restart classification

- Grounding for this slice confirmed that the existing health split is the
  correct contract:
  - `/health` is liveness
  - `/api/health` is aggregate readiness
- The first review-surfaced issue in the new live reconciliation suite was a
  harness defect, not a product defect:
  - the generic restart helper always waited for `/api/health == ok`
  - that is wrong for the `cancelling` recovery scenario where the worker is
    intentionally stopped so the gateway can surface `cancel_pending` repair
    truth while aggregate readiness is still degraded
- The helper was fixed in the same slice to allow scenario-specific liveness vs
  readiness waits, and the `cancelling` suite now waits on `/health` before
  asserting thread repair state.

Impact:

- The core restart-classification claim in `#67` is now proven on the live
  Postgres path:
  - pre-existing paused approval threads remain durably `input_required`
  - pre-existing running threads are reconstructed as
    `reconciling/needs_reconciliation`
  - pre-existing cancelling threads are reconstructed as
    `cancelling/cancel_pending`
- Phase 2 is no longer blocked on basic restart repair semantics. The remaining
  live-verification work has shifted to replay/degradation behavior and the
  broader partial/skipped test cleanup queue.

Evidence:

- `src/vaultspec_a2a/tests/test_permission_durability_live.py`: gateway restart
  helper now supports explicit liveness vs readiness waits for live Postgres
  restart scenarios.
- `src/vaultspec_a2a/tests/test_reconciliation_live.py`: new live Postgres
  suites prove restart reconciliation for pre-existing `running` and
  `cancelling` threads using real gateway, real worker, live Postgres, and a
  real healthy provider override.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/tests/test_permission_durability_live.py src/vaultspec_a2a/tests/test_reconciliation_live.py`
  - `uv run pytest src/vaultspec_a2a/tests/test_reconciliation_live.py -m live -q`
  - results: `2 passed`

Review finding:

- No new open product defect remained at the end of the slice.
- The only review-surfaced issue was the helper-level liveness/readiness
  assumption, and that was fixed before closure.

Recommendation:

- Mark `#67` as `FIXED`.
- Continue Phase 2 with replay/reconnect and snapshot-degradation verification,
  not more restart-classification work.

### 2026-03-09 20:00 - High - Live degraded snapshot behavior is now proven against a real checkpoint-backend outage; the review-surfaced defect was replay-status misclassification and it was fixed in the same slice

- Grounding for this slice confirmed the intended contract boundary:
  - LangGraph checkpoints/state history are the durable execution recovery
    surface
  - WebSocket transport itself does not imply durable replay after reconnect
  - a checkpoint reader failure must therefore be surfaced explicitly, not
    silently mapped onto the same semantics as a missing checkpoint
- The live test used two real Postgres containers:
  - one for the app-owned database
  - one for the checkpoint backend
- That allowed a real failure mode:
  - create a real paused approval thread
  - stop only the checkpoint Postgres container
  - fetch the reconnect snapshot while the app DB remains available

Review finding:

- The first live run exposed a real product defect:
  - the endpoint correctly marked checkpoint-read failures as
    `replay_status="unknown"` inside the exception path
  - but then the final fallback logic overwrote that result to
    `replay_status="gap_detected"` whenever no checkpoint tuple was present and
    the thread was non-terminal
- That collapsed two materially different states into one client-facing
  classification:
  - reader failure / unknown replay truth
  - checkpoint missing / gap detected

Fix:

- Snapshot replay/degradation finalization is now centralized so explicit
  checkpoint read failures keep `replay_status="unknown"` instead of being
  overwritten to `gap_detected`.

Impact:

- The gateway now correctly returns an explicitly degraded snapshot when the
  checkpoint backend is unavailable while preserving durable paused-thread truth
  from the app DB.
- This closes the audit item that snapshot failure paths must not surface
  misleading false-empty truth.
- The remaining Phase 2 gap is now narrower:
  there is still no certifying live reconnect/replay suite for actual WebSocket
  disconnect and resubscribe behavior.

Evidence:

- `src/vaultspec_a2a/tests/test_snapshot_degradation_live.py`: new live
  two-Postgres outage test covering checkpoint-backend loss with the app DB
  still available.
- `src/vaultspec_a2a/api/endpoints.py`: replay/degradation finalization now
  preserves explicit checkpoint failure classification.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/tests/test_snapshot_degradation_live.py`
  - `uv run pytest src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/tests/test_snapshot_degradation_live.py -m "not live or live" -q`
  - results: `25 passed`

Recommendation:

- Add a new queue item for the still-missing live reconnect/replay verification.
- Mark the explicit snapshot-degradation verification gap as `FIXED`.

### 2026-03-09 20:20 - High - Live WebSocket reconnect behavior is now proven against the Postgres stack; the gateway contract is snapshot recovery, not implicit replay of missed frames

- Grounding for this slice confirmed that the missing test needed a real
  WebSocket client:
  - FastAPI documents connection/disconnect handling, not replay semantics
  - the gateway connection manager emits `ConnectedEvent` and routes live
    subscribed events, but does not implement a durable missed-frame replay
    layer
- The repository now uses a real asyncio WebSocket client in the live suite via
  the `websockets` library.
- The certifying test proves the actual contract:
  - receive a real thread-scoped event over `/ws`
  - confirm `/api/threads/{id}/state` has durably caught up with
    `last_sequence >= observed_event.sequence`
  - disconnect
  - stop the worker so no new events can be produced
  - reconnect and verify the client gets `ConnectedEvent` plus durable snapshot
    recovery, not an implicit replay of the already-accounted-for thread event

Impact:

- The Phase 2 replay/reconnect gap is now materially smaller. There is a live
  Postgres test proving that reconnect correctness depends on the durable
  snapshot cursor, not on magical replay of missed WebSocket frames.
- This aligns the implementation with the documented contract and removes a
  major frontend-facing ambiguity.

Evidence:

- `pyproject.toml` / `uv.lock`: added the real `websockets` dev dependency for
  live `/ws` verification.
- `src/vaultspec_a2a/tests/test_replay_reconnect_live.py`: new live Postgres
  reconnect suite using a real WebSocket client against the running gateway.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/tests/test_replay_reconnect_live.py`
  - `uv run pytest src/vaultspec_a2a/tests/test_replay_reconnect_live.py -m live -q`
  - result: `1 passed`

Review finding:

- No new open product defect remained in this slice.
- The implementation conclusion is that the contract is now explicitly proven
  as snapshot-based recovery, not WebSocket-frame replay.

Recommendation:

- Mark the live reconnect/replay verification task as `FIXED`.
- Continue from here into the remaining partial/skipped test cleanup track.

### 2026-03-09 22:35 - Medium - The no-doubles test audit was stale; the remaining cleanup targets are narrower and different than the original queue implied

- A fresh audit of the current MCP/worker/core suites shows several original mock-removal tasks were already materially closed, while the real remaining gaps have shifted.
- `protocols/mcp/tests/test_server.py` no longer uses `MemorySaver` or `MockTransport`; this slice removed the last private-state forcing (`spawner._spawned = True`) by switching the test to the public `LazyWorkerSpawner.replace_process(None)` API.
- `worker/tests/test_executor.py` no longer needs `object.__new__(Executor)` to reach `_build_graph_input`; the production helper is now a static method and the tests call it directly.
- The real remaining no-doubles gaps are now concentrated in `core/tests/test_supervisor.py` (`_StubChatModel`) and `core/tests/test_graph.py` (`Provider.MOCK` coverage), not the older `MockTransport` / `unittest.mock` references cited by the stale audit.

Impact:

- The partial/skipped cleanup queue cannot be executed safely from stale audit assumptions; it needs a refreshed source-of-truth or it will optimize the wrong tests.
- The MCP and worker test surfaces are materially cleaner than the old queue suggested, but the core graph/supervisor tests still violate the repository's stricter no-doubles mandate.

Evidence:

- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`: uses `AsyncSqliteSaver`, `ASGITransport`, and now `LazyWorkerSpawner.replace_process(None)` instead of private `_spawned` mutation.
- `src/vaultspec_a2a/worker/executor.py`: `_build_graph_input()` is now a `@staticmethod`.
- `src/vaultspec_a2a/worker/tests/test_executor.py`: removed `object.__new__(Executor)` bypass and now calls `Executor._build_graph_input(...)` directly.
- `src/vaultspec_a2a/core/tests/test_supervisor.py`: still defines `_StubChatModel`.
- `src/vaultspec_a2a/core/tests/test_graph.py`: still uses `Provider.MOCK`.
- Grounding for this refresh is captured in `docs/research/2026-03-09-postgres-persistence-grounding.md`.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/worker/executor.py src/vaultspec_a2a/worker/tests/test_executor.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
  - `uv run pytest src/vaultspec_a2a/worker/tests/test_executor.py src/vaultspec_a2a/protocols/mcp/tests/test_server.py -q`
  - result: `63 passed`

Recommendation:

- Refresh the consolidated queue statuses for `#57`, `#59`, `#64`, and `#66`.
- Retarget the remaining cleanup work toward supervisor/model doubles and any residual provider-mock coverage instead of re-solving already-closed MockTransport/MemorySaver issues.

### 2026-03-09 22:50 - Medium - The graph-side no-doubles cleanup is now closed; the remaining core gap is isolated to the supervisor model-double path

- The old `Provider.MOCK` coverage in `core/tests/test_graph.py` is gone.
- This slice split worker-model preference resolution from provider construction so tests can verify precedence/fallback behavior without instantiating a fake provider.
- The same slice also extracted deterministic supervisor decision helpers in production code, which reduces the remaining supervisor cleanup to the actual model-invocation path instead of all routing logic.

Impact:

- `#58` can now be closed as a stale no-doubles finding.
- The remaining core cleanup work is narrower: `test_supervisor.py` still depends on `_StubChatModel`, but graph preference coverage no longer relies on `Provider.MOCK`.

Evidence:

- `src/vaultspec_a2a/core/graph.py`: `_resolve_worker_model_preferences(...)` now owns provider/capability/fallback precedence; `_resolve_model_for_worker(...)` only performs real provider construction on top of that decision.
- `src/vaultspec_a2a/core/tests/test_graph.py`: replaced the old `Provider.MOCK` test with a pure precedence assertion over worker overrides.
- `src/vaultspec_a2a/core/nodes/supervisor.py`: added `_evaluate_supervisor_response(...)` and `_build_supervisor_messages(...)` to isolate deterministic routing/gating logic from the actual model call.
- Verification on 2026-03-09:
  - `uv run ruff check src/vaultspec_a2a/core/graph.py src/vaultspec_a2a/core/tests/test_graph.py src/vaultspec_a2a/core/nodes/supervisor.py`
  - `uv run pytest src/vaultspec_a2a/core/tests/test_graph.py -k "resolve_worker_model_preferences_honors_worker_override_precedence or compile_graph_structure or compile_team_graph_accepts_workspace_root or compile_interrupt_before_always_empty or compile_unknown_topology_raises" -q`
  - result: `9 passed`

Recommendation:

- Close `#58`.
- Continue the same helper-extraction approach for `#66`, but treat the remaining `_StubChatModel` dependency as a separate supervisor-only problem rather than a graph/compiler problem.

### 2026-03-10 00:20 - Medium - Supervisor verification in this environment is being masked by shell-profile side effects and `uv` cache permission failures, not just by product code

- Re-running the supervisor slice exposed a repeated tooling-level failure before the actual supervisor assertions could be evaluated cleanly.
- The command runner is still sourcing a PowerShell profile that tries to write terminal-icon preference files outside the writable roots, which emits repeated `Access is denied` noise on every shell invocation.
- Separately, `uv run ...` attempts to persist interpreter/cache state outside the writable area or into a workspace-local cache path that still fails under the current wrapper, producing `Access is denied` before the product-level supervisor test result can be trusted.

Impact:

- The supervisor cleanup loop now has two layers of risk:
  - real remaining code debt in `core/tests/test_supervisor.py`
  - repeated false-negative verification noise from the shell/runner environment
- This is the second time the same class of command-environment failure has surfaced, so it must be treated as an investigated workflow issue rather than incidental noise.

Evidence:

- Repeated shell output during 2026-03-10 verification attempts:
  - `Export-Clixml ... Access to the path ... is denied`
  - `Set-PSReadLineOption ... The predictive suggestion feature cannot be enabled`
  - `uv ... Failed to persist temporary file ... Access is denied`
- The persisted cleanup work before this blocker remains on disk:
  - `src/vaultspec_a2a/core/graph.py`
  - `src/vaultspec_a2a/core/nodes/supervisor.py`
  - `src/vaultspec_a2a/core/tests/test_graph.py`

Recommendation:

- Treat `uv`-based verification under the current shell wrapper as unreliable until it is run with a truly profile-free shell or replaced by direct `.venv\\Scripts\\python.exe -m pytest` / `-m ruff`.
- Keep the supervisor cleanup work moving, but record verification mode explicitly when the runner environment is the limiting factor instead of the application code.

### 2026-03-10 10:30 - Medium - The supervisor no-doubles cleanup is now closed, but the remaining core model-double debt has moved into other core test modules

- Grounding for this slice used current LangChain and LangGraph docs via Context7 plus the repo's own temp/cache-safe verification recipes.
- `core/tests/test_supervisor.py` no longer uses `_StubChatModel` or an in-memory checkpointer path.
- The suite now validates deterministic supervisor behavior directly through production helpers:
  - `_evaluate_supervisor_response(...)`
  - `_build_supervisor_messages(...)`
- `Justfile` now has `verify-core`, which applies the repo-local temp/cache isolation pattern already used by other verification targets and makes the graph/supervisor slice runnable without the earlier `tmp_path`/cache-root failure mode.

Impact:

- `#66` is now materially fixed.
- The shell/profile noise still exists, but the supervisor/core verification path now succeeds despite it.
- The no-doubles cleanup trail is not actually complete after this fix: the remaining core model-double debt now sits in other test modules rather than `core/tests/test_supervisor.py`.

Evidence:

- `src/vaultspec_a2a/core/tests/test_supervisor.py`: rewritten around deterministic production helpers; `_StubChatModel` removed.
- `Justfile`: added `verify-core` with repo-local `TMP/TEMP/TMPDIR`, `PYTEST_DEBUG_TEMPROOT`, `cache_dir`, and `--basetemp` wiring.
- Verification on 2026-03-10:
  - `.venv\\Scripts\\python.exe -m ruff check src\\vaultspec_a2a\\core\\tests\\test_supervisor.py src\\vaultspec_a2a\\core\\nodes\\supervisor.py`
  - `just verify-core`
  - result: `55 passed, 1 deselected`

Review finding:

- New follow-up required: the remaining core no-doubles violations are now in
  `core/nodes/tests/test_supervisor.py`, `core/nodes/tests/test_worker.py`, and
  `core/tests/test_worker.py`, which still use LangChain fake-model or custom
  model-double patterns.

Recommendation:

- Mark `#66` fixed.
- Add a new queue item for the remaining core model-double cleanup outside the
  graph/supervisor deterministic-helper surface.

### 2026-03-10 14:15 - Medium - Core node/worker no-doubles cleanup is now closed; the remaining hard-mandate test gaps are outside the old fake-model core slice

- Grounding for this slice used current LangChain and LangGraph docs via
  Context7, focused on whether fake chat models are optional test utilities or
  required for deterministic coverage.
- The answer was clear: fake chat models are library-supported testing tools,
  but not required for the deterministic routing, prompt-building,
  permission-wiring, or worker-error surfaces under test here.
- Production code now exposes deterministic worker helpers in
  `core/nodes/worker.py`:
  - `_build_worker_messages(...)`
  - `_resolve_effective_worker_model(...)`
  - `_wrap_worker_exception(...)`
  - `_finalize_worker_response(...)`
- The remaining `#81` files were rewritten around those helpers and real model
  types instead of fake-model/local-subclass patterns.

Impact:

- `#81` is now materially fixed.
- The targeted core suites no longer use `FakeListChatModel`,
  `_GraphInterruptModel`, `_AlwaysFailModel`, or `_StubChatModel`.
- Real ACP invocation coverage remains intact through
  `core/nodes/tests/test_worker_integration.py`, which still passes.

Evidence:

- `src/vaultspec_a2a/core/nodes/tests/test_supervisor.py`
  - now validates deterministic supervisor helper behavior directly
- `src/vaultspec_a2a/core/nodes/tests/test_worker.py`
  - now validates worker message building, callback wiring, and response
    finalization via production helpers and real `AcpChatModel` /
    `ChatOpenAI` instances
- `src/vaultspec_a2a/core/tests/test_worker.py`
  - now validates worker exception wrapping through `_wrap_worker_exception(...)`
    instead of local `BaseChatModel` subclasses
- `Justfile`
  - `verify-core` now includes the node-level supervisor/worker suites in the
    repo-safe temp/cache verification path
- Verification on 2026-03-10:
  - `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\core\nodes\worker.py src\vaultspec_a2a\core\nodes\tests\test_supervisor.py src\vaultspec_a2a\core\nodes\tests\test_worker.py src\vaultspec_a2a\core\tests\test_worker.py`
  - `just verify-core`
  - `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\core\nodes\tests\test_worker_integration.py -q`
  - results: `78 passed, 1 deselected` and `3 passed`

Review outcome:

- No new product defect was surfaced in this slice.
- The remaining hard-mandate test gaps now sit in other audit items
  (`#57`, `#60`, `#35`, `#36`) rather than the old core fake-model cluster.

Recommendation:

- Mark `#81` fixed.
- Continue with the next promoted verification gap, prioritizing live MCP/IPC
  integration work over more core-helper refactoring.

### 2026-03-10 18:20 - Medium - Live Postgres IPC heartbeat and MCP stdio verification are now closed on the certifying path

- Grounding for this slice used current MCP Python SDK and HTTPX docs via
  Context7, plus the existing Postgres-backed subprocess harness already used by
  the restart/recovery suites.
- The new live tests are now on disk and passing against the real stack:
  - `src/vaultspec_a2a/tests/test_ipc_heartbeat_live.py`
  - `src/vaultspec_a2a/tests/test_mcp_e2e_live.py`
- The IPC suite originally exposed a real contract mismatch in the test design:
  waiting for provider-driven autonomous completion was too nondeterministic for
  a certifying live suite. The test now proves the intended contract directly:
  worker heartbeat marks the thread active, a real cancel request is accepted,
  the thread moves into visible `cancelling`/terminal truth, and the
  heartbeat-derived `active_threads` set clears.
- The MCP suite originally exposed a real parser mismatch in the test:
  MCP output uses the current 32-character hex thread IDs, not only hyphenated
  UUIDs. The test now accepts the real emitted ID format and validates the live
  stdio tool surface end to end.

Impact:

- `#35` is now materially fixed.
- `#36` is now materially fixed.
- The live verification surface for the promoted no-doubles queue is stronger:
  both IPC heartbeat truth and MCP stdio control flow are now proven against
  live gateway + worker + Postgres processes instead of inferred from the
  in-process harness.
- The remaining MCP-related hard-mandate cleanup is no longer missing live E2E
  coverage; it has narrowed to the separate in-process policy question tracked
  in `#57`.

Evidence:

- `src/vaultspec_a2a/tests/test_ipc_heartbeat_live.py`
  - proves `/health` + `/api/team/status` active-thread truth, real cancel
    semantics, and eventual active-thread clearing
- `src/vaultspec_a2a/tests/test_mcp_e2e_live.py`
  - launches the real MCP stdio server, initializes a real `ClientSession`,
    lists tools, starts a real thread, and reads its live status through the
    gateway
- `Justfile`
  - `verify-live-orchestration` now runs the certifying Postgres-backed live
    IPC + MCP slice
- Verification on 2026-03-10:
  - `.\\.venv\\Scripts\\python.exe -m ruff check src\\vaultspec_a2a\\tests\\test_mcp_e2e_live.py src\\vaultspec_a2a\\tests\\test_ipc_heartbeat_live.py`
  - `.\\.venv\\Scripts\\python.exe -m pytest src\\vaultspec_a2a\\api\\tests\\test_endpoints.py -q`
  - `.\\.venv\\Scripts\\python.exe -m pytest src\\vaultspec_a2a\\tests\\test_ipc_heartbeat_live.py src\\vaultspec_a2a\\tests\\test_mcp_e2e_live.py -m live -q`
  - results: `24 passed` and `2 passed`

Review outcome:

- No new product defect was surfaced after the final live fixes.
- The only remaining MCP/test-policy question from this cluster is `#57`
  (`dependency_overrides` under the repo's hard no-patches rule), not the live
  orchestration path itself.

Recommendation:

- Mark `#35` fixed.
- Mark `#36` fixed.
- Continue with the remaining partial/skipped queue, starting with `#57` and
  `#60`.

### 2026-03-10 18:35 - Medium - Provider-factory skip debt is now closed, and the remaining skip-policy drift has narrowed to CLI stale-PID tests

- Grounding for this slice used current pytest skip guidance plus the actual
  provider-factory implementation contract in `providers/factory.py`.
- The key finding was that the remaining Claude binary-backend tests did not
  need skips at all. The production code already defines a truthful negative
  contract: `backend="binary"` without a bundled executable raises
  `ConfigError`.
- `providers/tests/test_factory.py` now asserts that real contract in both
  environments:
  - if the bundled binary exists, the tests assert the positive command/env/use-exec
    behavior
  - if the bundled binary does not exist, the tests assert `ConfigError`
    instead of disappearing from the suite

Impact:

- The provider-factory portion of `#60` is now fixed.
- The global skip scan is much narrower than the old audit state implied.
- The remaining live code skip debt is no longer in provider tests; it is now
  isolated to two CLI stale-PID tests that still use `pytest.skip()` when their
  chosen "dead" PID unexpectedly exists on the current machine.

Evidence:

- `src/vaultspec_a2a/providers/tests/test_factory.py`
  - binary-backend tests now assert either success or the real `ConfigError`
    failure contract
- Verification on 2026-03-10:
  - `.\\.venv\\Scripts\\python.exe -m ruff check src\\vaultspec_a2a\\providers\\tests\\test_factory.py`
  - `.\\.venv\\Scripts\\python.exe -m pytest src\\vaultspec_a2a\\providers\\tests\\test_factory.py -q`
  - results: `19 passed, 4 deselected`
- Global skip scan after the fix:
  - remaining hits are only
    `src/vaultspec_a2a/cli/tests/test_service.py:129` and `:160`

Review finding:

- New follow-up required: the stale-PID tests in
  `src/vaultspec_a2a/cli/tests/test_service.py` still use skip-based escape
  hatches and should be rewritten around a deterministically dead PID strategy.

Recommendation:

- Keep `#60` open only for the remaining CLI stale-PID tests, not the provider
  factory suite.
- Add a new queue item for the CLI skip cleanup so the debt is explicit.

### 2026-03-10 18:50 - Medium - Skip-policy cleanup is now complete in code, but CLI suite verification is blocked by a separate pytest tmp-path cleanup failure

- The CLI stale-PID tests no longer rely on a hard-coded "dead" PID plus
  `pytest.skip()`.
- They now generate a real dead PID by spawning a short-lived Python child
  process, waiting for it to exit, and reusing that PID for the stale-record
  assertions.
- A full source scan of `src/vaultspec_a2a` now returns no remaining
  `pytest.skip`, `skipif`, or `xfail` usage.

Impact:

- `#60` is now materially fixed.
- `#82` is now materially fixed.
- The review surfaced a new workflow issue unrelated to the skip-removal logic:
  the CLI test module cannot currently complete under this execution
  environment because pytest fails during `tmp_path` fixture setup/cleanup with
  `PermissionError` on the chosen `basetemp` directory before the test bodies
  run.

Evidence:

- `src/vaultspec_a2a/cli/tests/test_service.py`
  - stale-PID tests now use a real exited child-process PID instead of
    `pytest.skip()`
- Verification on 2026-03-10:
  - `.\\.venv\\Scripts\\python.exe -m ruff check src\\vaultspec_a2a\\cli\\tests\\test_service.py`
  - source scan:
    `rg -n "pytest\\.skip|@pytest\\.mark\\.skip|skipif|xfail" src/vaultspec_a2a -g "*.py"`
  - result: lint passed, skip scan returned no matches
- Attempted module verification:
  - `.\\.venv\\Scripts\\python.exe -m pytest src\\vaultspec_a2a\\cli\\tests\\test_service.py ...`
  - repeated result: `PermissionError` during pytest tmp-path setup/cleanup,
    before the test bodies execute

Review finding:

- New follow-up required: the CLI verification path is now blocked by a pytest
  temp-root/cleanup failure in this Windows environment, and that needs to be
  investigated separately from the test logic.

Recommendation:

- Mark `#60` fixed.
- Mark `#82` fixed.
- Add a new task for the pytest tmp-path cleanup failure that is blocking CLI
  suite verification.

### 2026-03-10 18:45 - Medium - The MCP/API dependency-override policy gap is now closed; the remaining temp-root failure is isolated to CLI verification

- The in-process API and MCP fixtures now inject real dependencies through
  `app.state` instead of `app.dependency_overrides`.
- `get_db(request: Request)` now reads `request.app.state.db_session_factory`
  when present, which gives the test app a production-shaped injection seam
  instead of a test-only override dict.
- The MCP test module was also moved off `tmp_path` and onto repo-local `.tmp`
  directories for its checkpointer and workspace-root fixtures.

Evidence:

- `src/vaultspec_a2a/database/session.py`
- `src/vaultspec_a2a/api/tests/conftest.py`
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\database\session.py src\vaultspec_a2a\api\tests\conftest.py src\vaultspec_a2a\protocols\mcp\tests\test_server.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py -q`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\protocols\mcp\tests\test_server.py -q`
- results: `41 passed` and `38 passed`

Review outcome:

- No new product defect was surfaced by the app-state DB seam.
- The old `#57` policy question is now resolved in code and verification.
- The separate runner issue `#83` remains real, but it is now narrowed to the
  CLI test module rather than the MCP path.

### 2026-03-10 20:05 - Medium - API harness closeout removes the last in-memory SQLite drift from `#56`

- Grounding for this closeout used the current FastAPI testing guidance and
  SQLAlchemy async-engine documentation: official patterns permit test-time DI
  seams and SQLite usage, but this repo's stricter no-doubles policy still
  rejects `:memory:` databases where the production path is file- or
  service-backed.
- The remaining `#56` drift was no longer mocks or overrides. It was the
  API-side use of in-memory SQLite in `api/tests/conftest.py` and one
  projection test case.
- The API harness now uses isolated file-backed SQLite databases under the
  repo-approved writable memory root, while keeping the real `AsyncSqliteSaver`
  and in-process ASGI worker path already established in earlier passes.

Evidence:

- `src/vaultspec_a2a/api/tests/conftest.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/api/tests/test_projection.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\api\tests\conftest.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_projection.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_internal.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- Result: `49 passed`

Review outcome:

- No new product defect surfaced in the `#56` closeout diff.
- The API test harness now satisfies the current repo mandate for this slice:
  no `MockTransport`, no `MemorySaver`, no `dependency_overrides`, and no
  in-memory SQLite persistence on the API path.

### 2026-03-10 00:30 - Medium - Worker supervision now preserves durable stderr diagnostics across restart cycles

- Grounding for this slice used the official Python subprocess documentation.
  The key constraint is that long-lived `stderr=PIPE` ownership is the wrong
  authority for crash diagnostics here: it either requires a dedicated draining
  loop or it leaves later worker crashes with only a bare return code.
- The gateway supervision path now redirects auto-spawned worker stderr to a
  deterministic repo-local runtime log and latches that path into both health
  surfaces and watchdog restart records.
- `/health` and `/api/health` now expose `worker_stderr_log_path`, and the
  watchdog's `worker_last_restart_detail` now includes `stderr_log=...` plus a
  compact stderr tail when there is crash output to read.

Evidence:

- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/api/endpoints.py`
- `src/vaultspec_a2a/api/tests/test_app.py`
- `src/vaultspec_a2a/tests/test_crash_recovery.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\api\app.py src\vaultspec_a2a\api\endpoints.py src\vaultspec_a2a\api\tests\test_app.py src\vaultspec_a2a\tests\test_crash_recovery.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_app.py src\vaultspec_a2a\api\tests\test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- elevated live Postgres verification:
  `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_crash_recovery.py -m live -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- Results: `27 passed` and `4 passed`

Review findings:

- First pass defect: the new diagnostic path was added only to `/health`, while
  the API-side verification and operator readiness flow also consume
  `/api/health`. Fixed in-slice by exposing the same field there.
- First pass defect: a new helper test used `tmp_path` and re-triggered the
  known Windows cleanup failure. Fixed in-slice by moving the test path under
  the writable Codex memory root.
- No remaining product defect was surfaced after those fixes.

Recommendation:

- Mark `#52` fixed.
- Continue with the next open operational slice (`#42` or `#41`) under the
  same grounded research -> implementation -> verification -> review -> audit
  loop.

Recommendation:

- Mark `#56` fixed.
- Continue to the next open execution-plan item under the same grounded
  research -> implementation -> verification -> review -> audit loop.

Recommendation:

- Mark `#57` fixed.
- Narrow `#83` to the CLI `tmp_path`/temp-root failure only.

### 2026-03-10 18:55 - Medium - The CLI temp-root blocker is closed; the real remaining issue in that slice was a stale-PID setup assumption, and it is fixed

- `cli/tests/test_service.py` no longer depends on pytest's `tmp_path`; it now
  uses a repo-local runtime-dir fixture under `.tmp/cli-test-runtime/...`.
- The first rerun exposed a real test-design defect: on this Windows host a
  just-exited child PID was still reported as running by `_is_pid_running()`.
- The stale-PID setup was corrected to use a dynamically discovered
  non-running PID, which matches the actual CLI contract more closely.

Evidence:

- `src/vaultspec_a2a/cli/tests/test_service.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\cli\tests\test_service.py src\vaultspec_a2a\database\session.py src\vaultspec_a2a\api\tests\conftest.py src\vaultspec_a2a\protocols\mcp\tests\test_server.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\cli\tests\test_service.py -q`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\cli\tests\test_service.py src\vaultspec_a2a\protocols\mcp\tests\test_server.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py -q`
- results: `10 passed` and `89 passed`

Review outcome:

- The original `#83` runner blocker is closed for the repo.
- One real implementation-adjacent finding surfaced during the fix:
  the stale-PID test had encoded a false assumption about Windows PID liveness.
  That finding was fixed in the same slice.

Recommendation:

- Mark `#83` fixed.

### 2026-03-10 19:00 - High - Durable approval restart semantics are now proven live on Postgres; the blocked run was a Docker-access policy issue, not an application failure

- `test_permission_durability_live.py` now passes end to end against a real
  Postgres container, real gateway, and real worker when Docker access is
  available.
- The test proves:
  - a plan-approval thread reaches durable `input_required`
  - the same `approval_request_id` remains discoverable after gateway restart
  - duplicate approval responses with the same `Idempotency-Key` return the
    same action identity and action status
- Review of the first sandboxed rerun showed the failure was Docker daemon
  access denied on `//./pipe/docker_engine`, not approval-state behavior.
- The live harness now converts that bootstrap failure into an explicit
  readiness error via `_start_container_or_fail(...)`.

Evidence:

- `src/vaultspec_a2a/tests/conftest.py`
- `src/vaultspec_a2a/tests/test_permission_durability_live.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\tests\conftest.py`
- sandboxed run:
  `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_permission_durability_live.py -m live -q`
- elevated Docker-enabled run:
  `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_permission_durability_live.py -m live -q`
- result: `1 passed`

Review outcome:

- No new product defect was surfaced in the approval-state model.
- The live verification gap that kept `#70` partial is now closed.
- The only newly surfaced issue in this slice was poor Docker preflight
  diagnostics, and that was fixed in the same slice.

Recommendation:

- Mark `#70` fixed.

### 2026-03-10 19:10 - Medium - Checkpoint projection is materially richer now, but the remaining repair-truth gap has narrowed to `StateSnapshot.tasks/next`, which raw checkpointer tuples do not expose

- `src/vaultspec_a2a/database/checkpoints.py`: the runtime `Checkpointer`
  protocol now exposes `alist(...)`, which lets the gateway inspect bounded
  checkpoint history without dropping to backend-specific concrete types.
- `src/vaultspec_a2a/api/projection.py`: checkpoint projection now includes
  parent checkpoint linkage, source/step metadata, updated channels,
  pending-write channels/count, and bounded `history_depth`.
- `src/vaultspec_a2a/api/schemas/snapshots.py`: `ThreadStateSnapshot` now
  surfaces these tuple/history fields directly so reconnecting clients and
  operators can distinguish actual checkpoint lineage from empty/default state.
- `src/vaultspec_a2a/api/endpoints.py`: history loading is now optional
  degradation. The first implementation treated `alist(...)` failure as fatal
  even when `aget_tuple(...)` had already succeeded; review surfaced that as a
  real defect, and it was fixed in the same slice by degrading history
  independently (`checkpoint_history_timeout` /
  `checkpoint_history_unavailable`) instead of collapsing the whole snapshot.
- This closes the old `channel_values`-only criticism for tuple metadata and
  checkpoint lineage, but it does not fully close repair-aware execution
  reconstruction: LangGraph documents `tasks` and `next` on `StateSnapshot`,
  not on the raw `CheckpointTuple`, so the gateway still cannot truthfully
  infer full next-task state from the current read path alone.

Evidence:

- Context7 grounding:
  `/websites/langchain_oss_python_langgraph`
- `src/vaultspec_a2a/database/checkpoints.py`
- `src/vaultspec_a2a/api/projection.py`
- `src/vaultspec_a2a/api/endpoints.py`
- `src/vaultspec_a2a/api/schemas/snapshots.py`
- `src/vaultspec_a2a/api/tests/test_projection.py`
- `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `src/vaultspec_a2a/api/schemas/tests/test_schemas.py`
- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\database\checkpoints.py src\vaultspec_a2a\api\projection.py src\vaultspec_a2a\api\endpoints.py src\vaultspec_a2a\api\schemas\snapshots.py src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py -q`
- results: `74 passed`

Review outcome:

- One real defect surfaced and was fixed in the same slice:
  history loading must degrade independently from tuple loading.
- `#68` should remain partial, but its scope should now be narrowed to the
  missing `StateSnapshot.tasks/next` truth rather than generic checkpoint
  metadata.
- Add a follow-up task for the higher-fidelity execution-state projection path
  instead of leaving that residual gap implicit.

### 2026-03-10 19:25 - Medium - Local code review reinforces that `#84` should be a worker-owned execution-state projection, not gateway graph rehydration

- Official LangGraph docs already pointed to `graph.get_state(...)` /
  `get_state_history(...)` as the authority for `StateSnapshot.tasks/next`.
- Local code review adds an important repo-specific precedent:
  `src/vaultspec_a2a/core/aggregator.py` already performs worker-side
  `graph.aget_state(config)` inspection after runs in order to surface durable
  interrupt truth from `state.tasks[*].interrupts`.
- That means the repo already relies on worker-owned `StateSnapshot` inspection
  for a narrower use case. Generalizing that into a normalized execution-state
  projection is architecturally consistent with both LangGraph's model and
  ADR-031.
- Reintroducing compiled-graph state inspection into the gateway would now be a
  stronger form of drift than previously understood, because the worker already
  has the correct authority surface in place.

Evidence:

- Context7 grounding:
  `/websites/langchain_oss_python_langgraph`
- `src/vaultspec_a2a/core/aggregator.py`
- `docs/adrs/031-worker-process-architecture.md`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No new implementation defect was found in code for this slice.
- The implementation direction for `#84` is now more strongly constrained:
  prefer a worker-owned execution-state projection, with any gateway graph
  compilation treated as an architectural revision that must be audited first.

### 2026-03-10 20:05 - Medium - LangGraph stream-mode research narrows `#84` but does not remove the worker-owned projection requirement

Grounding against current LangGraph docs and the installed package confirms
that:

- `StateSnapshot` is the documented checkpoint/state object and contains
  `next`, `tasks`, and `interrupts`
- `graph.get_state(...)` / `get_state_history(...)` remain the authoritative
  state inspection APIs
- `stream_mode="checkpoints"` emits `StateSnapshot`-shaped updates and
  `stream_mode="tasks"` emits task lifecycle signals

This narrows the design space, but it does not justify continuing gateway-side
reconstruction from raw `CheckpointTuple` data. The remaining gap is still a
worker-owned execution-state projection path. Stream-mode checkpoint/task
signals are a LangGraph-native alternative input, but in the current
`astream_events(version="v2")` worker pipeline they are an optimization path,
not a replacement for the missing durable projection contract.

Evidence:

- Context7 grounding for `/websites/langchain_oss_python_langgraph`
- `.venv/Lib/site-packages/langgraph/types.py`
- `src/vaultspec_a2a/core/aggregator.py`
- `src/vaultspec_a2a/worker/executor.py`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No new product defect was identified in this grounding pass.
- `#84` should stay open and should be implemented as a worker-owned durable
  execution-state projection.

### 2026-03-10 20:20 - Medium - `#84` grounding now constrains both storage format and IPC shape

Further grounding against current SQLAlchemy docs and the local internal event
path narrows the first corrective slice for `#84`:

- use a dedicated latest execution-state projection read model rather than
  duplicating LangGraph history in the app DB
- store normalized task payloads as JSON-encoded `Text`, not backend-native
  `JSON`, to avoid SQLite JSON1 portability drift on the fallback path
- add a new worker-emitted internal event type (e.g.
  `execution_state_projection`) over the existing `/internal/events/batch`
  transport instead of overloading heartbeat

Evidence:

- Context7 grounding for `/websites/sqlalchemy_en_20`
- `src/vaultspec_a2a/api/schemas/internal.py`
- `src/vaultspec_a2a/worker/ipc.py`
- `src/vaultspec_a2a/database/models.py`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No new implementation defect surfaced.
- `#84` is now sufficiently constrained to move into schema/CRUD design when
  the next coding slice begins.

### 2026-03-10 20:30 - Medium - `#84` also requires an explicit frontend-safe execution-state snapshot surface

The current reconnect contract in `ThreadStateSnapshot` exposes repair and
degradation semantics, but it still has no explicit field for normalized
execution truth (`next` / `tasks`). If `#84` is implemented only as a hidden
DB/internal projection, the reconnect API would still force clients to infer
repair state indirectly.

Recommended public-contract addition for the first corrective slice:

- `next_nodes`
- `task_count`
- `pending_interrupt_count`
- a normalized `execution_tasks` collection

This should remain a normalized application contract, not a raw LangGraph
object dump.

Evidence:

- `src/vaultspec_a2a/api/schemas/snapshots.py`
- `src/vaultspec_a2a/api/endpoints.py`
- `docs/adrs/011-frontend-backend-contract.md`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No new product defect was fixed here.
- `#84` now clearly spans persistence, IPC, and public snapshot contract work.

### 2026-03-10 20:40 - Medium - `#84` freshness can be anchored to checkpoint ID and recovery epoch instead of wall-clock guesswork

The local runtime already has better freshness anchors than timestamps alone:

- latest checkpoint identity from the gateway checkpointer read path
- durable `recovery_epoch`
- durable `repair_generation`

That means the execution-state projection does not need ad hoc time-based
staleness heuristics. The next slice should classify projection freshness by
checkpoint/recovery linkage instead:

- missing projection row -> degraded
- projection checkpoint mismatch -> stale
- recovery epoch mismatch -> stale

Evidence:

- `src/vaultspec_a2a/api/endpoints.py`
- `src/vaultspec_a2a/api/projection.py`
- `src/vaultspec_a2a/core/reconciliation.py`
- `src/vaultspec_a2a/database/models.py`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No code defect fixed here.
- The first `#84` implementation can use deterministic freshness rules without
  inventing wall-clock repair heuristics.

### 2026-03-10 20:50 - Medium - `#84` grounding is now concrete enough to move into a dedicated latest-row execution-state model

The local persistence and CRUD review suggests the first implementation should
not overload `threads` or `control_actions`. The cleaner fit is a dedicated
latest execution-state read model keyed by `thread_id`, with normalized
task/interrupt/next payloads stored as JSON-encoded `Text`.

That keeps LangGraph as the checkpoint-history authority while giving the
gateway one durable app-owned projection row for restart/reconnect truth.

Evidence:

- `src/vaultspec_a2a/database/models.py`
- `src/vaultspec_a2a/database/crud.py`
- `src/vaultspec_a2a/database/migrations/versions/0002_orchestration_journal.py`
- `docs/research/2026-03-09-postgres-persistence-grounding.md`

Review outcome:

- No product defect fixed here.
- `#84` is now grounded enough to enter implementation without inventing the
  schema mid-pass.

### 2026-03-10 21:10 - High - `#84` first execution-state projection slice implemented; review defect fixed in-slice

The worker-owned execution-state projection slice for `#84` is now in code:

- worker inspects runtime state via `graph.aget_state(...)`
- worker emits normalized `execution_state_projection` events
- gateway persists a latest-row `thread_execution_state` read model
- reconnect snapshots now expose normalized execution-state fields:
  - `next_nodes`
  - `task_count`
  - `pending_interrupt_count`
  - `execution_tasks`
- freshness is classified by checkpoint ID and recovery epoch

Review finding surfaced during the implementation pass:

- degraded-only execution-state updates were overwriting a previously good
  durable row with empty checkpoint/task payloads.
- that would destroy better repair truth after a transient state-inspection
  failure.
- fixed: degraded-only updates now preserve the last good normalized payload
  and update only degradation metadata / freshness bookkeeping.

Test-harness review finding surfaced during the same pass:

- file-backed SQLite migration/WAL tests on the mapped `Y:` workspace path
  produced real `aiosqlite` `disk I/O error` failures unrelated to the code
  under test.
- fixed: database and API checkpointer tests now use a local writable runtime
  root under `C:\Users\hello\.codex\memories\tmp\...`.

Verification completed:

- `ruff check` on touched runtime/test files
- targeted non-Postgres suite:
  `src/vaultspec_a2a/api/tests/test_projection.py`
  `src/vaultspec_a2a/api/tests/test_internal.py`
  `src/vaultspec_a2a/api/tests/test_endpoints.py`
  `src/vaultspec_a2a/api/schemas/tests/test_schemas.py`
  `src/vaultspec_a2a/database/tests/test_migrations.py::TestAlembicUpgradeDowngrade`
  `src/vaultspec_a2a/database/tests/test_migrations.py::TestRunMigrations::test_run_migrations_programmatic`
  `src/vaultspec_a2a/database/tests/test_database.py::TestWALMode::test_wal_mode_on_file_db`
- result:
  `105 passed`

Residual gap:

- the worker-owned execution-state projection has not yet been proven on the
  live Postgres restart/reconnect path.
- `#84` should move from `Pending` to `Partial`, not `Fixed`.

### 2026-03-10 22:25 - High - `#84` is now live-verified; sequential paused-thread restart tests exposed a real shared-Postgres contamination issue and a redacted-URL fixture bug, both fixed in-slice

The `#84` closeout run surfaced a real live-suite issue before the slice could
be considered done:

- the paused-thread restart tests in
  `src/vaultspec_a2a/tests/test_permission_durability_live.py` were sharing one
  logical Postgres database across multiple function-scoped scenarios
- that allowed durable thread/checkpoint state to leak between cases and
  produced misleading startup failures during sequential live verification

The fix keeps the same real Postgres container but isolates each test onto a
fresh logical database created and dropped with Postgres DDL under autocommit.

Review of that fixture change surfaced a second defect:

- the first implementation used `str(make_url(...))` for the derived URLs
- SQLAlchemy redacted the password to `***` in that string form
- worker and gateway subprocesses then failed authentication against the fresh
  databases
- fixed in-slice by using
  `render_as_string(hide_password=False)` for the derived runtime URLs

Impact:

- live Postgres verification for paused approval durability and execution-state
  projection is now deterministic across sequential runs
- the execution-state projection feature is now proven against the
  production-authoritative backend rather than only local targeted suites
- reconnect snapshots for paused threads now have live proof for normalized
  `next_nodes` / `execution_tasks` durability across gateway restart

Evidence:

- `src/vaultspec_a2a/tests/conftest.py`: new `isolated_postgres_urls` fixture
  creates a fresh logical Postgres database per test and drops it with
  `DROP DATABASE ... WITH (FORCE)`
- `src/vaultspec_a2a/tests/test_permission_durability_live.py`: the two paused
  restart tests now consume `isolated_postgres_urls`
- verification on 2026-03-10:
  - `python -m pytest -p no:cacheprovider ...` targeted local suite
  - result: `105 passed`
  - `python -m pytest src/vaultspec_a2a/tests/test_permission_durability_live.py::test_plan_approval_survives_gateway_restart_and_response_retry src/vaultspec_a2a/tests/test_permission_durability_live.py::test_execution_state_projection_survives_gateway_restart_for_paused_thread -m live -q`
  - result: `2 passed`

Resolution:

- Fixed in the same slice.
- `#84` is now closed.
- Because `#84` was the remaining open portion of the checkpoint-projection
  task, `#68` is also now closed.

### 2026-03-10 23:20 - High - prod-like Docker/Postgres verification surfaced two real production-image defects; both fixed in-slice and the staged verification target now passes

Grounding for the prod-like Docker/Postgres slice was done against current
Docker Compose health/dependency behavior and the repo's Postgres dual-backend
ADR/research trail before code changes. The implementation added a dedicated
Postgres prod-like overlay plus a staged verification target:

- `docker-compose.prod.postgres.yml`
- `just verify-prodlike-docker`
- `just verify-claude-docker`
- `just verify-gemini-docker`

The first real prod-like run surfaced two production-image defects:

1. The production images still launched the gateway and worker with
   `uv run uvicorn ...`.
   - In the installed image this re-entered `uv` at container startup instead
     of using the already-synced runtime.
   - That caused avoidable startup overhead and broke the worker health timing
     contract in the prod-like stack.
   - Fixed by launching `uvicorn` directly from `/app/.venv/bin/python -m
     uvicorn ...` in `docker/prod.Dockerfile`.

2. Gateway startup in the installed image failed during migrations because
   `database/migrate.py` resolved `alembic.ini` relative to the package path.
   - In the non-editable production image that path resolved under
     `site-packages`, where no repo-root `alembic.ini` existed.
   - Fixed by resolving Alembic config from `Path(settings.project_root) /
     "alembic.ini"`, copying `alembic.ini` into the image, and setting
     `VAULTSPEC_PROJECT_ROOT=/app` for the gateway image stage.

Additional operational hardening shipped in the same slice:

- base prod compose now explicitly declares SQLite backend selection
- Postgres overlay now explicitly sets both DB/checkpoint backends plus
  `VAULTSPEC_POSTGRES_REQUIRED=true`
- Jaeger v2 image/health endpoints were corrected to use
  `cr.jaegertracing.io/jaegertracing/jaeger:2.16.0` and `/13133/status`
- Docker docs now distinguish the transitional SQLite base stack from the
  production-authoritative Postgres overlay

Verification completed:

- `ruff check src/vaultspec_a2a/database/migrate.py src/vaultspec_a2a/worker/app.py src/vaultspec_a2a/tests/test_repo_hygiene.py`
- `pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
- `docker compose -f docker-compose.integration.yml config`
- `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
- `just verify-prodlike-docker`
- `just verify-claude-docker`
- `just verify-gemini-docker`
- result:
  - repo hygiene suite passed
  - both compose configs rendered successfully
  - prod-like Docker/Postgres stack booted successfully
  - `/api/health` reported Postgres-backed readiness
  - real thread create + state lookup passed against the prod-like stack

Review outcome:

- No additional open product defect remained in the touched prod-like files
  after the two image/startup defects were fixed.
- `#73` is now closed for runtime/config/readiness behavior.
- `#74` should move to `Partial`: the staged prod-like verification target now
  exists and passes locally, but CI-matrix integration/promotion is still
  separate work.
- `#72` remains `Partial`: backend abstraction and fallback posture are in
  place, but SQLite fallback hardening remains intentionally non-certifying.

### 2026-03-10 23:55 - High - prod-like Docker/Postgres verification is now promoted into CI through a shared repo-owned verifier; the first CI-shaped run exposed a retry bug in the verifier itself and it was fixed in-slice

The `#74` follow-up moved prod-like Docker/Postgres verification from a local
staged recipe into a CI-ready shared verification path:

- added a shared CLI verifier under `vaultspec test prodlike-docker`
- `just verify-prodlike-docker` now delegates to that script
- `just verify-claude-docker` / `just verify-gemini-docker` provide simpler
  provider-specific entry points
- added `.github/workflows/prodlike-docker.yml` for `push`,
  `pull_request`, and `workflow_dispatch`

Review of the first shared-verifier run surfaced a real verifier defect:

- the initial health poll only retried `urllib.error.URLError`
- a real prod-like warmup run produced `http.client.RemoteDisconnected` while
  the gateway was still starting
- the verifier treated that transient startup disconnect as fatal and tore the
  stack down early
- fixed in-slice by widening the retryable startup exceptions to include
  `HTTPException`, `OSError`, and transient JSON decode failures during the
  warmup loop

Impact:

- the prod-like verification path is now authoritative across both local runs
  and GitHub Actions instead of duplicating logic in PowerShell and CI YAML
- PR validation can now use the same verification contract that was already
  proven locally against the production compose stack

Evidence:

- `vaultspec test prodlike-docker`: shared verifier for compose bring-up,
  readiness polling, backend assertions, thread create, state lookup, and
  teardown
- `.github/workflows/prodlike-docker.yml`: CI job for prod-like Docker/Postgres
  verification on `push`, `pull_request`, and `workflow_dispatch`
- `Justfile`: `verify-prodlike-docker` now calls the shared verifier
- `Justfile`: `verify-claude-docker` and `verify-gemini-docker` provide
  explicit provider-specific shortcuts
- verification on 2026-03-10:
  - `python -m ruff check src/vaultspec_a2a/cli/_verify.py`
  - `pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
  - `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
  - elevated real prod-like run via `uv run vaultspec test prodlike-docker`
  - result: all passed after the verifier retry fix

Resolution:

- Fixed in the same slice.
- `#74` is now closed as the initial CI promotion target.

### 2026-03-11 00:05 - Medium - The backend readiness execution plan has been rewritten against the actual remaining queue, closing the stale-plan drift

The old backend-readiness execution plan still treated major completed work as
active:

- repair closure
- live Postgres recovery/reconnect verification
- most no-doubles cleanup
- Postgres runtime/readiness and prod-like verification

That was no longer acceptable because the plan had drifted behind the audit
truth and the consolidated queue.

Implementation outcome:

- rewrote `docs/plans/2026-03-09-backend-readiness-execution-plan.md`
- the refreshed plan now tracks only the actually open work:
  - `#56`
  - `#71`
  - `#72`
  - `#41`
  - `#52`
  - `#42`
- it also carries forward the still-relevant deferred findings:
  - `DCK-L04`
  - `PROV-O01`
  - `WRK-K06`
  - `WRK-K01`
  - `CLI-I06`

Impact:

- the active plan, research trail, and consolidated queue are now aligned again
- future execution slices can follow a truthful order instead of re-traversing
  already-closed repair/Postgres work

Evidence:

- `docs/plans/2026-03-09-backend-readiness-execution-plan.md`
- `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`

Verification:

- review-only/documentation slice
- no runtime or test command was required

Resolution:

- Fixed in the same slice.
- `#75` is now closed.

### 2026-03-11 00:58 - Medium - WebSocket phantom-thread handling is now repair-aware and no longer silently treats a missing thread row as total absence

- Grounding for `#42` used current FastAPI WebSocket guidance plus the
  repository's durable repair model.
- The implementation now rejects phantom-thread commands with explicit
  recoverable WebSocket `error` events instead of accepting or silently
  discarding them.
- Missing-thread commands are classified as:
  - `THREAD_STATE_DRIFT` when durable backend residue exists
  - `THREAD_STATE_UNVERIFIED` when checkpoint truth cannot be verified
  - `THREAD_NOT_FOUND` when no durable residue exists

Important implementation conclusion:

- Under the current schema, orphaned execution-state projection rows are not
  the normal phantom-thread case because `thread_execution_state.thread_id`
  remains tied to `threads` by the app-owned data model.
- The real contentious deletion/drift risk is checkpoint residue outliving the
  gateway's thread row, so that is the path the production test now exercises.

Evidence:

- `src/vaultspec_a2a/api/app.py`: `_classify_missing_ws_thread()` now probes
  both app-owned execution-state and real checkpointer residue before deciding
  how to reject the command.
- `src/vaultspec_a2a/api/websocket.py`: accepted WebSocket connections now send
  structured `error` events for handler-level rejections.
- `src/vaultspec_a2a/api/tests/test_app.py`: phantom-thread drift is now
  verified by seeding a real checkpoint through `AsyncSqliteSaver.aput(...)`
  instead of attempting to fabricate an impossible orphaned projection row.
- verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/websocket.py src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_app.py`
  - `python -m pytest src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_app.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
  - result: `20 passed`

Review outcome:

- No new open product defect remained in this slice after the truthful
  checkpoint-residue test replaced the impossible execution-state orphan test.

Resolution:

- Fixed in the same slice.
- `#42` is now closed.

### 2026-03-11 01:12 - Medium - The remaining Docker restart/healthcheck queue item was stale; the production-authoritative compose path already enforces restart policy, health-ordered dependencies, and internal-token presence

- Re-grounding `#41` against current Docker Compose docs and the live compose
  files showed that the earlier defect is no longer present on the
  production-authoritative path.
- `docker-compose.prod.yml` and `docker-compose.prod.postgres.yml` already use:
  - `restart: unless-stopped`
  - `depends_on.condition: service_healthy`
  - required-variable interpolation for `VAULTSPEC_INTERNAL_TOKEN`
- The remaining work was documentation drift, not compose/runtime drift.

Evidence:

- `docker-compose.prod.yml`: gateway/worker/jaeger all use restart policies;
  gateway and worker depend on healthy upstream services.
- `docker-compose.prod.postgres.yml`: postgres is health-gated and the gateway
  overlay depends on healthy postgres/jaeger/worker services.
- `docker-compose.dev.yml` and `docker-compose.integration.yml`: current
  dependency ordering also uses `service_healthy` where the stack depends on a
  healthy peer.
- `docker/README.md`: now explicitly documents `VAULTSPEC_INTERNAL_TOKEN` and
  `POSTGRES_PASSWORD` as required production env when running the compose
  stacks.
- verification on 2026-03-11:
  - `python -m pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
  - `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
    with `VAULTSPEC_INTERNAL_TOKEN` set
  - result: passed

Review outcome:

- No new product defect remained in the compose/runtime path for `#41`.
- The old `DCK-L04` note is now stale as an open issue because the production
  compose file already refuses to render without `VAULTSPEC_INTERNAL_TOKEN`.

Resolution:

- Fixed as a queue/audit correction slice.
- `#41` is now closed.

### 2026-03-11 01:35 - Medium - SQLite fallback posture is now operator-visible instead of being implied from backend names alone

- Grounding for `#72` used current SQLAlchemy SQLite docs plus official SQLite
  WAL guidance.
- The implementation did not change the architecture; it closed the remaining
  visibility gap.
- Health surfaces now expose explicit `sqlite_fallback` diagnostics with:
  - `active`
  - `busy_timeout_ms`
  - `production_certifying`
  - `limitations`
  - per-file WAL diagnostics for app/checkpoint SQLite files

Evidence:

- `src/vaultspec_a2a/database/session.py`: `inspect_sqlite_database(...)`
  now performs real file-backed SQLite inspection.
- `src/vaultspec_a2a/api/app.py`: startup builds and stores
  `sqlite_fallback_diagnostics`; `/api/health` exposes it.
- `src/vaultspec_a2a/api/endpoints.py`: aggregated `/health` now exposes the
  same fallback block.
- `src/vaultspec_a2a/api/tests/test_app.py` and
  `src/vaultspec_a2a/api/tests/test_endpoints.py`: real file-backed tests prove
  WAL-backed inspection and payload exposure.
- verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/database/session.py src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py`
  - `python -m pytest src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
  - result: `33 passed`

Review outcome:

- No new product defect surfaced in this slice.
- The previous partial state for `#72` was accurate but narrow: missing
  diagnostics, not missing backend abstraction.

Resolution:

- Fixed in the same slice.
- `#72` is now closed.

### 2026-03-11 01:55 - Low - Worker `/dispatch` auth gap is now closed and aligned with the existing internal-token contract

- Grounding for `WRK-K06` used current FastAPI auth/dependency guidance plus
  the repo's existing internal bearer-token model on gateway `/internal/*`
  routes and the worker IPC bridge.
- The product defect was real: the gateway->worker dispatch path was still an
  unauthenticated privileged mutation surface.

Evidence:

- `src/vaultspec_a2a/worker/app.py`: `/dispatch` now depends on
  `_verify_dispatch_token(...)`, requiring bearer auth whenever
  `settings.internal_token` is configured and failing loudly on
  non-development misconfiguration.
- `src/vaultspec_a2a/api/app.py`: the gateway-owned worker client now sends
  `Authorization: Bearer <internal_token>` when configured.
- `src/vaultspec_a2a/api/tests/conftest.py`: the in-process worker harness now
  enforces the same auth boundary, so dispatch tests no longer run through a
  permissive helper.
- `src/vaultspec_a2a/worker/tests/test_app.py`: direct route tests now prove:
  - `401` for missing bearer token when auth is configured
  - `401` for incorrect bearer token
  - `500` for missing token configuration outside development
- verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/worker/app.py src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/tests/conftest.py src/vaultspec_a2a/api/tests/test_endpoints.py`
  - `python -m pytest src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
  - result: `29 passed`

Review outcome:

- The first review pass found one real gap: the non-development misconfiguration
  path existed but lacked direct test coverage. That was fixed in the same slice.
- No additional product defect remained in the dispatch auth path after that
  coverage fix.

Resolution:

- Fixed in the same slice.
- `WRK-K06` is now closed.

### 2026-03-11 02:05 - Low - `worker/health.py` was confirmed as dead code and removed without changing the runtime health contract

- Grounding for `WRK-K01` used current FastAPI app-structure guidance plus a
  local authority review of the worker runtime.
- The result matched the older audit findings exactly: the live worker health
  contract already exists in `worker/app.py` and `worker/ipc.py`, while
  `worker/health.py` was only an empty placeholder class.

Evidence:

- `src/vaultspec_a2a/worker/app.py`: owns the actual `/health` route.
- `src/vaultspec_a2a/worker/ipc.py`: owns the actual heartbeat loop.
- `src/vaultspec_a2a/worker/health.py`: contained only an empty `HealthCheck`
  class and had no runtime imports or test references.
- verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/worker src/vaultspec_a2a/worker/tests/test_app.py`
  - `python -m pytest src/vaultspec_a2a/worker/tests/test_app.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Review outcome:

- No hidden dependency on `worker/health.py` surfaced.
- This was a true dead-code cleanup, not a latent runtime feature removal.

Resolution:

- Fixed in the same slice.
- `WRK-K01` is now closed.

### 2026-03-11 02:15 - Low - The CLI MCP tool list no longer drifts from the actual FastMCP registration surface

- Grounding for `CLI-I06` used current FastMCP docs, which identify
  `list_tools()` as the canonical inspection API for registered tools.
- The defect was real but low-severity: `vaultspec mcp tools` and
  `vaultspec mcp status` were driven by a hardcoded `_TOOLS` list in the CLI,
  not by the actual MCP server registration surface.

Evidence:

- `src/vaultspec_a2a/cli/_mcp.py`: now derives tool rows from
  `mcp.list_tools()` and renders concise one-line descriptions from the live
  tool metadata.
- `src/vaultspec_a2a/cli/tests/test_mcp.py`: new CLI tests prove:
  - the derived tool rows match the registered MCP surface
  - `vaultspec mcp tools` renders registered tool names
  - `vaultspec mcp status` reports the live tool count
- verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/cli/_mcp.py src/vaultspec_a2a/cli/tests/test_mcp.py`
  - `python -m pytest src/vaultspec_a2a/cli/tests/test_mcp.py src/vaultspec_a2a/cli/tests/test_service.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
  - result: `13 passed`

Review outcome:

- The first pass test overfit the exact `cancel_thread` wording and would have
  recreated description drift in the test itself. That was fixed in-slice by
  asserting live registration authority without freezing non-critical wording.
- No additional product defect remained after that correction.

Resolution:

- Fixed in the same slice.
- `CLI-I06` is now closed.

### 2026-03-11 02:30 - Medium - The old Docker ACP-runtime finding is now too broad; the worker image includes the Claude Node/ACP runtime, but the full Claude/Gemini provider matrix is still not Docker-certified

- Re-grounding `PROV-O01` against the current `docker/prod.Dockerfile` showed
  that the original claim is no longer accurate.
- The worker image now copies:
  - a glibc-compatible `node` runtime from `node:22-slim`
  - root `node_modules` containing `@zed-industries/claude-agent-acp`
- That means the old blanket finding "Docker worker has no Node.js/ACP runtime"
  is stale.

What remains open:

- Gemini still depends on a real `gemini` CLI binary and OAuth material under
  `~/.gemini/oauth_creds.json`; the Docker image does not provision that CLI.
- Claude's Node-backed ACP adapter runtime is present, but the prod-like Docker
  verification path has not yet certified a real Claude auth/session flow in
  the containerized worker.
- The compose files currently wire only backend/database settings for the
  worker; they do not define a supported path for ACP provider auth material.

Evidence:

- `docker/prod.Dockerfile`: worker stage copies `/usr/local/bin/node` from
  `node:22-slim` and `/app/node_modules` from the build stage.
- `package.json`: root production dependency contains
  `@zed-industries/claude-agent-acp`.
- `src/vaultspec_a2a/providers/factory.py`: Claude Node backend resolves to
  `node <project_root>/node_modules/@zed-industries/claude-agent-acp/dist/index.js`;
  Gemini still resolves to `gemini --experimental-acp`.
- `src/vaultspec_a2a/providers/gemini_auth.py`: Gemini depends on host-style
  CLI auth material under `~/.gemini/oauth_creds.json`.

Review outcome:

- No new Docker runtime bug was found in the current image definition.
- The real issue is now documentation and queue drift: the limitation must be
  described as incomplete provider-matrix certification, not missing Node.js.

Resolution:

- Fixed as a research/audit correction slice.
- The remaining provider-matrix limitation stays open in narrowed form.

Follow-up queue split:

- `#85`: Docker worker Gemini CLI provisioning/support path
- `#86`: Dockerized Claude/Gemini auth-material contract and certifying
  provider verification

### 2026-03-11 03:05 - High - The Docker Gemini runtime path is now real and executable, but full Claude/Gemini provider certification remains credential-gated

- The worker image now includes the official Gemini CLI runtime instead of
  relying on a host-installed `gemini` binary.
- The first implementation exposed a real product defect: copying the global
  `/usr/local/bin/gemini` wrapper into the worker image was insufficient
  because that launcher expects relative sources beside itself and failed with
  `ERR_MODULE_NOT_FOUND`.
- That defect was fixed in-slice by switching the runtime authority to the
  actual package entrypoint under Node:
  `node /usr/local/lib/node_modules/@google/gemini-cli/dist/index.js`.
- The provider/runtime contract is also now aligned with official Gemini CLI
  non-interactive auth docs:
  - `GEMINI_API_KEY` and `GOOGLE_API_KEY` are explicitly re-injected by the
    provider layer for Gemini subprocesses
  - OAuth refresh becomes a no-op when env-based Gemini auth is already present
- Review surfaced one more Docker verifier defect in the same slice:
  the repo-owned Docker verifier scripts were still vulnerable to Docker
  Compose's default project `.env` interpolation. They now set
  `COMPOSE_DISABLE_ENV_FILE=1` explicitly so verification uses only explicit
  inputs.

Evidence:

- `docker/prod.Dockerfile`: dedicated `gemini-cli` stage installs pinned
  `@google/gemini-cli@0.3.3`, and the worker copies the package runtime.
- `src/vaultspec_a2a/providers/factory.py`: Gemini command resolution now
  prefers the packaged `dist/index.js` entrypoint under Node in Docker and
  explicitly injects supported env-based auth.
- `src/vaultspec_a2a/providers/gemini_auth.py`: env-auth detection now short-
  circuits OAuth refresh.
- `vaultspec test prodlike-docker` and
  `vaultspec test prodlike-provider <claude|gemini>`: now disable implicit Compose
  `.env` loading.
- Verification on 2026-03-11:
  - `python -m ruff check src/vaultspec_a2a/providers/factory.py src/vaultspec_a2a/providers/gemini_auth.py src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/probes/gemini.py src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/providers/tests/test_gemini_auth.py src/vaultspec_a2a/cli/_verify.py`
  - `python -m pytest src/vaultspec_a2a/providers/tests/test_factory.py -q --capture=sys`
  - `python -m pytest src/vaultspec_a2a/providers/tests/test_gemini_auth.py -k "TestGeminiUsesEnvAuth or TestIsExpired" -q --capture=sys`
  - direct runtime no-op verification for `refresh_gemini_token(..., env={...})`
  - `docker build -f docker/prod.Dockerfile --target worker -t vaultspec-a2a-worker:test .`
  - `docker run --rm vaultspec-a2a-worker:test node /usr/local/lib/node_modules/@google/gemini-cli/dist/index.js --help`

Review outcome:

- `#85` is closed.
- `#86` remains partial because the provider-specific Docker verifier now exists
  but could not be fully run in this environment without explicit live provider
  credentials.

Resolution:

- Closed the Gemini runtime-installation sub-gap.
- Kept the remaining provider-certification/auth-material gap open in narrowed
  form.

### 2026-03-11 10:05 - High - prod-like verification now belongs to the CLI instead of `scripts/`, but the real remaining defect is a gateway readiness timeout with insufficient startup diagnostics

Repository-hygiene correction shipped in this slice:

- the ad hoc verifier scripts were moved into the supported CLI surface under
  `vaultspec test`:
  - `vaultspec test prodlike-docker`
  - `vaultspec test prodlike-provider <claude|gemini>`
  - `vaultspec test claude-docker`
  - `vaultspec test gemini-docker`
- `Justfile` and `.github/workflows/prodlike-docker.yml` now call the CLI
  entry points
- the `scripts/` directory was removed after the move

Grounding used:

- current OpenTelemetry Python docs for OTLP exporter setup, `service.name`
  attribution, and collector-backed multi-service debugging
- current Jaeger query API docs for `/api/traces` evidence gathering
- local ADR/audit requirements that multi-domain verification must use Jaeger
  and not treat a bare timeout as an acceptable result

The verifier itself was hardened in the same slice:

- forces `VAULTSPEC_LOG_LEVEL=DEBUG` for the prod-like stack
- persists artifact directories under `.vaultspec/runtime/verify-prodlike-docker`
- uploads those diagnostics from CI via the prod-like workflow
- requires Jaeger trace evidence for both `vaultspec-a2a` and
  `vaultspec-worker` on successful cross-service verification

Real review finding from the first elevated CLI run on 2026-03-11:

- `uv run vaultspec test prodlike-docker` still failed for a real product path:
  `gateway not ready after 120s: <urlopen error timed out>`
- the artifact directory existed, but gateway/worker/postgres/jaeger logs were
  empty and the trace files were empty placeholders because the verifier still
  tears down too early and does not yet capture richer container health/inspect
  data before shutdown

Evidence:

- `src/vaultspec_a2a/cli/_verify.py`
- `src/vaultspec_a2a/cli/_test.py`
- `.github/workflows/prodlike-docker.yml`
- artifact dir from the failing elevated run:
  `.vaultspec/runtime/verify-prodlike-docker/20260311T084424Z`

Resolution:

- repository hygiene issue fixed: verifier support surface is now CLI-owned
- new open task required for the actual remaining defect:
  `#87` prod-like gateway readiness timeout + too-thin startup diagnostics

### 2026-03-11 12:10 - Medium - local ACP bridge remains intact; current local failures split into provider quota vs Docker-only certification gap

Grounding and verification performed:

- inspected current provider command resolution in
  `src/vaultspec_a2a/providers/factory.py`
- verified that local non-Docker resolution still prefers:
  - Claude: project `node_modules/@zed-industries/claude-agent-acp/dist/index.js`
  - Gemini: project package if present, otherwise system `gemini` on PATH
- ran the real local probes with elevation after sandbox limitations blocked the
  initial runs

Observed results on this machine:

- Gemini local ACP probe passed end to end:
  - OAuth refresh succeeded
  - `initialize`, `session/new`, and `session/prompt` all completed
  - returned `Hello`
- Claude local ACP probe proved the bridge and session wiring:
  - `initialize` succeeded
  - `session/new` succeeded
  - `session/prompt` failed due to provider quota exhaustion, not bridge
    breakage:
    `Internal error: You've hit your limit · resets Mar 13, 5am (Europe/Madrid)`

Interpretation:

- The recent Docker/provider work has not replaced or broken the previously
  working local ACP bridge architecture.
- The remaining open provider item is still Docker/provider certification
  (`#86`) and not a newly introduced local ACP regression.
- Claude local provider availability should still be treated as an operational
  readiness concern when using OAuth-backed ACP, but it is not evidence of an
  architectural ACP handoff failure.

Resolution:

- no new architecture-change defect opened from this slice
- preserved the provider-certification concern under `#86`
- preserved the prod-like startup/diagnostics concern under `#87`

### 2026-03-11 12:25 - High - tracing is present, but log/trace correlation and ACP observability boundaries are not formally designed

Grounding and audit conclusion:

- Jaeger trace evidence is working and remains mandatory.
- However, the repository does not yet define a formal architecture for
  correlating structured debug logs with traces across:
  - gateway
  - worker
  - Docker container boundaries
  - ACP subprocess boundaries
- Official OpenTelemetry guidance supports log/trace correlation by attaching
  `trace_id` and `span_id` to log records. It does not treat spans as a
  replacement for arbitrary debug logging.
- Jaeger is trace-centric. It is not, by itself, the complete answer for
  durable debug-log transport and search.

Current repo state:

- `src/vaultspec_a2a/utils/logging.py` emits structured JSON logs but does not
  inject OTel correlation fields into every record
- `src/vaultspec_a2a/telemetry/instrumentation.py` configures tracing/metrics
  only; there is no formal log-export or log-correlation layer
- `src/vaultspec_a2a/cli/_verify.py` captures service logs and Jaeger traces
  separately, but there is no concerted evidence model joining them
- ADR-010 covers tracing, but not log/trace correlation or Dockerized ACP
  observability authority

Why this matters:

- Prod-like failures such as `#87` are still too expensive to root-cause
  because trace evidence and debug logs are not concerted into one
  authoritative diagnostic story
- The local-vs-Docker ACP authority split is now grounded, but the
  observability story around those boundaries is still under-documented

Resolution:

- open a dedicated observability architecture task for log/trace correlation
- open a dedicated ADR/research task for ACP local-vs-Docker authority and
  observability boundaries

### 2026-03-11 15:10 - High - the observability pivot is now grounded and ADR-backed, and the correct next implementation path is correlation-first rather than backend expansion

Grounding and architecture outcome:

- `#88` and `#89` were re-grounded against the current repo, OpenTelemetry
  docs/spec guidance, and Jaeger’s trace-centric role.
- The repo now has an explicit research trail and two proposed ADRs:
  - `docs/research/2026-03-11-observability-debug-correlation-grounding.md`
  - `docs/adrs/036-debug-evidence-surface.md`
  - `docs/adrs/037-acp-runtime-authority.md`
- The resulting architecture direction is:
  - keep Jaeger as the authoritative trace backend
  - keep structured logs as the authoritative debug-log surface
  - require automatic `trace_id` / `span_id` correlation on service-owned log
    records
  - defer OTLP logs until a real log-capable backend and operator workflow are
    chosen
  - treat local-native ACP runtime and Docker-bundled provider runtime as
    separate environment-scoped authorities, with the worker remaining the sole
    ACP execution authority in both modes

Current code-path conclusions:

- `src/vaultspec_a2a/utils/logging.py` already emits structured JSON in
  non-interactive contexts, so correlation is a bounded extension of the
  existing log surface rather than a replacement project.
- `src/vaultspec_a2a/telemetry/instrumentation.py` still configures traces and
  metrics only, confirming that an OTLP-logs path would be a new architecture
  decision, not a small toggle.
- `src/vaultspec_a2a/providers/acp_chat_model.py` and
  `src/vaultspec_a2a/providers/_subprocess.py` already own ACP subprocess
  lifecycle truth, but currently expose it only through weakly structured
  service logs.
- `src/vaultspec_a2a/cli/_verify.py` still captures logs and Jaeger traces as
  separate evidence silos, which keeps `#87` open until correlation and
  pre-teardown inspect/health capture are implemented.

Implication for the queue:

- the next correct implementation order is:
  1. `#88` logger correlation and debug-surface hardening
  2. `#89` ACP runtime-boundary observability hardening
  3. `#87` verifier evidence capture under that authority model
- `#86` remains a separate credential-backed certification task and should not
  drive the architecture decision.

### 2026-03-11 15:35 - High - the first implementation pass is now explicitly sequenced, and routing general debug logs into Jaeger traces has been rejected as the wrong default

Planning outcome:

- the repo now has a concrete implementation plan at
  `docs/plans/2026-03-11-trace-debug-implementation-plan.md`
- the ordered next slices are:
  1. automatic trace/log correlation fields in the structured logger
  2. consistent high-value runtime keys on service paths
  3. ACP runtime/subprocess evidence hardening
  4. prod-like verifier pre-teardown evidence capture
  5. optional developer-facing review client only after authoritative evidence
     is complete

Architectural clarification:

- forwarding general debug logs into spans for Jaeger was explicitly rejected
  as the default design because traces and logs are different signals and
  Jaeger remains trace-centric
- a developer-facing client that reads logs, traces, and verifier artifacts is
  acceptable, but only as a downstream review surface rather than a second
  source of truth

Immediate implementation implication:

- the next bounded implementation slice should stay narrow:
  `src/vaultspec_a2a/utils/logging.py` plus focused tests for automatic
  `trace_id` / `span_id` correlation
- that is the lowest-blast-radius change that improves both the broader debug
  framework and the still-open Docker verifier diagnostics task
- A detailed execution sequence for the first implementation wave now exists in
  `docs/plans/2026-03-11-trace-debug-implementation-plan.md`, with the first
  bounded slice focused on automatic trace/log correlation in the existing
  structured logger.

### 2026-03-11 16:05 - High - `#88` Phase 1 is now implemented: first-party logs gain automatic OTel correlation in the shared logging layer, but service-path runtime identifiers still need follow-on work

- The first bounded observability implementation slice was completed in the
  shared logging layer instead of widening immediately into service call sites.
- `src/vaultspec_a2a/utils/logging.py` now attaches an OTel-aware correlation
  filter in `setup_logging()` so both JSON and Rich handler paths inject, when
  a current span exists and the fields are absent:
  - `trace_id`
  - `span_id`
  - `trace_sampled`
  - `service_name`
- This preserves caller-provided values rather than overwriting them, which
  keeps the new automatic fields compatible with future explicit runtime-owned
  extras such as `thread_id`, `dispatch_id`, and `client_id`.

Verification:

- `python -m ruff check src/vaultspec_a2a/utils/logging.py src/vaultspec_a2a/utils/tests/test_logging.py`
- `python -m pytest src/vaultspec_a2a/utils/tests/test_logging.py -q`
- reported result: `8 passed`

Review outcome:

- No new defect surfaced in the Phase 1 slice itself.
- The meaningful remaining gap is intentionally narrower now:
  - the log substrate is correlation-capable
  - the next value comes from enriching high-value service paths with runtime
    identifiers already present at those call sites

Queue implication:

- `#88` should no longer be described as pure architecture/design work.
- Its current state is now:
  - architecture grounded
  - Phase 1 correlation substrate implemented and verified
  - follow-on implementation still pending for service-path enrichment

### 2026-03-11 16:40 - High - `#88` Phase 2 is now implemented at the top-priority service paths: runtime-owned identifiers are attached to gateway, WebSocket, and worker IPC logs where those ids were already naturally in hand

- The next bounded observability slice stayed tight to the highest-value
  service-path logs instead of widening into verifier or provider/runtime work.
- `src/vaultspec_a2a/api/endpoints.py` now enriches the main create/message/
  resume/cancel dispatch logs and related rejection/failure logs with bounded
  runtime fields such as `thread_id`, `dispatch_id`, `request_id`, `agent_id`,
  and action metadata.
- `src/vaultspec_a2a/api/websocket.py` now enriches the main connect/
  disconnect, command, rejection, relay-backpressure, and send-failure logs
  with fields such as `client_id`, `thread_id`, `agent_id`, `command_type`,
  `error_code`, and queue metadata.
- `src/vaultspec_a2a/worker/ipc.py` now enriches buffered relay/flush/heartbeat
  logs with `worker_id`, batch sizing, retry attempt metadata, active-thread
  summaries, and drop counters.

Verification:

- `python -m ruff check src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/websocket.py src/vaultspec_a2a/worker/ipc.py src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/worker/tests/test_ipc.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/worker/tests/test_ipc.py -q`
- reported result: `65 passed`
- note: pytest emitted a non-failing `PytestCacheWarning` because `.pytest_cache`
  could not be written in the current workspace

Review outcome:

- No new product defect surfaced in the bounded Phase 2 slice itself.
- The meaningful remaining gap is narrower again:
  - top-priority service-path fields are now present
  - lower-priority call sites and verifier consumption still remain open

### 2026-03-11 17:07 - High - `#88` internal relay-boundary coverage is now implemented, narrowing the remaining observability gap to executor and verifier consumers

- The next bounded observability slice stayed merge-safe against unrelated
  execution-state work already in `src/vaultspec_a2a/api/internal.py` and
  `src/vaultspec_a2a/api/tests/test_internal.py`.
- `src/vaultspec_a2a/api/internal.py` now enriches the existing internal
  boundary log statements with bounded runtime fields:
  - terminal update / transition-skip / failure logs carry `thread_id`,
    `status`, `event_type`, and action metadata
  - malformed worker event envelope warnings carry `message_type`,
    `transport`, and `frame_size`
  - connection-manager-unavailable drop warnings carry `thread_id`,
    `event_type`, `transport`, and action metadata
  - internal WebSocket and HTTP heartbeat logs carry `message_type`,
    `active_thread_count`, and `transport`
  - unknown internal WS message-type warnings carry `message_type`,
    `transport`, and `frame_size`
- `src/vaultspec_a2a/api/tests/test_internal.py` now proves those fields with
  focused `caplog` assertions on the real HTTP and WebSocket paths, plus the
  real terminal-status helper path.

Verification:

- `python -m ruff check src/vaultspec_a2a/api/internal.py src/vaultspec_a2a/api/tests/test_internal.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_internal.py -q`
- reported result: `26 passed`
- note: pytest emitted a non-failing `PytestCacheWarning` because `.pytest_cache`
  could not be written in the current workspace

Review outcome:

- No new product defect surfaced in the bounded internal-boundary slice.
- The first verification attempt exposed only a test-fixture assumption error:
  the terminal-update assertion needed to move the thread into `RUNNING`
  through the real CRUD transition path before expecting a terminal update log.
- The meaningful remaining `#88` gap is narrower again:
  - the shared logger, top-priority service paths, and internal relay boundary
    are now covered
  - the next highest-value residual targets are `worker/executor.py` and then
    `cli/_verify.py`

### 2026-03-11 17:34 - High - `#88` executor-path coverage is now implemented, concentrating the remaining observability gap into verifier evidence capture and artifact consumption

- `src/vaultspec_a2a/worker/executor.py` now enriches the existing executor log
  statements with bounded runtime fields at the main worker-owned debugging
  seams:
  - dispatch-bound warnings and exceptions carry `thread_id`, `dispatch_id`,
    `dispatch_action`, `worker_id`, `agent_id`, `team_preset`, and action labels
  - checkpoint pre-flight fallback and short-circuit logs carry
    `thread_id`, `worker_id`, bounded outcome metadata, and fallback/action labels
  - graph-missing, compile-failure, and concurrent-ingest rejection logs now
    include `runtime_mode` plus the dispatch correlation fields already in hand
  - ingest/resume failure logs and execution-state inspection warnings now carry
    the same bounded worker/runtime context rather than only a free-text message
  - config-discovery warnings in `_compile_graph()` now identify the
    `agent_id`, `team_preset`, `workspace_root`, and worker action path
- `src/vaultspec_a2a/worker/tests/test_executor.py` now proves those fields with
  focused `caplog` assertions on real executor dispatch paths for ingest
  graph-missing warnings, resume graph-missing warnings, and concurrent-ingest
  rejection warnings.

Verification:

- `python -m ruff check src/vaultspec_a2a/worker/executor.py src/vaultspec_a2a/worker/tests/test_executor.py`
- `python -m pytest src/vaultspec_a2a/worker/tests/test_executor.py -q`
- reported result: `25 passed`
- note: pytest emitted a non-failing `PytestCacheWarning` because `.pytest_cache`
  could not be written in the current workspace; Ruff also emitted a non-failing
  cache write denial warning

Review outcome:

- No new product defect surfaced in the bounded executor slice.
- The meaningful remaining `#88` gap is now narrower again:
  - the shared logger, top-priority service paths, internal relay boundary,
    and worker executor paths are now covered
  - the next highest-value residual target is `src/vaultspec_a2a/cli/_verify.py`
    under `#87`, where correlation-aware artifact capture and pre-teardown
    diagnostics still remain open

### 2026-03-11 18:05 - High - `#87` verifier evidence capture is now materially stronger, but still needs a fresh elevated prod-like rerun to prove the original timeout is classifiable end to end

- `src/vaultspec_a2a/cli/_verify.py` no longer stops at `compose ps`, raw logs,
  and a failure string.
- The verifier now writes a bounded pre-teardown evidence bundle that includes:
  - `readiness-probes.json` capturing repeated health-probe attempts across the
    startup window
  - `compose.config.yaml` capturing the effective compose config used for the run
  - per-service `docker inspect` artifacts alongside existing per-service logs
  - richer `trace-manifest.json` entries with discovered `trace_id` values in
    addition to trace counts
  - `evidence-manifest.json` linking artifact files, compose files, services,
    health summary, readiness-probe counts, thread id when available, trace
    artifacts, and provider probe artifacts
  - provider verifier stdout/stderr artifacts for
    `vaultspec test prodlike-provider <claude|gemini>`
- `src/vaultspec_a2a/cli/tests/test_verify.py` now proves:
  - readiness-probe history persists across a non-ready then ready transition
    on a real local HTTP path
  - provider probe stdout/stderr artifacts are preserved
  - evidence manifests record bounded correlation metadata and artifact refs

Verification:

- `python -m ruff check src/vaultspec_a2a/cli/_verify.py src/vaultspec_a2a/cli/tests/test_verify.py`
- `python -m pytest src/vaultspec_a2a/cli/tests/test_verify.py -q`
- reported result: `3 passed`
- note: pytest still emitted a non-failing `PytestCacheWarning` because
  `.pytest_cache` could not be written in the current workspace; Ruff also
  emitted a non-failing cache write denial warning

Review outcome:

- No new runtime defect surfaced in the bounded verifier slice itself.
- The remaining open item is no longer “build the evidence surface”; it is to
  run the real elevated prod-like verifier again and confirm that the new
  artifacts make the original gateway-readiness timeout diagnostically
  classifiable without an immediate rerun.

### 2026-03-11 16:25 - High - The prod-like gateway startup permission regression is fixed, and the elevated rerun now fails one stage later at Jaeger trace verification with zero traces for both services

- A fresh elevated `uv run vaultspec test prodlike-docker` rerun was executed
  after the bounded gateway startup-path fix in `src/vaultspec_a2a/api/app.py`.
- The original runtime-root cause from
  `.vaultspec/runtime/verify-prodlike-docker/20260311T150927Z` is now fixed:
  the gateway no longer crashes on startup trying to create
  `/app/.vaultspec/runtime` while `VAULTSPEC_AUTO_SPAWN_WORKER=false`.
- The bounded fix was:
  - `LazyWorkerSpawner` now only resolves a stderr log path when auto-spawn is
    enabled
  - the watchdog/app-state handoff preserves `worker_stderr_log_path=None`
    instead of forcing a startup-owned runtime path
- Focused verification passed:
  - `python -m ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/tests/test_app.py`
  - `python -m pytest src/vaultspec_a2a/api/tests/test_app.py -q`
  - reported result: `10 passed`
- The elevated rerun artifact bundle at
  `.vaultspec/runtime/verify-prodlike-docker/20260311T152303Z` proves the stack
  got materially farther:
  - `compose.ps.txt` shows gateway, worker, Postgres, and Jaeger all healthy
  - `gateway.log` shows successful startup and live request handling
  - `failure.json` now records
    `Jaeger trace verification failed; no traces found for services: vaultspec-a2a, vaultspec-worker`
  - `trace-manifest.json` reports `trace_count: 0` for both services
- `#87` should therefore no longer be described as a gateway-readiness timeout
  with thin diagnostics. That part is fixed.
- The remaining certifying gap is now runtime trace-export / Jaeger-query triage
  on an otherwise healthy prod-like stack.
- `#88` is effectively complete on runtime emission and verifier-consumption
  surfaces; the open follow-on has shifted fully back under `#87` and remains
  separate from `#89`.

### 2026-03-11 18:45 - High - `#87` is now fixed and verified: the bounded verifier Jaeger query-contract fix landed, and a fresh elevated prod-like rerun passed with preserved trace evidence

- A bounded verifier follow-on in `src/vaultspec_a2a/cli/_verify.py` corrected
  the Jaeger trace-verification contract to match the exercised baseline
  prod-like flow:
  - Jaeger queries now use the repo's grounded `service + lookback` pattern
    instead of the earlier `start` / `end` query window shape
  - `verify_prodlike_docker()` now requires traces only for
    `vaultspec-a2a`, which is the service actually exercised by the certifying
    thread-create/state-read flow
  - trace manifests and evidence manifests are now scoped to the queried trace
    services for the run
- Focused verifier coverage passed:
  - `python -m ruff check src/vaultspec_a2a/cli/_verify.py src/vaultspec_a2a/cli/tests/test_verify.py`
  - `python -m pytest src/vaultspec_a2a/cli/tests/test_verify.py -q`
  - reported result: `5 passed`
- A fresh elevated `uv run vaultspec test prodlike-docker` rerun then passed on
  March 11, 2026.
- The certifying success bundle is preserved at
  `.vaultspec/runtime/verify-prodlike-docker/20260311T154053Z`:
  - `trace-manifest.json` reports `vaultspec-a2a` with `trace_count: 4`
  - `evidence-manifest.json` records `thread_id:
    b594e0ce071b4a36aa89e7911ea86fb9`, `readiness_probe_count: 3`, healthy
    Postgres-backed status, and scoped trace services
  - the bundle contains no failure artifact, which is consistent with a
    successful certifying run
- `#87` should now move to fixed/verified rather than remaining open as
  verifier trace-query triage.
- `#88` remains complete on runtime emission and verifier-consumption surfaces.
- `#89` remains unchanged.

### 2026-03-11 20:15 - High - `#89` Phase 1 is now implemented: worker-owned ACP runtime authority is explicit in emitted evidence, and subprocess/handshake failures are now classifiable without widening protocol behavior

- `src/vaultspec_a2a/providers/factory.py` now classifies the resolved ACP
  runtime boundary instead of treating all provider startup paths as an
  undifferentiated command string.
- The emitted evidence now distinguishes bounded runtime-authority surfaces for
  the supported Claude/Gemini ACP paths:
  - local project entrypoints under `node_modules`
  - Docker-bundled Gemini CLI entrypoints
  - package binary authority for bundled single-file Claude ACP binaries
  - explicit executable and system-CLI authority when those paths are used
- The same slice now passes bounded provider/runtime metadata into
  `AcpChatModel`, including:
  - `provider`
  - `runtime_authority`
  - `acp_backend`
  - `command_origin`
  - `command_kind`
  - `command_executable`
  - `command_target`
  - bounded `auth_mode`
- `src/vaultspec_a2a/providers/_subprocess.py` now emits bounded subprocess
  lifecycle evidence for spawn start, spawn failure, spawn success, process
  pid, cwd, spawn mode, and termination escalation/outcome instead of leaving
  those seams mostly implicit.
- `src/vaultspec_a2a/providers/acp_chat_model.py` now adds narrow handshake
  evidence around `initialize`, `session/new`, `session/load`, stderr event
  counting, and early subprocess exit, without broadening prompt/tool-call
  behavior or logging secrets/payloads.

Verification:

- `python -m ruff check src/vaultspec_a2a/providers/factory.py src/vaultspec_a2a/providers/_subprocess.py src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/providers/tests/test_acp_chat_model.py src/vaultspec_a2a/providers/tests/test_subprocess.py`
- `python -m pytest src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/providers/tests/test_acp_chat_model.py src/vaultspec_a2a/providers/tests/test_subprocess.py -q`
- reported result: `31 passed, 8 deselected`
- note: pytest still emitted a non-failing `PytestCacheWarning` because
  `.pytest_cache` could not be written in the current workspace; Ruff also
  emitted a non-failing cache write denial warning

Review outcome:

- No new product defect surfaced in the bounded `#89` Phase 1 slice itself.
- One verification limitation remains explicit: direct asyncio subprocess-pipe
  lifecycle tests hit `PermissionError: [WinError 5] Access is denied` in this
  Windows workspace, so the landed test surface proves the metadata contracts
  and existing provider behavior without resorting to mocks, skips, or fake
  subprocesses.
- `#89` should now move from “implementation pending” to “Phase 1 complete”.
- The next residual scope under `#89` is to carry the same evidence model into
  probe/certifying provider surfaces and then use it in the still-open Docker
  provider certification track under `#86`.

### 2026-03-11 20:55 - High - The live Claude Docker provider certification is now classifiable as a provider quota/account-state failure, and Gemini remains blocked on missing env-key auth in the current Docker cert surface

- A real Docker-backed Claude certification run on March 11, 2026:
  - `uv run vaultspec test prodlike-provider claude`
  failed with preserved evidence at
  `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z`.
- The bundle shows a healthy stack rather than a packaging/runtime collapse:
  - `compose.ps.txt` and `evidence-manifest.json` show healthy gateway, worker,
    Postgres, and Jaeger surfaces
  - `claude.probe.stdout.txt` shows ACP subprocess spawn succeeded, `initialize`
    succeeded, and `session/new` succeeded
  - the failure narrowed to `session/prompt` with provider error:
    `Internal error: You've hit your limit · resets Mar 13, 4am (UTC)`
- This means the Claude Docker path is no longer blocked by:
  - packaging
  - subprocess launch
  - generic auth absence
  - Docker runtime-authority ambiguity
- It is now blocked by provider quota/account state in the current Claude
  credential.
- Gemini remains unverified in this environment because the current Docker cert
  surface requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`, and the current `.env`
  does not provide a non-empty value for that path.

Evidence anchors:

- `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z/claude.probe.stdout.txt`
- `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z/claude.probe.json`
- `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z/evidence-manifest.json`
- `.vaultspec/runtime/verify-prodlike-docker/20260311T205100Z/trace-manifest.json`

Implications:

- `#86` remains open, but it is now narrowed into:
  - Claude: provider quota/account-state retry
  - Gemini: missing env-key auth for the current Docker certification path
- `#89` Phase 1 evidence proved its value by making the Claude failure
  classifiable without another code change.

### 2026-03-11 22:05 - High - The Gemini Docker cert surface now supports mounted local OAuth-backed CLI state, but Gemini CLI ACP still rejects `session/new` as unauthenticated

- The Docker/provider cert surface was extended so Gemini no longer depends
  only on `GEMINI_API_KEY` / `GOOGLE_API_KEY`:
  - `src/vaultspec_a2a/cli/_verify.py` now detects a host-local Gemini CLI
    state root and wires it into Compose as `GEMINI_HOST_CLI_HOME`
  - `docker-compose.prod.providers.yml` now mounts that host root into the
    worker and sets `GEMINI_CLI_HOME`
  - `src/vaultspec_a2a/providers/gemini_auth.py` now resolves the OAuth creds
    path from `GEMINI_CLI_HOME/.gemini/oauth_creds.json`
  - `src/vaultspec_a2a/providers/factory.py` / `probes/gemini.py` now propagate
    the mounted CLI home and set the official Gemini CLI OAuth selector env for
    non-interactive ACP runs
- Focused verification passed:
  - `ruff check src/vaultspec_a2a/core/config.py src/vaultspec_a2a/providers/gemini_auth.py src/vaultspec_a2a/providers/factory.py src/vaultspec_a2a/providers/probes/gemini.py src/vaultspec_a2a/cli/_verify.py src/vaultspec_a2a/providers/tests/test_gemini_auth.py src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/cli/tests/test_verify.py`
  - `pytest src/vaultspec_a2a/providers/tests/test_gemini_auth.py src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/cli/tests/test_verify.py -q`
- The certifying live rerun still failed, but at a narrower boundary:
  - `uv run vaultspec test prodlike-provider gemini`
  - evidence bundles:
    - `.vaultspec/runtime/verify-prodlike-docker/20260311T215323Z`
    - `.vaultspec/runtime/verify-prodlike-docker/20260311T220148Z`
  - `gemini.probe.stdout.txt` shows:
    - mounted OAuth-backed Gemini state is visible
    - token refresh succeeds or validates successfully
    - ACP `initialize` succeeds
    - ACP `session/new` fails with `{"code": -32000, "message": "Authentication required"}`
- Additional grounding from the installed Gemini CLI source explains why this
  residual is specific to Gemini CLI ACP behavior:
  - `.../dist/src/acp/acpClient.js` throws the `Authentication required`
    error from `session/new`
  - `.../gemini-cli-core/dist/src/utils/paths.js` confirms
    `GEMINI_CLI_HOME` is the official home override
  - `.../gemini-cli-core/dist/src/core/contentGenerator.js` and
    `dist/src/validateNonInterActiveAuth.js` show non-interactive auth-type
    selection is an explicit Gemini CLI concern, not a repo-local inference

Implications:

- `#86` remains open, but its Gemini side is reclassified from
  “missing env-key auth” to:
  - Docker auth-material path implemented
  - worker-side OAuth token visibility verified
  - residual Gemini CLI ACP auth/session contract failure at `session/new`
- This is now a better-bounded provider/runtime integration issue than the
  previous blanket “Gemini not certifiable in Docker” status.

### 2026-03-11 23:10 - High - Gemini Docker OAuth-backed certification now passes after aligning subprocess `HOME` with mounted `GEMINI_CLI_HOME`, and mutable runtime outputs no longer target `.vaultspec/runtime`

- The remaining Gemini Docker auth failure was not a missing-token issue after
  all; it was a settings-resolution split inside the container:
  - mounted OAuth state was available under `GEMINI_CLI_HOME`
  - but Gemini CLI still resolved user settings from `HOME=/home/appuser`
  - that dropped `security.auth.selectedType=oauth-personal` and caused
    unauthenticated `session/new`
- The fix landed in:
  - `src/vaultspec_a2a/providers/factory.py`
  - `docker-compose.prod.providers.yml`
- The subprocess/container environment now aligns `HOME` with
  `GEMINI_CLI_HOME`, so Gemini CLI resolves both settings and OAuth creds from
  the same mounted state root.
- The certifying rerun passed:
  - `uv run vaultspec test prodlike-provider gemini`
  - success bundle:
    `.vault/runtime/verify-prodlike-docker/20260311T230801Z`
  - `gemini.probe.stdout.txt` shows:
    - `Loaded cached credentials.`
    - ACP `initialize` ok
    - ACP `session/new` ok
    - ACP `session/prompt` ok
    - `PROBE PASSED`, response text `Hello`
- In the same pass, mutable runtime sinks were moved out of `.vaultspec`:
  - `src/vaultspec_a2a/cli/_verify.py`
  - `src/vaultspec_a2a/cli/_service.py`
  - `src/vaultspec_a2a/api/app.py`
  now emit mutable verifier bundles, service registry/logs, and worker stderr
  logs under `.vault/runtime`.
- Historical evidence bundles under `.vaultspec/runtime/...` remain valid
  historical references; future mutable runtime output now targets
  `.vault/runtime/...`.

Evidence anchors:

- `.vault/runtime/verify-prodlike-docker/20260311T230801Z/gemini.probe.stdout.txt`
- `.vault/runtime/verify-prodlike-docker/20260311T230801Z/gemini.probe.json`
- `.vault/runtime/verify-prodlike-docker/20260311T230801Z/evidence-manifest.json`

Implications:

- `#86` remains partial only because Claude is still provider-quota blocked.
- Gemini Docker OAuth-backed certification is now fixed and verified.
- One non-blocking follow-up remains:
  the worker image still emits Gemini CLI stderr noise for workspace MCP
  extensions like `context7` / `nanobanana` that are not installed inside the
  minimal worker image.

### 2026-03-12 08:46 - Medium - Gemini Docker verifier isolation now removes workspace/user MCP noise while preserving the already-passing OAuth-backed cert path

- The remaining verifier-only Gemini noise was not another auth regression; it
  came from the Docker cert path inheriting both:
  - repo workspace `.gemini/settings.json` when the probe executed from `/app`
  - the full mounted user `.gemini` state, including local extension / MCP
    config
- The hardening fix landed in:
  - `src/vaultspec_a2a/cli/_verify.py`
  - `src/vaultspec_a2a/providers/probes/certifying.py`
  - `src/vaultspec_a2a/cli/tests/test_verify.py`
  - `src/vaultspec_a2a/providers/probes/tests/test_certifying.py`
- The verifier now:
  - executes the Docker Gemini provider probe from `/tmp`
  - mounts a temp-backed minimal `GEMINI_CLI_HOME` containing only auth
    material plus `security.auth.selectedType`
  - cleans up that temp-backed verifier auth home on process exit
  - no longer lets the outer certifying wrapper hard-cut interactive ACP
    providers before their own auth watchdog resolves
- Focused verification passed:
  - `uv run ruff check src/vaultspec_a2a/cli/_verify.py src/vaultspec_a2a/providers/probes/certifying.py src/vaultspec_a2a/cli/tests/test_verify.py src/vaultspec_a2a/providers/probes/tests/test_certifying.py`
  - `uv run python -m pytest src/vaultspec_a2a/cli/tests/test_verify.py src/vaultspec_a2a/providers/probes/tests/test_certifying.py -q`
  - result: `13 passed`
- Real certifying verification passed again:
  - `uv run vaultspec test prodlike-provider gemini`
  - clean bundle:
    `.vault/runtime/verify-prodlike-docker/20260312T084628Z`
  - `gemini.probe.stdout.txt` is now clean of the previous `context7` /
    `nanobanana` MCP discovery noise; only a non-blocking upstream Node
    deprecation warning remains

Implications:

- `#86` remains partial only because Claude is still provider-quota blocked.
- Carry `#86` forward for Friday, March 13, 2026 and rerun the Claude Docker
  certification after the provider reset at 4:00 AM UTC.
- The prior Gemini verifier-noise follow-up is now closed for the Docker
  certification surface.
- The Docker Gemini cert path is now both credential-valid and verifier-clean.

### 2026-03-12 10:30 - Medium - ACP interactive auth failures now surface the browser OAuth URL, and the host-local Gemini ACP path remains healthy

- The remaining auth UX gap was not another Gemini auth regression; it was a
  low-context failure surface in the ACP client itself.
- `src/vaultspec_a2a/providers/acp_chat_model.py` now captures the browser-auth
  handoff prompt and follow-up OAuth URL from ACP stderr, preserves that URL in
  session context, and includes it when auth ends by watchdog expiry or early
  subprocess exit.
- The auth-wait seam remains narrowly scoped to:
  - `_authenticate_rpc(...)`
  - `_wait_for_authenticate_response(...)`
  - the existing `_setup_session(...)` / `authenticate(...)` callers
- Focused verification passed:
  - `uv run ruff check src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/tests/test_acp_chat_model.py`
  - `uv run python -m pytest src/vaultspec_a2a/providers/tests/test_acp_chat_model.py -q`
  - result: `14 passed, 4 deselected`
- Real host-local Gemini ACP verification also still passed:
  - `uv run python -m vaultspec_a2a.providers.probes.gemini`
  - `initialize` ok
  - `session/new` ok
  - `session/prompt` ok
  - `PROBE PASSED`
- Official Gemini CLI docs remain aligned with this model:
  browser-based Google login for local machines, cached credentials for future
  sessions, `GEMINI_CLI_HOME` as the state root, and cached-cred/env auth for
  headless/containerized flows.

Implications:

- The local Gemini ACP bridge is still functioning and authenticated.
- `#89` is stronger on operator-facing auth evidence and subprocess-exit
  classification.
- The `#89` auth seam now classifies those outcomes explicitly via bounded
  `AcpAuthError.data["auth_outcome"]` values, but focused async verification of
  that exact follow-on slice is partially blocked by a host-level Windows
  interpreter failure importing `asyncio` (`OSError: [WinError 10106] ...
  _overlapped`).
