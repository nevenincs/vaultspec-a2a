# 2026-03-09 Postgres Persistence Grounding

## Slice

Phase 1: persistence posture flip from SQLite-shaped runtime wiring to a
backend-selectable runtime with Postgres as the default and SQLite as an
explicit fallback.

## Current local implementation

- The app DB engine in `src/vaultspec_a2a/database/session.py` is hard-coded to
  `sqlite+aiosqlite`.
- The gateway and worker lifespans in
  `src/vaultspec_a2a/api/app.py` and
  `src/vaultspec_a2a/worker/app.py` open
  `AsyncSqliteSaver` directly from a SQLite file path.
- `settings.database_path` is treated as the canonical runtime persistence
  primitive, which makes Postgres impossible without broad call-site changes.
- Startup checkpoint backfill is currently a SQLite file mutation path in
  `src/vaultspec_a2a/database/migrations/__init__.py`.
- The live subprocess harness in `src/vaultspec_a2a/tests/conftest.py` still
  provisions a temporary SQLite database.

## Libraries and components grounded

- SQLAlchemy async engine/session configuration
- Alembic async migration environment
- LangGraph checkpoint persistence
- Gateway and worker lifespan startup wiring

## Context7 findings

### SQLAlchemy

Library: `/websites/sqlalchemy_en_20`

Confirmed:

- `create_async_engine("postgresql+asyncpg://...")` is the standard async
  Postgres engine path.
- `create_async_engine("sqlite+aiosqlite:///...")` remains the SQLite path.
- Connection events must be attached to `engine.sync_engine`.
- Backend-specific initialization at the engine factory boundary is the normal
  pattern.
- For a unified cross-backend schema, SQLAlchemy recommends either:
  - a database-native timezone-aware timestamp type such as
    `TIMESTAMP(timezone=True)` where supported, or
  - a `TypeDecorator` that stores timezone-aware UTC datetimes as naive UTC and
    restores UTC on read.
- When the physical column remains timezone-naive, sending timezone-aware
  `datetime` values directly to Postgres drivers such as `asyncpg` is not safe.

Rejected hypothesis:

- Keeping SQLite-only engine construction and swapping just the URL later.
  This would leave SQLite-specific PRAGMAs and path assumptions spread through
  runtime startup.
- Leaving the existing timezone-aware `datetime.now(UTC)` defaults untouched
  while keeping `DateTime()` / `TIMESTAMP WITHOUT TIME ZONE` columns.
  That shape is tolerated in SQLite but fails on the Postgres path.

### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Production persistence is expected to use database-backed checkpointers.
- Async Postgres checkpointing uses
  `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
- Recommended usage is:

  - `async with AsyncPostgresSaver.from_conn_string(DB_URI) as checkpointer`
  - `await checkpointer.setup()`

- The Postgres saver examples use a plain `postgresql://...` connection string,
  not a SQLAlchemy async dialect URL.

Rejected hypothesis:

- Reusing the SQLAlchemy async URL unchanged for the LangGraph Postgres
  checkpointer. The checkpointer should own its own normalized DSN.

## Official-source fallback research

Not needed for this slice. Context7 coverage was sufficient for the factory
boundary and connection-string decisions.

## Supported constraints

- The app-owned schema remains unified under Alembic.
- Backend abstraction belongs at the engine/checkpointer factory boundary, not
  in divergent ORM models.
- Timestamp semantics must remain UTC-aware at the Python boundary even if the
  storage representation is normalized for backend portability.
- SQLite-specific PRAGMAs and file-path helpers must be gated behind an explicit
  SQLite backend check.
- The checkpoint backfill helper is SQLite-only and must not run for Postgres.

## Chosen implementation direction

- Add explicit `database_backend` and `checkpoint_backend` settings.
- Keep one Alembic-managed app schema.
- Normalize connection handling in config:

  - SQLAlchemy app DB keeps backend-specific SQLAlchemy URLs.
  - LangGraph checkpointer gets a backend-specific connection string derived
    from config.

- Introduce a runtime checkpointer factory module used by both gateway and
  worker lifespans.
- Update session initialization to support both SQLite and Postgres without
  changing call sites outside the persistence boundary.
- Normalize ORM timestamp fields through a shared UTC `TypeDecorator` so the
  codebase keeps timezone-aware UTC values while persisting portable naive UTC
  values underneath.
- Treat SQLite-only operational helpers as explicitly unsupported for Postgres
  rather than silently pretending they work.

## Slice extension: deterministic live restart verification

### Current local implementation

- `src/vaultspec_a2a/api/app.py` exposes transient `worker_status` values from
  the watchdog on `/health`.
- `src/vaultspec_a2a/tests/test_crash_recovery.py` currently tries to observe
  `worker_status="restarting"` directly, but that state is brief and makes the
  test warning-based rather than deterministic.

### Libraries and components grounded

- FastAPI lifespan and application state patterns
- Gateway watchdog state reporting
- Live crash-recovery test harness behavior

### Context7 findings

#### FastAPI

Library: `/fastapi/fastapi`

Confirmed:

- Lifespan-managed resources and state owned by the application are the normal
  place to store long-lived runtime metadata for exposure through endpoints.
- Exposing background-task/process metadata from an endpoint is compatible with
  the standard `FastAPI(lifespan=...)` pattern already used by the gateway.

Rejected hypothesis:

- Keeping restart verification tied only to a transient `worker_status`
  transition. That leaves the test suite race-prone even when recovery is
  functioning correctly.

### Chosen implementation direction

- Keep the runtime state machine, but add latched restart metadata on
  `app.state`:
  restart count, machine-readable reason, optional detail, timestamps, success,
  and attempts.
- Surface that metadata on `/health` so live crash-recovery tests can assert a
  durable repair observation instead of racing a transient `restarting` window.

## Slice extension: Postgres-required startup guards and dependency diagnostics

### Current local implementation

- Backend selection is configurable, but the runtime does not yet enforce that
  `VAULTSPEC_POSTGRES_REQUIRED=true` actually implies Postgres-backed app DB and
  checkpoint backends.
- `/api/health` reports gateway/database/worker status, but it does not yet
  expose backend-specific readiness detail for the configured database and
  checkpointer.
- The async SQLAlchemy engine factory does not yet enable pool pre-ping on the
  Postgres path.

### Libraries and components grounded

- SQLAlchemy async engine configuration
- LangGraph Postgres checkpointer startup
- Gateway/worker health and startup surfaces

### Context7 findings

#### SQLAlchemy

Library: `/websites/sqlalchemy_en_20`

Confirmed:

- `pool_pre_ping=True` is the documented pessimistic disconnect-handling pattern
  for pooled SQLAlchemy engines and is appropriate when stale Postgres
  connections are a production concern.
- Backend-specific engine initialization at the engine factory boundary remains
  the right abstraction point.

Rejected hypothesis:

- Keeping Postgres connection handling identical to SQLite-oriented engine
- creation. That leaves stale pooled-connection behavior untreated and keeps
  backend-specific operational concerns hidden from the runtime boundary.

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Postgres-backed checkpoint persistence expects the saver's `setup()` method to
  be run during startup or deployment.
- Treating checkpointer setup as part of startup readiness is aligned with the
  documented database-backed persistence model.

### Chosen implementation direction

- Add an explicit runtime validation step for `VAULTSPEC_POSTGRES_REQUIRED` so
  gateway and worker startup fail immediately when the configured backends are
  not both Postgres-backed.
- Enable `pool_pre_ping=True` for Postgres SQLAlchemy engines.
- Expose backend-specific database/checkpointer diagnostics from the gateway and
  worker health surfaces so operator-visible readiness matches the configured
  persistence mode.

## Slice extension: Jaeger live-smoke harness compatibility

### Current local implementation

- The live smoke suite uses a real Jaeger v2 container for OTLP verification.
- The fixture had been updated to a current v2 image, but it still probed the
  retired admin port assumption (`14269`, `GET / -> 204`) from the older
  deployment model.
- The real v2 container was healthy, but the fixture timed out because it never
  probed the active health endpoint.

### Libraries and components grounded

- Jaeger v2 all-in-one container behavior
- OpenTelemetry collector health extension behavior
- Live Docker-based smoke harness readiness

### Web research findings

Official Jaeger documentation confirms the v2 all-in-one image exposes the
OpenTelemetry collector health extension on port `13133`. Direct container
inspection in the local environment confirmed the v2 process listens on
`13133`, not `14269`, for readiness, and the active probe path is
`/status` rather than `/`.

Confirmed:

- Jaeger v2 uses the OTel health extension port (`13133`) and `/status` probe
  path for health probing in the current all-in-one deployment.
- The query UI on `16686` can be up even when the old admin-port probe is
  invalid, so the health fixture must target the actual health endpoint rather
  than infer readiness from the UI.

Rejected hypothesis:

- Treating `14269` as the stable health probe port for Jaeger v2. That is no
  longer compatible with the current image and causes false smoke-suite

## Slice extension: partial/skipped no-doubles audit refresh

### Current local implementation

- The old test-suite mock-violations audit is stale in several places.
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py` no longer uses
  `MemorySaver` or `httpx.MockTransport`; it uses a real `AsyncSqliteSaver`
  and a real in-process ASGI worker over `httpx.ASGITransport`.
- `src/vaultspec_a2a/worker/tests/test_ipc.py` no longer uses
  `httpx.MockTransport`.
- `src/vaultspec_a2a/worker/tests/test_executor.py` no longer uses
  `httpx.MockTransport`, but it still had an `object.__new__(Executor)` bypass
  for `_build_graph_input` tests before this slice.
- `src/vaultspec_a2a/core/tests/test_supervisor.py` still depends on a local
  `_StubChatModel`.
- `src/vaultspec_a2a/core/tests/test_graph.py` no longer uses
  `unittest.mock`, but it still exercises `Provider.MOCK`.

### Libraries and components grounded

- FastAPI test dependency injection
- LangChain chat-model testing guidance
- Current MCP/worker/core test implementations

### Context7 findings

#### FastAPI

Library: `/fastapi/fastapi`

Confirmed:

- `app.dependency_overrides` is the official FastAPI testing mechanism for
  binding alternate dependencies during tests.
- Resetting `app.dependency_overrides = {}` is the documented cleanup pattern.
- Using dependency overrides is supported framework behavior, but it is still a
  test-only indirection layer and should be minimized when the repository's
  hard mandate is "no patches/no doubles".

Rejected hypothesis:

- Treating every `dependency_overrides` use as equivalent to a transport mock.
  The framework explicitly treats it as supported DI wiring, and in the current
  MCP tests it binds real DB/checkpointer/ASGI worker dependencies rather than
  fake responses.

#### LangChain

Library: `/websites/langchain`

Confirmed:

- LangChain's own testing guidance recommends fake chat models for
  deterministic unit tests.

Rejected hypothesis:

- Adopting LangChain's fake-model guidance as acceptable for this repository.
  The project mandate is stricter than the library-default guidance, so model

## Slice extension: `#84` execution-state projection authority

### Current local implementation

- The gateway reconstructs reconnect snapshots from raw checkpointer reads plus
  durable app-owned control state.
- The worker already owns compiled graph lifecycle via
  `src/vaultspec_a2a/worker/executor.py`.
- The worker already performs runtime-owned `StateSnapshot` inspection in
  `src/vaultspec_a2a/core/aggregator.py` by calling `graph.aget_state(config)`
  after execution to inspect `state.tasks[*].interrupts`.
- Internal worker -> gateway communication already supports arbitrary pushed
  event payloads via `/internal/events/batch`.

### Libraries and components grounded

- LangGraph persistence / state inspection
- LangGraph stream modes
- Current worker/gateway IPC wiring
- Existing worker-side interrupt detection

### Context7 findings

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- `graph.get_state(config)` and `graph.get_state_history(config)` are the
  documented state/history inspection APIs.
- `StateSnapshot` is the documented checkpoint/state object and contains:
  `values`, `next`, `tasks`, `metadata`, `created_at`, and `parent_config`.
- `CheckpointTuple` is the raw persistence surface, not the documented
  application-facing execution-state surface.
- `stream_mode="checkpoints"` emits events in the same format as `get_state()`.
- `stream_mode="tasks"` emits task lifecycle events, including results/errors.

Installed-package confirmation (`.venv/Lib/site-packages/langgraph/types.py`):

- `StateSnapshot` fields are:
  `values`, `next`, `config`, `metadata`, `created_at`, `parent_config`,
  `tasks`, `interrupts`.
- `PregelTask` fields are:
  `id`, `name`, `path`, `error`, `interrupts`, `state`, `result`.

Rejected hypotheses:

- Reconstructing truthful `tasks` / `next` in the gateway from raw
  `CheckpointTuple` reads. This drifts from LangGraph's intended authority
  model and exceeds the documented persistence contract.
- Treating `stream_mode="tasks"` payloads alone as a durable replacement for
  `StateSnapshot`. Task stream events are useful runtime signals, but the
  authoritative checkpoint/state object remains `StateSnapshot`.

### Local code review findings

- The existing worker-side interrupt detection path in
  `src/vaultspec_a2a/core/aggregator.py` already proves that runtime-owned
  `graph.aget_state(config)` inspection is accepted by the current design.
- The current IPC/event batch path is a better fit than heartbeat for any new
  execution-state projection because heartbeat is ephemeral liveness data,
  while `/internal/events/batch` already carries arbitrary worker-owned facts
  that the gateway can persist durably.
- A worker pull endpoint could supplement refresh behavior, but it cannot be
  the sole authority because it disappears when the worker is down, which is
  exactly when restart/reconnect truth matters most.

### Alternative options grounded

#### Option A: Gateway compiles graphs and calls `get_state(...)`

Pros:

- Direct access to `StateSnapshot` in the gateway.

Cons:

- Conflicts with ADR-031's worker-owned graph lifecycle.
- Reintroduces graph/runtime authority into the gateway.
- Risks configuration drift between worker and gateway compiled graphs.

Status:

- Rejected unless a future architecture revision explicitly replaces ADR-031.

#### Option B: Worker pushes normalized execution-state projections

Pros:

- Aligns with official LangGraph runtime-owned inspection.
- Extends the existing worker-side `graph.aget_state(...)` precedent.
- Preserves gateway role as durable control/read-model surface.
- Works across worker restarts once persisted.

