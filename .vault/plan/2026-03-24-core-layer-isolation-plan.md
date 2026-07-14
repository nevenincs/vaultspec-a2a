---
tags:
  - '#plan'
  - '#core-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-23-core-layer-boundary-research]]'
  - '[[2026-03-24-core-layer-review-audit]]'
---

# `core-layer` `layer-1-isolation` plan

Close ALL remaining boundary violations surfaced by the 2026-03-24
code review audit. Phases 0-7 moved files to the right packages. This
plan finishes the job: **zero cross-layer imports in Layer 1 production
code**, a properly decomposed aggregator, and all ADR decisions (D-01
through D-06) fully implemented.

## Context

The audit identified three categories of open violations:

- **8 production files** in `context/` and `graph/` import `settings`
  from `control.config` (Layer 2) instead of `domain_config` (Layer 1)
- **`graph/compiler.py`** retains a lazy fallback importing
  `ProviderFactory` from `providers/` (Layer 2)
- **`streaming/aggregator.py`** (1,977 lines) was moved as-is from
  `core/` without implementing ADR D-01 (domain events replace wire
  events) or D-04 (telemetry hooks replace direct instrumentation).
  It imports 16 Pydantic event classes from `api.schemas.events` and
  calls `get_tracer`/`get_meter` from `telemetry.instrumentation` at
  module scope.

The scaffolding exists: `graph/events.py` defines 10 domain event
dataclasses, `graph/protocols.py` defines `TelemetryHook` and
`NullTelemetryHook`, `graph/enums.py` owns the domain enums. The
remaining work is wiring.

## Proposed Changes

Four categories, in dependency order:

**Category A — `domain_config` singleton + settings swap**

Add `domain_config = DomainConfig()` singleton to `domain_config.py`.
Swap `from vaultspec_a2a.control.config import settings` to
`from vaultspec_a2a.domain_config import domain_config` in all Layer 1
production files. Pure import substitution — every field accessed
already exists on `DomainConfig`.

8 production files + 2 test files.

**Category B — Remove provider factory fallback**

Delete `_get_provider_factory()` from `graph/compiler.py`. Make
`provider_factory` a required parameter. Update test call sites to
pass a factory explicitly.

**Category C — Aggregator domain event conversion (ADR D-01)**

Refactor `streaming/aggregator.py` to emit `graph.events.*` domain
event dataclasses instead of constructing `api.schemas.events.*`
Pydantic models inline. Create `api/event_adapter.py` that translates
domain events to wire-protocol events at the WebSocket boundary.

The aggregator has 47 wire-protocol event constructions across ~15
emit methods. Each becomes a domain event construction (simpler —
dataclass, not Pydantic). The `api/event_adapter.py` then maps domain
→ wire at the single point where events leave the domain.

After this: `streaming/aggregator.py` imports from `graph.events` and
`graph.enums` only — zero `api.schemas` imports.

**Category D — Telemetry hook injection (ADR D-04)**

Replace module-level `get_tracer`/`get_meter` calls (lines 75-94) and
all `_tracer.start_as_current_span(...)` / `_counter.add(...)` calls
with the `TelemetryHook` protocol from `graph/protocols.py`.

- `EventAggregator.__init__` gains
  `telemetry: TelemetryHook | None = None` parameter, defaults to
  `NullTelemetryHook()`
- All `_tracer.*` and `_meter.*` calls become `self._telemetry.*`
- Module-level OTel imports removed
- `api/app.py` passes the real OTel hook at construction time

After this: `streaming/aggregator.py` has zero `telemetry/` imports.

**Category E — Aggregator `settings` swap**

Same as Category A but for the 13 `settings.*` accesses inside the
aggregator. Swap to `domain_config.*`. Must happen after Category A
(singleton exists).

## Tasks

- Phase 8a: Add `domain_config` singleton
  1. Add `domain_config = DomainConfig()` at end of
     `domain_config.py`
  1. Add `domain_config` to `__all__`

- Phase 8b: Swap `settings` → `domain_config` in `context/`
  1. Replace import + usage in `metadata.py`, `anchoring.py`,
     `token_budget.py`
  1. Replace import in `tests/test_metadata.py`,
     `tests/test_anchoring.py`
  1. Verify context/ tests pass

- Phase 8c: Swap `settings` → `domain_config` in `graph/`
  1. Replace import + usage in `compiler.py`,
     `nodes/supervisor.py`, `nodes/worker.py`,
     `nodes/vault_reader.py`, `tools/task_queue.py`
  1. Verify graph/ tests pass

