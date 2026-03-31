---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase7` `step3`

Slimmed `api/app.py` from 751 to 309 lines by extracting remaining business logic.

- Created: `src/vaultspec_a2a/api/ws_dispatch.py` (283 lines)
- Modified: `src/vaultspec_a2a/api/app.py` (309 lines, down from 751)
- Modified: `src/vaultspec_a2a/control/dispatch.py` (added `redispatch_reconciling_threads`)
- Modified: `src/vaultspec_a2a/api/tests/test_app.py` (updated imports)

## Description

Three extractions completed:

- **WS dispatch handler factories** (`_create_dispatch_message_handler`,
  `_create_dispatch_control_handler`) moved to `api/ws_dispatch.py` along
  with helpers `_raise_missing_thread` and `_ws_mark_failed_and_broadcast`.
  Renamed to drop leading underscore (public in new module).

- **`_redispatch_reconciling`** inner function moved to
  `control/dispatch.py` as `redispatch_reconciling_threads`. Accepts
  explicit dependencies instead of closing over lifespan locals.

- **`_ws_mark_failed_and_broadcast`** split: DB update delegates to
  `control.diagnostics.mark_thread_failed`; WS broadcast stays in
  `api/ws_dispatch.py`.

`app.py` now contains only `create_app()`, `main()`, and `_lifespan()`.

## Tests

All 10 `test_app.py` tests pass. 1026 tests pass across the full suite
(1 pre-existing failure in `test_factory.py` excluded). 425 core tests pass.
Ruff lint clean on all modified files.