Cons:

- Requires new durable schema and internal event handling.

Status:

- Preferred.

#### Option C: Worker switches or supplements with `stream_mode=\"checkpoints\"`

Pros:

- LangGraph-native source of `StateSnapshot`-shaped updates during execution.
- Avoids an extra state read after every run if integrated carefully.

Cons:

- Current worker pipeline is built around `astream_events(version=\"v2\")`.
- Introducing checkpoint/task streaming would require executor/aggregator
  redesign, not just a small projection patch.
- Even if adopted, durable reconnect truth still needs a normalized persisted
  projection on the gateway side.

Status:

- Viable as a later optimization or enhancement, but not the minimal
  corrective path for `#84`.

#### Option D: Worker pull endpoint returning normalized execution state

Pros:

- Useful as an on-demand freshness mechanism while the worker is healthy.

Cons:

- Not durable.
- Unavailable exactly when the worker is down or restarting.

Status:

- Acceptable only as a supplement to a pushed/persisted projection.

### Projection contract constraints

The normalized durable execution-state projection should be limited to fields
that are both:

1. present on LangGraph's documented runtime state surfaces, and
2. stable/serializable enough to persist as reconnect truth.

Recommended projected fields:

- `thread_id`
- `checkpoint_id`
- `parent_checkpoint_id`
- `snapshot_created_at`
- `next_nodes` (normalized from `StateSnapshot.next`)
- `interrupt_count`
- `interrupt_types`
- `task_count`
- `tasks_json` containing only normalized summaries:
  - `task_id`
  - `name`
  - `path`
  - `has_error`
  - `error_type`
  - `interrupt_ids`
  - `interrupt_types`
  - `has_nested_state`
  - `has_result`
- `worker_generation` / `recovery_epoch` where helpful
- `degraded_reasons`
- `recorded_at`

Explicitly avoid persisting as authoritative reconnect truth:

- raw `PregelTask.result`
- raw nested `PregelTask.state`
- arbitrary exception payloads beyond normalized type/message summaries
- non-serializable runtime objects

### SQLAlchemy portability note for projection storage

Library: `/websites/sqlalchemy_en_20`

Confirmed:

- SQLAlchemy's generic `JSON` type can target PostgreSQL and SQLite.
- SQLite JSON support depends on the JSON1 extension/runtime support.

Implication for this repository:

- because SQLite remains a supported fallback mode, depending on SQLite JSON
  behavior for a critical repair/read-model table adds avoidable portability
  risk
- the safer first slice is to persist normalized task/projection payloads as
  JSON-encoded `Text`, matching existing repository patterns such as
  `allowed_options_json` and `payload_json`

Rejected hypothesis:

- introducing a JSON-typed critical projection column as the initial
  implementation. That is attractive on the Postgres path but makes the SQLite
  fallback path more environment-sensitive than the current schema design.

### Persistence shape recommendation

LangGraph already owns the authoritative checkpoint history. The app-owned DB
does not need to duplicate full execution history to solve `#84`.

Recommended persistence shape for the first corrective slice:

- one latest execution-state projection row per thread
- row replaced/updated whenever the worker records a fresher
  `StateSnapshot`-derived projection
- checkpoint linkage (`checkpoint_id`, `parent_checkpoint_id`) preserved so the
  gateway can correlate the normalized projection with LangGraph history
- normalized task data stored in JSON-encoded `Text` columns for backend
  portability in the first slice

Why this is preferred:

- reconnect/readiness needs current truthful `tasks` / `next`, not a second
  historical event log
- LangGraph already provides historical state via `get_state_history(...)`
- duplicating full history in the app DB would create a second historical
  authority surface and expand drift risk

Implication:

- the control journal remains the durable control/audit log
- LangGraph remains the authoritative checkpoint history
- the new app DB execution-state projection should be treated as a latest
  normalized read model for restart/reconnect truth

### Internal event contract recommendation

The current internal worker -> gateway event envelope is intentionally generic:

- `thread_id`
- `payload: dict`

That means the first `#84` slice can add a new worker-emitted internal event
type without changing the transport shape itself.

Recommended event family:

- `type: "execution_state_projection"`

Recommended payload fields:

- `checkpoint_id`
- `parent_checkpoint_id`
- `snapshot_created_at`
- `next_nodes`
- `interrupt_types`
- `interrupt_count`
- `task_count`
- `tasks`
- `degraded_reasons`

Gateway handling recommendation:

- validate and normalize this event in `api/internal.py`
- persist it to a dedicated execution-state projection table
- do not broadcast this internal projection event directly to browser clients
  unless and until there is an explicit frontend contract for it

### Public snapshot contract recommendation

The current `ThreadStateSnapshot` contract already exposes repair/degradation
semantics (`snapshot_complete`, `degraded_reasons`, `replay_status`) but it has
no explicit execution-state surface for truthful `next` / `tasks`.

The first `#84` slice should expose a normalized, frontend-safe projection
rather than raw LangGraph internals.

Recommended snapshot additions:

- `next_nodes: list[str]`
- `task_count: int`
- `pending_interrupt_count: int`
- `execution_tasks: list[ExecutionTaskSnapshot]`

Recommended `ExecutionTaskSnapshot` shape:

- `task_id: str`
- `name: str`
- `path: list[str]`
- `has_error: bool`
- `error_type: str | None`
- `interrupt_ids: list[str]`
- `interrupt_types: list[str]`
- `has_nested_state: bool`
- `has_result: bool`

Why this shape:

- enough for reconnect/repair truth
- stable across restart
- avoids leaking raw LangGraph runtime objects or provider-specific data
- aligns with the existing snapshot design, which already normalizes messages,
  permissions, tool calls, and artifacts instead of returning raw internal
  models

Degradation rule:

- if durable execution-state projection is absent or stale while checkpoint
  truth exists, the snapshot should remain explicit:
  `snapshot_complete = False` plus a degradation reason such as
  `execution_state_projection_missing` or `execution_state_projection_stale`

### Freshness and staleness rules

The repository already has durable fields that can anchor projection freshness:

- checkpoint identity from the LangGraph read path (`checkpoint_id`)
- `threads.recovery_epoch`
- `threads.repair_generation`

Recommended first-slice staleness rules:

1. If checkpoint truth is available and there is no execution-state projection
   row for the thread:
   - mark `execution_state_projection_missing`

2. If checkpoint truth is available and the persisted execution-state
   `checkpoint_id` does not match the latest checkpoint read by the gateway:
   - mark `execution_state_projection_stale`

3. If the thread entered a new recovery epoch and the projection row does not
   reflect the current `recovery_epoch`:
   - mark `execution_state_projection_stale`

4. If checkpoint truth is unavailable:
   - do not treat the execution-state projection as a replacement for missing
     checkpoint truth; keep checkpoint degradation authoritative

Resulting contract behavior:

- execution-state projection can enrich truthful reconnect state
- checkpoint truth remains primary for checkpoint availability/freshness
- stale projection rows are explicit degraded reconstruction, not silent truth

### Proposed schema and CRUD shape for the first implementation slice

To match the existing repository style, the first `#84` slice should use:

- one dedicated ORM model
- one dedicated Alembic migration
- a small CRUD surface for record/read operations
- JSON-encoded `Text` payload columns where structured task summaries are needed

Recommended table: `thread_execution_state`

Recommended columns:

- `thread_id` (PK + FK to `threads.id`)
- `checkpoint_id`
- `parent_checkpoint_id`
- `snapshot_created_at`
- `recorded_at`
- `recovery_epoch`
- `task_count`
- `interrupt_count`
- `next_nodes_json`
- `interrupt_types_json`
- `tasks_json`
- `degraded_reasons_json`

Recommended indexes/constraints:

- primary key on `thread_id` (latest-row read model)
- index on `checkpoint_id`

Recommended CRUD helpers:

- `record_thread_execution_state(...)`
  - create-or-update latest row for a thread
- `get_thread_execution_state(...)`
  - fetch latest row for snapshot/reconciliation paths
- `delete_thread_execution_state(...)`
  - optional cleanup helper for thread deletion

Normalization helpers should live outside CRUD:

- runtime `StateSnapshot` -> normalized projection payload
- normalized DB row -> `ThreadStateSnapshot` enrichment

This keeps:

- ORM/CRUD focused on persistence
- LangGraph-specific normalization in API/worker projection helpers
- internal event handling in `api/internal.py`

### Chosen direction

- Keep the worker as the `StateSnapshot` authority.
- Generalize the existing worker-side `graph.aget_state(...)` inspection into a
  worker-owned execution-state projection path.
- Persist a normalized execution-state record on the gateway side so restart
  and reconnect surfaces can read durable `tasks` / `next` truth without
  guessing from raw saver rows.
- Treat `stream_mode=\"checkpoints\"` / `\"tasks\"` as a documented LangGraph
  alternative worth revisiting, but not the immediate corrective path while the
  runtime is already built around `astream_events(version=\"v2\")`.
  doubles remain an open cleanup target here.

### Chosen implementation direction

- Remove the concrete bypasses that are easy to close immediately:
  - replace the MCP test's private `spawner._spawned = True` mutation with the
    public `LazyWorkerSpawner.replace_process(None)` API
  - make `Executor._build_graph_input()` a static production helper so tests no
    longer need `object.__new__(Executor)`
- Reclassify the stale audit items against the actual current suite.
- Carry forward the real remaining no-doubles gaps:
  - `_StubChatModel` in `core/tests/test_supervisor.py`
  - broader policy decision on whether FastAPI `dependency_overrides` used only
    to bind real test-local dependencies is acceptable or should be replaced by
    an explicit app-factory injection seam

## Slice extension: graph-side model-double removal

### Current local implementation

- `core/tests/test_graph.py` had already dropped `unittest.mock`, but it still
  exercised `Provider.MOCK` to prove provider-selection behavior without
  needing real credentials.
- `_resolve_model_for_worker()` coupled two concerns:
  - deterministic provider/capability/fallback precedence
  - actual provider construction via `ProviderFactory.create(...)`

### Libraries and components grounded

- LangGraph graph compilation path
- provider-selection logic in `core/graph.py`
- repository certifying-provider posture for real provider construction

### Chosen implementation direction

- Split deterministic selection from provider construction:
  - `_resolve_worker_model_preferences(...)` now owns precedence/fallback
    resolution as a pure production helper
  - `_resolve_model_for_worker(...)` consumes that decision and performs real
    provider construction
- Replace the old `Provider.MOCK` test with a pure preference test over worker
  overrides so the graph/compiler suite no longer relies on a mock provider.
- Extract `_evaluate_supervisor_response(...)` and
  `_build_supervisor_messages(...)` in `core/nodes/supervisor.py` to prepare the
  same pattern for the remaining supervisor model-double cleanup.

## Slice extension: supervisor verification runner instability

### Current local implementation

- The current shell runner still injects a PowerShell profile before command
  execution.
- That profile attempts to write terminal-icon preference files outside the
  writable roots and emits repeated `Access is denied` noise.
- `uv run ...` verification also attempts to persist cache/interpreter state in
  locations that are currently failing under this execution environment.

### Grounded constraint

- In this environment, `uv`-driven verification is not a trustworthy signal
  until it is run with a truly profile-free shell or bypassed entirely with the
  existing virtualenv interpreter.

### Chosen implementation direction

- Persist the supervisor/graph audit findings before retrying verification so no
  analysis remains only in session memory.
- Prefer direct `.venv\\Scripts\\python.exe -m pytest` / `-m ruff` for the
  supervisor slice when `uv` is the failing layer rather than the product code.

## Slice extension: interrupt outcome classification for durable plan approval

### Current local implementation

- The worker executor only suppresses terminal status emission when the
  aggregator returns `"interrupted"`.
- The aggregator already inspects `graph.aget_state(config)` after every run and
  emits durable permission events from `state.tasks[*].interrupts`.
- Real live plan-approval runs can end their `astream_events` loop without the
  worker catching a `GraphInterrupt` exception on the streaming path, even
  though checkpoint state still contains a pending interrupt.
- In that shape, the aggregator emits the durable permission request but still
  returns `"completed"`, which causes the executor to publish an incorrect
  terminal status and the gateway to persist `completed` over a paused thread.

### Libraries and components grounded

- LangGraph interrupt and checkpoint state semantics
- Worker executor terminal-status handling
- Gateway durable permission projection

### Context7 findings

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- LangGraph documents interrupts as durable state visible through
  `__interrupt__` payloads and checkpoint-backed graph state.
- Human-in-the-loop examples resume execution with `Command(resume=...)` after
  inspecting interrupt state rather than relying on a specific exception shape.
- Streaming examples detect pauses from update payloads containing
  `__interrupt__`; the docs do not guarantee that every streaming path will
  surface a caught `GraphInterrupt` exception in the caller.

Rejected hypothesis:

- Treating a caught `GraphInterrupt` as the only authoritative signal that a
  run paused for approval. That is too narrow for the live streaming behavior
  now observed in this stack.

### Chosen implementation direction

- Keep exception-based interrupt detection as an early signal.
- Promote post-run checkpoint interrupt state to the authoritative outcome
  classifier for paused runs.
- Make the aggregator return `"interrupted"` when `aget_state()` shows pending
  approval interrupts and no harder failure/cancel outcome already won.
- Let the worker executor continue to suppress terminal events for
  `"interrupted"` outcomes so paused threads remain durably `input_required`.

## Slice extension: live reconciliation verification for pre-existing running and cancelling threads

### Current local implementation

- `src/vaultspec_a2a/core/reconciliation.py` currently classifies restart-time
  non-terminal threads as follows:
  - pending durable permissions => `input_required` + `paused_resumable`
  - `cancelling` => `cancel_pending`
  - checkpoint unavailable => `repair_needed` + `checkpoint_unavailable`
  - everything else with checkpoint availability => `reconciling` +
    `needs_reconciliation`
- The paused-thread branch is now proven live.
- The remaining Phase 2 gap is proving the other two restart classifications
  with real gateway+worker+Postgres processes:
  pre-existing `running` and pre-existing `cancelling`.

### Libraries and components grounded

- Gateway startup reconciliation
- Existing live crash-recovery harness
- LangGraph durable execution semantics for resumed workflows

### Context7 findings

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Durable execution is already present when a checkpointer is configured; a
  workflow may resume from its last recorded step after interruption or failure.
