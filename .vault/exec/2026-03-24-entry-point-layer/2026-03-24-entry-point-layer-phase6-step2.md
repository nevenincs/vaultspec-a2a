---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-6` `step-2`

Deduplicated `_trace_headers` (R-02) and extracted `_mark_worker_connected`.

- Created: `src/vaultspec_a2a/api/_utils.py`
- Modified: `src/vaultspec_a2a/api/app.py`

## Description

Created `api/_utils.py` with `trace_headers()` and `mark_worker_connected()`.
The duplicate `_trace_headers` in `app.py` now delegates to the shared
`trace_headers()`. The `opentelemetry.propagate` import was removed from
`app.py`. All route modules import from `_utils`.

## Tests

All 99 API tests pass. No behavioral changes.
