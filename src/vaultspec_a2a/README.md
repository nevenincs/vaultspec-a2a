# vaultspec_a2a — Package Architecture

**Binding ADR:** `docs/adrs/040-layer-boundary-enforcement.md`

## Full Tree

```text
src/vaultspec_a2a/

# ══════════════════════════════════════════════════════════════
# LAYER 1 — Pure domain. Zero infrastructure. Zero services.
#           Accepted frameworks: Pydantic, langchain_core, langgraph
# ══════════════════════════════════════════════════════════════

├── domain_config.py                   (141)  Cross-cutting domain settings (18 fields)
│
├── team/                              ~515 lines Python (+ presets TOML/YAML)
│   ├── __init__.py                     (77)
│   ├── team_config.py                 (438)  TOML team/agent definitions + validation
│   │                                         discover_team_preset_ids,
│   │                                         discover_agent_preset_ids, load_agent_config
│   └── presets/                              Preset TOML files (incl. mock/tapes/)
│
├── thread/                            ~670 lines
│   ├── __init__.py                     (95)
│   ├── state.py                       (168)  TeamState TypedDict + reducers
│   ├── models.py                       (89)  TokenUsageEntry, PlanStep, ArtifactRef
│   └── errors.py                      (318)  Full error taxonomy + ProviderSessionError
│
├── context/                           ~774 lines
│   ├── __init__.py                     (35)
│   ├── metadata.py                    (171)  Thread metadata + context ref discovery
│   ├── preamble.py                     (55)  System message builder
│   ├── anchoring.py                    (63)  Workspace/feature state anchoring
│   ├── stage.py                        (21)  Pipeline phase inference
│   ├── rules.py                       (270)  RuleManager — .vaultspec/rules/ discovery
│   └── token_budget.py               (159)  Token estimation + context compaction
│
├── graph/                             ~2,093 lines
│   ├── __init__.py
│   ├── compiler.py                    (790)  StateGraph assembly from TeamConfig
│   ├── events.py                      (139)  Domain event dataclasses (DomainEvent base)
│   ├── enums.py                       (162)  ToolKind, PermissionType, AgentLifecycleState,
│   │                                         Model, Provider, MODEL_MAP, PROVIDER_DEFAULT_MODELS
│   ├── protocols.py                    (92)  ProviderFactoryProtocol, TelemetryHook
│   ├── nodes/
│   │   ├── __init__.py                       Re-exports create_*_node factories
│   │   ├── supervisor.py              (378)  Routing + phase gates
│   │   ├── worker.py                  (247)  Task execution + permissions
│   │   └── vault_reader.py            (116)  Vault document mounting
│   └── tools/
│       ├── __init__.py
│       └── task_queue.py              (156)  Persistent task queue (filesystem I/O)
│
# ══════════════════════════════════════════════════════════════
# LAYER 1.5 — Bridges domain to infrastructure. Depends on
#             Layer 1 only. May use LangGraph runtime types.
# ══════════════════════════════════════════════════════════════
│
├── streaming/                         ~2,286 lines
│   ├── __init__.py                     (11)  Public API: EventAggregator
│   ├── aggregator.py                  (326)  EventAggregator facade (compose buffer+emit+ingest)
│   ├── types.py                       (203)  StreamableGraph protocol, classify_tool_kind
│   ├── subscribers.py                 (199)  Client queue mgmt, subscribe/unsubscribe
│   ├── buffering.py                   (235)  Chunk batching, debounce, flush scheduling
│   ├── emitters.py                    (629)  emit_* methods, sequence numbering, permissions
│   ├── transformer.py                 (469)  LangGraph callback → domain event translation
│   └── ingest.py                      (214)  Graph consumption loop, cancel, shutdown
│
├── lifecycle/                         ~169 lines
│   ├── __init__.py                      (5)
│   └── reconciliation.py             (164)  Pure decision logic (zero external imports)
│
# ══════════════════════════════════════════════════════════════
# LAYER 2 — Entry points. Thin protocol adapters. Zero
#           business logic. Translate external protocols into
#           Layer 1 + control/ calls.
# ══════════════════════════════════════════════════════════════
│
├── api/                               ~4,615 lines │ FastAPI + WebSocket + Pydantic
│   ├── app.py                         (312)  Application factory, lifespan, main()
│   ├── middleware.py                   (40)  CacheControlMiddleware (cache headers)
│   ├── dependencies.py                (79)  FastAPI Depends() providers
│   ├── _utils.py                      (42)  trace_headers(), mark_worker_connected()
│   ├── ws_dispatch.py                (282)  WS dispatch handler factories
│   ├── websocket.py                  (719)  WS ConnectionManager + event streaming
│   ├── auth.py                        (40)  Bearer token validation
│   ├── internal.py                   (369)  Worker-facing internal routes + event relay
│   ├── event_adapter.py              (264)  Domain event → wire protocol translation
│   ├── routes/                               Per-resource REST route modules
│   │   ├── __init__.py                (33)  register_routes(app) helper
│   │   ├── health.py                  (82)  GET /health
│   │   ├── threads.py                (425)  POST/GET/DELETE threads, archive, metadata
│   │   ├── thread_state.py           (145)  GET /threads/{id}/state
│   │   ├── messages.py               (205)  POST /threads/{id}/messages
│   │   ├── cancel.py                 (163)  POST /threads/{id}/cancel
│   │   ├── teams.py                  (102)  GET /teams, /team/status, /team/presets
│   │   ├── permissions.py            (309)  POST /permissions/{id}/respond
│   │   └── admin.py                   (15)  POST /admin/shutdown
│   └── schemas/                              Pydantic request/response models
│       ├── base.py                    (43)
│       ├── commands.py                (90)
│       ├── enums.py                   (86)  Re-exports from graph/enums
│       ├── events.py                 (271)
│       ├── rest.py                   (200)
│       └── snapshots.py              (140)
│
├── cli/                               ~1,269 lines │ Click + httpx + Rich
│   ├── _agent.py                      (74)  Agent preset commands (via team.team_config)
│   ├── _team.py                      (493)  Team commands (Click definitions only)
│   ├── _renderers.py                 (442)  Domain event rendering, status display,
│   │                                         permission prompts, thread list
│   └── _util.py                      (173)  API client helpers
│
├── worker/                            ~1,740 lines │ FastAPI + LangGraph + anyio
│   ├── app.py                        (243)  Worker HTTP service
│   ├── executor.py                   (490)  Dispatch orchestration, concurrency gating
│   ├── graph_lifecycle.py            (317)  GraphLifecycleManager: cache, compile, input
│   ├── state_projection.py           (297)  StateProjector: checkpoint, normalize, emit
│   └── ipc.py                        (356)  WorkerBridge: event relay to gateway
│
├── protocols/                         ~1,131 lines │ MCP SDK + httpx
│   ├── mcp/                                  IDE tool server (Cursor, Windsurf, Claude)
│   │   ├── server.py                (1042)
│   │   └── __main__.py                (55)
│   └── adapter/                              Protocol adapters
│
# ══════════════════════════════════════════════════════════════
# LAYER 2 — Infrastructure services. Shared modules consumed
#           by entry points. Never import from entry points.
# ══════════════════════════════════════════════════════════════
│
├── ipc/                               ~116 lines │ Pydantic
│   ├── __init__.py                           Public API re-exports
│   ├── schemas.py                     (85)  DispatchRequest, DispatchResponse,
│   │                                         ExecutionStateProjectionPayload,
│   │                                         ExecutionTaskProjectionPayload
│   └── serializers.py                 (18)  sequenced_to_dict (event serialization)
│
├── control/                           ~4,948 lines │ Runtime + dev-tooling
│   │
│   │   # ── Production runtime (process supervision, dispatch, health) ──
│   ├── circuit_breaker.py             (98)  WorkerCircuitBreaker (protocol-agnostic)
│   ├── worker_management.py          (604)  LazyWorkerSpawner, WorkerWatchdog, WorkerState
│   ├── dispatch.py                   (221)  dispatch_to_worker(), domain error types
│   ├── projection.py                 (491)  Checkpoint/state projection (from api/)
│   ├── snapshot.py                   (286)  Snapshot assembly (from api/endpoints)
│   ├── event_handlers.py             (473)  Event handlers + relay_event() (from api/internal)
│   ├── health.py                     (170)  assemble_health_status() (consolidated)
│   ├── diagnostics.py                (150)  classify_missing_ws_thread, mark_thread_failed
│   │
│   │   # ── Dev-tooling + infrastructure config ──
│   ├── config.py                     (632)  InfraConfig (75 infra fields) + Settings facade
│   ├── db.py                         (312)  DB lifecycle (migrate, snapshot, restore)
│   ├── doctor.py                     (383)  System health checks
│   ├── verify.py                     (894)  Schema consistency
│   └── hooks.py                      (191)  Pre-commit hook management
│
├── database/                          ~2,116 lines │ SQLAlchemy + Alembic + aiosqlite
│   ├── session.py                    (269)  Engine factory (SQLite/Postgres)
│   ├── models.py                     (288)  ORM table definitions
│   ├── crud.py                       (976)  Query/mutation functions
│   ├── checkpoints.py                (270)  LangGraph checkpointer factory
│   ├── migrate.py                     (47)  Alembic runner
│   ├── reconciliation.py             (194)  Reconciliation I/O executor
│   └── migrations/                           Alembic versions
│
├── providers/                         ~4,031 lines │ Anthropic + OpenAI + Google + Zhipu SDKs
│   ├── factory.py                    (459)  ProviderFactory (implements ProviderFactoryProtocol)
│   ├── acp_chat_model.py           (1,821)  Claude ACP subprocess wrapper
│   ├── mock_chat_model.py            (210)  VidaiMock tape-replay model
│   ├── gemini_auth.py                (223)  Google auth flow
│   ├── _subprocess.py                (182)  Subprocess management utilities
│   ├── acp_exceptions.py              (91)  ACP-specific error types
│   └── probes/                               Per-provider health checks
│       ├── _protocol.py              (463)  Base probe protocol
│       ├── _http.py                   (69)  HTTP probe utilities
│       ├── certifying.py              (82)  Production certification probe
│       ├── claude.py                 (143)  Claude probe
│       ├── openai.py                  (66)  OpenAI probe
│       ├── gemini.py                  (78)  Gemini probe
│       └── zhipu.py                   (67)  Zhipu probe
│
├── telemetry/                         ~684 lines │ OpenTelemetry SDK + LangSmith
│   ├── instrumentation.py            (343)  Tracer/meter factory (implements TelemetryHook)
│   ├── middleware.py                 (238)  FastAPI auto-instrumentation
│   └── aggregator_hook.py             (49)  Aggregator telemetry bridge
│
├── workspace/                         ~641 lines │ pathlib + subprocess (git)
│   ├── environment.py                (135)  .venv/workspace discovery
│   └── git_manager.py               (485)  Git operations
│
├── utils/                             ~496 lines │ stdlib + OTel trace context
│   ├── enums.py                       (54)  AgentState, LogLevel, Environment, AcpRequestId
│   ├── logging.py                    (163)  Log setup
│   ├── timestamp.py                   (68)  Monotonic clock helpers
│   ├── trace.py                      (177)  OTel span context utilities
│   └── asyncio_compat.py              (15)  Windows Proactor event loop stub
│
# ══════════════════════════════════════════════════════════════
# LAYER 3 — Infrastructure config. Topology, not behaviour.
# ══════════════════════════════════════════════════════════════
│
├── docker-compose.dev.yml                    Gateway + Worker + Vite (SQLite)
├── docker-compose.prod.yml                   Gateway + Worker + Jaeger (SQLite)
├── docker-compose.prod.postgres.yml          Postgres override
├── docker-compose.integration.yml            VidaiMock + test fixtures
├── Justfile                           (515)  Service lifecycle, migrations, linting
└── .env.example                              Full config template
```

