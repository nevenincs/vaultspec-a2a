---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-03-23'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# phase-1: extract `thread/` module

## Summary

Extracted `state.py`, `models.py`, and `exceptions.py` from `core/` into
a new `thread/` leaf module. Moved `asyncio_compat.py` to `utils/`.
Added `ProviderSessionError` to `thread/errors.py`. Created thin
re-export shims in `core/` so that all existing `from ..core.exceptions
import X` paths continue to resolve.

## Files created

- `src/vaultspec_a2a/thread/__init__.py` — re-exports all public symbols
- `src/vaultspec_a2a/thread/state.py` — TeamState + reducers (from core/state.py)
- `src/vaultspec_a2a/thread/models.py` — ArtifactRef, PlanStep, TokenUsageEntry
- `src/vaultspec_a2a/thread/errors.py` — all exceptions + ProviderSessionError (new)
- `src/vaultspec_a2a/thread/tests/__init__.py`
- `src/vaultspec_a2a/thread/tests/test_state.py`
- `src/vaultspec_a2a/thread/tests/test_models.py`
- `src/vaultspec_a2a/thread/tests/test_errors.py`
- `src/vaultspec_a2a/utils/asyncio_compat.py` — moved from core/

## Files replaced with re-export shims

- `src/vaultspec_a2a/core/exceptions.py` — shim re-exporting from thread.errors
- `src/vaultspec_a2a/core/state.py` — shim re-exporting from thread.state
- `src/vaultspec_a2a/core/models.py` — shim re-exporting from thread.models
- `src/vaultspec_a2a/core/asyncio_compat.py` — shim re-exporting from utils

## Files modified

- `src/vaultspec_a2a/core/__init__.py` — removed eager exception/model imports,
  moved TeamState from `_LAZY_IMPORTS` to `_REDIRECTS`, added 22 redirect entries
- `src/vaultspec_a2a/api/app.py` — import asyncio_compat from utils
- `src/vaultspec_a2a/worker/app.py` — import asyncio_compat from utils
- `src/vaultspec_a2a/core/aggregator.py` — import from thread.errors
- `src/vaultspec_a2a/core/graph.py` — import from thread.errors + thread.state
- `src/vaultspec_a2a/core/context.py` — import from thread.state
- `src/vaultspec_a2a/core/anchoring.py` — import from thread.state
- `src/vaultspec_a2a/core/team_config.py` — import from thread.errors
- `src/vaultspec_a2a/core/nodes/mount.py` — import from thread.state
- `src/vaultspec_a2a/core/nodes/supervisor.py` — import from thread.state
- `src/vaultspec_a2a/core/nodes/worker.py` — import from thread.errors + thread.state
- `src/vaultspec_a2a/core/tests/test_aggregator.py` — import from thread.errors
- `src/vaultspec_a2a/core/tests/test_graph.py` — import from thread.errors
- `src/vaultspec_a2a/core/tests/test_context.py` — import from thread.state
- `src/vaultspec_a2a/core/tests/test_supervisor.py` — import from thread.state
- `src/vaultspec_a2a/core/tests/test_worker.py` — import from thread.errors
- `src/vaultspec_a2a/core/tests/test_team_config.py` — import from thread.errors
- `src/vaultspec_a2a/core/nodes/tests/test_supervisor.py` — import from thread.state
- `src/vaultspec_a2a/core/nodes/tests/test_worker.py` — import from thread.state
- `src/vaultspec_a2a/core/nodes/tests/test_worker_integration.py` — import from thread.state

## Test deleted from core/tests/

- `test_state.py`, `test_models.py`, `test_exceptions.py` — originals removed,
  replaced by thread/tests/ copies

## Test results

- `pytest src/vaultspec_a2a/thread/tests/ -x -q`: **91 passed** (0.32s)
- `pytest src/vaultspec_a2a/core/tests/ -x -q --ignore=test_graph.py`: **315 passed, 9 deselected** (3.77s)