- Restart-safe behavior is therefore about how the application reconciles its
  app-owned status model with persisted checkpoint state, not about replaying
  the entire run from scratch.
- Human-in-the-loop pause/resume remains keyed by stable `thread_id`.

Rejected hypothesis:

- Treating restart verification for `running` and `cancelling` as purely a unit
  concern. These classifications depend on real process restart ordering and
  persisted runtime state, so they need live verification.

### Chosen implementation direction

- Reuse the paused-thread live harness and crash-recovery subprocess pattern.
- For `cancelling`:
  create a real paused approval thread, issue a real cancel request, restart
  the gateway before any terminal confirmation arrives, and assert
  `repair_status="cancel_pending"`.
- For `running`:
  create a real paused approval thread, submit a real approval response to move
  the thread into the resumed execution path, restart the gateway while the
  worker continues, and assert the startup reconciliation classification
  `status="reconciling"` with `repair_status="needs_reconciliation"`.
- Use the existing real Postgres stack and real certifying provider path; no
  mocks, in-memory DBs, or fake worker paths are acceptable for this slice.

## Slice extension: live Postgres paused-thread recovery across gateway restart

### Current local implementation

- The live subprocess harness in `src/vaultspec_a2a/tests/conftest.py` already
  provisions a real gateway, real worker, and live Postgres container.
- `src/vaultspec_a2a/tests/test_crash_recovery.py` already demonstrates the
  correct per-test subprocess pattern for restart-oriented assertions: fresh
  ports, explicit process ownership, and hard-fail startup checks.
- The plan approval path in `src/vaultspec_a2a/core/nodes/supervisor.py`
  interrupts only when all of the following are true:
  - supervised mode
  - the routed worker is an exec worker
  - `active_feature` is set
  - `vault_index["plan"]` is non-empty
  - approval has not already been granted
- `ThreadMetadata.workspace_root` must be absolute, and the gateway auto-builds
  the initial vault index from the workspace plus `feature_tag`.
- There is no repository `.vault/plan` directory in the current worktree, so a
  valid live approval test must create its own real workspace and plan artifact.

### Libraries and components grounded

- HTTPX async client polling and timeout configuration
- LangGraph durable interrupt and resume semantics
- Existing gateway/worker subprocess harness
- Plan-approval trigger conditions in the supervisor

### Context7 findings

#### HTTPX

Library: `/encode/httpx`

Confirmed:

- `AsyncClient` is the correct client for repeated async polling against a live
  HTTP service.
- Timeouts should be explicit, and `httpx.Timeout(...)` supports separate
  connect/read/write/pool bounds when polling a service that may restart during
  the scenario.
- Connection and timeout exceptions are expected control flow for retry loops
  around restarting services.

Rejected hypothesis:

- Using default implicit client timeouts while restarting the gateway mid-test.
  That makes failures harder to classify and produces brittle polling behavior.

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Durable human-in-the-loop flows resume by invoking the graph with
  `Command(resume=...)` while reusing the same `thread_id`.
- Interrupt payloads are part of the persisted execution state when a durable
  checkpointer is configured.
- Restart-safe resume semantics therefore depend on stable thread identity and
  durable checkpoint availability, not on in-memory gateway state.

Rejected hypothesis:

- Treating the approval request identity as reconstructible only from transient
  gateway memory. The durable model must survive gateway restart and resume
  through the persisted thread/checkpoint state.

### Supported constraints

- The live recovery test must run against real Postgres and real subprocesses.
- The test must create a temporary workspace containing a real
  `.vault/plan/<feature>-plan.md` artifact so the supervisor actually emits the
  plan approval interrupt.
- The test should restart only the gateway while keeping Postgres and the
  worker alive, because the target claim is paused-thread discovery and resume
  after gateway restart.
- Assertions must be against wire-visible thread state and permission-response
  semantics, not internal in-memory objects.
- The repo already contains real provider probes via `vaultspec run probe
  <provider>`, so live-suite readiness should reuse that path rather than
  inventing a second credential check mechanism.

### Chosen implementation direction

- Add a dedicated live Postgres test for paused-thread durability and resume in
  `src/vaultspec_a2a/tests/test_permission_durability_live.py`.
- Reuse the per-test subprocess management pattern from
  `src/vaultspec_a2a/tests/test_crash_recovery.py` instead of the
  session-scoped service fixtures, so the gateway can be stopped and restarted
  deterministically within a single test.
- Create a real temporary workspace with a matching plan artifact and use
  `team_preset="vaultspec-adaptive-coder"` plus `autonomous=false` to force the
  real plan-approval interrupt path.
- Add a real workspace-local `.vaultspec/teams/vaultspec-adaptive-coder.toml`
  override so the test uses one explicit provider path instead of relying on
  the bundled mixed-provider defaults.
- Fail fast when the required live provider probe does not pass. This remains a
  hard failure, not a skip, because the slice is production-certifying.
- Add explicit Just targets for provider-readiness and live Postgres recovery
  verification so the required probe step is part of the executable workflow,
  not only the test body.
- Assert that the thread remains `input_required`, the same approval request ID
  survives gateway restart, and the approval response remains idempotent across
  retries with the same `Idempotency-Key`.
  failures.

### Chosen implementation direction

- Switch the live Jaeger fixture and local `requires_jaeger` gate to the v2
  health endpoint on port `13133`.
- Keep Jaeger verification fully live; do not fall back to fake exporters or
  disable tracing assertions when the harness drifts.

## Slice extension: removing the orphaned `created` lifecycle state

### Current local implementation

- The live create-thread path persists new threads as `submitted`.
- Repository search found no reviewed runtime writer that sets
  `ThreadStatus.CREATED`.
- The dead `created` state still leaks through the durable enum, transition
  table, snapshot fallback logic, CLI status filter choices, and a schema test.

### Libraries and components grounded

- SQLAlchemy string-backed status persistence
- Alembic migration behavior for schema vs data changes
- Thread lifecycle/readiness surfaces in the gateway and CLI

### Context7 findings

#### Alembic

Library: `/sqlalchemy/alembic`

Confirmed:

- Alembic autogenerate is schema-diff oriented; if the database schema does not
  change, an application-only value removal from a plain string column will not
  produce a meaningful schema migration by itself.
- When application semantics change without a column-type change, the right
  migration tool is a data migration that rewrites existing rows as needed.

Rejected hypothesis:

- Treating `created` removal as a backend-specific schema divergence. The
  `threads.status` column is a plain string on both SQLite and Postgres, so the
  cleanup should stay at the application and data-migration layers.

### Chosen implementation direction

- Remove `created` from the application lifecycle enum and transition table.
- Rewrite any legacy `threads.status='created'` rows to `submitted` in a
  dedicated Alembic data migration so upgraded databases remain readable.
- Remove `created` from snapshot fallback logic, CLI filters, and schema/tests
  so new code cannot accidentally reintroduce it.

## Slice extension: repair-aware checkpoint projection beyond `channel_values`

### Current local implementation

- The gateway thread-state endpoint was still treating the checkpointer as a
  `channel_values` source only.
- That left persisted interrupt truth, checkpoint timestamps, and pause-cause
  data invisible to the reconnect path unless the gateway's own durable journal
  happened to provide a matching permission record.
- The open repair gap was not "can the gateway read checkpoint bytes?" but
  "does it inspect persisted checkpoint structure closely enough to classify
  interrupted workflows after restart?"

### Libraries and components grounded

- LangGraph checkpoint tuple persistence
- LangGraph interrupt persistence behavior
- Gateway reconnect snapshot projection

### Context7 findings

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- `CheckpointTuple` contains more than checkpoint `channel_values`; it also
  carries `config`, `metadata`, and `pending_writes`.
- Persisted execution state in LangGraph includes interrupt/task data beyond the
  business-state channels.
- LangGraph's persistence documentation also makes clear that `StateSnapshot`
  tracks `next` and `tasks`, and interrupted graphs surface extra interrupt data
  there; this means a gateway-side repair projection cannot legitimately treat
  `channel_values` as the whole checkpoint truth.

### Local implementation inspection

- Local package inspection confirmed the installed LangGraph types expose:
  `CheckpointTuple`, `StateSnapshot`, `PregelTask`, and `Interrupt`.
- A real interrupted graph was executed locally against a temporary SQLite
  `AsyncSqliteSaver`.
- That live experiment confirmed the persisted checkpoint tuple stores pending
  interrupt payloads under `pending_writes` on the `__interrupt__` channel and
  preserves stable interrupt IDs.

Confirmed:

- Persisted interrupt payloads can be recovered from the checkpoint tuple
  without relying on gateway memory.
- Checkpoint timestamp (`checkpoint["ts"]`) is available and worth surfacing to
  clients/operators because it helps classify freshness and degraded recovery.

Rejected hypothesis:

- Keeping the reconnect path limited to `channel_values` and deferring interrupt
  interpretation entirely to future durable journal work. That would preserve a
  misleading "checkpoint loaded successfully" signal even when the
  pause/interruption truth is missing from the projection.

### Chosen implementation direction

- Introduce a dedicated checkpoint projection helper that normalizes:
  channel values, checkpoint identity, checkpoint timestamp, persisted pending
  interrupts, pause cause, and degraded projection reasons.
- Merge that normalized projection into the API snapshot after the existing
  business-state enrichment step.
- Treat this slice as a partial repair closure, not the final projection model:
  the gateway now reads persisted interrupt writes, but full task/next/history
  reconstruction and durable plan-approval state still belong to the remaining
  Phase 2 work.

## Slice extension: durable plan approval state and stable request identity

### Current local implementation

- The app-owned persistence model already had a durable `permission_requests`
  table and control journal, but plan approval still collapsed to
  `plan_approved: bool` in graph state and did not surface a durable
  thread-level approval state.
- The aggregator was also minting in-memory request IDs for interrupts instead
  of preserving the stable LangGraph interrupt/request identity.
- That combination meant the system could pause for approval and resume, but it
  could not reliably answer "which approval request is this thread blocked on?"
  from durable truth alone.

### Libraries and components grounded

- LangGraph interrupt resume and human-in-the-loop approval patterns
- Alembic schema + data migration guidance
- Existing durable permission/control journal implementation

### Context7 findings

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- Human-in-the-loop approvals are modeled as interrupts plus a later
  `Command(resume=...)`; the request identity is part of the paused execution
  surface and must remain stable across pause/resume.
- Approval workflows are not just booleans; they have a pending blocked phase
  and a later applied outcome.

Rejected hypothesis:

- Keeping plan approval as a boolean-only graph-state concern while hoping the
  durable request table is "close enough" for repair. That still leaves the
  frontend and repair logic without a single durable approval truth surface.

#### Alembic

Library: `/sqlalchemy/alembic`

Confirmed:

- Adding a richer durable approval model to the existing `threads` table is a
  normal explicit schema migration.
- Semantic state upgrades like this belong in explicit Alembic migrations, not
  in implicit runtime mutation.

### Chosen implementation direction

- Extend the existing durable blocked-state model rather than creating a second
  approval-specific table:
  keep `permission_requests` for request lifecycle, add thread-level
  `approval_status`, `approval_request_id`, reason, response-action identity,
  and timestamp for frontend/repair consumption.
- Preserve stable interrupt identity by using payload/request IDs or LangGraph
  interrupt IDs rather than generating new in-memory IDs in the aggregator.
- Switch the active supervisor path away from boolean-only approval semantics,
  while keeping backward compatibility for legacy checkpoints that still carry
  `plan_approved`.

## Slice extension: certifying live-provider selection for Postgres recovery suites

### Current local implementation

- The first paused-thread Postgres recovery suite initially hard-coded the
  OpenAI provider path.
- Real verification showed that was the wrong certifying assumption for this
  environment:
  - OpenAI probe failed with `429 insufficient_quota`
  - Gemini probe initialized but timed out during `session/new`
  - Claude ACP probe passed end to end
- The bundled `vaultspec-adaptive-coder` preset already defaults to `claude`,
  so a single-vendor OpenAI gate was stricter than the actual repo runtime.

### Libraries and components grounded

- Existing repo provider probes under `src/vaultspec_a2a/providers/probes`
- Just-based verification entrypoints
- Live Postgres paused-thread recovery suite

### Confirmed by live verification

- `uv run python -m vaultspec_a2a.providers.probes.claude` passes in this
  environment.
- `uv run python -m vaultspec_a2a.providers.probes.openai` fails with
  `429 insufficient_quota`.
- `uv run python -m vaultspec_a2a.providers.probes.gemini` can initialize but
  times out during `session/new`.
- A provider-agnostic certifying selector is therefore more correct than an
  OpenAI-only gate for this repository.

### Chosen implementation direction

- Add a certifying provider selector that runs the real provider probes in
  priority order and returns the first healthy real provider.
- Wire `Justfile` verification through that selector so the certifying live
  Postgres suite uses a real available provider instead of assuming one vendor.
- Keep the paused-thread recovery suite on a real provider path only; do not
  add any skips, fakes, or fallback doubles.

### New runtime finding from live verification

- Removing the provider-specific blocker exposed a deeper runtime issue:
  the paused-thread recovery test does not reach durable `input_required`.
- After real thread creation on live Postgres with a healthy real Claude
  provider, the thread remains durably:
  - `status='submitted'`
  - `approval_status=None`
  - `pause_cause=None`
  - `pending_permissions=0`
  - `repair_status='healthy'`
- That means the remaining blocker is now the submission-to-execution/interrupt
  path, not provider readiness.

## Slice extension: live reconciliation verification for pre-existing `running` and `cancelling` threads

### Current local implementation

- The gateway startup reconciliation path already classifies pre-existing
  non-terminal threads into repair-aware states.
- What was still unproven was the live Postgres behavior for threads that
  already existed before gateway restart:
  - an actively running thread
  - a cancellation that had been requested but not yet durably applied

### Libraries and components grounded

- Existing live subprocess harness in `src/vaultspec_a2a/tests/conftest.py`
- Gateway restart helper paths in the live Postgres suites
- FastAPI liveness/readiness split already implemented in `app.py`

### Confirmed constraints

- `/health` is the gateway liveness endpoint.
- `/api/health` is aggregate readiness and may intentionally remain non-ready
  when the worker dependency is absent or distressed.