## Dependency Graph

```text
                         LAYER 1 (pure domain)

                    ┌─────────────────┐
                    │ domain_config.py │  Cross-cutting domain knobs (18 fields)
                    └────────┬────────┘
                             │ (consumed by all Layer 1 modules)
                             │
    ┌──────────┐    ┌────────▼─┐    ┌──────────┐    ┌──────────┐
    │  team/   │    │ thread/  │    │ context/ │    │  graph/  │
    │          │    │          │    │          │    │          │
    │ team_cfg │    │ state    │    │ metadata │    │ compiler │
    │ presets  │    │ models   │    │ preamble │    │ nodes/*  │
    │          │    │ errors   │    │ anchoring│    │ tools/*  │
    │          │    │          │    │ rules    │    │ events   │
    │          │    │          │    │ token_   │    │ enums    │
    │          │    │          │    │  budget  │    │ protocols│
    └──────────┘    └──────────┘    │ stage    │    └──────────┘
                                    └──────────┘
    Dependency direction (imports from):
    ─ graph/   imports from ► context/, thread/, team/, domain_config
    ─ context/ imports from ► thread/, domain_config
    ─ team/    imports from ► thread/errors, graph/enums
    ─ thread/  imports from ► (nothing — leaf module)

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
                      LAYER 1.5 (bridges)
              ┌───────────────┐    ┌────────────┐
              │  streaming/   │    │ lifecycle/ │
              │               │    │            │
              │ aggregator    │    │ reconcile  │
              │ types         │    │            │
              │ transformer   │    └────────────┘
              │ buffering     │
              │ emitters      │    Imports from: Layer 1 only
              │ subscribers   │    streaming: thread/errors
              │ ingest        │    lifecycle: (nothing — self-contained)
              └───────────────┘

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
              LAYER 2 — Entry Points (thin protocol adapters)
 ┌──────────────┐ ┌────────┐ ┌────────────┐ ┌──────────┐
 │     api/     │ │  cli/  │ │  worker/   │ │protocols/│
 │ FastAPI      │ │ Click  │ │ FastAPI    │ │ MCP SDK  │
 │ routes/*     │ │ httpx  │ │ executor   │ │ httpx    │
 │ ws_dispatch  │ │ Rich   │ │ graph_life │ │          │
 │ dependencies │ │ render │ │ state_proj │ │          │
 │ middleware   │ │        │ │ ipc        │ │          │
 └──────┬───────┘ └───┬────┘ └─────┬──────┘ └────┬─────┘
        │             │            │              │
        ▼             ▼            ▼              ▼
─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
         LAYER 2 — Infrastructure Services (shared)
 ┌──────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐
 │ ipc/ │ │ control/ │ │ database/ │ │providers/│ │ telemetry/│
 │      │ │          │ │           │ │          │ │           │
 │schema│ │circuit_  │ │ session   │ │ factory  │ │instrument.│
 │serial│ │ breaker  │ │ models    │ │ acp_chat │ │ middleware│
 │      │ │worker_   │ │ crud      │ │ mock_    │ │ agg_hook  │
 │      │ │ mgmt     │ │ checkpts  │ │ gemini   │ │           │
 │      │ │dispatch  │ │ migrate   │ │ probes/* │ │           │
 │      │ │projection│ │ reconcile │ │          │ │           │
 │      │ │snapshot  │ │           │ │          │ │           │
 │      │ │event_    │ │           │ │          │ │           │
 │      │ │ handlers │ │           │ │          │ │           │
 │      │ │health    │ │           │ │          │ │           │
 │      │ │diagnost. │ │           │ │          │ │           │
 │      │ │config    │ │           │ │          │ │           │
 │      │ │db/doctor │ │           │ │          │ │           │
 │      │ │verify    │ │           │ │          │ │           │
 │      │ │hooks     │ │           │ │          │ │           │
 └──────┘ └──────────┘ └───────────┘ └──────────┘ └───────────┘
 ┌───────────┐ ┌───────┐
 │ workspace/│ │ utils/│
 │ git+path  │ │stdlib │
 └───────────┘ └───────┘

─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
                       LAYER 3 (infrastructure config)
 ┌─────────────────┐ ┌──────────────┐ ┌─────────────┐
 │docker-compose.* │ │  Justfile    │ │.env.example  │
 │dev/prod/integ.  │ │ 515 lines    │ │              │
 │Jaeger,Postgres  │ │ pwsh recipes │ │              │
 └─────────────────┘ └──────────────┘ └──────────────┘
```

