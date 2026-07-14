---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-03-23'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# core-layer phase-6 streaming + lifecycle extraction

## Summary

Moved `core/aggregator.py` (1,977 lines) into `streaming/aggregator.py` as-is,
split `core/reconciliation.py` into pure decision logic
(`lifecycle/reconciliation.py`) and I/O executor
(`database/reconciliation.py`), and wired backward-compat shims.

## Changes

- **`streaming/`** — new package
  - `aggregator.py`: moved from `core/aggregator.py`, single import change
    (`from .config import settings` to `from ..control.config import settings`)
  - `__init__.py`: re-exports `EventAggregator`, `StreamableGraph`,
    `classify_tool_kind`
  - `tests/test_aggregator.py`: copied from `core/tests/`, updated config
    import path

- **`lifecycle/`** — new package
  - `reconciliation.py`: pure function `compute_reconciliation_actions()`
    taking `ThreadSnapshot` list + checkpoint/permission maps, returns
    `ReconciliationAction` descriptors. No async, no database imports.

- **`database/reconciliation.py`** — new module
  - `probe_checkpoints()`: async checkpoint availability probing
  - `execute_reconciliation()`: applies action descriptors via CRUD calls
  - `reconcile_threads_on_startup()`: drop-in replacement composing probe +
    decide + execute

- **`core/aggregator.py`** — replaced with re-export shim from
  `streaming.aggregator`

- **`core/reconciliation.py`** — replaced with re-export shim from
  `database.reconciliation`

- **`core/__init__.py`** — `EventAggregator` and `StreamableGraph` moved from
  `_LAZY_IMPORTS` to `_REDIRECTS` pointing at `streaming.aggregator`

## Verification

- `pytest src/vaultspec_a2a/streaming/tests/ -x -q` — 47 passed
- `pytest src/vaultspec_a2a/core/tests/ -x -q` (excl. test_graph) — 315
  passed, 9 deselected
- `ruff check` — all checks passed
- `ruff format --check` — all files formatted
- `ty check` — all checks passed
