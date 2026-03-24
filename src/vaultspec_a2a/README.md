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
├── team/                              ~502 lines Python (+ presets TOML/YAML)
│   ├── __init__.py                     (77)
│   ├── team_config.py                 (425)  TOML team/agent definitions + validation
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
# LAYER 2 — Entry points. Thin adapters. Protocol translation.
# ══════════════════════════════════════════════════════════════
│
├── api/                               ~6,823 lines │ FastAPI + WebSocket + Pydantic
│   ├── app.py                                Lifespan, middleware, SPA mount
│   ├── endpoints.py                          REST routes
│   ├── websocket.py                          WS event streaming
│   ├── auth.py                               Bearer token validation
│   ├── internal.py                           Worker-facing internal routes
│   ├── projection.py                         State projection helpers
│   ├── event_adapter.py                      Domain event → wire protocol translation
│   └── schemas/                              Pydantic request/response models
│       ├── base.py, commands.py
│       ├── enums.py                          Re-exports from graph/enums
│       ├── events.py, internal.py
│       ├── rest.py, snapshots.py
│
├── cli/                               ~1,164 lines │ Click + httpx + Rich
│   ├── _agent.py                             Agent commands
│   ├── _team.py                              Team commands
│   └── _util.py                              API client helpers
│
├── worker/                            ~1,619 lines │ FastAPI + LangGraph + anyio
│   ├── app.py                                Worker HTTP service
│   ├── executor.py                           Graph dispatch + execution
│   └── ipc.py                                Event relay to gateway
│
├── protocols/                         ~1,131 lines │ MCP SDK + httpx
│   ├── mcp/                                  IDE tool server (Cursor, Windsurf, Claude)
│   │   ├── server.py
│   │   └── __main__.py
│   └── adapter/                              Protocol adapters
│
# ══════════════════════════════════════════════════════════════
# LAYER 2 — Infrastructure services. Database, providers, etc.
# ══════════════════════════════════════════════════════════════
│
├── database/                          ~2,339 lines │ SQLAlchemy + Alembic + aiosqlite
│   ├── session.py                            Engine factory (SQLite/Postgres)
│   ├── models.py                             ORM table definitions
│   ├── crud.py                               Query/mutation functions
│   ├── checkpoints.py                        LangGraph checkpointer factory
│   ├── migrate.py                            Alembic runner
│   ├── reconciliation.py                     Reconciliation I/O executor
│   └── migrations/                           Alembic versions
│
├── providers/                         ~4,031 lines │ Anthropic + OpenAI + Google + Zhipu SDKs
│   ├── factory.py                            ProviderFactory (implements ProviderFactoryProtocol)
│   ├── acp_chat_model.py                     Claude ACP subprocess wrapper
│   ├── mock_chat_model.py                    VidaiMock tape-replay model
│   ├── gemini_auth.py                        Google auth flow
│   └── probes/                               Per-provider health checks
│
├── telemetry/                         ~684 lines │ OpenTelemetry SDK + LangSmith
│   ├── instrumentation.py                    Tracer/meter factory (implements TelemetryHook)
│   └── middleware.py                         FastAPI auto-instrumentation
│
├── control/                           ~2,432 lines │ Click + Alembic + subprocess
│   ├── config.py                      (632)  InfraConfig (75 infra fields) + Settings facade
│   ├── db.py                                 DB lifecycle (migrate, snapshot, restore)
│   ├── doctor.py                             System health checks
│   ├── verify.py                             Schema consistency
│   └── hooks.py                              Pre-commit hook management
│
├── workspace/                         ~641 lines │ pathlib + subprocess (git)
│   ├── environment.py                        .venv/workspace discovery
│   └── git_manager.py                        Git operations
│
├── utils/                             ~496 lines │ stdlib + OTel trace context
│   ├── enums.py                       (54)   AgentState, LogLevel, Environment, AcpRequestId
│   ├── logging.py                            Log setup
│   ├── timestamp.py                          Monotonic clock helpers
│   ├── trace.py                              OTel span context utilities
│   └── asyncio_compat.py                     Windows Proactor event loop stub
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
                       LAYER 2 (entry points + infra services)
 ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐ ┌───────────┐
 │  api/  │ │  cli/  │ │worker/ │ │protocols/│ │ control/  │
 │FastAPI │ │ Click  │ │FastAPI │ │ MCP SDK  │ │Click+Alem.│
 │Pydantic│ │ httpx  │ │LangGr. │ │ httpx    │ │InfraConfig│
 │SQLAlch.│ │ Rich   │ │anyio   │ │          │ │subprocess │
 └───┬────┘ └───┬────┘ └───┬────┘ └────┬─────┘ └─────┬─────┘
     │          │          │           │              │
     ▼          ▼          ▼           ▼              ▼
 ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌───────────┐
 │database/ │ │providers/ │ │telemetry/│ │workspace/ │
 │SQLAlchemy│ │Anthropic  │ │OpenTelm. │ │git+pathlib│
 │Alembic   │ │OpenAI     │ │LangSmith │ │           │
 │aiosqlite │ │Google     │ │Jaeger    │ │           │
 │asyncpg   │ │subprocess │ │          │ │           │
 └──────────┘ └───────────┘ └──────────┘ └───────────┘

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
| **team/team_config** | providers/factory, providers/acp_chat_model, worker/executor | LangChain, subprocess |
| **thread/errors** | database/crud, providers/factory, workspace/git_manager, streaming/subscribers | SQLAlchemy, subprocess |
| **thread/state** | worker/executor, api/endpoints (via graph/) | LangGraph, FastAPI |
| **context/*** | graph/nodes/* only (via facade) | Internal — not consumed by Layer 2 directly |
| **graph/compiler** | worker/executor | LangGraph, LangChain |
| **graph/events** | api/event_adapter | Pydantic (wire translation) |
| **graph/enums** | team/team_config, streaming/, api/schemas/enums (re-export) | StrEnum |
| **graph/protocols** | providers/factory (implements), worker/executor (passes) | LangChain |

## Layer 1.5 Consumers

| Layer 1.5 module | Consumed by | Stack |
|---|---|---|
| **streaming/** | api/websocket, api/endpoints, worker/ipc | FastAPI WebSocket, httpx |
| **lifecycle/** | api/app (startup hook only) | FastAPI lifespan |

## Layer Boundary Rules

1. **Layer 1** imports NOTHING from Layer 1.5, 2, or 3. Importable in a bare Python REPL.
2. **Layer 1.5** imports from Layer 1 only. May use LangGraph runtime types. No database, no HTTP, no telemetry.
3. **Layer 2 entry points** import from Layer 1 and 1.5. Never import from each other (api/ does not import cli/, worker/ does not import api/).
4. **Layer 2 infra services** import from Layer 1. Entry points import from infra services. Infra services never import from entry points.
5. **Layer 3** defines topology. No code execution logic. No business rules.

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
```