- A restart test that intentionally removes the worker must wait on liveness,
  not full readiness, before asserting the reconciled thread state.

### Rejected implementation hypothesis

- It is not correct to require `/api/health == ok` for every restart scenario.
  That would make the `cancel_pending` recovery case fail for the wrong reason:
  the gateway can be alive and able to report repair truth while aggregate
  readiness is still degraded.

### Chosen implementation direction

- Keep the restart helper reusable, but let each live test choose whether it is
  waiting for liveness or readiness.
- Prove the `running` recovery path with the worker still present and full
  readiness after restart.
- Prove the `cancelling` recovery path by stopping the worker after issuing the
  real cancel request, restarting the gateway on liveness, and asserting the
  durably reconstructed `cancel_pending` state from the thread snapshot.

## Slice extension: live degraded snapshot verification with separate app DB and checkpoint DB

### Current local implementation

- The reconnect snapshot endpoint already advertises:
  - `snapshot_complete`
  - `degraded_reasons`
  - `replay_status`
- The app DB and checkpoint DB are now independently configurable, which means
  a live failure test can keep durable thread/control truth available while
  deliberately breaking checkpoint reads.

### Libraries and components grounded

- LangGraph persistence docs:
  `get_state()`, `get_state_history()`, and checkpoint tuple inspection are the
  durable recovery surfaces; stream-time event delivery is not the same thing as
  durable replay.
- FastAPI WebSocket docs:
  connection/disconnect handling is transport lifecycle only and does not imply
  missed-message replay after reconnect.
- Local snapshot endpoint implementation in `api/endpoints.py`

### Confirmed constraints

- A missing or failed checkpoint read must not be presented as a successful
  durable replay state.
- Durable app-owned truth can still surface paused-thread state even when the
  checkpoint backend is unavailable.
- A real degraded-snapshot test should break only the checkpoint backend, not
  the app database.

### Rejected implementation hypothesis

- It is not correct to treat all checkpoint failures as `gap_detected`.
  `gap_detected` means the snapshot lacks checkpoint truth without a reader
  failure signal; an explicit checkpoint read failure should remain
  `replay_status="unknown"` with a degradation reason such as
  `checkpoint_unavailable` or `checkpoint_timeout`.

### Chosen implementation direction

- Use two live Postgres containers:
  - primary Postgres for the app-owned database
  - separate Postgres for the checkpoint backend
- Create a real paused approval thread so the app DB contains durable paused
  truth.
- Stop only the checkpoint Postgres container and assert that the snapshot API:
  - returns `snapshot_complete=false`
  - returns an explicit checkpoint degradation reason
  - preserves durable paused-thread truth from the app DB
  - does not silently collapse the response into a false-empty snapshot

## Slice extension: live WebSocket reconnect verification on the Postgres stack

### Current local implementation

- The gateway exposes `/ws` and a reconnect snapshot endpoint, but there was no
  certifying live test proving the actual contract between them.
- Local code inspection confirmed:
  - the connection manager sends `ConnectedEvent` on open
  - client subscriptions are explicit
  - per-thread sequence counters support snapshot-based gap handling
  - there is no durable WebSocket message replay layer in the gateway itself

### Libraries and components grounded

- `websockets` asyncio client docs:
  real async client connections, JSON frame send/receive, timeout handling, and
  reconnect patterns are supported cleanly for integration tests.
- FastAPI WebSocket docs:
  transport lifecycle and disconnect handling are the documented guarantees, not
  replay of missed frames.
- Local connection-manager implementation in `api/websocket.py`

### Confirmed constraints

- A certifying reconnect test must use a real WebSocket client, not an in-proc
  test double.
- The reconnect claim should verify snapshot recovery plus explicit lack of
  implicit message replay, not invent stronger guarantees than the gateway
  actually implements.
- To make the reconnect window deterministic, the worker can be stopped after a
  real thread-scoped event is observed and a durable snapshot cursor is
  confirmed.

### Chosen implementation direction

- Add `websockets` as a dev dependency so the repository can run a real
  async client against `/ws`.
- Prove the contract with one live test:
  - observe a real thread-scoped event over WebSocket
  - wait until `/api/threads/{id}/state` reports a durable snapshot with
    `last_sequence >= observed_event.sequence`
  - disconnect
  - stop the worker to prevent new events
  - reconnect and verify the client receives `ConnectedEvent` but not an
    implicit replay of the already-accounted-for thread event

## Slice extension: supervisor no-doubles cleanup and repo-safe core verification

### Current local implementation

- The old `core/tests/test_supervisor.py` suite used a local `_StubChatModel`
  subclass to drive routing and approval tests through `create_supervisor_node()`.
- The repository already had a working temp/cache isolation pattern in
  `Justfile` for backend verification, but the core graph/supervisor suite did
  not use it.
- The actual deterministic routing, gating, and approval-request logic had
  already been extracted into production helpers:
  `_evaluate_supervisor_response(...)` and `_build_supervisor_messages(...)`.

### Libraries and components grounded

- LangChain model config/tag propagation on `invoke/ainvoke`
- LangGraph interrupt semantics for compiled graphs
- Repository-local pytest temp/cache isolation pattern in `Justfile`
- Supervisor deterministic routing/gating helpers in `core/nodes/supervisor.py`

### Context7 findings

#### LangChain

Library: `/websites/langchain`

Confirmed:

- Runnable/model config, including `tags`, is a documented `invoke(..., config=...)`
  / `ainvoke(..., config=...)` path.
- Tag propagation is a runtime invocation concern, not something that requires a
  handwritten test-only fake model to validate all other supervisor behavior.

Rejected hypothesis:

- Keeping a local pseudo-model in the supervisor suite just to preserve broad
  routing/gating coverage. That keeps the tests coupled to a local model double
  even though the routing/gating logic is now deterministic production code.

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- `interrupt()` remains a compiled-graph runtime concern with checkpoint-backed
  pause/resume semantics and `__interrupt__` payloads.
- The approval decision surface itself can still be validated before runtime by
  asserting the generated interrupt payload and blocked-state semantics.

Rejected hypothesis:

- Preserving the old in-graph supervisor approval test as the only acceptable
  way to verify approval semantics. That test shape required a local model
  double and was no longer the cleanest way to validate the deterministic
  supervisor decision path under the repository's no-doubles mandate.

### Chosen implementation direction

- Add a repo-safe `just verify-core` target using the same temp/cache isolation
  pattern already used by the backend smoke/verification recipes.
- Rewrite `core/tests/test_supervisor.py` around production helpers instead of
  a local `_StubChatModel`.
- Keep the supervisor slice focused on deterministic routing/gating/approval
  semantics and rule/message construction.
- Record the remaining no-doubles follow-up separately where model-runtime tests
  still use LangChain fake models in other core suites.

### New review finding from this slice

- `core/tests/test_supervisor.py` is now clean of `_StubChatModel`, but the
  broader core no-doubles trail is not done yet.
- Remaining model-double usage still exists in:
  - `src/vaultspec_a2a/core/nodes/tests/test_supervisor.py`
  - `src/vaultspec_a2a/core/nodes/tests/test_worker.py`
  - `src/vaultspec_a2a/core/tests/test_worker.py`
- That follow-up should be tracked as a new queue item rather than mislabelled
  as part of `#66`, which is now closed.

## Slice extension: core node/worker no-doubles cleanup

### Current local implementation

- The remaining `#81` scope was concentrated in three files:
  - `src/vaultspec_a2a/core/nodes/tests/test_supervisor.py`
  - `src/vaultspec_a2a/core/nodes/tests/test_worker.py`
  - `src/vaultspec_a2a/core/tests/test_worker.py`
- Those files still relied on LangChain fake chat models or local
  `BaseChatModel` subclasses to test deterministic routing, prompt assembly,
  permission-callback wiring, and worker exception wrapping.
- The repository already had a real ACP-backed integration suite in
  `core/nodes/tests/test_worker_integration.py`, so the fake-model unit tests
  were no longer the only coverage for actual worker invocation.

### Context7 findings

#### LangChain

Library: `/websites/langchain`

Confirmed:

- `FakeListChatModel` and `GenericFakeChatModel` are documented testing
  utilities, not required runtime semantics.
- `invoke/ainvoke(..., config={tags: [...]})` remains a standard runtime path,
  which supports extracting deterministic prompt/routing logic from model
  invocation without weakening production behavior.

Rejected hypothesis:

- Keeping first-party fake chat models in these suites because the library
  itself documents them. That still violates this repository's stricter
  no-doubles mandate.

#### LangGraph

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- `interrupt()` returns resume payloads index-by-index on node replay.
- Human-in-the-loop guidance centers on deterministic interrupt payloads and
  idempotent pre-interrupt work, which matches extracting deterministic worker
  and supervisor helpers into production code.
- `GraphInterrupt` / `GraphBubbleUp` behavior is runtime signaling; tests do not
  need a handwritten local model subclass just to validate that these values
  stay unwrapped.

Rejected hypothesis:

- Preserving local `BaseChatModel` subclasses as the simplest way to test
  worker error wrapping and interrupt propagation. The deterministic wrapping
  boundary can live in production helpers instead.

### Chosen implementation direction

- Extract deterministic worker helpers in production code:
  - `_build_worker_messages(...)`
  - `_resolve_effective_worker_model(...)`
  - `_wrap_worker_exception(...)`
  - `_finalize_worker_response(...)`
- Rewrite the remaining node/worker unit suites around those helpers.
- Use real `AcpChatModel` instances for permission-callback wiring checks.
- Keep actual invocation coverage on the existing real ACP integration suite
  rather than preserving fake-model unit paths.

### Verification

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\core\nodes\worker.py src\vaultspec_a2a\core\nodes\tests\test_supervisor.py src\vaultspec_a2a\core\nodes\tests\test_worker.py src\vaultspec_a2a\core\tests\test_worker.py`
- `just verify-core`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\core\nodes\tests\test_worker_integration.py -q`

Results:

- `verify-core`: `78 passed, 1 deselected`
- worker integration: `3 passed`

## Slice extension: live IPC heartbeat + live MCP stdio verification

### Current local implementation

- `src/vaultspec_a2a/tests/conftest.py` already provides the correct
  certifying base: real gateway subprocess, real worker subprocess, and live
  Postgres.
- `src/vaultspec_a2a/worker/tests/test_ipc.py` validates bridge semantics
  against a real ASGI app, but it is still an in-process contract suite rather
  than live subprocess verification.
- `src/vaultspec_a2a/protocols/mcp/tests/test_server.py` validates tool
  behavior through direct tool calls, `TestClient`, and dependency overrides.
  That is useful contract coverage, but it does not satisfy the repository's
  certifying live-service mandate.
- The repository does not yet contain a true MCP end-to-end suite under
  `src/vaultspec_a2a/tests/`.

### Libraries and components grounded

- FastAPI testing and dependency override guidance
- HTTPX transport guidance
- MCP Python client stdio session APIs
- Existing Postgres-backed subprocess harness

### Context7 findings

#### FastAPI

Library: `/fastapi/fastapi`

Confirmed:

- `app.dependency_overrides` is an official FastAPI testing mechanism.
- `TestClient` is the documented in-process path for HTTP and WebSocket tests.

Rejected hypothesis:

- Treating FastAPI's official in-process testing mechanisms as sufficient for
  this repository's certifying backend-readiness claims. They are valid local
  contract tools, but they do not replace the repo's stricter live-process
  verification mandate.

#### HTTPX

Library: `/encode/httpx`

Confirmed:

- `httpx.ASGITransport` is the documented path for directly driving ASGI apps
  without a network hop.
- It is a testing transport, not a substitute for end-to-end subprocess
  verification when the repository requires real network/service boundaries.

Rejected hypothesis:

- Expanding the in-process `ASGITransport` pattern as the primary answer to the
  remaining IPC/MCP audit gaps. That would deepen local contract coverage but
  would not close the live-service verification debt.

### Local library inspection

The installed MCP package in `.venv/Lib/site-packages/mcp` confirms the client
surface needed for a real stdio E2E test already exists:

- `mcp.client.stdio.StdioServerParameters`
- `mcp.client.stdio.stdio_client(...)`
- `mcp.client.session.ClientSession`
- `ClientSession.initialize()`
- `ClientSession.list_tools()`
- `ClientSession.call_tool(...)`

This means the repository can run a real MCP stdio subprocess in tests instead
of fabricating requests through internal helper functions.

### Supported constraints

- The certifying path for `#35` and `#36` must live under
  `src/vaultspec_a2a/tests/` and use the real subprocess stack plus live
  Postgres.
- Existing in-process suites remain useful as non-certifying contract tests,
  but they cannot be treated as proof of production readiness.
- The next implementation should reuse helpers from
  `test_permission_durability_live.py` and `tests/conftest.py` rather than
  inventing a parallel stack bootstrap path.

### Chosen implementation direction

- Add a new live IPC/heartbeat suite that:
  - boots the real gateway and worker on live Postgres
  - creates a real thread
  - asserts `/health`, `/api/health`, and `/api/team/status` reflect worker
    heartbeat and active-thread truth
  - waits for the heartbeat-reported active-thread set to clear after work
    completes
- Add a new live MCP stdio suite that:
  - boots the real gateway and worker on live Postgres
  - launches the real MCP server via stdio using the installed MCP client
  - initializes a real session, lists tools, and calls read/write tools against
    the live gateway
  - proves the MCP layer uses the real end-to-end control plane rather than the
    in-process test harness

## Grounding delta: MCP stdio + cancel semantics

### Context7 findings

#### MCP Python SDK

Library: `/modelcontextprotocol/python-sdk`

Confirmed:

- `StdioServerParameters`, `stdio_client(...)`, and `ClientSession` remain the
  supported client path for stdio E2E sessions.
- The documented flow is:
  - create `StdioServerParameters`
  - `async with stdio_client(...) as (read, write)`
  - `async with ClientSession(read, write) as session`
  - `await session.initialize()`
  - `await session.list_tools()`
  - `await session.call_tool(...)`

Implication:

- The current live MCP test is structurally correct. The remaining failure is
  not transport usage; it is output parsing and must be fixed at the test
  contract layer.

#### HTTPX

Library: `/encode/httpx`

Confirmed:

- `AsyncClient.post(...)` with explicit `Timeout(...)` configuration is the
  current supported async request path for live integration tests.
