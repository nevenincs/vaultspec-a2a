---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase7` `step4`

Verification of Phase 7 (D-08: slim app.py to thin application factory).

## Description

All acceptance criteria met:

- `api/app.py`: 309 lines (target: under 500)
- `api/middleware.py`: 40 lines
- `api/ws_dispatch.py`: 283 lines
- `control/diagnostics.py`: 146 lines
- No `control/` -> `api/` imports (avoided by returning
  `MissingThreadClassification` dataclass instead of WS error type)
- No re-export shims
- No `# noqa` comments

## Tests

- `pytest -m core`: 425 passed
- Full suite: 1026 passed, 1 pre-existing failure in `test_factory.py`
  (confirmed unrelated by testing on stashed clean state)
- Ruff lint: all checks passed on all modified files
