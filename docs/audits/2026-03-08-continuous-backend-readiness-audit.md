# Continuous Backend Readiness Audit

Date: 2026-03-08
Scope: backend implementation, LangGraph service management, worker robustness, process handling, Docker deployment, service separation, production readiness, frontend/backend decoupling
Method: iterative code audit with findings appended as they are confirmed

## Findings

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