- The right way to make the IPC heartbeat test deterministic is to drive a real
  cancel request through the HTTP API instead of waiting for provider-dependent
  autonomous completion.

### Chosen implementation adjustment

- Relax MCP thread-ID extraction to accept the real thread ID format emitted by
  the server, including 32-character lowercase hex IDs.
- Replace the heartbeat suite's natural-completion wait with:
  - prove worker heartbeat and `active_threads` visibility
  - issue a real `POST /api/threads/{thread_id}/cancel`
  - assert truthful `cancelling`/terminal state progression
  - assert `active_threads` eventually clears

## Slice extension: skip removal for provider binary-backend coverage

### Current local implementation

- `providers/tests/test_factory.py` still contains imperative `pytest.skip()`
  calls for the Claude ACP binary-backend cases when no bundled binary is
  present under `src/vaultspec_a2a/bin/`.
- The production implementation already has a defined negative contract:
  requesting `backend="binary"` without a bundled executable raises
  `ConfigError`.

### Context7 findings

#### Pytest

Library: `/pytest-dev/pytest`

Confirmed:

- `pytest.skip()` is a supported mechanism for conditionally suppressing tests
  when a requirement is not available.
- That support does not change the repository's stricter policy: required
  verification must fail or assert a truthful negative contract instead of
  silently disappearing from the result set.

#### FastAPI

Library: `/fastapi/fastapi`

Confirmed:

- `dependency_overrides` remains the framework-supported way to replace
- dependencies in in-process tests.

Implication:

- `#57` is now a repository-policy question, not a hidden framework misuse.
- The actionable coding work in this slice is `#60`: remove the remaining
  skip-based provider-factory escape hatches.

### Chosen implementation direction

- Replace binary-backend `pytest.skip()` usage with two truthful assertions:
  - when the bundled binary is present, assert the positive command/env/use-exec
    behavior
  - when the bundled binary is absent, assert the production negative contract:
    `ConfigError` from `_build_acp_command("binary")` or
    `ProviderFactory.create(..., backend="binary")`

## Slice extension: deterministic dead-PID strategy for CLI service tests

### Current local implementation

- `cli/tests/test_service.py` still contains two imperative `pytest.skip()`
  paths because the tests rely on a hard-coded "dead" PID that can
  unexpectedly exist on some machines.
- The runtime contract under test is not "a magic PID is always dead"; it is
  "a recorded PID that is no longer running is classified as stale."

### Context7 findings

#### Pytest

Library: `/pytest-dev/pytest`

Confirmed:

- Runtime `pytest.skip()` is supported when a condition can only be determined
  during execution.
- That does not override the repository policy: if a deterministic runtime setup
  is possible, the test should set up that condition instead of skipping.

### Chosen implementation direction

- Replace the hard-coded dead PID with a real short-lived subprocess PID:
  - spawn a minimal Python child process
  - wait for it to exit
  - assert `_is_pid_running(pid)` is false
  - use that PID for stale-record CLI assertions
- This preserves real process semantics and removes the final skip-based escape
  hatch from the current tree.

## Slice extension: remove FastAPI dependency_overrides from MCP/API in-process app fixtures

### Current local implementation

- `api/tests/conftest.py` and `protocols/mcp/tests/test_server.py` had already
  removed transport/checkpointer doubles, but they still used
  `app.dependency_overrides[...]` to inject the DB session, aggregator,
  checkpointer, worker client, circuit breaker, and worker spawner.
- Most production dependency access in the gateway already resolves through
  `request.app.state`.
- The remaining mismatch was `get_db()`, which still only read the module
  session singleton rather than an app-owned session factory.

### Context7 findings

#### FastAPI

Library: `/fastapi/fastapi`

Confirmed:

- Declaring `Request` in a dependency signature is a supported FastAPI pattern.
- `app.dependency_overrides` is the official test override mechanism, but it is
  still a test-only indirection layer rather than a production seam.

Rejected hypothesis:

- Keeping `dependency_overrides` because FastAPI documents them. That would
  preserve a test-only patch layer even though the gateway already has a clean
  app-state injection path for the same dependencies.

### Chosen implementation direction

- Change `get_db(request: Request)` to first read
  `request.app.state.db_session_factory` and only fall back to the module
  singleton when the app does not provide one.
- Remove `dependency_overrides` from the API and MCP in-process fixtures.
- Set `app.state.db_session_factory` directly in those fixtures.
- Replace remaining `tmp_path` use in the MCP module with repo-local `.tmp`
  paths so the MCP suite verifies the new seam rather than inheriting the
  unrelated Windows temp-root lock failure.

### Verification

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\database\session.py src\vaultspec_a2a\api\tests\conftest.py src\vaultspec_a2a\protocols\mcp\tests\test_server.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py -q`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\protocols\mcp\tests\test_server.py -q`

Results:

- `ruff`: passed
- API tests: `41 passed`
- MCP suite: `38 passed`

Outcome:

- The `dependency_overrides` policy gap is now closed in code for the API and
  MCP in-process fixtures.
- The remaining temp-root failure (`#83`) is narrowed to the CLI module and is
  no longer blocking MCP verification.

## Slice extension: remove pytest temp-root dependency from CLI service tests

### Current local implementation

- `cli/tests/test_service.py` still used `tmp_path` for runtime-dir isolation.
- On this Windows host, the original failure mode was a `PermissionError`
  during pytest temp-root lock creation under `%LOCALAPPDATA%\\Temp`.
- After moving off `tmp_path`, the rerun surfaced a second real test-design
  defect: a just-exited child PID was still reported as running by the CLI's
  `_is_pid_running()` helper on this host.

### Context7 findings

#### Pytest

Library: `/pytest-dev/pytest`

Confirmed:

- `tmp_path` is only a convenience fixture for unique temporary directories.
- The tested CLI code does not depend on pytest-managed temp retention or lock
  semantics; it only needs an isolated writable directory.

Rejected hypothesis:

- Keeping `tmp_path` because it is the default pytest path fixture. That keeps
- the CLI suite coupled to an unrelated host-specific temp-root behavior.

### Chosen implementation direction

- Replace `tmp_path` in the CLI module with a repo-local `runtime_dir` fixture
  under `.tmp/cli-test-runtime/...`.
- Replace the stale-PID setup with a dynamically discovered non-running PID,
  which matches the actual CLI contract (`_is_pid_running(pid) is False`)
  better than assuming a just-exited child PID will be reported dead on this
  Windows host.

### Verification

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\cli\tests\test_service.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\cli\tests\test_service.py -q`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\cli\tests\test_service.py src\vaultspec_a2a\protocols\mcp\tests\test_server.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\tests\test_internal.py -q`

Results:

- CLI module: `10 passed`
- combined verification: `89 passed`

Outcome:

- The old Windows temp-root blocker is no longer present in the CLI module.
- The review uncovered and resolved a real stale-PID test assumption in the
  same slice.

## Slice extension: live Postgres approval-restart verification and Docker preflight hardening

### Current local implementation

- `test_permission_durability_live.py` already encoded the right certifying
  scenario:
  create a real approval-paused thread on live Postgres, restart the gateway,
  rediscover the same pending approval request, and verify duplicate approval
  responses remain idempotent.
- In the default sandboxed run, the session-scoped Postgres testcontainer
  fixture failed early with Docker daemon access denied on
  `//./pipe/docker_engine`.
- The existing fixture surfaced a low-level Docker SDK traceback instead of a
  clean readiness failure.

### Context7 findings

#### Testcontainers Python

Library: `/testcontainers/testcontainers-python`

Confirmed:

- container startup failures should be caught explicitly and surfaced with
  informative error handling around `DockerContainer(...).start()`
- the fixture boundary is the correct place to convert daemon/bootstrap
  failures into clear test failures

### Chosen implementation direction

- Add `_start_container_or_fail(...)` to the live test harness so Docker daemon
  access failures become explicit readiness errors for Jaeger/Postgres
  testcontainers.
- Re-run the blocked approval-restart test with Docker access available to
  distinguish sandbox/daemon access from application behavior.

### Verification

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\tests\conftest.py`
- sandboxed run:
  `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_permission_durability_live.py -m live -q`
- elevated run with Docker access:
  `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\tests\test_permission_durability_live.py -m live -q`

Results:

- sandboxed run: explicit hard failure
  `Postgres live fixture requires Docker daemon access...`
- elevated run: `1 passed`

Outcome:

- Durable approval restart semantics are now proven live on the Postgres stack.
- The remaining issue in the blocked run was Docker daemon access policy, not
  approval-state correctness.

## Slice extension: checkpoint tuple/history projection on the Postgres-primary path

### Current local implementation

- The gateway already reads `CheckpointTuple` via `checkpointer.aget_tuple(...)`
  and projects `channel_values`, checkpoint ID/timestamp, and interrupt writes
  from `pending_writes`.
- The gap was that the snapshot contract still did not surface durable
  checkpoint metadata like parent checkpoint linkage, source/step metadata,
  pending-write channels, or any bounded history signal.
- Local inspection confirmed the endpoint was still effectively
  `channel_values`-centric for repair-aware snapshot reconstruction.

### Context7 findings

Library: `/websites/langchain_oss_python_langgraph`

Confirmed:

- `CheckpointTuple` durably exposes:
  `config`, `checkpoint`, `metadata`, `parent_config`, and `pending_writes`.
- checkpointers support listing checkpoint history via `alist(...)`.
- LangGraph documents `next` and `tasks` on `StateSnapshot`, not on the raw
  `CheckpointTuple`.
- Therefore the gateway can truthfully enrich snapshots from tuple metadata and
  history, but it cannot fabricate `StateSnapshot.tasks/next` from the raw
  checkpointer contract alone.

### Rejected implementation hypotheses

- Do not invent `execution_tasks` or `next_nodes` fields from partial tuple
  metadata.
- Do not treat history listing failure as fatal if the primary tuple read
  succeeds; that would incorrectly downgrade a usable snapshot to
  checkpoint-unavailable.

### Chosen implementation direction

- Expand the `Checkpointer` protocol to include `alist(...)`.
- Extend the checkpoint projection layer and `ThreadStateSnapshot` with durable
  tuple/history fields:
  `checkpoint_parent_id`, `checkpoint_source`, `checkpoint_step`,
  `checkpoint_updated_channels`, `pending_write_channels`,
  `pending_write_count`, `history_depth`.
- Keep history listing optional degradation:
  `checkpoint_history_unknown`, `checkpoint_history_timeout`, and
  `checkpoint_history_unavailable` are surfaced without discarding an otherwise
  readable checkpoint.
- Record the remaining task/next gap explicitly in the audit queue rather than
  pretending the raw tuple path can fully close it.

### Verification

- `.\.venv\Scripts\python.exe -m ruff check src\vaultspec_a2a\database\checkpoints.py src\vaultspec_a2a\api\projection.py src\vaultspec_a2a\api\endpoints.py src\vaultspec_a2a\api\schemas\snapshots.py src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py`
- `.\.venv\Scripts\python.exe -m pytest src\vaultspec_a2a\api\tests\test_projection.py src\vaultspec_a2a\api\tests\test_endpoints.py src\vaultspec_a2a\api\schemas\tests\test_schemas.py -q`

Results:

- `ruff`: passed
- focused API/schema/projection suite: `74 passed`

Outcome:

- The gateway now projects durable tuple/history metadata instead of only
  `channel_values` plus interrupt writes.
- Review surfaced one real defect in the initial implementation:
  history loading was treated as mandatory and could incorrectly collapse a
  usable snapshot into full checkpoint failure. That was fixed in the same
  slice by making history loading degrade independently.
- The remaining gap is now precise:
  truthful `StateSnapshot.tasks/next` reconstruction requires a higher-fidelity
  state source than raw `CheckpointTuple` alone.

## Slice extension: grounding the remaining `tasks/next` repair gap

### Current local implementation

- The gateway has a read-only checkpointer and no compiled graph instances.
- The worker owns graph compilation and already caches `CompiledStateGraph`
  instances in `src/vaultspec_a2a/worker/executor.py`.
- The gateway can inspect raw checkpoint tuples and history, but that only
  yields `checkpoint`, `metadata`, `parent_config`, and `pending_writes`.

### Context7 findings

Libraries:

- `/websites/langchain_oss_python_langgraph`
- `/langchain-ai/langgraph/1.0.8`

Confirmed:

- LangGraph documents `StateSnapshot.next` and `StateSnapshot.tasks` on
  `graph.get_state(config)` and `graph.get_state_history(config)`.
- The checkpointer APIs (`get`, `get_tuple`, `list`, `alist`) expose raw
  checkpoint persistence primitives, not full `StateSnapshot` reconstruction.
- The documented persistence pattern for inspecting `tasks/next` is through a
  compiled graph bound to the same checkpointer, not by parsing raw checkpoint
  tuples in isolation.

### Grounded conclusion

- The remaining `#68` gap is not best solved by more tuple parsing in the
  gateway.
- A truthful implementation needs one of these two paths:
  1. a gateway-side compiled graph capable of `get_state(...)` against the same
     checkpointer and the same graph topology, or
  2. a worker-owned execution-state projection surface that publishes the
     `StateSnapshot`-level truth to the gateway/operators.

### Preferred direction

- Prefer a worker-owned/state-runtime projection path over reintroducing full
- graph compilation into the gateway.
- That preserves the current architecture boundary:
  the worker owns graph lifecycle, while the gateway consumes a normalized
  execution-state projection instead of rebuilding graph runtime locally.

### Implication for next implementation slice

- `#84` should target a higher-fidelity execution-state projection interface,
  not further `CheckpointTuple` enrichment.

### Alternative options and authority check

Option A: compile graphs in the gateway and call `get_state(...)`

- Pros:
  - matches LangGraph's documented `StateSnapshot` access pattern directly
  - gives the gateway native access to `tasks` and `next`
- Cons:
  - reintroduces graph compilation/runtime authority into the gateway
  - duplicates worker-owned graph lifecycle and topology/config loading
  - creates drift risk if gateway and worker compile different graph variants
  - pushes the architecture back toward the pre-separation model

Authority assessment:

- This is compatible with LangGraph's API surface, but it drifts from the
  repo's intended service split where the worker owns execution lifecycle.

Option B: worker-owned execution-state projection surface