## Layer 1 Consumers

| Layer 1 module | Consumed by | Stack |
|---|---|---|
| **domain_config** | All Layer 1 modules, control/config (composes into Settings) | Pydantic |
| **team/team_config** | providers/factory, providers/acp_chat_model, worker/executor, cli/_agent | LangChain, subprocess |
| **thread/errors** | database/crud, providers/factory, workspace/git_manager, streaming/subscribers | SQLAlchemy, subprocess |
| **thread/state** | worker/executor, api/routes/* (via graph/) | LangGraph, FastAPI |
| **context/*** | graph/nodes/* only (via facade) | Internal — not consumed by Layer 2 directly |
| **graph/compiler** | worker/graph_lifecycle | LangGraph, LangChain |
| **graph/events** | api/event_adapter | Pydantic (wire translation) |
| **graph/enums** | team/team_config, streaming/, api/schemas/enums (re-export) | StrEnum |
| **graph/protocols** | providers/factory (implements), worker/executor (passes) | LangChain |

## Layer 1.5 Consumers

| Layer 1.5 module | Consumed by | Stack |
|---|---|---|
| **streaming/** | api/websocket, api/routes/*, worker/ipc, control/event_handlers | FastAPI WebSocket, httpx |
| **lifecycle/** | api/app (startup hook only) | FastAPI lifespan |

## IPC Contract Consumers

| IPC type | Consumed by |
|---|---|
| **DispatchRequest** | api/routes/*, api/ws_dispatch, control/dispatch, worker/app, worker/executor |
| **DispatchResponse** | control/dispatch, worker/app |
| **ExecutionStateProjectionPayload** | control/event_handlers, worker/state_projection |
| **ExecutionTaskProjectionPayload** | worker/state_projection |
| **sequenced_to_dict** | worker/executor |

## Layer Boundary Rules

1. **Layer 1** imports NOTHING from Layer 1.5, 2, or 3. Importable in a bare Python REPL.
2. **Layer 1.5** imports from Layer 1 only. May use LangGraph runtime types. No database, no HTTP, no telemetry.
3. **Layer 2 entry points** import from Layer 1, 1.5, and infra services. Never import from each other (api/ does not import cli/, worker/ does not import api/).
4. **Layer 2 infra services** import from Layer 1. Entry points import from infra services. Infra services never import from entry points.
5. **IPC package** (`ipc/`) is a neutral contract consumed equally by api/ and worker/. Neither owns it.
6. **control/** contains both production runtime (dispatch, health, projection, event handlers) and dev-tooling (db, doctor, hooks, verify). Both categories are Layer 2 infra services.
7. **Layer 3** defines topology. No code execution logic. No business rules.

## Validation

```bash
# Layer 1 import test — must pass with zero services running
python -c "
from vaultspec_a2a.domain_config import DomainConfig
from vaultspec_a2a.team.team_config import TeamConfig
from vaultspec_a2a.thread.state import TeamState
from vaultspec_a2a.context.metadata import ThreadMetadata
from vaultspec_a2a.graph.compiler import compile_team_graph
from vaultspec_a2a.graph.events import MessageChunk, ToolCallStart
from vaultspec_a2a.graph.protocols import ProviderFactoryProtocol
print('Layer 1: PASS')
"

# Layer 1 + 1.5 test isolation — no Docker, no database, no services.
# The 'core' marker is registered in pyproject.toml and selects all tests
# under team/, thread/, context/, graph/, streaming/, and lifecycle/.
pytest -m core

# IPC import test — neutral contract, no entry point dependencies
python -c "
from vaultspec_a2a.ipc import DispatchRequest, DispatchResponse
from vaultspec_a2a.ipc.serializers import sequenced_to_dict
print('IPC: PASS')
"
```
