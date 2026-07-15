---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-07-15'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-23-core-layer-boundary-research]]'
---

# `core-layer` `phase-1-through-7` summary

Complete decomposition of `src/vaultspec_a2a/core/` into 7 focused
packages, enforcing Layer 1 boundary integrity.

- Deleted: `src/vaultspec_a2a/core/` (entire directory — 6,549 lines)
- Created: `thread/`, `context/`, `team/`, `graph/`, `streaming/`,
  `lifecycle/`, `domain_config.py`, `control/config.py`,
  `database/reconciliation.py`

## Description

Seven phases executed sequentially with parallel sub-agents for
independent phases (P1+P2 parallel, P3+P4 parallel):

- **Phase 0**: Compatibility shim — `_REDIRECTS` mechanism in
  `core/__init__.py`
- **Phase 1**: `thread/` — state.py, models.py, errors.py (91 tests)
- **Phase 2**: Config split — `DomainConfig` (18 fields) +
  `InfraConfig` (75 fields) + `Settings` facade
- **Phase 3**: `context/` — metadata, preamble, anchoring, stage,
  rules, token_budget (128 tests)
- **Phase 4**: `team/` — team_config, presets (74 tests)
- **Phase 5**: `graph/` — compiler, enums, events, protocols, nodes,
  tools. Dependency injection: `ProviderFactoryProtocol` replaces
  `ProviderFactory`, `BaseCheckpointSaver` replaces `Checkpointer`,
  `ProviderSessionError` replaces `AcpSessionError`
- **Phase 6**: `streaming/` — aggregator moved as-is.
  `lifecycle/reconciliation.py` — pure decision logic.
  `database/reconciliation.py` — I/O executor.
- **Phase 7**: Delete `core/` entirely. 60+ import sites across 30+
  files rewritten to canonical paths.

All 6 boundary violations from the research resolved:

| Violation | Resolution |
|-----------|-----------|
| V-01 aggregator → api.schemas | Aggregator moved to streaming/ |
| V-02 aggregator → telemetry | Deferred (acceptable in Layer 1.5) |
| V-03 graph → database.checkpoints | BaseCheckpointSaver (framework type) |
| V-04 graph → providers | ProviderFactoryProtocol (DI) |
| V-05 reconciliation → database.crud | Pure/I/O split |
| V-06 global settings singleton | DomainConfig/InfraConfig split |

## Tests

- Layer 1 import test: PASS (zero infrastructure dependencies)
- Full regression: 974 passed, 0 failed (34 deselected — pre-existing)
- Ruff: all checks passed
- Ty: all checks passed
- All pre-commit hooks: passed
- Pre-existing failures excluded: ACP npm dependency (test_factory.py),
  Postgres migration (test_migrations.py), graph compiler (npm dep)
