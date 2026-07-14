---
tags:
  - '#audit'
  - '#core-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# core-layer adr verification audit

**Scope:** Decision-by-decision verification of
`2026-03-23-core-layer-boundary-adr.md` (D-01 through D-06) against actual
code in `src/vaultspec_a2a/`.

**Auditor note:** All findings below are based on direct code inspection.
No implementation claims were taken at face value.

---

## D-01: Domain-local event types in core

**Verdict: IMPLEMENTED**

Evidence:

- `graph/events.py` exists and defines 11 domain event dataclasses
  (`DomainEvent`, `MessageChunk`, `ThoughtChunk`, `ToolCallStart`,
  `ToolCallUpdate`, `PermissionRequest`, `PlanUpdate`, `ArtifactUpdate`,
  `AgentStatus`, `TeamStatus`, `ErrorOccurred`).
- All types use plain `@dataclass` (stdlib `dataclasses`). Zero Pydantic
  inheritance anywhere in that file.
- `streaming/emitters.py` imports exclusively from `..graph.events` and
  emits `SequencedEvent(event=<DomainEvent>, ...)`. No API schema types
  appear in any `streaming/` file.
- `api/event_adapter.py` exists and is the sole translation point:
  imports `graph.events.*` and `api.schemas.events.*`, converting with
  `domain_to_wire()` / `sequenced_to_wire()`.
- Dependency direction confirmed correct: `api/` imports from `graph/`;
  no `streaming/` file imports from `api/`.

No issues found.

---

## D-02: Inject checkpoint and provider dependencies

**Verdict: IMPLEMENTED**

Evidence:

- `compile_team_graph()` signature (compiler.py:261–272):
  ```
  def compile_team_graph(
      team_config: Any,
      agent_configs: dict[str, Any],
      *,
      provider_factory: ProviderFactoryProtocol,   # required, no default
      checkpointer: BaseCheckpointSaver | None = None,
      ...
  )
  ```
- `provider_factory` is a required keyword-only parameter (no default
  value). ADR constraint satisfied.
- `checkpointer` type is `BaseCheckpointSaver` from
  `langgraph.checkpoint.base` — the framework-level type, not a
  database-specific import.
- `ProviderFactoryProtocol` is defined in `graph/protocols.py` (not in
  `providers/`). The compiler imports it from there.
- No direct import of `ProviderFactory`, `Checkpointer`, or
  `AcpSessionError` appears in `graph/compiler.py`.

No issues found.

---

## D-03: Extract reconciliation I/O into callback protocol

**Verdict: IMPLEMENTED**

Evidence:

- `lifecycle/reconciliation.py` exists and contains only pure decision
  logic: `ThreadSnapshot`, `ReconciliationAction`, and
  `compute_reconciliation_actions()`.
- File imports: `dataclasses`, `enum`, `typing` only. Zero async
  keywords. Zero database imports. Confirmed genuinely pure.
- `database/reconciliation.py` exists as the I/O executor. It imports
  `lifecycle.reconciliation` types and delegates database mutations to
  `database.crud`. The direction is correct: database imports from
  lifecycle, not the reverse.

One note: the ADR describes a "ReconciliationSink callback" pattern, but
the implementation uses a different shape — `compute_reconciliation_actions()`
returns a list of `ReconciliationAction` descriptors that the I/O executor
then processes. This is functionally equivalent (pure decisions, I/O
separation) but the API differs from the "callback the caller provides"
language in the ADR. The intent of D-03 (boundary separation) is fully met;
only the interface shape differs from the ADR description.

No boundary violations found.

---

## D-04: Make telemetry opt-in via instrumentation hooks

**Verdict: IMPLEMENTED**

Evidence:

- `TelemetryHook` protocol defined in `graph/protocols.py` with three
  methods: `start_span`, `increment_counter`, `record_histogram`.
- `NullTelemetryHook` defined in the same file as a concrete no-op class
  (not a protocol stub).
- `EventAggregator.__init__` (streaming/aggregator.py:44) accepts
  `telemetry: TelemetryHook | None = None`, defaulting to
  `NullTelemetryHook()`.
- `telemetry/aggregator_hook.py` contains `OTelAggregatorHook`, the real
  OTel implementation, separate from `streaming/`.
