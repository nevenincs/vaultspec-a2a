---
tags:
  - '#plan'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-07-15'
related:
  - '[[2026-03-23-core-layer-boundary-research]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# `core-layer` `phase-1-through-7` plan

Decompose `src/vaultspec_a2a/core/` into 6 focused modules (`thread/`,
`context/`, `team/`, `graph/`, `streaming/`, `lifecycle/`) plus a
`domain_config.py`, enforcing Layer 1 boundary integrity per the accepted ADR.
Seven phases, each independently shippable with a green test suite.

## Proposed Changes

Extract all core files into purpose-built packages, removing the 6 boundary
violations identified in the research (4 CRITICAL cross-layer imports, 2 HIGH
configuration coupling). A compatibility shim in `core/__init__.py` ensures
backwards compatibility during migration. Domain events replace API wire
schemas. Dependency injection replaces concrete imports. The 1,976-line
aggregator decomposes into 6 streaming sub-modules via composition.

Grounded in the ADR decisions D-01 through D-06. The v2 plan supersedes the
original 5-phase plan.

```
Phase 0 (shim)
    |
    +-- Phase 1 (thread/)       -- no deps beyond P0
    +-- Phase 2 (domain_config) -- no deps beyond P0
    |
    +-- Phase 3 (context/)      -- depends on P1 + P2
    +-- Phase 4 (team/)         -- depends on P1 + P2
    |
    Phase 5 (graph/)            -- depends on P1-P4
    |
    Phase 6 (streaming/ + lifecycle/) -- depends on P5
    |
    Phase 7 (cleanup)           -- remove shim
```

## Tasks

- Phase 0: compatibility shim
  1. Replace `core/__init__.py` with `__getattr__` redirector preserving eager
     imports for unmoved symbols
  1. Verify full test suite passes with empty shim

- Phase 1: `thread/` — leaf module (zero internal deps)
  1. Create `thread/` with `state.py`, `models.py`, `errors.py` from core
  1. Add `ProviderSessionError` to `thread/errors.py`
  1. Move `asyncio_compat.py` to `utils/`
  1. Add redirect entries to shim, delete originals, verify

- Phase 2: `domain_config.py` — config split
  1. Create `domain_config.py` with ~18 domain fields
  1. Create `control/config.py` with ~75 infrastructure fields and
     backwards-compatible `Settings` facade
  1. Test facade: `DomainConfig()` defaults match, `isinstance(settings,
     DomainConfig)` holds
  1. Progressively parameterize Layer 1 functions with optional config params
  1. Delete `core/config.py`, verify

- Phase 3: `context/` — prompt enrichment pipeline
  1. Create `context/` with `metadata.py`, `preamble.py`, `anchoring.py`,
     `stage.py`, `rules.py`, `token_budget.py`
  1. Update imports: `config` -> `domain_config`, `state` -> `thread.state`
  1. Update shim, delete originals, verify

- Phase 4: `team/` — agent/team definitions
  1. Create `team/` with `team_config.py` and `presets/`
  1. Update imports: `exceptions` -> `thread.errors`
  1. Update shim, delete originals, verify

- Phase 5: `graph/` — compilation + nodes + tools + events
  1. Create `graph/enums.py` (move domain enums from `api/schemas/enums.py`)
  1. Create `graph/events.py` (domain event dataclasses per ADR D-01)
  1. Create `graph/protocols.py` (`ProviderFactoryProtocol`, `TelemetryHook`,
     `NullTelemetryHook` per ADR D-04)
  1. Create `graph/compiler.py` from `core/graph.py` — inject
     `BaseCheckpointSaver` and `ProviderFactoryProtocol` per ADR D-02
  1. Move `nodes/` and `task_queue.py` into `graph/`
  1. Update all `compile_team_graph` call sites (executor, test prep, tests)
  1. Wrap `AcpSessionError` -> `ProviderSessionError` in providers layer per
     ADR D-02
  1. Update shim, delete originals, verify

- Phase 6: `streaming/` + `lifecycle/` — Layer 1.5 bridge
  1. Partition aggregator state into 5 groups: subscribers, buffering,
     emitters, ingest, transformer
  1. Create `streaming/` with composition root `EventAggregator` delegating to
     `SubscriberManager`, `BufferingManager`, `EventEmitters`, `IngestManager`,
     `transformer.py` (stateless)
  1. Create `api/event_adapter.py` for domain-to-wire event translation
  1. Create `lifecycle/reconciliation.py` with pure
     `compute_reconciliation_actions()` function per ADR D-03
  1. Create `database/reconciliation.py` with I/O executor +
     `probe_checkpoints()`
  1. Update call site in `api/app.py` to use pure/I/O split
  1. Update shim, delete originals, verify

- Phase 7: cleanup — remove shim and `core/`
  1. Audit remaining `from ..core import` references
  1. Batch update all imports to new module paths
  1. Delete `src/vaultspec_a2a/core/` entirely
  1. Run final validation gate

## Parallelization

- P1 and P2 can run in parallel (both depend only on P0)
- P3 and P4 can run in parallel (both depend on P1 + P2)
- P5 waits for P1-P4 (all leaf modules must be in place)
- P6 waits for P5 (needs `graph/events` and `graph/enums`)
- P7 waits for P6 (all modules must be extracted before shim removal)

Sub-agents can handle P1 and P2 concurrently, then P3 and P4 concurrently.

## Verification

Final validation gate after Phase 7:

- Layer 1 import test: import `DomainConfig`, `TeamConfig`, `TeamState`,
  `ConfigError`, `ProviderSessionError`, `ThreadMetadata`, `estimate_tokens`,
  `compile_team_graph`, `MessageChunk`, `ToolCallStart`, `PermissionRequest`,
  `ToolKind`, `AgentLifecycleState`, `ProviderFactoryProtocol` with zero
  infrastructure — must succeed
- Layer 1 test isolation: `pytest` on `team/`, `thread/`, `context/`,
  `graph/` tests with `-m "not live and not requires_vidaimock"` — all pass
- No remaining `core/` references: `grep -r "vaultspec_a2a\.core" src/` returns
  0 matches
- Full regression: `pytest src/vaultspec_a2a/ -x -q` — green

Per-phase verification: every phase runs `pytest src/vaultspec_a2a/ -x -q`
before and after to confirm the shim preserves backwards compatibility. No
phase may leave a broken test suite.
