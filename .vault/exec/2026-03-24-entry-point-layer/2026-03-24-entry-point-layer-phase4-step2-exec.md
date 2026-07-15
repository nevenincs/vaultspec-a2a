---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase4` `step2`

Fixed 2 bare raise chain violations (R-01) by adding `from e` to exception chains.

- Modified: `src/vaultspec_a2a/api/internal.py`

## Description

Two `except ValueError` blocks in `receive_worker_event` (line 233) and `receive_worker_event_batch` (line 294) raised `HTTPException` without chaining the original `ValueError`. This violated B904 (raise-without-from-inside-except) and was suppressed with `# noqa: B904` comments.

Fixed by binding the exception as `e` and appending `from e` to the raise statement. Removed both `# noqa: B904` comments. Zero `noqa` comments remain in the file.

## Tests

All 26 tests in `test_internal.py` pass. The Content-Length validation paths are not directly tested but the fix is a pure exception chaining improvement with no behavioral change.