- Pros:
  - preserves the current repo architecture: worker owns compiled graphs
  - keeps `StateSnapshot` truth close to the runtime that actually owns it
  - allows the gateway to consume normalized repair truth rather than
    reconstructing runtime state from persistence internals
- Cons:
  - requires a new internal interface or persisted projection contract
  - needs careful durability rules so the projection does not become another
    optimistic memory-only state source

Authority assessment:

- This aligns best with both the repo architecture and LangGraph's intended
  ownership model: runtime state comes from the compiled graph/runtime, not
  from reverse-engineering raw saver rows.

Option C: persist a worker-owned execution-state summary into the app DB

- Pros:
  - gateway can read durable repair truth without graph compilation
  - restart visibility becomes straightforward for operators and clients
- Cons:
  - introduces another projection layer that must be kept consistent
  - requires explicit rules for what is copied from `StateSnapshot` and when
  - if overused, risks shadowing the real checkpoint truth with stale app data

Authority assessment:

- Viable only if treated as a normalized, explicitly versioned projection of
  runtime truth rather than a replacement for the checkpoint substrate.

Drift flag

- Any implementation that keeps adding gateway-side raw checkpointer parsing in
  order to approximate `StateSnapshot.tasks/next` should be treated as
  architectural drift from LangGraph's documented model.
- If a future slice proposes reconstructing `tasks/next` from tuple metadata,
  channel versions, or pending writes alone, that proposal should trigger a
  fresh audit before implementation.

## Slice extension: official precedent for runtime-owned state inspection

### Additional official-source grounding

Official LangGraph docs reinforce the same authority boundary:

- Persistence docs:
  - `graph.get_state(config)` returns the current `StateSnapshot`
  - `graph.get_state_history(config)` returns historical `StateSnapshot`
    objects
  - `StateSnapshot` is the documented home of `values`, `next`, and `tasks`
- Checkpointer docs:
  - raw saver interfaces (`get_tuple`, `list`) are the persistence primitives
  - those are used to populate higher-level state/history APIs, but are not
    themselves documented as the application-facing runtime inspection surface
- LangGraph Platform / Agent Server docs:
  - server-managed threads/history are presented as the authoritative way to
    inspect execution state over time
  - checkpointing and thread-state inspection are handled by the runtime/server
    layer rather than pushed into a separate client-side reconstruction layer

### Grounded implication

- The strongest official precedent is not "every consumer parses raw saver
  state"; it is "the runtime that owns the graph exposes thread state/history".
- That means the repo should bias toward a worker-owned or runtime-owned state
  inspection interface for `tasks/next`, because that is the closest analogue
  to LangGraph's intended design.

### Updated recommendation

- Treat the worker as the execution-state authority for `StateSnapshot`-level
  truth.
- Use the gateway for durable control truth and client-facing normalization.
- If the gateway needs `tasks/next`, it should obtain them from a worker-owned
  execution-state projection or an explicitly persisted worker-produced
  projection, not from raw saver reverse-engineering.

### Reference sources

- LangGraph persistence:
  <https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph durable execution:
  <https://docs.langchain.com/oss/python/langgraph/durable-execution>
- LangGraph interrupts:
  <https://docs.langchain.com/oss/python/langgraph/interrupts>
- LangGraph Platform threads/history:
  <https://docs.langchain.com/langgraph-platform/use-threads>

## Slice extension: local code precedent for worker-owned `StateSnapshot` authority

### Current local implementation

- The worker already performs runtime-owned state inspection today.
- `src/vaultspec_a2a/core/aggregator.py` calls `graph.aget_state(config)` after
  execution in order to inspect `state.tasks[*].interrupts` and surface pending
  permission/plan-approval interrupts.
- The gateway does not do this; it only reads the raw checkpointer and durable
  app-owned control state.

### Grounded implication

- A worker-owned execution-state projection is not a novel architectural leap
  for this repo; it is an extension of an existing runtime-owned inspection
  pattern already used for interrupt recovery.
- The next step for `#84` should therefore be:
  - generalize worker-side `StateSnapshot` inspection beyond interrupt-only use
  - normalize the relevant `tasks/next` truth
  - expose it to the gateway through an internal interface or persisted
    projection surface

### Option ranking after local-code review

1. Worker-owned execution-state projection
   - best fit with official LangGraph state authority
   - best fit with ADR-031 worker ownership
   - leverages an existing worker-side `aget_state(...)` precedent

2. Worker-persisted normalized execution-state summary
   - viable if explicitly treated as a projection of runtime truth
   - requires careful durability/versioning rules

3. Gateway-side graph compilation + `get_state(...)`
   - least preferred
   - introduces authority drift against ADR-031 by moving graph-runtime
     inspection back into the gateway

### Implementation design constraint for `#84`

- Do not implement `#84` as more gateway-side checkpointer parsing.
- Do not implement `#84` by silently compiling production graphs in the gateway
  without first recording that as an architectural revision.

## Slice extension: worker-gateway IPC options for `#84`

### Current local implementation

- Worker -> gateway IPC currently has two active HTTP surfaces:
  - `/internal/events/batch` for batched worker events
  - `/internal/heartbeat` for worker liveness and `active_threads`
- The worker bridge already carries arbitrary event payloads on the batch path.
- Heartbeat handling in the gateway only updates in-memory app state:
  `worker_last_heartbeat_ts` and `worker_active_threads`.

### Grounded constraint

- Heartbeat is intentionally lightweight and ephemeral. It is not a durable
  repair-truth channel.
- Event batches are expressive enough to carry normalized execution-state
  payloads, but the current event relay path is still transient unless the
  gateway persists what it receives.
- A pure pull-only worker endpoint (for example `GET /internal/thread-state`)
  would align with runtime-owned authority, but it would become unavailable
  exactly when the worker is down or restarting, which is one of the states the
  repair model must classify correctly.

### Option comparison for `#84`

Option A: extend heartbeat payload with `tasks/next` summary

- Rejected direction.
- Reason:
  heartbeat semantics are liveness-oriented and app-state-only; overloading them
  with restart-relevant execution truth would blur authority and encourage
  silent staleness.

Option B: push execution-state projection over `/internal/events/batch`

- Viable.
- Worker can inspect `graph.aget_state(config)` and emit normalized
  execution-state update events on meaningful transitions.
- Gateway can persist the normalized projection on receipt so reconnect/restart
  semantics remain durable.

Option C: add an internal worker read endpoint for on-demand execution-state
inspection

- Also viable as a supplement, not as the only source.
- Best use:
  when the worker is healthy, the gateway can request fresh `StateSnapshot`
  projection for a thread.
- Limitation:
  unavailable during worker outage, so it cannot be the only repair-truth path.

Option D: persist worker-produced execution-state summary into app DB

- Strong candidate, likely combined with Option B.
- Worker remains the authority because it reads `graph.aget_state(...)`.
- Gateway consumes a durable normalized projection instead of reconstructing
  state locally.

### Current preferred architecture

- Hybrid worker-owned execution-state projection:
  - worker inspects `graph.aget_state(...)`
  - worker emits/persists normalized execution-state summaries
  - gateway reads the durable projection for restart/reconnect truth
  - optional on-demand worker read endpoint can refresh or deepen projection
    when the worker is healthy

### Why this best matches the mandates

- Aligns with LangGraph's runtime-owned `StateSnapshot` authority
- Preserves ADR-031 worker ownership of compiled graphs
- Avoids gateway-side authority drift
- Supports restart-stable frontend and operator semantics when the worker is
  unavailable

## Slice extension: persistence shape for normalized execution-state truth

### Current local implementation

- `ThreadModel` already stores coarse durable control/repair truth:
  `status`, `repair_status`, `execution_readiness`, approval linkage, and last
  requested/applied control actions.
- `ControlActionModel` is the ordered journal of control intent and repair
  actions.
- There is no dedicated durable record for richer runtime execution-state
  projection such as checkpoint-linked `tasks/next` summaries.

### Grounded implication

- `ThreadModel` should remain coarse and operator-facing; it is not a good home
  for a richer, evolving execution-state projection with checkpoint linkage.
- `ControlActionModel` is also the wrong fit because `tasks/next` truth is not
  a control action; it is runtime execution state.
- The likely clean design for `#84` is a dedicated, app-owned execution-state
  projection record keyed by thread and checkpoint identity, produced by the
  worker from `graph.aget_state(...)`.

### Preferred persistence direction

- Add a dedicated durable execution-state projection table or equivalent model
  that can carry:
  - thread ID
  - checkpoint ID
  - parent checkpoint ID
  - state freshness timestamp
  - normalized `next` node names
  - normalized task summaries / interrupt summaries
  - degraded / unavailable reasons when state inspection could not complete
  - worker generation / recovery epoch linkage where useful

### Why this is preferable

- Keeps coarse lifecycle/repair state separate from richer execution-state
  detail
- Avoids repeatedly mutating the `threads` table with highly specific runtime
  projection fields
- Allows versioned evolution of the execution-state contract without
  overloading the main thread row
- Better matches the hybrid-truth model:
  app DB owns normalized control and operator truth, while LangGraph remains
  the execution substrate authority

## 2026-03-10 21:05 - `#84` implementation and review outcome

The first corrective slice for `#84` is now implemented and verified locally.

Implemented:

- dedicated latest-row execution-state persistence model:
  `thread_execution_state`
- worker-owned runtime inspection via `graph.aget_state(...)`
- worker-emitted internal `execution_state_projection` events
- gateway persistence of normalized execution-state truth
- reconnect snapshot enrichment with:
  - `next_nodes`
  - `task_count`
  - `pending_interrupt_count`
  - `execution_tasks`
- freshness classification anchored to:
  - checkpoint ID
  - recovery epoch

Important review finding from the implementation pass:

- a degraded-only execution-state event would overwrite a previously good
  durable projection row with empty `checkpoint_id` / empty tasks.
- that behavior was incorrect because it destroys better durable truth after a
  transient runtime inspection failure.
- the fix preserves the last good normalized execution-state payload and only
  updates `degraded_reasons`, `recorded_at`, and `recovery_epoch` for
  degraded-only updates.

Additional environment finding:

- file-backed SQLite verification on the mapped `Y:` workspace path produced
  real `disk I/O error` failures under `aiosqlite` for migration/WAL tests.
- the tests were moved to a local writable root under
  `C:\Users\hello\.codex\memories\tmp\...` so verification reflects SQLite
  behavior instead of mapped-drive quirks.
- this reinforces the broader audit position that SQLite path/filesystem
  behavior must not be assumed equivalent across environments.

Verification completed for this slice:

- `ruff check` on touched runtime/test files
- targeted API/internal/projection/schema/database suites
- result:
  `105 passed`

Remaining open work:

- live Postgres verification that the new execution-state projection survives
  real worker/gateway restart paths and produces truthful reconnect snapshots
  under the production-authoritative backend
- until that live verification exists, `#84` should remain `PARTIAL` rather
  than `FIXED`

## 2026-03-10 22:20 - `#84` live verification closeout and fixture isolation finding

Grounding used for the closeout fix:

- SQLAlchemy docs confirm Postgres statements that must run outside a
  transaction should use DBAPI autocommit / `isolation_level="AUTOCOMMIT"`.
- That is an appropriate fit for `CREATE DATABASE` / `DROP DATABASE` setup for
  live-suite isolation.

Implementation/review outcome:

- The first live closeout run for `#84` exposed a real suite-level issue:
  `test_permission_durability_live.py` reused one logical Postgres database
  across multiple paused-thread restart tests.
- That allowed durable thread/checkpoint state from one test to leak into the
  next and produced misleading startup failures in sequential runs.
- The fix keeps the same live Postgres container but allocates a fresh logical
  database per test via a new `isolated_postgres_urls` fixture.
- Review of the first fixture implementation surfaced a second real defect:
  converting derived URLs with `str(make_url(...))` redacted the password to
  `***`, which caused worker/gateway authentication failures.
- Fixed in-slice by rendering URLs with
  `render_as_string(hide_password=False)`.

Verification completed after the fix:

- local targeted suite:
  `105 passed`
- live paused-thread restart suite:
  - `test_plan_approval_survives_gateway_restart_and_response_retry`
  - `test_execution_state_projection_survives_gateway_restart_for_paused_thread`
  - result: `2 passed`

Current conclusion:

- `#84` is now fully implemented and live-verified.
- This also closes the remaining `#68` gap for truthful `tasks/next`
  reconstruction because reconnect snapshots now use worker-owned normalized
  execution-state truth instead of raw `CheckpointTuple` inference.

## 2026-03-10 23:20 - Postgres prod-like Docker grounding and closeout

Grounding used for this slice:

- Docker Compose health/dependency guidance supports `depends_on:
  condition: service_healthy` for database-backed startup ordering.
- Postgres setup/teardown operations that must run outside a transaction should
  use autocommit.
- The production image should start the already-built runtime directly, not
  trigger a fresh dependency resolution/build step at container startup.

Implementation and review outcome:

- Added a dedicated Postgres prod-like overlay:
  `docker-compose.prod.postgres.yml`
- Updated Jaeger image/health wiring in the compose stack to the current v2
  health endpoint (`13133/status`)
- Added `just up-prod-postgres`, `just down-prod-postgres`, and
  `just verify-prodlike-docker`
  `just verify-claude-docker`
  `just verify-gemini-docker`
- Updated Docker docs and repo hygiene coverage for the new overlay

Real defects surfaced by the first prod-like run:

1. Production images still launched with `uv run uvicorn`, which caused the
   worker container to perform a runtime dependency/build step before startup.
   That made the worker fail its health timing contract in the prod-like stack.
   Fixed by launching the prebuilt `.venv` interpreter directly in
   `docker/prod.Dockerfile`.

2. The gateway container could not run migrations in the installed image
   because `database/migrate.py` resolved `alembic.ini` relative to the
   site-packages path and the image did not contain a repo-root `alembic.ini`.
   Fixed by:
   - resolving Alembic config from `settings.project_root`
   - copying `alembic.ini` into the image
   - setting `VAULTSPEC_PROJECT_ROOT=/app` for the gateway image too

Verification completed:

