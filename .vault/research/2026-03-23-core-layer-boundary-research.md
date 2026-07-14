---
tags:
  - '#research'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-03-23'
related:
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# `core-layer` research: `layer-1-boundary-violations`

Static analysis of `src/vaultspec_a2a/core/` against Layer 1 integrity
criteria. Layer 1 rule: pure domain logic, importable and testable with zero
infrastructure.

The `core/` module contains 6 boundary violations across 3 files plus a
systemic configuration coupling pattern affecting 9+ core files via a global
settings singleton. 17 of 21 production files are clean.

## Findings

### Cross-layer import violations

| # | File | Imports From | Severity |
|---|------|-------------|----------|
| V-01 | `aggregator.py:25-49` | `api.schemas.enums`, `api.schemas.events` | CRITICAL |
| V-02 | `aggregator.py:50` | `telemetry.instrumentation` | CRITICAL |
| V-03 | `graph.py:25` | `database.checkpoints` | CRITICAL |
| V-04 | `graph.py:26-27` | `providers.factory`, `providers.acp_exceptions` | CRITICAL |
| V-05 | `reconciliation.py:13-23` | `database.crud` | HIGH |
| V-06 | `config.py:731` + 9 files | Global `settings` singleton | HIGH |

### V-01 + V-02: `aggregator.py`

Wire-protocol event schemas (lines 25-49) import `PermissionOptionKind`,
`PermissionType`, `ToolCallStatus`, `ToolKind` and 16 event classes from
`api.schemas`. Telemetry instrumentation (line 50) imports `get_meter`,
`get_tracer` from `telemetry.instrumentation`.

Why these violate Layer 1:

- Wire-protocol event classes are API-layer contracts (HTTP/WS serialization)
- OpenTelemetry spans/meters/counters are deployment instrumentation
- `EventAggregator` cannot be used in non-HTTP contexts (embedded, CLI, testing)
- Cannot test aggregator without pulling in API schema infrastructure

Module-level `get_tracer`/`get_meter` calls create spans, counters, and
histograms at import time.

### V-03 + V-04: `graph.py`

Database checkpoint import (line 25) pulls `Checkpointer` from
`database.checkpoints`. Provider factory + ACP exception imports (lines 26-27)
pull `ProviderFactory` and `AcpSessionError` from `providers`.

Why these violate Layer 1:

- `Checkpointer` is a database persistence concern — graph compilation should
  accept an abstract checkpoint interface
- `ProviderFactory` is an infrastructure factory — provider selection is a
  composition concern
- `AcpSessionError` is specific to one provider backend (ACP)
- Cannot compile a graph without database and provider packages installed

### V-05: `reconciliation.py`

Database CRUD imports (lines 13-23) pull `ControlActionResultStatus`,
`ControlActionType`, `RepairStatus`, `ThreadStatus`, and 5 CRUD functions from
`database.crud`.

Why this violates Layer 1:

- Reconciliation logic directly executes database queries via CRUD functions
- Database enums are persistence-layer types
- The function is async and performs I/O — it is an application service
- Thread reconciliation decisions (pure logic) are tangled with database
  mutations

### V-06: configuration coupling — global singleton

`config.py` defines a `Settings(BaseSettings)` class using `pydantic-settings`
with `env_file=".env"` and `env_prefix="VAULTSPEC_"`. A global singleton is
created at module scope (line 731): `settings = Settings()`.

80+ configuration values auto-loaded from environment:

| Category | Count | Examples |
|----------|-------|---------|
| Database/persistence | 7 | `DATABASE_URL`, `CHECKPOINT_BACKEND` |
| Network/ports | 6 | `HOST`, `PORT`, `WORKER_PORT` |
| API keys/secrets | 11 | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| Timeouts/polling | 12 | `PROVIDER_TIMEOUT`, `HEARTBEAT_TIMEOUT` |
| IPC/buffering | 8 | `EVENT_QUEUE_MAXSIZE`, `IPC_MAX_EVENT_BUFFER` |
| Filesystem paths | 3 | `WORKSPACE_ROOT`, `PROJECT_ROOT` |
| Domain (legitimate) | ~10 | `CONTEXT_LIMIT_TOKENS`, `CHARS_PER_TOKEN` |

Infrastructure values vastly outnumber domain values. 28+ files across the
codebase depend on the singleton. Pure functions become impure by reading
from environment-backed global state.

### Transitive dependency chains

```
core/graph.py
  -> database/checkpoints.py -> langgraph.checkpoint.base, psycopg3

core/reconciliation.py
  -> database/crud.py -> SQLAlchemy AsyncSession, database-specific enums

core/aggregator.py
  -> api/schemas/events.py -> pydantic serialization models
  -> telemetry/instrumentation.py -> opentelemetry SDK

core/graph.py
  -> providers/factory.py -> core/config.py (circular), acp_chat_model.py
```

### Test isolation — PASS

The core test suite is properly isolated: 21 test files, ~264 tests, 18
requiring zero infrastructure. 3 files use conditional markers and skip
gracefully. No imports from database, api, worker, or providers in test files.
In-memory SQLite used for graph tests. No import-time side effects.

### Clean files (Layer 1 compliant)

17 files have zero boundary violations: `anchoring.py`, `asyncio_compat.py`,
`context.py`, `exceptions.py`, `metadata.py`, `models.py`, `phase.py`,
`preamble.py`, `rules.py`, `state.py`, `task_queue.py`, `team_config.py`,
`nodes/__init__.py`, `nodes/mount.py`, `nodes/supervisor.py`,
`nodes/worker.py`, `presets/`. Files marked as using `config` singleton
participate in the systemic coupling from V-06 but are structurally clean.