- Phase 8d: Remove `_get_provider_factory()` fallback
  1. Delete `_get_provider_factory()` from `compiler.py`
  1. Make `provider_factory` required in `_resolve_worker_model()`
     and `_resolve_supervisor_model()`
  1. Update `compile_team_graph()` to raise `TypeError` if
     `provider_factory is None`
  1. Update test call sites in `graph/tests/test_compiler.py` to
     pass a factory
  1. Verify graph/ tests pass

- Phase 8e: Aggregator domain event conversion
  1. Swap `api.schemas.enums` → `graph.enums` imports in
     `streaming/aggregator.py` (5 enum imports)
  1. Replace all 47 wire-protocol event constructions
     (`MessageChunkEvent(...)` → `MessageChunk(...)` etc.) with
     domain event dataclasses from `graph.events`
  1. Update type annotations: `Queue[ServerEvent]` →
     `Queue[DomainEvent]`, method return types, etc.
  1. Remove all `api.schemas.events` imports from aggregator
  1. Create `api/event_adapter.py` with `domain_to_wire()` function
     that maps each domain event to its wire-protocol counterpart
  1. Update `api/websocket.py` to call `domain_to_wire()` before
     sending events to clients
  1. Verify streaming/ tests pass + full suite green

- Phase 8f: Telemetry hook injection
  1. Add `telemetry: TelemetryHook | None = None` parameter to
     `EventAggregator.__init__`, default `NullTelemetryHook()`
  1. Replace all `_tracer.start_as_current_span(...)` calls with
     `self._telemetry.start_span(...)`
  1. Replace all `_counter.add(...)` calls with
     `self._telemetry.increment_counter(...)`
  1. Replace all `_histogram.record(...)` calls with
     `self._telemetry.record_histogram(...)`
  1. Remove module-level `get_tracer`, `get_meter` imports and the 6
     instrument definitions (lines 75-94)
  1. Create `telemetry/aggregator_hook.py` (or similar) that
     implements `TelemetryHook` using real OTel
  1. Wire in `api/app.py`: pass real hook to `EventAggregator()`
  1. Verify streaming/ tests pass + full suite green

- Phase 8g: Aggregator `settings` → `domain_config` swap
  1. Replace `from ..control.config import settings` with
     `from ..domain_config import domain_config` (or from
     `vaultspec_a2a.domain_config`)
  1. Replace all `settings.X` with `domain_config.X` (13 usages)
  1. Verify streaming/ tests pass

- Phase 8h: Final boundary validation
  1. Run Layer 1 boundary grep — zero Layer 2+ imports in
     production code of `thread/`, `context/`, `team/`, `graph/`,
     `lifecycle/`, `domain_config.py`
  1. Run Layer 1.5 boundary grep — `streaming/` imports only from
     Layer 1 packages + stdlib + framework. Zero `api/`, `database/`,
     `providers/`, `telemetry/` imports.
  1. Run full test suite
  1. Run ruff + ty

## Parallelization

- 8a must land first (singleton)
- 8b and 8c can run in parallel (both depend on 8a)
- 8d depends on 8c
- 8e and 8f can run in parallel (both touch aggregator but different
  concerns — 8e changes what events are emitted, 8f changes how
  instrumentation works). However, since both modify the same file
  heavily, sequential may be safer: 8e first, then 8f.
- 8g depends on 8a (singleton) but is independent of 8e/8f
- 8h runs last

## Verification

**Layer 1 boundary** (production files only):

```bash
grep -rn \
  "from.*control\.\|from.*api\.\|from.*database\|from.*providers\|from.*telemetry\|from.*worker\|from.*streaming" \
  src/vaultspec_a2a/thread/ \
  src/vaultspec_a2a/context/ \
  src/vaultspec_a2a/team/ \
  src/vaultspec_a2a/graph/ \
  src/vaultspec_a2a/lifecycle/ \
  src/vaultspec_a2a/domain_config.py \
  --include="*.py" \
  | grep -v "/tests/"
```

Must return zero.

**Layer 1.5 boundary** (`streaming/` production files):

```bash
grep -rn \
  "from.*api\.\|from.*database\|from.*providers\|from.*telemetry\|from.*worker\|from.*control\." \
  src/vaultspec_a2a/streaming/ \
  --include="*.py" \
  | grep -v "/tests/"
```

Must return zero.

**Full regression**: `pytest src/vaultspec_a2a/ -x -q` green.