- `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
- `docker compose -f docker-compose.dev.yml -f docker-compose.integration.yml config`
- `pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
- `ruff check src/vaultspec_a2a/database/migrate.py src/vaultspec_a2a/worker/app.py src/vaultspec_a2a/tests/test_repo_hygiene.py`
- `just verify-prodlike-docker`
- `just verify-claude-docker`
- `just verify-gemini-docker`

Result:

- the Postgres prod-like Docker stack now boots successfully
- `/api/health` reports `status="ok"` on the Dockerized gateway
- thread create + thread state lookup pass against the prod-like Postgres stack

Queue implication:

- `#73` is now effectively closed for runtime/config/readiness behavior
- `#74` should move to `PARTIAL` because the staged verification target now
  exists and passes, but CI-matrix integration is still a separate follow-up

## 2026-03-10 23:55 - CI promotion grounding for prod-like Docker/Postgres verification

Grounding used for this slice:

- GitHub Actions on `ubuntu-latest` supports running Docker/Compose workloads
  directly on the runner host, which is the simplest way to promote the
  existing prod-like Docker verification into a PR gate without introducing a
  second verification implementation.
- The local PowerShell-only `Justfile` recipe is not an appropriate CI
  authority because it would force the workflow to depend on shell-specific
  behavior rather than the actual verification contract.
- The cleaner authority model is:
  - one repo-owned verifier implementation
  - local Just recipe calls it
  - GitHub Actions workflow calls the same verifier

Implementation and review outcome:

- Added `vaultspec test prodlike-docker` as the single verifier authority
  implementation for:
  - compose bring-up
  - `/api/health` polling
  - backend/checkpointer assertions
  - real thread create + state lookup
  - guaranteed teardown in `finally`
- `just verify-prodlike-docker` now delegates to that script
- `just verify-claude-docker` / `just verify-gemini-docker` provide simpler
  provider-specific shortcuts
- Added `.github/workflows/prodlike-docker.yml` so prod-like Docker/Postgres
  verification runs on `push`, `pull_request`, and `workflow_dispatch`

Real review finding surfaced during the first run:

- the first verifier implementation only retried `urllib.error.URLError` during
  gateway startup polling
- the real prod-like run exposed `http.client.RemoteDisconnected` while the
  gateway was still warming up
- that was a verifier bug, not a product bug: the stack was still coming up,
  but the script treated the transient disconnect as fatal and tore everything
  down early
- fixed in-slice by widening the retryable warmup exceptions to include
  `HTTPException`, `OSError`, and JSON parse failures during the health poll

Verification completed:

- `python -m ruff check src/vaultspec_a2a/cli/_verify.py`
- `pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
- `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
- elevated real prod-like run via
  `uv run vaultspec test prodlike-docker`

Current conclusion:

- `#74` is now grounded and implemented as a real PR-gate candidate, not just a
  local staged recipe
- the remaining work is workflow evolution/matrix expansion, not initial CI
  promotion

## 2026-03-10 20:00 - API harness grounding for `#56` closeout

Grounding used for this slice:

- FastAPI's official testing guidance still treats application-construction and
  dependency injection seams as normal testing tools, but this repo's stricter
  mandate intentionally forbids `dependency_overrides` and other monkeypatched
  substitution on certifying paths.
- SQLAlchemy's async-engine documentation supports both in-memory and
  file-backed SQLite for tests, but in-memory SQLite remains a test-only
  substitute with materially different lifecycle and connection semantics from
  the production-backed database story in this repo.
- Under the repo's hard no-doubles/no-in-memory rule, the remaining `#56` gap
  was therefore the API suite's continued use of `sqlite+aiosqlite:///:memory:`
  rather than any mock transport or fake worker behavior.

Implementation and review outcome:

- `src/vaultspec_a2a/api/tests/conftest.py` now provisions isolated
  file-backed SQLite databases under the writable Codex memory root instead of
  `:memory:`.
- `src/vaultspec_a2a/api/tests/test_projection.py` was updated to remove its
  last in-memory SQLite case.
- The existing app-state injection seam and real `AsyncSqliteSaver` /
  in-process ASGI worker path remain unchanged.
- Review of the actual diff did not surface a new product or harness defect.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/api/tests/conftest.py src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/tests/test_projection.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_endpoints.py src/vaultspec_a2a/api/tests/test_projection.py src/vaultspec_a2a/api/tests/test_internal.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Current conclusion:

- `#56` is now fully closed.
- The API harness no longer relies on `MockTransport`, `MemorySaver`,
  `dependency_overrides`, private spawner state mutation, or in-memory SQLite
  persistence.

## 2026-03-10 00:25 - Worker supervision grounding for `#52`

Grounding used for this slice:

- Python's official subprocess documentation warns that `PIPE` is only safe
  when the parent actively drains it; otherwise it is easy to lose diagnostics
  or deadlock on buffered output.
- For this gateway's supervision path, the real operational requirement is not
  interactive streaming. It is durable crash diagnostics that survive long
  enough to be exposed through health/readiness surfaces after a worker crash.
- That makes a deterministic stderr log file a better fit than keeping a live
  `stderr=PIPE` handle attached to a long-lived worker child process.

Implementation and review outcome:

- Gateway-managed worker spawns now redirect stderr to a deterministic
  repo-local runtime log under `.vaultspec/runtime/`.
- Both `/health` and `/api/health` now expose `worker_stderr_log_path`, and
  restart records include `stderr_log=...` plus a compact stderr tail when one
  exists.
- The live crash-recovery suite now asserts that the durable restart record
  includes the stderr log path on the real Postgres-backed gateway+worker stack.

Real review findings surfaced and were fixed in-slice:

- The first implementation attached the new diagnostic field only to `/health`,
  but the existing API-side verification path uses `/api/health`. Fixed by
  exposing the same diagnostic path there as well.
- The first helper test used `tmp_path` and re-hit the known Windows pytest
  cleanup issue. Fixed by moving the test file path onto the writable Codex
  memory root instead of relying on `tmp_path`.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/tests/test_crash_recovery.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- elevated live Postgres verification:
  `python -m pytest src/vaultspec_a2a/tests/test_crash_recovery.py -m live -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Current conclusion:

- `#52` is now closed.
- Gateway-owned worker supervision preserves actionable stderr diagnostics
  across restart cycles instead of collapsing later crashes to a bare
  returncode.

## 2026-03-11 00:58 - WebSocket phantom-thread grounding for `#42`

Grounding used for this slice:

- Context7 / FastAPI docs confirm that accepted WebSocket connections should
  surface protocol/state rejections as structured in-band error messages when
  the server wants the client to recover without dropping the socket.
- LangGraph checkpoint docs and the repository's own repair model confirm that
  a missing app-owned thread row is not enough to conclude the thread is
  truly gone. Durable backend residue can still exist in the checkpoint store.
- Local CRUD/model review clarified an important constraint: the app-owned
  `thread_execution_state` projection is foreign-keyed to `threads`, so an
  orphaned execution-state row is not the normal phantom-thread case under the
  current schema. The real phantom risk path is checkpoint residue, not a
  surviving projection row.

Implementation and review outcome:

- WebSocket command handlers now raise a structured
  `WebSocketCommandRejectedError` for:
  - missing thread rows
  - terminal threads
  - `input_required` threads
- Missing-thread commands are classified as:
  - `THREAD_STATE_DRIFT` when durable backend residue still exists
  - `THREAD_STATE_UNVERIFIED` when checkpoint truth cannot be verified
  - `THREAD_NOT_FOUND` when no durable residue is found
- The accepted WebSocket connection remains open and receives an explicit
  `error` frame instead of silently accepting or dropping the command.

Real review findings surfaced and were fixed in-slice:

- The first verification attempt tried to create phantom drift via
  `record_thread_execution_state(...)`, but the production CRUD path correctly
  refuses to persist execution-state rows without a real thread row.
- The truthful test was rewritten to seed a real LangGraph checkpoint through
  `AsyncSqliteSaver.aput(...)`, which exposed another real saver requirement:
  the config must include `configurable.checkpoint_ns`.
- After adding the valid checkpoint config shape, the focused suite passed.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/websocket.py src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_app.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_websocket.py src/vaultspec_a2a/api/tests/test_app.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Current conclusion:

- `#42` is now closed.
- Phantom-thread handling is now explicitly repair-aware:
  a missing gateway row is no longer treated as sufficient proof that the
  thread is safe to forget or delete.

## 2026-03-11 01:12 - Docker/service dependency grounding for `#41`

Grounding used for this slice:

- Context7 / Docker Compose docs confirm the intended semantics here:
  - service-level `restart` is the right place for runtime restart policy
  - `depends_on.condition: service_healthy` is the right way to gate startup on
    actual health instead of mere process start
- Local compose review shows the repo now already follows that model on the
  production-authoritative path:
  - `docker-compose.prod.yml`
  - `docker-compose.prod.postgres.yml`
  - `docker-compose.dev.yml`
  - `docker-compose.integration.yml`

Implementation and review outcome:

- No new compose code change was required for `#41`.
- Verification showed the old queue entry was stale:
  - `docker-compose.prod.yml` and the Postgres overlay already use
    `restart: unless-stopped`
  - gateway/worker/jaeger/postgres dependencies already use
    `condition: service_healthy` where appropriate
  - `VAULTSPEC_INTERNAL_TOKEN` is already enforced by the production compose
    file via required variable interpolation
- The remaining gap was documentation drift, so `docker/README.md` now states
  the required production env explicitly.

Verification completed:

- `python -m pytest src/vaultspec_a2a/tests/test_repo_hygiene.py -q`
- `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml config`
  with `VAULTSPEC_INTERNAL_TOKEN` set in the shell

Important review conclusion:

- `#41` is closed as a stale queue item, not as a fresh code defect.
- The old `DCK-L04` note is also no longer an open product issue because the
  compose file already hard-fails when `VAULTSPEC_INTERNAL_TOKEN` is absent.
- `docker-compose.integration.yml` is still an overlay, so rendering it alone
  is not a meaningful failure signal.

Current conclusion:

- `#41` is now closed.
- Remaining Docker/posture work is limited to the SQLite fallback track (`#72`)
  and normal maintenance, not a restart/health-ordering defect.

## 2026-03-11 01:35 - SQLite fallback diagnostics grounding for `#72`

Grounding used for this slice:

- Context7 / SQLAlchemy SQLite docs confirm the intended operational pattern:
  - SQLite-specific runtime configuration such as connection pragmas belongs in
    connect-event hooks
  - file-backed async SQLite remains a valid backend shape, but operational
    truth still needs to be surfaced by the application
- Official SQLite guidance reinforces the remaining fallback risk:
  - WAL availability is environment/filesystem sensitive
  - `busy_timeout` is a configured runtime behavior, not a durable health fact
  - operator-visible fallback diagnostics are therefore required if SQLite
    remains supported

Implementation and review outcome:

- The repo already had the right architecture:
  - backend-selectable DB/checkpointer factories
  - Postgres as the certifying backend
  - SQLite as fallback only
  - WAL/busy-timeout setup on the SQLAlchemy engine
- The remaining gap was visibility, not persistence design.
- The closeout therefore exposes explicit `sqlite_fallback` diagnostics instead
  of trying to promote SQLite into a certifying path.

Implemented diagnostics:

- `inspect_sqlite_database(path)` inspects a real SQLite file for:
  - existence
  - current `journal_mode`
  - whether WAL is actually enabled
  - a detail message when WAL is unavailable
- The gateway now records `sqlite_fallback` diagnostics at startup and exposes
  them on both `/api/health` and `/health`.
- The payload makes the fallback contract explicit:
  - `active`
  - `busy_timeout_ms`
  - `production_certifying: false`
  - `limitations: ["sqlite_fallback_not_production_certifying"]`
  - per-file diagnostics for the app DB and checkpoint DB when SQLite is used

Verification completed:

- `python -m ruff check src/vaultspec_a2a/database/session.py src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/endpoints.py src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py`
- `python -m pytest src/vaultspec_a2a/api/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Current conclusion:

- `#72` is now closed.
- SQLite fallback remains supported and explicit, but visibly non-certifying.

## 2026-03-11 01:55 - Worker `/dispatch` auth grounding for `WRK-K06`

Grounding used for this slice:

- Context7 / FastAPI docs confirm the intended pattern for internal service
  authentication:
  - enforce bearer-token validation at the route/dependency boundary
  - return `401` for invalid or missing credentials when auth is configured
  - use explicit config failure when a privileged internal route is exposed in
    a non-development environment without the required secret
- Local authority checks already matched that shape:
  - gateway `/internal/*` routes validate `Authorization: Bearer ...`
  - `WorkerBridge` already knows how to send the internal bearer token
  - worker `/dispatch` was the remaining auth gap in the gateway->worker path

Implementation and review outcome:

- The worker `/dispatch` route now depends on `_verify_dispatch_token(...)`.
- The gateway-owned worker client now sends the same bearer token by default.
- The in-process API test worker was upgraded to enforce the same auth contract,
  so the gateway dispatch path is verified against a real auth boundary rather
  than a permissive test helper.
- Review surfaced one coverage gap in the first pass: the non-development
  misconfiguration path (`internal_token=None`) existed but was untested.
  That is now covered directly.

Implemented contract:

- if `settings.internal_token` is configured:
  - `/dispatch` requires `Authorization: Bearer <token>`
  - invalid or missing credentials return `401`
- if `settings.internal_token` is not configured:
  - development allows the route for local convenience
  - non-development environments fail loudly with `500` configuration error

Verification completed:

- `python -m ruff check src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/worker/app.py src/vaultspec_a2a/api/app.py src/vaultspec_a2a/api/tests/conftest.py src/vaultspec_a2a/api/tests/test_endpoints.py`
- `python -m pytest src/vaultspec_a2a/worker/tests/test_app.py src/vaultspec_a2a/api/tests/test_endpoints.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- result: `29 passed`

Current conclusion:

- `WRK-K06` is now closed.
- The gateway->worker dispatch path now matches the repo's existing internal
  bearer-token model instead of being an unauthenticated exception.

## 2026-03-11 02:05 - Worker health-module grounding for `WRK-K01`

Grounding used for this slice:

- Context7 / FastAPI docs reaffirm the intended shape here:
  - route handlers are plain callables attached directly to `FastAPI` or
    `APIRouter`
  - application structure is modularized with routers/modules, not placeholder
    stateful classes with no runtime wiring
- Local authority checks showed the repo already follows that intended pattern:
  - worker `/health` is implemented directly in `worker/app.py`
  - worker heartbeat emission lives in `worker/ipc.py`
  - `worker/health.py` was an empty `HealthCheck` class with no imports, no
    exports, no runtime callers, and no tests

Implementation and review outcome:

- The dead module `src/vaultspec_a2a/worker/health.py` was removed.
- No runtime behavior changed because the actual health endpoint and heartbeat
  loop were already implemented elsewhere.
- Review did not surface a hidden import or compatibility edge; the file was
  genuinely unused.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/worker src/vaultspec_a2a/worker/tests/test_app.py`
