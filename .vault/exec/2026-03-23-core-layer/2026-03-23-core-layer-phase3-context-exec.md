---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-07-15'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# core-layer phase-3 context extraction

Extracted 6 source files from `core/` into the new `context/` package
and created corresponding test mirrors.

## files created

- `src/vaultspec_a2a/context/__init__.py` — re-exports all 13 public symbols
- `src/vaultspec_a2a/context/metadata.py` — from `core/metadata.py`
- `src/vaultspec_a2a/context/preamble.py` — from `core/preamble.py`
- `src/vaultspec_a2a/context/anchoring.py` — from `core/anchoring.py`
- `src/vaultspec_a2a/context/stage.py` — from `core/phase.py` (renamed)
- `src/vaultspec_a2a/context/rules.py` — from `core/rules.py`
- `src/vaultspec_a2a/context/token_budget.py` — from `core/context.py` (renamed)
- `src/vaultspec_a2a/context/tests/` — 6 test files mirroring originals

## import rewiring

- `from .config import settings` replaced with `from vaultspec_a2a.control.config import settings`
- `from .state import ...` replaced with `from vaultspec_a2a.thread.state import ...`
- Cross-references within context/ use relative imports (`from .metadata import ...`)

## shims installed

Each original `core/*.py` file replaced with a thin re-export shim
delegating to the canonical `vaultspec_a2a.context.*` module.

## core/__init__.py updates

- Removed eager imports for metadata, anchoring, phase, preamble symbols
- Moved `compact_context`, `estimate_tokens`, `prepare_handoff`,
  `should_compact`, `build_context_preamble` from `_LAZY_IMPORTS` to `_REDIRECTS`
- Added 15 new `_REDIRECTS` entries for all Phase 3 symbols
- `__all__` unchanged

## verification

- `pytest src/vaultspec_a2a/context/tests/ -x -q` — 128 passed
- `pytest src/vaultspec_a2a/core/tests/ -x -q --ignore=test_graph.py` — 315 passed, 9 deselected
- `ruff check` — all checks passed
- `ruff format --check` — 59 files already formatted