- Grep for `get_tracer` and `get_meter` across all `streaming/` files:
  **zero matches**. The instrumentation calls are gone from the streaming
  layer.

No issues found.

---

## D-05: Split Settings into domain config vs infrastructure config

**Verdict: IMPLEMENTED**

Evidence:

- `domain_config.py` (at the package root, `src/vaultspec_a2a/`) defines
  `DomainConfig` — 18 behavioral fields covering debounce windows, buffer
  sizes, token budgets, vault limits, graph settings, and cache sizes.
  Exports a `domain_config` singleton.
- `control/config.py` defines `InfraConfig` (~75 fields: ports, hosts,
  URLs, API keys, filesystem paths, pool sizes, worker settings, etc.) and
  `Settings(DomainConfig, InfraConfig)` as the backwards-compatible facade.
- Layer 1 files (`context/anchoring.py`, `context/metadata.py`,
  `context/token_budget.py`, `graph/compiler.py`) import from
  `vaultspec_a2a.domain_config`, not from `control.config`.

One concern worth flagging: `domain_config.py` is placed at the package
root (`src/vaultspec_a2a/domain_config.py`) rather than inside `core/`.
The ADR says "Domain fields stay in `core/domain_config.py`". The ADR also
describes a migration where the `core/` module is being decomposed into
`thread/`, `context/`, `graph/`, `streaming/` — so placement at the
package root is consistent with that migration. This is a naming drift from
the ADR text, not a boundary violation.

No infrastructure imports found in Layer 1 domain config files.

---

## D-06: Preserve test isolation

**Verdict: PARTIALLY IMPLEMENTED**

Evidence of isolation:

- `thread/tests/` — 3 test files found. Grep for database/api/providers/
  worker imports: **zero matches**. Fully isolated.
- `context/tests/` — 6 test files found. Grep for infrastructure imports:
  **zero matches**. Fully isolated.
- `graph/tests/` — `test_compiler.py` imports
  `from vaultspec_a2a.providers.factory import ProviderFactory`.
  `test_e2e_live.py` and `test_graph_execution.py` also import
  `ProviderFactory` from `providers/`. `test_worker_integration.py` imports
  `AcpChatModel` from `providers/`.

The ADR constraint is: "no new infrastructure imports in core test files."
The graph/ tests import from `providers/`, which is a higher-layer module.
Whether this is a pre-existing condition or introduced during this sprint
cannot be determined without git blame — but it is a live violation of the
isolation guarantee.

- `streaming/tests/test_aggregator.py` imports
  `from ...control.config import settings` (line 13). This pulls
  infrastructure configuration into a Layer 1 streaming test.

**Summary of D-06 violations:**

| File | Violating import |
| ---- | ---------------- |
| `graph/tests/test_compiler.py` | `providers.factory.ProviderFactory` |
| `graph/tests/test_e2e_live.py` | `providers.factory.ProviderFactory` |
| `graph/tests/test_graph_execution.py` | `providers.factory.ProviderFactory` |
| `graph/tests/nodes/test_worker_integration.py` | `providers.acp_chat_model.AcpChatModel` |
| `streaming/tests/test_aggregator.py` | `control.config.settings` |

The `thread/` and `context/` test suites are clean. The `graph/` and
`streaming/` test suites carry infrastructure dependencies.

---

## Summary

| Decision | Status | Notes |
| --- | --- | --- |
| D-01: Domain event types in core | **IMPLEMENTED** | All dataclasses, correct dependency arrow |
| D-02: Inject checkpoint/provider deps | **IMPLEMENTED** | `provider_factory` required, types correct |
| D-03: Reconciliation I/O split | **IMPLEMENTED** | Pure lifecycle module + I/O executor; interface shape differs from ADR text but boundary holds |
| D-04: Telemetry opt-in hooks | **IMPLEMENTED** | Hook protocol + NullHook in graph/protocols; OTel impl in telemetry/; no get_tracer/get_meter in streaming/ |
| D-05: Settings split | **IMPLEMENTED** | DomainConfig at pkg root; InfraConfig + Settings facade in control/; Layer 1 imports domain_config correctly |
| D-06: Test isolation preserved | **PARTIALLY IMPLEMENTED** | thread/ and context/ tests clean; graph/ tests import providers/; streaming tests import control.config |