- `python -m pytest src/vaultspec_a2a/worker/tests/test_app.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`

Current conclusion:

- `WRK-K01` is now closed.
- The worker health/runtime surface now has a single authority path:
  `worker/app.py` for `/health` and `worker/ipc.py` for heartbeat emission.

## 2026-03-11 02:15 - MCP CLI tool-list grounding for `CLI-I06`

Grounding used for this slice:

- Context7 / FastMCP docs identify `list_tools()` as the canonical API for
  inspecting registered tool metadata.
- That is the correct authority boundary for this repo too: the MCP server
  already owns the tool registry, so the CLI should derive its `mcp tools`
  output from the live FastMCP registration surface instead of duplicating a
  second hand-maintained tool list.

Implementation and review outcome:

- `src/vaultspec_a2a/cli/_mcp.py` now derives tool names and one-line
  descriptions from `mcp.list_tools()` at runtime.
- `vaultspec mcp status` now reports the live registered tool count.
- `vaultspec mcp tools` now renders the live registered tool names and concise
  descriptions instead of a hardcoded `_TOOLS` list.
- Review surfaced one test issue in the first pass: asserting the full
  `cancel_thread` description reintroduced hardcoded drift into the test. That
  assertion was relaxed to verify live registration authority without freezing
  the exact wording.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/cli/_mcp.py src/vaultspec_a2a/cli/tests/test_mcp.py`
- `python -m pytest src/vaultspec_a2a/cli/tests/test_mcp.py src/vaultspec_a2a/cli/tests/test_service.py -q --capture=sys -o cache_dir=$cacheDir --basetemp=$tmpDir`
- result: `13 passed`

Current conclusion:

- `CLI-I06` is now closed.
- The CLI now reads the MCP server's actual registered tool surface instead of
  carrying a stale duplicate list.

## 2026-03-11 02:30 - Docker ACP runtime grounding for `PROV-O01`

Grounding used for this slice:

- The repo's existing Docker ACP research was re-read against the current
  `docker/prod.Dockerfile`.
- Context7 / Docker docs reaffirm the intended runtime pattern:
  - use multi-stage builds
  - copy only the runtime artifacts needed by the final image
  - keep optional runtime dependencies out of unrelated final images
- Local provider/runtime review narrowed the real issue:
  - the worker image now does copy a glibc-compatible `node` binary
  - the worker image now does copy root `node_modules` with
    `@zed-industries/claude-agent-acp`
  - so the old blanket claim "Docker worker has no Node.js/ACP runtime" is now
    stale

What remains true:

- Gemini still requires a real `gemini` CLI binary plus OAuth material under
  `~/.gemini/oauth_creds.json`; the Docker worker does not provision that CLI.
- Claude still requires real auth material (`CLAUDE_CODE_OAUTH_TOKEN`) and has
  not yet been proven in the prod-like Docker stack as a certifying provider
  path.
- The real remaining limitation is therefore provider-matrix completeness, not
  absence of Node.js/ACP runtime in general.

Actionable split:

- provider runtime completeness:
  - add/verify Gemini CLI availability in the worker image if Gemini is meant
    to be Docker-supported
- provider auth/materialization:
  - define how Claude and Gemini auth material is supplied to Dockerized worker
    instances
  - add a certifying Docker verification target only after that supply path is
    explicit and supported

Implementation and review outcome:

- No runtime code change was required in this slice.
- The fix was a research/audit/doc correction:
  - `docker/README.md` now states the actual provider-runtime boundary for the
    worker image
  - the consolidated audit is narrowed from a blanket ACP-runtime claim to the
    remaining provider-specific Docker limitations

Current conclusion:

- `PROV-O01` should no longer be described as "worker supports OpenAI/Zhipu
  only because Node.js/ACP runtime is missing".
- The remaining open issue is narrower:
  Docker does not yet certify the full Claude/Gemini ACP provider matrix.

## 2026-03-11 03:05 - Docker Gemini CLI + explicit provider-auth grounding for `#85` / `#86`

Grounding used for this slice:

- Context7 / Docker docs reaffirmed the intended production image pattern:
  copy only the runtime artifacts needed by the final image from dedicated
  build stages.
- Context7 / Gemini CLI docs confirmed the official non-interactive auth paths:
  `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and service-account style
  `GOOGLE_APPLICATION_CREDENTIALS`.
- Official npm package metadata for `@google/gemini-cli` showed the package is
  installable as the authoritative CLI distribution. On 2026-03-11 the npm
  package page reported version `0.3.3`.
- Official Docker docs also surfaced a second risk during review:
  `docker compose` still loads a project `.env` for interpolation by default
  unless that behavior is explicitly disabled.

Implementation and review outcome:

- The worker image now installs the official Gemini CLI in a dedicated
  `node:22-slim` stage and copies the package runtime into the final worker
  image.
- The first implementation tried to copy the global `/usr/local/bin/gemini`
  launcher directly. Review found a real bug there: the copied wrapper looked
  for relative sources under `/usr/local/bin/src/gemini.js` and failed at
  runtime.
- That defect was fixed in-slice by switching the runtime authority to the
  package entrypoint itself:
  `node /usr/local/lib/node_modules/@google/gemini-cli/dist/index.js`.
- The Gemini provider/runtime path is now aligned with the official
  non-interactive auth contract:
  - provider layer explicitly re-injects `GEMINI_API_KEY` / `GOOGLE_API_KEY`
    into the subprocess environment
  - OAuth refresh is now skipped when env-based Gemini auth is already present
  - the Gemini probe uses the same auth logic and command resolution as the
    production provider path
- A provider-specific Docker auth overlay and verifier were added:
  - `docker-compose.prod.providers.yml`
  - `uv run vaultspec test prodlike-provider <claude|gemini>`
  - `just verify-claude-docker`
  - `just verify-gemini-docker`
  - compatibility alias: `just verify-prodlike-docker-provider <claude|gemini>`
- Review found one more operational drift issue: the repo-owned Docker verifier
  scripts were still inheriting Docker Compose's default project `.env`
  interpolation. That is now disabled explicitly via
  `COMPOSE_DISABLE_ENV_FILE=1`.

Verification completed:

- `python -m ruff check src/vaultspec_a2a/providers/factory.py src/vaultspec_a2a/providers/gemini_auth.py src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/probes/gemini.py src/vaultspec_a2a/providers/tests/test_factory.py src/vaultspec_a2a/providers/tests/test_gemini_auth.py src/vaultspec_a2a/cli/_verify.py`
- `python -m pytest src/vaultspec_a2a/providers/tests/test_factory.py -q --capture=sys`
- `python -m pytest src/vaultspec_a2a/providers/tests/test_gemini_auth.py -k "TestGeminiUsesEnvAuth or TestIsExpired" -q --capture=sys`
- direct runtime no-op verification:
  `python - <<... refresh_gemini_token(Path('missing-oauth-creds.json'), env={'GEMINI_API_KEY': 'test-key'}) ...`
- compose authority check with implicit `.env` loading disabled:
  `docker compose -f docker-compose.prod.yml -f docker-compose.prod.postgres.yml -f docker-compose.prod.providers.yml config`
- real worker-image build:
  `docker build -f docker/prod.Dockerfile --target worker -t vaultspec-a2a-worker:test .`
- real container runtime smoke:
  `docker run --rm vaultspec-a2a-worker:test node /usr/local/lib/node_modules/@google/gemini-cli/dist/index.js --help`

Current conclusion:

- `#85` is closed: the worker image now has a real, pinned, executable Gemini
  CLI runtime.
- `#86` is only partially closed:
  - the explicit supported Docker auth-material path now exists
  - the provider-specific verifier now exists
  - but full provider certification still depends on supplying real
    `CLAUDE_CODE_OAUTH_TOKEN`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY` at
    verification time
- Official Anthropic Claude Code docs also advertise Anthropic API credentials
  as a supported auth type, but the current repo runtime still intentionally
  keeps the Claude ACP path OAuth-only per the older ADR/research direction.
  That should remain an explicit audited divergence rather than an implicit
  assumption.

## 2026-03-11 12:10 - Local ACP authority and probe grounding

Grounding conclusion:

- The local ACP bridge remains the primary authority path for non-Docker
  execution.
- Docker packaging was added to make the worker image self-sufficient and
  version-pinned in prod-like verification, not to replace the local bridge.
- Current runtime resolution confirms that split:
  - Claude local ACP resolves to the project-level Node entrypoint
    `node_modules/@zed-industries/claude-agent-acp/dist/index.js`
  - Gemini local ACP on this machine resolves to the system-installed
    `gemini.CMD` because there is no project-local `@google/gemini-cli`
    package installed
  - Docker-only Gemini resolution still prefers the packaged
    `/usr/local/lib/node_modules/@google/gemini-cli/dist/index.js`

Real local verification on 2026-03-11:

- Initial sandboxed runs were not authoritative:
  - Claude failed during Windows subprocess pipe creation (`WinError 5`)
  - Gemini failed during OAuth refresh network access
- Elevated local probe runs established the real behavior:
  - `python -m vaultspec_a2a.providers.probes.gemini`
    - passed end to end
    - refreshed OAuth successfully against `oauth2.googleapis.com`
    - completed `initialize -> session/new -> session/prompt`
    - returned `Hello`
  - `python -m vaultspec_a2a.providers.probes.claude`
    - passed ACP `initialize`
    - passed ACP `session/new`
    - failed at `session/prompt` with provider-side quota exhaustion:
      `Internal error: You've hit your limit · resets Mar 13, 5am (Europe/Madrid)`

Authority implication:

- The local Gemini ACP bridge is currently functioning on this machine.
- The local Claude ACP bridge is also functioning at the protocol/bridge level;
  the observed failure is provider availability/quota, not ACP startup or ACP
  session wiring breakage.
- This means the recent Docker/provider work has not displaced the previously
  working local ACP architecture. The remaining open Docker/provider concern is
  still `#86` credential-backed container certification, not local ACP
  regression.

## 2026-03-11 12:25 - Observability grounding: traces vs debug logs and ACP/container risk

Grounding conclusion:

- Jaeger is the trace evidence backend in this repository, not a complete log
  backend.
- Official OpenTelemetry guidance supports correlating logs with traces by
  including `trace_id` and `span_id` in structured log records.
- Official OpenTelemetry guidance does not support treating spans as a
  replacement for arbitrary debug logs.
- Jaeger documentation is trace-centric. For logs, the normal production
  pattern is either:
  - a separate log backend with trace/log correlation fields, or
  - an OTLP logs pipeline via an OpenTelemetry Collector and a log-capable
    backend

Implication for this repo:

- The current design has real Jaeger trace evidence, but no formalized
  architecture for log/trace correlation across:
  - gateway
  - worker
  - Docker container boundaries
  - ACP subprocesses
- The current JSON logger already emits structured fields, but it does not yet
  inject OTel correlation fields (`trace_id`, `span_id`, sampled flag) into
  every log record.
- The current prod-like Docker verifier captures service logs and Jaeger traces
  separately, but there is no concerted debug surface that joins them by
  correlation identifiers.

Authority / risk assessment:

- This is a real architecture/documentation gap, not just a verifier defect.
- The Docker/provider/ACP work is high-risk without an explicit ADR that states:
  - what the authoritative debug surface is
  - whether logs are exported via OTLP or kept as structured stdout/container
    logs only
  - how ACP subprocess stderr/stdout is correlated back to request/thread/trace
    context
- The current repo has ADR-010 for tracing, but it does not yet formalize
  log/trace correlation or containerized ACP observability boundaries.

Grounded recommendation:

- Do not route generic debug output into Jaeger spans.
- Add OTel log correlation fields to the structured JSON logger.
- Decide and document one of:
  - keep logs as structured stdout/container logs + correlate via trace IDs
  - add OTLP logs export to a proper log backend / collector path
- Add an ADR specifically for:
  - log/trace correlation
  - ACP local-vs-Docker authority boundaries
  - multi-boundary debug evidence requirements in prod-like verification

## 2026-03-11 10:05 - Prod-like verification ownership and timeout diagnostics grounding

Grounding conclusion:

- These prod-like verifiers are repository-owned verification tooling, not
  standalone utility scripts, so they belong in the supported CLI surface.
- Official OpenTelemetry Python docs and Jaeger query docs support the current
  authority model for this verifier:
  - distinct service attribution for gateway vs worker
  - OTLP export to Jaeger
  - trace evidence queried through `/api/traces`
- Therefore the supported verifier authority should be:
  - `vaultspec test prodlike-docker`
  - `vaultspec test prodlike-provider <claude|gemini>`
  - `just verify-prodlike-docker`
  - `just verify-claude-docker`
  - `just verify-gemini-docker`

Implementation/review outcome:

- moved the verifier logic from `scripts/` into `src/vaultspec_a2a/cli/_verify.py`
- exposed the supported commands from `src/vaultspec_a2a/cli/_test.py`
- rewired `Justfile` and `.github/workflows/prodlike-docker.yml` to call the
  CLI instead of raw script files
- removed the `scripts/` directory after the move

Real finding from the elevated live run:

- `uv run vaultspec test prodlike-docker` still failed with
  `gateway not ready after 120s: <urlopen error timed out>`
- the new artifact directory existed, but the container log captures were empty
  and the Jaeger query payloads were empty placeholders
- that means the remaining issue is not “lack of a place to put diagnostics”
  anymore; it is specifically that the verifier still needs richer pre-teardown
  health/inspect capture to root-cause container startup stalls

Next fix direction:

- capture `docker compose ps`, container health/inspect state, and startup
  failure details before teardown
- then root-cause why the gateway can reach `Started` state while `/api/health`
  still times out for 120 seconds in the prod-like stack
