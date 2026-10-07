---
tags:
  - '#adr'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-10-07'
body_hash: 'sha256:d7ed31d1feda3bc3f5c51bb8b2ab02e61990a5de758fa61da814bd7efaa22220'
related:
  - '[[2026-03-23-core-layer-boundary-research]]'
  - '[[2026-03-23-core-layer-boundary-plan]]'
  - '[[2026-10-06-codebase-remediation-audit]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-08-04-canonical-homes-adr]]'
  - '[[2026-03-28-infra-config-adr]]'
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

> As built: the split landed as decided, but the `core/` package was
> subsequently dissolved, so the domain half is now the top-level
> `src/vaultspec_a2a/domain_config.py` rather than `core/domain_config.py`. The
> infrastructure half is at `src/vaultspec_a2a/control/config.py` as stated. The
> decision stands; only the locator moved.

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

## Amendment (2026-10-07): one run read model, served from Layer 1

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

**Change.** The Layer-1 dataclasses in `src/vaultspec_a2a/thread/snapshots.py` are the single source of the run read model. The api edge serves them directly through FastAPI `response_model` and Pydantic `TypeAdapter`, which validate, serialize and publish a stdlib dataclass without a wire mirror.

- Wire bounds are `typing.Annotated` metadata from `annotated_types` (`MaxLen`, `Ge`) on the dataclass fields, with values taken from the shared bound constants, not literals. `thread/snapshots.py` gains no Pydantic import; `annotated-types` is already a direct dependency (`pyproject.toml:16`).
- The mirror family in `src/vaultspec_a2a/api/schemas/snapshots.py` is deleted, with `snapshot_to_wire` (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:573-581`) and `src/vaultspec_a2a/api/schemas/tests/test_snapshot_parity.py`. The two broadcast mirrors that test also pins, `AgentSummary` and `PermissionOption` in `src/vaultspec_a2a/api/schemas/events.py`, have no production user outside the dead `src/vaultspec_a2a/api/event_adapter.py` and leave with it first (R1-F2).
- `RunStatusResponse` (`src/vaultspec_a2a/api/schemas/gateway.py:478-580`) declares only its run-status-only fields. Every field it shares with the read model derives from the Layer-1 type. Where the copies disagree today, the typed form wins: `status`, `repair_status`, `execution_readiness`, `approval_status` and `provider_condition` carry their enums on run-history too.
- The execution task is declared once, as `ExecutionTaskData`. `ExecutionTaskSnapshot` and `ExecutionTaskProjectionPayload` (`src/vaultspec_a2a/ipc/schemas.py:343-354`) are deleted; the worker IPC payload and the persisted task JSON use the same type.
- The canonical clarification model is `thread/clarification.ClarificationRequest` (`src/vaultspec_a2a/thread/clarification.py:279`), the bounded model run-status already serves (`api/schemas/gateway.py:580`). The lenient mirrors are deleted: `ClarificationRequestData`, `ClarificationQuestionData` and their builders (`thread/snapshots.py:213-280,389-415`), and `ClarificationRequestSnapshot` and `ClarificationQuestionSnapshot` (`api/schemas/snapshots.py:77-97`). Run-history `state.pending_clarification` changes shape: `required` defaults to true, a text question serves `options: null`, and a payload the strict model refuses is no longer disclosed. This is a contract event under R6 of `2026-07-14-a2a-edge-conformance-adr`.
- OpenAPI component names are preserved where possible. Under the locked pydantic 2.13.5 and fastapi 0.141.1 the component key is the dataclass class name; a `__pydantic_config__` title changes only the schema `title`. A name is therefore preserved by giving the Layer-1 class the published name, for example `ThreadStateSnapshot`. A component that is still renamed or removed is a contract event in the same announcement.

**Why.** The mirrors have already lost fields; four silent-drop notes sit at `api/schemas/snapshots.py:198-224`. The production seam `ThreadStateSnapshot.model_validate(asdict(data))` drops an undeclared field without error (`api/routes/_gateway_read_endpoints.py:573-581`). The parity test guards a spelling, not an invariant, and `2026-08-04-canonical-homes-adr` rehomes a concept to one declaration rather than guarding a copy. Run-status and run-history disclose one pending question in two shapes. Evidence: R1-F11, R2-F3 and R2-F14 in `2026-10-06-codebase-remediation-audit`.

**Constraints.**

- `thread/snapshots.py` imports no Pydantic. The one Pydantic type the read model embeds is `ClarificationRequest`, which already lives in `thread/` as the contract `.vaultspec/rules/clarifications-are-typed-interrupts.md` names. To import it, `thread/clarification.py` stops importing `thread/snapshots.py` at module load (`thread/clarification.py:51`), and `pending_clarification` takes the already-computed `CheckpointProjection` (R2-F2).
- A wire field name changes only as an announced contract event.
- Implementation hypothesis: how `RunStatusResponse` composes the shared fields, and the naming of each component, are settled by probe P18 before Step M.6.

**Replaces.** For the run read model only: D-01's "a separate adapter in `api/` translates them into wire-protocol schemas", and the Negative consequence "Adapter layer in `api/` grows (event translation code)". No translation layer or mirror is declared for it. The Constraint "Domain events must be plain dataclasses (no Pydantic serialization in core)" stands: `Annotated` metadata is not Pydantic, and serialization runs at the api edge. Event-frame serialization is not ruled here.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

D-05's transitional facade is ended. Superseded sentence: "A backwards-compatible `Settings` facade composes both during migration." The 2026-10-07 amendment of `2026-03-28-infra-config-adr` replaces it. `Settings` derives from `InfraConfig` only, domain fields are read only through `domain_config`, and a guard keeps the two field sets disjoint. The composed form `class Settings(DomainSettingsConfig, InfraConfig)` (`src/vaultspec_a2a/control/config.py:53`) is the retired transitional contract. Grounding: R7-F23 in `2026-10-06-codebase-remediation-audit`; decision D16 in `2026-10-06-codebase-remediation-plan`.

D-05's split into domain and infrastructure configuration stands, as do its as-built note and the 2026-10-07 read-model amendment above.
