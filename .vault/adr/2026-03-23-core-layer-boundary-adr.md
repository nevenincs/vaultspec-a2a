---
tags:
  - '#adr'
  - '#core-layer'
date: '2026-03-23'
related:
  - '[[2026-03-23-core-layer-boundary-research]]'
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# `core-layer` adr: `layer-1-boundary-enforcement` | (**status:** `accepted`)

## Problem Statement

An audit of `src/vaultspec_a2a/core/` found 6 boundary violations: 3 files
import from higher layers (api, database, providers, telemetry) and a global
settings singleton couples 9 core files to environment-backed infrastructure
configuration. The core module cannot be extracted as a standalone package —
importing `core.aggregator` pulls in API wire schemas, importing `core.graph`
pulls in database checkpoints and provider factories.

## Considerations

- Layer 1 must contain pure domain logic, importable and testable with zero
  infrastructure
- The aggregator (1,976 lines) contains substantial domain logic (debouncing,
  batching, state machine callbacks) — moving it wholesale to api/ would make
  Layer 2 fat
- Reconciliation decisions are domain logic; executing them against a database
  is infrastructure
- LangGraph is the core domain framework; `BaseCheckpointSaver` from
  `langgraph.checkpoint.base` is an acceptable framework-level import
- The existing test suite (264 tests) is already properly isolated and must
  remain so
- 28+ files import the global settings singleton — splitting it has wide blast
  radius

## Constraints

- Each change must preserve a green test suite — no big-bang refactor
- The `core/__init__.py` public API must remain backwards-compatible during
  migration via a redirect shim
- Domain events must be plain dataclasses (no Pydantic serialization in core)
- No new imports from database, api, worker, or providers in core files

## Implementation

Six architectural decisions to enforce Layer 1 integrity:

**D-01: Domain-local event types in core.** Replace API wire-protocol imports
in `aggregator.py` with domain event dataclasses defined inside `core/`. The
aggregator emits domain events; a separate adapter in `api/` translates them
into wire-protocol schemas. Core never imports from `api.schemas`.

**D-02: Inject checkpoint and provider dependencies into graph compilation.**
Replace direct imports of `Checkpointer`, `ProviderFactory`, and
`AcpSessionError` in `graph.py` with dependency injection via function
parameters and `typing.Protocol`. `compile_team_graph()` accepts
`BaseCheckpointSaver` (framework type) and `ProviderFactoryProtocol` (defined
in core).

**D-03: Extract reconciliation I/O into a callback protocol.** Split
`reconciliation.py` into pure decision logic (given thread states, return
action list) and a `ReconciliationSink` callback the caller provides for
executing decisions against the database.

**D-04: Make telemetry opt-in via instrumentation hooks.** Remove direct
`get_meter`/`get_tracer` imports. The aggregator accepts optional
`TelemetryHook` at construction time. Core ships with `NullTelemetryHook`
defaults.

**D-05: Split Settings into domain config vs infrastructure config.** Domain
fields (~18) stay in `core/domain_config.py`. Infrastructure fields (~75) move
to `control/config.py`. A backwards-compatible `Settings` facade composes both
during migration. Core functions progressively accept config as parameters.

**D-06: Preserve test isolation — no regressions.** All changes must maintain
current isolation: `pytest src/vaultspec_a2a/core/tests/` passes with zero
running services, no new infrastructure imports in core test files.

## Rationale

The aggregator's job is observing LangGraph callbacks and producing structured
events — serialization format is an API concern. Graph topology is domain
logic; how checkpoints are persisted is infrastructure. Reconciliation decisions
are pure; executing them against a database is I/O. Telemetry is cross-cutting
infrastructure. A 730-line Settings class mixing database URLs and token budgets
is a boundary violation.

These decisions follow from the research findings in
`2026-03-23-core-layer-boundary-research` which identified 4 CRITICAL and 2
HIGH severity violations across `aggregator.py`, `graph.py`, and
`reconciliation.py`.

## Consequences

Positive:

- `core/` becomes extractable as a standalone Python package
- Core can be tested in complete isolation (production imports, not just tests)
- Aggregator can be used in non-HTTP contexts (embedded agents, CLI pipelines)
- Configuration is explicit — functions declare what config they need
- Telemetry instrumentation is pluggable

Negative:

- Additional protocol/interface definitions in core (small overhead)
- Adapter layer in `api/` grows (event translation code)
- Graph compilation call sites become slightly more verbose
- Two config classes to maintain instead of one

Risks:

- Incremental migration required — cannot refactor all 6 violations atomically
- 28+ files import the global settings singleton — wide blast radius on split
- The 7-phase plan must be followed in dependency order to avoid breakage
