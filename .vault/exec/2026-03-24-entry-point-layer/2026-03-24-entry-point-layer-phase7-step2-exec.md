---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase7` `step2`

Extracted `_classify_missing_ws_thread` from `api/app.py` to `control/diagnostics.py`.

- Created: `src/vaultspec_a2a/control/diagnostics.py` (146 lines)
- Modified: `src/vaultspec_a2a/api/tests/test_app.py` (updated imports)
- Modified: `src/vaultspec_a2a/control/__init__.py` (added diagnostics, health)

## Description

Created `control/diagnostics.py` with a protocol-agnostic
`classify_missing_ws_thread` function that returns a
`MissingThreadClassification` dataclass instead of
`WebSocketCommandRejectedError`. This avoids `control/` importing from
`api/` (which would invert the dependency). The API layer wraps the result
into `WebSocketCommandRejectedError`.

Also extracted `mark_thread_failed` — the DB update portion of
`_ws_mark_failed_and_broadcast` — into the same module.

Updated `control/__init__.py` docstring and `__all__` to include
`diagnostics` and `health`.

## Tests

`test_classify_missing_ws_thread_reports_not_found` and
`test_classify_missing_ws_thread_reports_state_drift` updated to import
from `control.diagnostics` and assert on `MissingThreadClassification`
fields. Both pass.
