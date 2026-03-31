---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# core-layer phase-4 team extraction

## summary

Extracted `team/` module from `core/team_config.py` as the canonical home for
agent and team configuration schemas, preset discovery, and TOML loading.

## changes

- Created `src/vaultspec_a2a/team/` with `__init__.py`, `team_config.py`,
  `presets/` (full copy of agents, teams, mock/tapes), and `tests/`.
- `team/team_config.py`: updated `from ..utils.enums` to absolute
  `from vaultspec_a2a.utils.enums`; `Path(__file__).parent / "presets"`
  resolves to `team/presets/` correctly.
- `core/team_config.py`: replaced with thin re-export shim importing all 20
  public symbols from `vaultspec_a2a.team.team_config`.
- `core/__init__.py`: removed 18 eager `from .team_config import` lines;
  added 18 `_REDIRECTS` entries pointing to `vaultspec_a2a.team.team_config`.
  `__all__` unchanged.
- `core/presets/` retained as-is (safe copy; removal deferred to Phase 7).

## verification

- `pytest src/vaultspec_a2a/team/tests/ -x -q` — 74 passed
- `pytest src/vaultspec_a2a/core/tests/ -x -q --ignore=test_graph.py` — 315 passed, 9 deselected
- `ruff check` — 0 errors (after `--fix` for I001 import sorting)
- `ruff format --check` — 6 files already formatted
